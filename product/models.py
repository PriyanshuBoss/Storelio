import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Optional, Union
from uuid import uuid4
from saleor.core.utils.json_serializer import CustomJsonEncoder
from django.db.models import Max
from django.conf import settings
from django.utils.text import slugify
from django.contrib.postgres.aggregates import StringAgg
from django.utils.safestring import mark_safe
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import JSONField  # type: ignore
from django.db.models import Case, Count, F, FilteredRelation, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.encoding import smart_text
from django_measurement.models import MeasurementField
from django_prices.models import MoneyField
from draftjs_sanitizer import clean_draft_js
from measurement.measures import Weight
from mptt.managers import TreeManager
from mptt.models import MPTTModel
from versatileimagefield.fields import PPOIField, VersatileImageField
from saleor.brand.states import BrandStatusEnum
from saleor.product.states import CollectionTypeEnum, ProductGroupingEnum
from saleor.product.templatetags.product_images import get_thumbnail
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities

from ..core.db.fields import SanitizedJSONField
from ..core.models import (
    ModelWithCreateTimestamp,
    ModelWithCreateUpdateTimestamp,
    ModelWithMetadata,
    PublishableModel,
    PublishedQuerySet,
    SortableModel,    
)
from ..core.permissions import ProductPermissions, ProductTypePermissions
from .templatetags.product_images import get_product_image_thumbnail
from ..core.utils import build_absolute_uri
from ..core.utils.draftjs import json_content_to_raw_text
from ..core.utils.translations import TranslationProxy
from ..core.weight import WeightUnits, zero_weight
from ..discount import DiscountInfo
from ..discount.utils import calculate_discounted_price
from ..seo.models import SeoModel, SeoModelTranslation
from . import AttributeInputType, BarterType,SourcingRequestStatus, BrandCollabStatusForSouringRequest
from saleor.brand.models import Brand
from saleor.store import models as store_models
from saleor.account import models as user_models
from saleor.product import models as product_models

if TYPE_CHECKING:
    # flake8: noqa
    from prices import Money

    from ..account.models import User
    from django.db.models import OrderBy


class Category(MPTTModel, ModelWithMetadata, SeoModel):
    name = models.CharField(max_length=250)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    description_json = JSONField(blank=True, default=dict)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="children", on_delete=models.CASCADE
    )
    background_image = VersatileImageField(
        upload_to="category-backgrounds", blank=True, null=True
    )
    background_image_alt = models.CharField(max_length=128, blank=True)

    objects = models.Manager()
    tree = TreeManager()
    translated = TranslationProxy()

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        return super().save(*args, **kwargs)

class CategoryTranslation(SeoModelTranslation):
    language_code = models.CharField(max_length=10)
    category = models.ForeignKey(
        Category, related_name="translations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    description_json = JSONField(blank=True, default=dict)

    class Meta:
        unique_together = (("language_code", "category"),)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        class_ = type(self)
        return "%s(pk=%r, name=%r, category_pk=%r)" % (
            class_.__name__,
            self.pk,
            self.name,
            self.category_id,
        )


class ProductType(ModelWithMetadata):
    name = models.CharField(max_length=250)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    has_variants = models.BooleanField(default=True)
    is_shipping_required = models.BooleanField(default=True)
    is_digital = models.BooleanField(default=False)
    weight = MeasurementField(
        measurement=Weight, unit_choices=WeightUnits.CHOICES, default=zero_weight
    )

    class Meta:
        ordering = ("slug",)
        app_label = "product"
        permissions = (
            (
                ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES.codename,
                "Manage product types and attributes.",
            ),
        )

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        class_ = type(self)
        return "<%s.%s(pk=%r, name=%r)>" % (
            class_.__module__,
            class_.__name__,
            self.pk,
            self.name,
        )


class ProductsQueryset(PublishedQuerySet):
    def published_with_variants(self):
        published = self.published()
        return published.filter(variants__isnull=False).distinct()

    def visible_to_user(self, user):
        if self.user_has_access_to_all(user):
            return self.all()
        return self.published_with_variants()

    def visible_to_all_user(self,user):
        return self.all()
        
    def sort_by_attribute(
        self, attribute_pk: Union[int, str], descending: bool = False
    ):
        """Sort a query set by the values of the given product attribute.

        :param attribute_pk: The database ID (must be a numeric) of the attribute
                             to sort by.
        :param descending: The sorting direction.
        """
        qs: models.QuerySet = self
        # If the passed attribute ID is valid, execute the sorting
        if not (isinstance(attribute_pk, int) or attribute_pk.isnumeric()):
            return qs.annotate(
                concatenated_values_order=Value(
                    None, output_field=models.IntegerField()
                ),
                concatenated_values=Value(None, output_field=models.CharField()),
            )

        # Retrieve all the products' attribute data IDs (assignments) and
        # product types that have the given attribute associated to them
        associated_values = tuple(
            AttributeProduct.objects.filter(attribute_id=attribute_pk).values_list(
                "pk", "product_type_id"
            )
        )

        if not associated_values:
            qs = qs.annotate(
                concatenated_values_order=Value(
                    None, output_field=models.IntegerField()
                ),
                concatenated_values=Value(None, output_field=models.CharField()),
            )

        else:
            attribute_associations, product_types_associated_to_attribute = zip(
                *associated_values
            )

            qs = qs.annotate(
                # Contains to retrieve the attribute data (singular) of each product
                # Refer to `AttributeProduct`.
                filtered_attribute=FilteredRelation(
                    relation_name="attributes",
                    condition=Q(attributes__assignment_id__in=attribute_associations),
                ),
                # Implicit `GROUP BY` required for the `StringAgg` aggregation
                grouped_ids=Count("id"),
                # String aggregation of the attribute's values to efficiently sort them
                concatenated_values=Case(
                    # If the product has no association data but has
                    # the given attribute associated to its product type,
                    # then consider the concatenated values as empty (non-null).
                    When(
                        Q(product_type_id__in=product_types_associated_to_attribute)
                        & Q(filtered_attribute=None),
                        then=models.Value(""),
                    ),
                    default=StringAgg(
                        F("filtered_attribute__values__name"),
                        delimiter=",",
                        ordering=(
                            [
                                f"filtered_attribute__values__{field_name}"
                                for field_name in AttributeValue._meta.ordering or []
                            ]
                        ),
                    ),
                    output_field=models.CharField(),
                ),
                concatenated_values_order=Case(
                    # Make the products having no such attribute be last in the sorting
                    When(concatenated_values=None, then=2),
                    # Put the products having an empty attribute value at the bottom of
                    # the other products.
                    When(concatenated_values="", then=1),
                    # Put the products having an attribute value to be always at the top
                    default=0,
                    output_field=models.IntegerField(),
                ),
            )

        # Sort by concatenated_values_order then
        # Sort each group of products (0, 1, 2, ...) per attribute values
        # Sort each group of products by name,
        # if they have the same values or not values
        ordering = "-" if descending else ""
        return qs.order_by(
            f"{ordering}concatenated_values_order",
            f"{ordering}concatenated_values",
            f"{ordering}name",
        )


class Product(SeoModel, ModelWithMetadata, PublishableModel):
    brand = models.ForeignKey(
        Brand, related_name="products", on_delete=models.CASCADE, null=True
    ) 
    product_type = models.ForeignKey(
        ProductType, related_name="products", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=250)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    description_plaintext = models.TextField(blank=True)
    search_vector = SearchVectorField(null=True, blank=True)
    description_json = SanitizedJSONField(
        blank=True, default=dict, sanitizer=clean_draft_js
    )
    category = models.ForeignKey(
        Category,
        related_name="products",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
        default=settings.DEFAULT_CURRENCY,
    )

    minimal_variant_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True,
    )
    minimal_variant_price = MoneyField(
        amount_field="minimal_variant_price_amount", currency_field="currency"
    )
    updated_at = models.DateTimeField(auto_now=True, null=True)
    charge_taxes = models.BooleanField(default=True)
    weight = MeasurementField(
        measurement=Weight, unit_choices=WeightUnits.CHOICES, blank=True, null=True
    )
    available_for_purchase = models.DateField(blank=True, null=True)
    visible_in_listings = models.BooleanField(default=False)
    default_variant = models.OneToOneField(
        "ProductVariant",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    has_custom_commission = models.BooleanField(default=False)
    commission_percentage = models.FloatField(default=0.0)
    step_price = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=Decimal('0.0')
    )
    brand_barter = models.CharField(max_length=30, choices=BarterType.CHOICES, default=BarterType.ACTIVE_BARTER)
    objects = ProductsQueryset.as_manager()
    translated = TranslationProxy()

    class Meta:
        app_label = "product"
        ordering = ("slug",)
        permissions = (
            (ProductPermissions.MANAGE_PRODUCTS.codename, "Manage products."),
        )
        indexes = [GinIndex(fields=["search_vector"])]

    def __iter__(self):
        if not hasattr(self, "__variants"):
            setattr(self, "__variants", self.variants.all())
        return iter(getattr(self, "__variants"))

    def __repr__(self) -> str:
        class_ = type(self)
        return "<%s.%s(pk=%r, name=%r)>" % (
            class_.__module__,
            class_.__name__,
            self.pk,
            self.name,
        )

    def __str__(self) -> str:
        return self.name

    @property
    def plain_text_description(self) -> str:
        return json_content_to_raw_text(self.description_json)

    def get_first_image(self):
        images = list(self.images.all())
        return images[0] if images else None

    @staticmethod
    def sort_by_attribute_fields() -> list:
        return ["concatenated_values_order", "concatenated_values", "name"]

    def is_available_for_purchase(self):

        brand_instance = self.brand
        
        return (
            self.available_for_purchase is not None
            and datetime.date.today() >= self.available_for_purchase
            and (brand_instance.status in [BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER] or brand_instance.brand_name == 'thrift_brand')
        )

    @property
    def msp(self):
        return self.variants.aggregate(Max('price_amount'))["price_amount__max"]

    def product_image_listing(self):
        if self.images.count():
            return mark_safe(
                '<img src="{url}" style="width: 120px; height:150px;" />'.format(
                    url=self.images.first().image.url,
                )
            )
        else:
            return "No Image Found"

    product_image_listing.short_description = "Image"
    product_image_listing.allow_tags = True

    def product_image(self):
        if self.images.count():
            return mark_safe(
                '<img src="{url}" style="width: 250px; height:350px;" />'.format(
                    url=self.images.first().image.url,
                )
            )
        else:
            return "No Image Found"

    product_image.short_description = "Image"
    product_image.allow_tags = True

    def get_product_url(self,size=1080): 
        
        '''This function is to get the exact image of the
            product that is visible on the zaamo stores'''

        search_image = self.metadata.get('search_image')
        if search_image:
            if size > 1000:
                res = 1080
            elif size > 500:
                res = 600
            else:
                res = 400
            thumbnail_url = search_image.rsplit('.', 1)[0] + f'_{res}.jpeg' 
        else:
            first_prod_image = self.get_first_image()
            thumbnail_url = get_thumbnail(first_prod_image.image,size, method="thumbnail")

        return thumbnail_url

    def product_image_thumbnail(self):
        image_url = None
        try:
            product_image = self.get_first_image()
            product_thumbnail = get_product_image_thumbnail(product_image, 120, method="thumbnail")
            image_url = product_thumbnail

        except Exception as e:
            pass

        return image_url

class ProductTranslation(SeoModelTranslation):
    language_code = models.CharField(max_length=10)
    product = models.ForeignKey(
        Product, related_name="translations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    description_json = SanitizedJSONField(
        blank=True, default=dict, sanitizer=clean_draft_js
    )

    class Meta:
        unique_together = (("language_code", "product"),)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        class_ = type(self)
        return "%s(pk=%r, name=%r, product_pk=%r)" % (
            class_.__name__,
            self.pk,
            self.name,
            self.product_id,
        )


class ProductVariantQueryset(models.QuerySet):
    def annotate_quantities(self):
        return self.annotate(
            quantity=Coalesce(Sum("stocks__quantity"), 0),
            quantity_allocated=Coalesce(
                Sum("stocks__allocations__quantity_allocated"), 0
            ),
        )

    def create(self, **kwargs):
        """Create a product's variant.

        After the creation update the "minimal_variant_price" of the product.
        """
        variant = super().create(**kwargs)

        # from .tasks import update_product_minimal_variant_price_task

        #update_product_minimal_variant_price_task.delay(variant.product_id)
        return variant

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False):
        """Insert each of the product's variant instances into the database.

        After the creation update the "minimal_variant_price" of all the products.
        """
        variants = super().bulk_create(
            objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts
        )
        product_ids = set()
        for obj in objs:
            product_ids.add(obj.product_id)
        product_ids = list(product_ids)

        from .tasks import update_products_minimal_variant_prices_of_catalogues_task

        update_products_minimal_variant_prices_of_catalogues_task.delay(
            product_ids=product_ids
        )
        return variants


class ProductVariant(SortableModel, ModelWithMetadata, ModelWithCreateUpdateTimestamp):
    sku = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True)
    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
        default=settings.DEFAULT_CURRENCY,
        blank=True,
        null=True,
    )
    price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
    )
    price = MoneyField(amount_field="price_amount", currency_field="currency")
    product = models.ForeignKey(
        Product, related_name="variants", on_delete=models.CASCADE
    )
    images = models.ManyToManyField("ProductImage", through="VariantImage")
    track_inventory = models.BooleanField(default=True)

    cost_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True,
    )
    cost_price = MoneyField(amount_field="cost_price_amount", currency_field="currency")
    weight = MeasurementField(
        measurement=Weight, unit_choices=WeightUnits.CHOICES, blank=True, null=True
    )

    objects = ProductVariantQueryset.as_manager()
    translated = TranslationProxy()

    class Meta:
        ordering = ("sort_order", "sku")
        app_label = "product"

    def __str__(self) -> str:
        return self.name or self.sku

    @property
    def is_visible(self) -> bool:
        return self.product.is_visible

    def get_price(self, discounts: Optional[Iterable[DiscountInfo]] = None) -> "Money":
        return calculate_discounted_price(
            product=self.product,
            price=self.price,
            collections=self.product.collections.all(),
            discounts=discounts,
        )

    def get_weight(self):
        return zero_weight()
        # return self.weight or self.product.weight or self.product.product_type.weight

    def is_shipping_required(self) -> bool:
        return True
        # return self.product.product_type.is_shipping_required

    def is_digital(self) -> bool:
        return False
        #is_digital = self.product.product_type.is_digital
        #return not self.is_shipping_required() and is_digital

    def display_product(self, translated: bool = False) -> str:
        if translated:
            product = self.product.translated
            variant_display = str(self.translated)
        else:
            variant_display = str(self)
            product = self.product
        product_display = (
            f"{product} ({variant_display})" if variant_display else str(product)
        )
        return smart_text(product_display)

    def get_first_image(self) -> "ProductImage":
        images = list(self.images.all())
        return images[0] if images else self.product.get_first_image()

    def get_ordering_queryset(self):
        return self.product.variants.all()

    def get_inventory(self):
        stock_filter = self.stocks.all()
        inventory = 0
        
        if stock_filter:
            inventory = stock_filter[0].quantity

        return inventory

class StoreProductViews(models.Model):
    store       = models.ForeignKey(store_models.StoreInfo, on_delete=models.CASCADE)
    product     = models.ForeignKey(Product, on_delete=models.CASCADE)
    views       = models.IntegerField(default=0)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return str(self.views)

class BrandVariantZaamoMapping(ModelWithCreateUpdateTimestamp):
    brand_name = models.CharField(max_length=255, blank=True, null=True)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    product_id_brand = models.CharField(max_length=255, blank=True, null=True)
    sku_id_brand = models.CharField(max_length=255, blank=True, null=True)
    variant_id_brand = models.CharField(max_length=255, blank=True, null=True)
    product_zaamo = models.ForeignKey(Product, on_delete=models.CASCADE,related_name='product_zaamo')
    variant_zaamo = models.ForeignKey(ProductVariant, on_delete=models.CASCADE,related_name='variant_zaamo')
    source = models.CharField(max_length=225, blank=True, null=True)
    brand_zaamo = models.ForeignKey(Brand, on_delete=models.CASCADE, null=True)

    def save(self, *args, **kwargs):
        super(self.__class__, self).save(*args, **kwargs)

class ProductVariantTranslation(models.Model):
    language_code = models.CharField(max_length=10)
    product_variant = models.ForeignKey(
        ProductVariant, related_name="translations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=255, blank=True)

    translated = TranslationProxy()

    class Meta:
        unique_together = (("language_code", "product_variant"),)

    def __repr__(self):
        class_ = type(self)
        return "%s(pk=%r, name=%r, variant_pk=%r)" % (
            class_.__name__,
            self.pk,
            self.name,
            self.product_variant_id,
        )

    def __str__(self):
        return self.name or str(self.product_variant)


class DigitalContent(ModelWithMetadata):
    FILE = "file"
    TYPE_CHOICES = ((FILE, "digital_product"),)
    use_default_settings = models.BooleanField(default=True)
    automatic_fulfillment = models.BooleanField(default=False)
    content_type = models.CharField(max_length=128, default=FILE, choices=TYPE_CHOICES)
    product_variant = models.OneToOneField(
        ProductVariant, related_name="digital_content", on_delete=models.CASCADE
    )
    content_file = models.FileField(upload_to="digital_contents", blank=True)
    max_downloads = models.IntegerField(blank=True, null=True)
    url_valid_days = models.IntegerField(blank=True, null=True)

    def create_new_url(self) -> "DigitalContentUrl":
        return self.urls.create()


class DigitalContentUrl(models.Model):
    token = models.UUIDField(editable=False, unique=True)
    content = models.ForeignKey(
        DigitalContent, related_name="urls", on_delete=models.CASCADE
    )
    created = models.DateTimeField(auto_now_add=True)
    download_num = models.IntegerField(default=0)
    line = models.OneToOneField(
        "order.OrderLine",
        related_name="digital_content_url",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if not self.token:
            self.token = str(uuid4()).replace("-", "")
        super().save(force_insert, force_update, using, update_fields)

    def get_absolute_url(self) -> Optional[str]:
        url = reverse("digital-product", kwargs={"token": str(self.token)})
        return build_absolute_uri(url)


class BaseAttributeQuerySet(models.QuerySet):
    @staticmethod
    def user_has_access_to_all(user: "User") -> bool:
        return user.is_active and user.has_perm(ProductPermissions.MANAGE_PRODUCTS)

    def get_public_attributes(self):
        raise NotImplementedError

    def get_visible_to_user(self, user: "User"):
        if self.user_has_access_to_all(user):
            return self.all()
        return self.get_public_attributes()


class BaseAssignedAttribute(models.Model):
    assignment = None
    values = models.ManyToManyField("AttributeValue")

    class Meta:
        abstract = True

    @property
    def attribute(self):
        return self.assignment.attribute

    @property
    def attribute_pk(self):
        return self.assignment.attribute_id


class AssignedProductAttribute(BaseAssignedAttribute):
    """Associate a product type attribute and selected values to a given product."""

    product = models.ForeignKey(
        Product, related_name="attributes", on_delete=models.CASCADE
    )
    assignment = models.ForeignKey(
        "AttributeProduct", on_delete=models.CASCADE, related_name="productassignments"
    )

    class Meta:
        unique_together = (("product", "assignment"),)


class AssignedVariantAttribute(BaseAssignedAttribute):
    """Associate a product type attribute and selected values to a given variant."""

    variant = models.ForeignKey(
        ProductVariant, related_name="attributes", on_delete=models.CASCADE
    )
    assignment = models.ForeignKey(
        "AttributeVariant", on_delete=models.CASCADE, related_name="variantassignments"
    )

    class Meta:
        unique_together = (("variant", "assignment"),)


class AssociatedAttributeQuerySet(BaseAttributeQuerySet):
    def get_public_attributes(self):
        return self.filter(attribute__visible_in_storefront=True)


class AttributeProduct(SortableModel):
    attribute = models.ForeignKey(
        "Attribute", related_name="attributeproduct", on_delete=models.CASCADE
    )
    product_type = models.ForeignKey(
        ProductType, related_name="attributeproduct", on_delete=models.CASCADE
    )
    assigned_products = models.ManyToManyField(
        Product,
        blank=True,
        through=AssignedProductAttribute,
        through_fields=("assignment", "product"),
        related_name="attributesrelated",
    )

    objects = AssociatedAttributeQuerySet.as_manager()

    class Meta:
        unique_together = (("attribute", "product_type"),)
        ordering = ("sort_order", "pk")

    def get_ordering_queryset(self):
        return self.product_type.attributeproduct.all()


class AttributeVariant(SortableModel):
    attribute = models.ForeignKey(
        "Attribute", related_name="attributevariant", on_delete=models.CASCADE
    )
    product_type = models.ForeignKey(
        ProductType, related_name="attributevariant", on_delete=models.CASCADE
    )
    assigned_variants = models.ManyToManyField(
        ProductVariant,
        blank=True,
        through=AssignedVariantAttribute,
        through_fields=("assignment", "variant"),
        related_name="attributesrelated",
    )

    objects = AssociatedAttributeQuerySet.as_manager()

    class Meta:
        unique_together = (("attribute", "product_type"),)
        ordering = ("sort_order", "pk")

    def get_ordering_queryset(self):
        return self.product_type.attributevariant.all()


class AttributeQuerySet(BaseAttributeQuerySet):
    def get_unassigned_attributes(self, product_type_pk: int):
        return self.exclude(
            Q(attributeproduct__product_type_id=product_type_pk)
            | Q(attributevariant__product_type_id=product_type_pk)
        )

    def get_assigned_attributes(self, product_type_pk: int):
        return self.filter(
            Q(attributeproduct__product_type_id=product_type_pk)
            | Q(attributevariant__product_type_id=product_type_pk)
        )

    def get_public_attributes(self):
        return self.filter(visible_in_storefront=True)

    def _get_sorted_m2m_field(self, m2m_field_name: str, asc: bool):
        sort_order_field = F(f"{m2m_field_name}__sort_order")
        id_field = F(f"{m2m_field_name}__id")
        if asc:
            sort_method = sort_order_field.asc(nulls_last=True)
            id_sort: Union["OrderBy", "F"] = id_field
        else:
            sort_method = sort_order_field.desc(nulls_first=True)
            id_sort = id_field.desc()

        return self.order_by(sort_method, id_sort)

    def product_attributes_sorted(self, asc=True):
        return self._get_sorted_m2m_field("attributeproduct", asc)

    def variant_attributes_sorted(self, asc=True):
        return self._get_sorted_m2m_field("attributevariant", asc)


class Attribute(ModelWithMetadata):
    slug = models.SlugField(max_length=250, unique=True, allow_unicode=True)
    name = models.CharField(max_length=255)

    input_type = models.CharField(
        max_length=50,
        choices=AttributeInputType.CHOICES,
        default=AttributeInputType.DROPDOWN,
    )

    product_types = models.ManyToManyField(
        ProductType,
        blank=True,
        related_name="product_attributes",
        through=AttributeProduct,
        through_fields=("attribute", "product_type"),
    )
    product_variant_types = models.ManyToManyField(
        ProductType,
        blank=True,
        related_name="variant_attributes",
        through=AttributeVariant,
        through_fields=("attribute", "product_type"),
    )

    value_required = models.BooleanField(default=False, blank=True)
    is_variant_only = models.BooleanField(default=False, blank=True)
    visible_in_storefront = models.BooleanField(default=True, blank=True)

    filterable_in_storefront = models.BooleanField(default=True, blank=True)
    filterable_in_dashboard = models.BooleanField(default=True, blank=True)

    storefront_search_position = models.IntegerField(default=0, blank=True)
    available_in_grid = models.BooleanField(default=True, blank=True)

    objects = AttributeQuerySet.as_manager()
    translated = TranslationProxy()

    class Meta:
        ordering = ("storefront_search_position", "slug")

    def __str__(self) -> str:
        return self.name

    def has_values(self) -> bool:
        return self.values.exists()


class AttributeTranslation(models.Model):
    language_code = models.CharField(max_length=10)
    attribute = models.ForeignKey(
        Attribute, related_name="translations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = (("language_code", "attribute"),)

    def __repr__(self):
        class_ = type(self)
        return "%s(pk=%r, name=%r, attribute_pk=%r)" % (
            class_.__name__,
            self.pk,
            self.name,
            self.attribute_id,
        )

    def __str__(self) -> str:
        return self.name


class AttributeValue(SortableModel):
    name = models.CharField(max_length=250)
    value = models.CharField(max_length=100, blank=True, default="")
    slug = models.SlugField(max_length=255, allow_unicode=True)
    attribute = models.ForeignKey(
        Attribute, related_name="values", on_delete=models.CASCADE
    )

    translated = TranslationProxy()

    class Meta:
        ordering = ("sort_order", "pk")
        unique_together = ("slug", "attribute")

    def __str__(self) -> str:
        return self.name

    @property
    def input_type(self):
        return self.attribute.input_type

    def get_ordering_queryset(self):
        return self.attribute.values.all()


class AttributeValueTranslation(models.Model):
    language_code = models.CharField(max_length=10)
    attribute_value = models.ForeignKey(
        AttributeValue, related_name="translations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = (("language_code", "attribute_value"),)

    def __repr__(self) -> str:
        class_ = type(self)
        return "%s(pk=%r, name=%r, attribute_value_pk=%r)" % (
            class_.__name__,
            self.pk,
            self.name,
            self.attribute_value_id,
        )

    def __str__(self) -> str:
        return self.name


def upload_to_product(instance, file_name):

    return "products/product_" + StringUtilities.convert_number_to_string(instance.product.id)+ "_"+ StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds()) + ".png"

class ProductImage(SortableModel):
    product = models.ForeignKey(
        Product, related_name="images", on_delete=models.CASCADE
    )
    image = VersatileImageField(upload_to=upload_to_product, ppoi_field="ppoi", blank=False)
    ppoi = PPOIField()
    alt = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ("sort_order", "pk")
        app_label = "product"

    def get_ordering_queryset(self):
        return self.product.images.all()

    def save(self, *args, **kwargs):
        
        super().save(*args, **kwargs)
        
        from saleor.product.thumbnails import create_product_thumbnails
        create_product_thumbnails(self.pk)
        


class VariantImage(models.Model):
    variant = models.ForeignKey(
        "ProductVariant", related_name="variant_images", on_delete=models.CASCADE
    )
    image = models.ForeignKey(
        ProductImage, related_name="variant_images", on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("variant", "image")


class CollectionProduct(ModelWithCreateTimestamp,SortableModel):
    collection = models.ForeignKey(
        "Collection", related_name="collectionproduct", on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        Product, related_name="collectionproduct", on_delete=models.CASCADE
    )

    class Meta:
        unique_together = (("collection", "product"),)

    def get_ordering_queryset(self):
        return self.product.collectionproduct.all()


class Collection(SeoModel, ModelWithMetadata, PublishableModel, ModelWithCreateUpdateTimestamp):
    name = models.CharField(max_length=250)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    products = models.ManyToManyField(
        Product,
        blank=True,
        related_name="collections",
        through=CollectionProduct,
        through_fields=("collection", "product"),
    )
    background_image = VersatileImageField(
        upload_to="collection-backgrounds", blank=True, null=True
    )
    background_image_alt = models.CharField(max_length=128, blank=True)
    description = models.TextField(blank=True)
    description_json = JSONField(blank=True, default=dict)

    image_url = models.TextField(blank=True)
    is_default = models.BooleanField(default=False, db_index=True)
    shop_look = models.BooleanField(default=False)
    is_thrift = models.BooleanField(default=False)
    media_type = models.TextField(default="image")
    ideas = models.BooleanField(default=False)
    translated = TranslationProxy()
    redirect_url = models.TextField(blank=True)
    collection_type = models.CharField(max_length=64, 
                            choices=CollectionTypeEnum.CHOICES, 
                            default=CollectionTypeEnum.ZAAMO_CURATION)

    class Meta:
        ordering = ("slug",)

    def __str__(self) -> str:
        return self.name

    @property
    def products_count(self):
        return self.products.count()

    @staticmethod
    def create_instance(info):
        
        if Collection.is_collection_exists(info.get('slug')):
            return

        instance = Collection()
        instance.name = info.get('name')
        instance.slug = info.get('slug')
        instance.image_url = info.get('image_url', '')
        instance.media_type = info.get('media_type','')
        instance.is_default = info.get('is_default', False)
        instance.is_published = info.get('is_published', False)
        instance.publication_date = datetime.date.today()
        instance.is_thrift = info.get('is_thrift',False)
        instance.save()

        return instance

    @staticmethod
    def is_collection_exists(slug):

        if not slug:
            return True

        return Collection.objects.filter(slug=slug).exists()

    @staticmethod
    def get_default_collection():
        return Collection.objects.filter(is_default=True).first()


class CollectionTranslation(SeoModelTranslation):
    language_code = models.CharField(max_length=10)
    collection = models.ForeignKey(
        Collection, related_name="translations", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    description_json = JSONField(blank=True, default=dict)

    class Meta:
        unique_together = (("language_code", "collection"),)

    def __repr__(self):
        class_ = type(self)
        return "%s(pk=%r, name=%r, collection_pk=%r)" % (
            class_.__name__,
            self.pk,
            self.name,
            self.collection_id,
        )

    def __str__(self) -> str:
        return self.name



class CollectionStore(ModelWithCreateTimestamp):

    user = models.ForeignKey(user_models.User, on_delete=models.CASCADE, related_name="collection_store")
    store = models.ForeignKey(store_models.StoreInfo, on_delete=models.CASCADE, related_name="collection_store" )
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name='collection_store')


    class Meta:
        unique_together = (("collection", "store"),)

    @staticmethod
    def create_instance(info):
        instance = CollectionStore()
        instance.user = info.get('user_instance')
        instance.store = info.get('store_instance')
        instance.collection = info.get('collection_instance')

        instance.save()

        return instance

class LandingPageCategories(ModelWithCreateTimestamp):
    
    category = models.OneToOneField(Category, related_name="parent_category", 
                                    on_delete=models.CASCADE, 
                                    limit_choices_to={'parent_id': None})
    sub_categories = models.ManyToManyField(Category, 
                     related_name="sub_categories",
                     through="LandingPageSubCategories",
                     through_fields=['landing_page_category', 'sub_category']
                    )    
    is_visible = models.BooleanField(default=True)
    category_rank = models.PositiveIntegerField(default=0)
    

    class Meta:
        ordering = ('category_rank', 'created_at')

class LandingPageSubCategories(ModelWithCreateTimestamp):
    landing_page_category = models.ForeignKey(LandingPageCategories, 
                                              related_name="through_landing_page_category",
                                              on_delete=models.CASCADE
                                            )
    sub_category = models.ForeignKey(Category, related_name='through_landing_page_subcategory', on_delete=models.CASCADE, limit_choices_to={'parent__isnull':False})
    sub_category_rank = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sub_category_rank', 'created_at')

    def __str__(self) -> str:
        return self.sub_category.name

class SourcingRequest(ModelWithCreateUpdateTimestamp, ModelWithMetadata):

    store = models.ForeignKey(store_models.StoreInfo,on_delete=models.CASCADE ,related_name="product_sourcing")
    influencer_managers = models.TextField(null=True)
    product = models.ForeignKey(Product,on_delete=models.CASCADE ,related_name="product_sourcing")
    variant = models.ForeignKey(ProductVariant,on_delete=models.CASCADE ,related_name="product_sourcing")
    brand = models.ForeignKey(Brand,on_delete=models.CASCADE ,related_name="product_sourcing")
    brand_managers = models.TextField(null=True)
    status = models.CharField(max_length=100, choices=SourcingRequestStatus.CHOICES, 
                                            default=SourcingRequestStatus.REQUEST_RECIEVED)
    user_last_updated = models.ForeignKey(user_models.User,on_delete=models.CASCADE ,related_name="product_sourcing")
    content = models.TextField(null=True)
    brand_collab = models.CharField(max_length=20, choices=BrandCollabStatusForSouringRequest.CHOICES, default=BrandCollabStatusForSouringRequest.NA)
    recommended = models.BooleanField(default=False)
    next_task = models.TextField(null=True, blank=True)
    next_date = models.DateTimeField(null=True, blank=True)
    notification = models.BooleanField(default=False)

class BrandPriceRecord(ModelWithCreateUpdateTimestamp):

    brand_name = models.CharField(max_length=255, blank=True, null=True)
    product_id_brand = models.CharField(max_length=255, blank=True, null=True)
    variant_id_brand = models.CharField(max_length=255, blank=True, null=True)
    source = models.CharField(max_length=225, blank=True, null=True)
    current_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
    )
    current_cost_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True,
    )
    prev_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
    )
    prev_cost_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True,
    )
    
    product_name = models.CharField(max_length=255, blank=True, null=True)
    variant_name = models.CharField(max_length=255, blank=True, null=True)
    data_source = models.CharField(max_length=255, blank=True, null=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ('-updated_at',)
        unique_together = (('brand_name','variant_id_brand'))


class ProductTag(ModelWithMetadata, ModelWithCreateUpdateTimestamp):

    name = models.CharField(max_length=240)
    product = models.ManyToManyField("product.Product", through='ProductTagMapping')

    class Meta:
        ordering = ('-updated_at',)

    def __str__(self) -> str:
        return self.name

class ProductTagMapping(ModelWithCreateUpdateTimestamp):

    product_tag = models.ForeignKey(ProductTag , on_delete=models.CASCADE ,related_name="through_product_tag")
    product = models.ForeignKey("product.Product" , on_delete=models.CASCADE ,related_name="through_product_tag_product")
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE ,related_name="through_product_tag_brand",null=True)
    weight = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True)
    percentile = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True)
    source = models.CharField(max_length=100)

    class Meta:
        ordering = ('-updated_at',)
        unique_together = (("product_tag", "product"),)

class ProductGrouping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    name = models.CharField(max_length=200,unique=True,)
    type = models.CharField(max_length=64, 
                            choices=ProductGroupingEnum.CHOICES, 
                            default=ProductGroupingEnum.TAGGED_COLLECTION)
    rule = JSONField(blank=True, null=True, default=dict, encoder=CustomJsonEncoder)
    product = models.ManyToManyField("product.Product", through='ProductGroupingMapping')
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True,null=True)
    image = VersatileImageField(
        upload_to="productgrouping", blank=True, null=True
    )
    class Meta:
        ordering = ('-updated_at',)

    def steal_deal(self):
        return self.rule.get('stealDeal')

class ProductGroupingMapping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):

    product_grouping = models.ForeignKey(ProductGrouping , on_delete=models.CASCADE ,related_name="through_product_grouping")
    product = models.ForeignKey("product.Product" , on_delete=models.CASCADE ,related_name="through_product_grouping_product")
    weight = models.IntegerField(default=0)

    class Meta:
        ordering = ('weight',)


class ZaamoShopifyCategoryMapping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):

    zaamo_category = models.ForeignKey(Category , on_delete=models.CASCADE,related_name='zaamo_category')
    shopify_category_id = models.CharField(max_length=200)
    shopify_category_name = models.CharField(max_length=200)

    class Meta:
        ordering = ('updated_at',)


class ZaamoShopifyProductMapping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):

    product_zaamo = models.ForeignKey(Product , on_delete=models.CASCADE,related_name='product_zaamo_shopify_mapping')
    variant_zaamo = models.ForeignKey(ProductVariant , on_delete=models.CASCADE,related_name='variant_zaamo_shopify_mapping')
    brand_variant_zaamo_mapping = models.ForeignKey(BrandVariantZaamoMapping , on_delete=models.CASCADE,related_name='zaamo_shopify_mapping',null=True)
    product_id_brand = models.CharField(max_length=200)
    variant_id_brand = models.CharField(max_length=200)
    status = models.CharField(max_length=200)
    extra_charges = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=Decimal('0.0')
    )

    class Meta:
        ordering = ('updated_at',)

class RejectedShopifyProduct(ModelWithCreateUpdateTimestamp):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=127)


class ReelUpMedia(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    
    shopify_file_id = models.CharField(max_length=200)
    title = models.CharField(max_length=200,null=True)
    shopify_media_url = models.TextField(blank=True)
    zaamo_media_url = models.TextField(blank=True)
    status = models.CharField(max_length=64,default='active')
    shopify_store_name = models.TextField(blank=True)

    class Meta:
        ordering = ('updated_at',)

    def reel_image_thumbnail(self):
        image_url = self.shopify_media_url
        try:
            reel_image = self.images.first()
            reel_thumbnail = get_product_image_thumbnail(reel_image, 120, method="thumbnail")
            image_url = reel_thumbnail

        except Exception as e:
            pass

        return image_url

class ReelUpProductMap(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    
    reel_up_media = models.ForeignKey(ReelUpMedia , on_delete=models.CASCADE,related_name='media_mapping')
    shopify_product_id = models.CharField(max_length=200)
    shopify_product_slug = models.CharField(max_length=200)
    shopify_product_url = models.CharField(max_length=2048)
    product_name = models.CharField(max_length=200,default='')
    status = models.CharField(max_length=64,default='active')
    shopify_collection_id = models.CharField(max_length=200)

    class Meta:
        ordering = ('updated_at',)

class ReelUpBrandCollection(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    
    brand_name = models.CharField(max_length=200)
    brand_collection_id = models.CharField(max_length=200)

    class Meta:
        ordering = ('updated_at',)

class ReelUpMediaPlaylist(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    title = models.CharField(max_length=200,unique=True)
    store_name = models.CharField(max_length=200)
    type = models.CharField(max_length=64)
    status = models.CharField(max_length=64,default='active')
    rank = models.IntegerField(default=0)
    
    class Meta:
        ordering = ('-rank','-updated_at')


class ReelUpMediaPlaylistItems(ModelWithCreateUpdateTimestamp,ModelWithMetadata):

    reel_up_media_playlist = models.ForeignKey(ReelUpMediaPlaylist , on_delete=models.CASCADE ,related_name="reel_up_media_playlist_map")
    reel_up_media = models.ForeignKey(ReelUpMedia , on_delete=models.CASCADE ,related_name="reel_up_media_mapp")
    rank = models.IntegerField(default=0)

    class Meta:
        ordering = ('-rank','-updated_at')


class ReelupStore(ModelWithCreateUpdateTimestamp,ModelWithMetadata):

    store_name = models.CharField(max_length=200,unique=True)
    access_pass = models.CharField(max_length=200,default='')
    url = models.CharField(max_length=200,unique=True)

    class Meta:
        ordering = ('-updated_at',)


def upload_to_reel_up(instance, file_name):

    return "reel/reel_" + StringUtilities.convert_number_to_string(instance.reel_up_media.id)+ "_"+ StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds()) + ".png"

class ReelUpMediaImage(SortableModel):
    reel_up_media = models.ForeignKey(
        ReelUpMedia, related_name="images", on_delete=models.CASCADE
    )
    image = VersatileImageField(upload_to=upload_to_reel_up, ppoi_field="ppoi", blank=False)
    ppoi = PPOIField()
    alt = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ("sort_order", "pk")
        app_label = "product"

    def get_ordering_queryset(self):
        return self.reel_up_media.images.all()

    def save(self, *args, **kwargs):
        
        super().save(*args, **kwargs)
        
        from saleor.product.thumbnails import create_reel_up_thumbnails
        create_reel_up_thumbnails(self.pk)
