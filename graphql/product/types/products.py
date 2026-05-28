from dataclasses import asdict
from typing import List, Union
import graphene
from django.conf import settings
from django.db.models import Count, Q, F, Subquery, OuterRef, Value, Case, When, Func, DateTimeField, ExpressionWrapper,Prefetch, BigIntegerField, TextField
from django.db.models.functions import Concat, ExtractDay, Cast
from graphene import relay
from graphene_federation import key
from graphql.error import GraphQLError

from saleor.brand.models import Brand,BrandCollection
from graphene_django.fields import DjangoConnectionField
from ....core.permissions import OrderPermissions, ProductPermissions
from ....core.weight import convert_weight_to_default_weight_unit
from ....product import BarterType, SourcingRequestStatus, models
from ....product.templatetags.product_images import (
    get_product_image_thumbnail,
    get_thumbnail,
)
from ....product.utils import calculate_revenue_for_variant
from ....product.utils.availability import (
    get_product_availability,
    get_variant_availability,
)
from ....product.utils.costs import get_margin_for_variant, get_product_costs_data
from ....warehouse.availability import (
    get_available_quantity,
    get_quantity_allocated,
    is_product_in_stock,
)
from ...account.enums import CountryCodeEnum
from ...core.connection import CountableConnection, CountableDjangoObjectType
from ...core.enums import ReportingPeriod, TaxRateType
from ..enums import CollectionMediaTypeEnum
from ...core.fields import BaseConnectionField, FilterInputConnectionField, PrefetchingConnectionField
from ...core.types import Image, Money, MoneyRange, TaxedMoney, TaxedMoneyRange, TaxType
from ...decorators import one_of_permissions_required, permission_required
from ...discount.dataloaders import DiscountsByDateTimeLoader
from ...meta.deprecated.resolvers import resolve_meta, resolve_private_meta
from ...meta.types import ObjectWithMetadata
from ...translations.fields import TranslationField
from ...translations.types import (
    CategoryTranslation,
    CollectionTranslation,
    ProductTranslation,
    ProductVariantTranslation,
)
from ...utils import get_database_id, get_requested_fields, get_user_or_app_from_context,resolve_global_ids_to_primary_keys
from ...utils.filters import reporting_period_to_date
from ...warehouse.dataloaders import (
    AvailableQuantityByProductVariantIdAndCountryCodeLoader,
)
from ...warehouse.types import Stock
from ..dataloaders import (
    CategoryByIdLoader,
    BrandByIdLoader,
    CollectionsByProductIdLoader,
    ImagesByProductIdLoader,
    ImagesByProductVariantIdLoader,
    ProductAttributesByProductTypeIdLoader,
    ProductByIdLoader,
    ProductTypeByIdLoader,
    ProductVariantByIdLoader,
    ProductVariantsByProductIdLoader,
    SelectedAttributesByProductIdLoader,
    SelectedAttributesByProductVariantIdLoader,
    VariantAttributesByProductTypeIdLoader,
)
from ..filters import AttributeFilterInput, ProductFilterInput
from ..resolvers import resolve_attributes, resolve_order_count_product, resolve_store_count_product, resolve_tagged_products, resolve_wishlist_count_product,resolve_store_slug
from ..sorters import ProductOrder
from .attributes import Attribute, SelectedAttribute
from .digital_contents import DigitalContent
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.discount.models import Voucher
from saleor.order import FulfillmentStatus, SourcingRequestOrderStatusFilter
from saleor.order.models import Fulfillment, FulfillmentLine, Order
from saleor.account.models import User
from saleor.brand.states import BrandEmailStateEnum
from django.contrib.postgres.fields.jsonb import KeyTextTransform



def resolve_attribute_list(
    instance: Union[models.Product, models.ProductVariant], *, user
) -> List[SelectedAttribute]:
    """Resolve attributes from a product into a list of `SelectedAttribute`s.

    Note: you have to prefetch the below M2M fields.
        - product_type -> attribute[rel] -> [rel]assignments -> values
        - product_type -> attribute[rel] -> attribute
    """
    resolved_attributes = []
    attributes_qs = None

    # Retrieve the product type
    if isinstance(instance, models.Product):
        product_type = instance.product_type
        product_type_attributes_assoc_field = "attributeproduct"
        assigned_attribute_instance_field = "productassignments"
        assigned_attribute_instance_filters = {"product_id": instance.pk}
        if hasattr(product_type, "storefront_attributes"):
            attributes_qs = product_type.storefront_attributes  # type: ignore
    elif isinstance(instance, models.ProductVariant):
        product_type = instance.product.product_type
        product_type_attributes_assoc_field = "attributevariant"
        assigned_attribute_instance_field = "variantassignments"
        assigned_attribute_instance_filters = {"variant_id": instance.pk}
    else:
        raise AssertionError(f"{instance.__class__.__name__} is unsupported")

    # Retrieve all the product attributes assigned to this product type
    if not attributes_qs:
        attributes_qs = getattr(product_type, product_type_attributes_assoc_field)
        attributes_qs = attributes_qs.get_visible_to_user(user)

    # An empty QuerySet for unresolved values
    empty_qs = models.AttributeValue.objects.none()

    # Goes through all the attributes assigned to the product type
    # The assigned values are returned as a QuerySet, but will assign a
    # dummy empty QuerySet if no values are assigned to the given instance.
    for attr_data_rel in attributes_qs:
        attr_instance_data = getattr(attr_data_rel, assigned_attribute_instance_field)

        # Retrieve the instance's associated data
        attr_data = attr_instance_data.filter(**assigned_attribute_instance_filters)
        attr_data = attr_data.first()

        # Return the instance's attribute values if the assignment was found,
        # otherwise it sets the values as an empty QuerySet
        values = attr_data.values.all() if attr_data is not None else empty_qs
        resolved_attributes.append(
            SelectedAttribute(attribute=attr_data_rel.attribute, values=values)
        )
    return resolved_attributes


class Margin(graphene.ObjectType):
    start = graphene.Int()
    stop = graphene.Int()


class BasePricingInfo(graphene.ObjectType):
    on_sale = graphene.Boolean(description="Whether it is in sale or not.")
    discount = graphene.Field(
        TaxedMoney, description="The discount amount if in sale (null otherwise)."
    )
    discount_local_currency = graphene.Field(
        TaxedMoney, description="The discount amount in the local currency."
    )


class VariantPricingInfo(BasePricingInfo):
    discount_local_currency = graphene.Field(
        TaxedMoney, description="The discount amount in the local currency."
    )
    price = graphene.Field(
        TaxedMoney, description="The price, with any discount subtracted."
    )
    price_undiscounted = graphene.Field(
        TaxedMoney, description="The price without any discount."
    )
    price_local_currency = graphene.Field(
        TaxedMoney, description="The discounted price in the local currency."
    )

    class Meta:
        description = "Represents availability of a variant in the storefront."


class ProductPricingInfo(BasePricingInfo):
    price_range = graphene.Field(
        TaxedMoneyRange,
        description="The discounted price range of the product variants.",
    )
    price_range_undiscounted = graphene.Field(
        TaxedMoneyRange,
        description="The undiscounted price range of the product variants.",
    )
    price_range_local_currency = graphene.Field(
        TaxedMoneyRange,
        description=(
            "The discounted price range of the product variants "
            "in the local currency."
        ),
    )

    class Meta:
        description = "Represents availability of a product in the storefront."


@key(fields="id")
class ProductVariant(CountableDjangoObjectType):
    quantity = graphene.Int(
        required=True,
        description="Quantity of a product available for sale.",
        deprecation_reason=(
            "Use the stock field instead. This field will be removed after 2020-07-31."
        ),
    )
    quantity_allocated = graphene.Int(
        required=False,
        description="Quantity allocated for orders.",
        deprecation_reason=(
            "Use the stock field instead. This field will be removed after 2020-07-31."
        ),
    )
    stock_quantity = graphene.Int(
        required=True,
        description="Quantity of a product available for sale.",
        deprecation_reason=(
            "Use the quantityAvailable field instead. "
            "This field will be removed after 2020-07-31."
        ),
    )
    price = graphene.Field(
        Money,
        description=(
            "Base price of a product variant. "
            "This field is restricted for admins. "
            "Use the pricing field to get the public price for customers."
        ),
    )

    pricing = graphene.Field(
        VariantPricingInfo,
        description=(
            "Lists the storefront variant's pricing, the current price and discounts, "
            "only meant for displaying."
        ),
    )
    is_available = graphene.Boolean(
        description="Whether the variant is in stock and visible or not.",
        deprecation_reason=(
            "Use the stock field instead. This field will be removed after 2020-07-31."
        ),
    )

    attributes = graphene.List(
        graphene.NonNull(SelectedAttribute),
        required=True,
        description="List of attributes assigned to this variant.",
    )
    cost_price = graphene.Field(Money, description="Cost price of the variant.")
    margin = graphene.Int(description="Gross margin percentage value.")
    quantity_ordered = graphene.Int(description="Total quantity ordered.")
    revenue = graphene.Field(
        TaxedMoney,
        period=graphene.Argument(ReportingPeriod),
        description=(
            "Total revenue generated by a variant in given period of time. Note: this "
            "field should be queried using `reportProductSales` query as it uses "
            "optimizations suitable for such calculations."
        ),
    )
    images = graphene.List(
        lambda: ProductImage, description="List of images for the product variant."
    )
    translation = TranslationField(
        ProductVariantTranslation, type_name="product variant"
    )
    digital_content = graphene.Field(
        DigitalContent, description="Digital content for the product variant."
    )
    stocks = graphene.Field(
        graphene.List(Stock),
        description="Stocks for the product variant.",
        country_code=graphene.Argument(
            CountryCodeEnum,
            description="Two-letter ISO 3166-1 country code.",
            required=False,
        ),
    )
    quantity_available = graphene.Int(
        required=True,
        description="Quantity of a product available for sale in one checkout.",
        country_code=graphene.Argument(
            CountryCodeEnum,
            description=(
                "Two-letter ISO 3166-1 country code. When provided, the exact quantity "
                "from a warehouse operating in shipping zones that contain this "
                "country will be returned. Otherwise, it will return the maximum "
                "quantity from all shipping zones."
            ),
        ),
    )

    discount_percentage = graphene.String(description= "Discount applied on variant")

    class Meta:
        description = (
            "Represents a version of a product such as different size or color."
        )
        only_fields = ["id", "name", "product", "sku", "track_inventory", "weight"]
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.ProductVariant

    @staticmethod
    @one_of_permissions_required(
        [ProductPermissions.MANAGE_PRODUCTS, OrderPermissions.MANAGE_ORDERS]
    )
    def resolve_stocks(root: models.ProductVariant, info, country_code=None):
        if not country_code:
            return root.stocks.annotate_available_quantity()
        return root.stocks.for_country(country_code).annotate_available_quantity()

    @staticmethod
    def resolve_quantity_available(
        root: models.ProductVariant, info, country_code=None
    ):
        if not root.track_inventory:
            return settings.MAX_CHECKOUT_LINE_QUANTITY

        return AvailableQuantityByProductVariantIdAndCountryCodeLoader(
            info.context
        ).load((root.id, country_code))

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_digital_content(root: models.ProductVariant, *_args):
        return getattr(root, "digital_content", None)

    @staticmethod
    def resolve_stock_quantity(root: models.ProductVariant, info):
        if not root.track_inventory:
            return settings.MAX_CHECKOUT_LINE_QUANTITY

        return AvailableQuantityByProductVariantIdAndCountryCodeLoader(
            info.context
        ).load((root.id, info.context.country))

    @staticmethod
    def resolve_attributes(root: models.ProductVariant, info):
        return SelectedAttributesByProductVariantIdLoader(info.context).load(root.id)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_margin(root: models.ProductVariant, *_args):
        return get_margin_for_variant(root)

    @staticmethod
    def resolve_cost_price(root: models.ProductVariant, *_args):
        return root.cost_price

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_price(root: models.ProductVariant, *_args):
        return root.price

    @staticmethod
    def resolve_pricing(root: models.ProductVariant, info):
        
        # ********************************************************************
            # Commenting code as sales and taxation are disabled.
         # ********************************************************************

        # context = info.context
        # product = ProductByIdLoader(context).load(root.product_id)
        # collections = CollectionsByProductIdLoader(context).load(root.product_id)
        
        # def calculate_pricing_info(discounts):
        #     def calculate_pricing_with_product(product):
        #         def calculate_pricing_with_collections(collections):
        #             availability = get_variant_availability(
        #                 variant=root,
        #                 product=product,
        #                 collections=collections,
        #                 discounts=discounts,
        #                 country=context.country,
        #                 local_currency=context.currency,
        #                 plugins=context.plugins,
        #             )
                    
        #             return VariantPricingInfo(**asdict(availability))

        #         return collections.then(calculate_pricing_with_collections)

        #     return product.then(calculate_pricing_with_product)

        # return (
        #     DiscountsByDateTimeLoader(context)
        #     .load(info.context.request_time)
        #     .then(calculate_pricing_info)
        # )


        availability = {
        'on_sale': False, 
        'price': TaxedMoney(net=root.price, gross=root.price), 
        'price_undiscounted': TaxedMoney(net=root.price, gross=root.price), 
        'discount': None, 
        'price_local_currency': None, 
        'discount_local_currency': None
        }

        return VariantPricingInfo(**availability)

    def resolve_discount_percentage(root: models.ProductVariant, info):
        
        percentage = ((root.cost_price - root.price)*100/root.cost_price)
        
        return "{0:.3f}".format(percentage)


    @staticmethod
    def resolve_product(root: models.ProductVariant, info):
        return ProductByIdLoader(info.context).load(root.product_id)

    @staticmethod
    def resolve_is_available(root: models.ProductVariant, info):
        if not root.track_inventory:
            return True

        def is_variant_in_stock(available_quantity):
            return available_quantity > 0

        return (
            AvailableQuantityByProductVariantIdAndCountryCodeLoader(info.context)
            .load((root.id, info.context.country))
            .then(is_variant_in_stock)
        )

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_quantity(root: models.ProductVariant, info):
        return get_available_quantity(root, info.context.country)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_quantity_ordered(root: models.ProductVariant, *_args):
        # This field is added through annotation when using the
        # `resolve_report_product_sales` resolver.
        return getattr(root, "quantity_ordered", None)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_quantity_allocated(root: models.ProductVariant, info):
        country = info.context.country
        return get_quantity_allocated(root, country)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_revenue(root: models.ProductVariant, *_args, period):
        start_date = reporting_period_to_date(period)
        return calculate_revenue_for_variant(root, start_date)

    @staticmethod
    def resolve_images(root: models.ProductVariant, info, *_args):
        return ImagesByProductVariantIdLoader(info.context).load(root.id)

    @classmethod
    def get_node(cls, info, pk):
        requestor = get_user_or_app_from_context(info.context)
        visible_products = models.Product.objects.visible_to_user(
            requestor
        ).values_list("pk", flat=True)
        qs = cls._meta.model.objects.filter(product__id__in=visible_products)
        return qs.filter(pk=pk).first()

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_private_meta(root: models.ProductVariant, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.ProductVariant, _info):
        return resolve_meta(root, _info)

    @staticmethod
    def __resolve_reference(root, _info, **_kwargs):
        return graphene.Node.get_node_from_global_id(_info, root.id)

    @staticmethod
    def resolve_weight(root: models.ProductVariant, _info, **_kwargs):
        return convert_weight_to_default_weight_unit(root.weight)


@key(fields="id")
class Product(CountableDjangoObjectType):
    url = graphene.String(
        description="The storefront URL for the product.",
        required=True,
        deprecation_reason="This field will be removed after 2020-07-31.",
    )
    thumbnail = graphene.Field(
        Image,
        description="The main thumbnail for a product.",
        size=graphene.Argument(graphene.Int, description="Size of thumbnail."),
    )
    pricing = graphene.Field(
        ProductPricingInfo,
        description=(
            "Lists the storefront product's pricing, the current price and discounts, "
            "only meant for displaying."
        ),
    )
    is_available = graphene.Boolean(
        description="Whether the product is in stock and visible or not."
    )
    minimal_variant_price = graphene.Field(
        Money, description="The price of the cheapest variant (including discounts)."
    )
    tax_type = graphene.Field(
        TaxType, description="A type of tax. Assigned by enabled tax gateway"
    )
    attributes = graphene.List(
        graphene.NonNull(SelectedAttribute),
        required=True,
        description="List of attributes assigned to this product.",
    )
    purchase_cost = graphene.Field(MoneyRange)
    margin = graphene.Field(Margin)
    image_by_id = graphene.Field(
        lambda: ProductImage,
        id=graphene.Argument(graphene.ID, description="ID of a product image."),
        description="Get a single product image by ID.",
    )
    variants = graphene.List(
        ProductVariant, description="List of variants for the product."
    )
    images = graphene.List(
        lambda: ProductImage, description="List of images for the product."
    )
    collections = graphene.List(
        lambda: Collection, description="List of collections for the product.",
        stores=graphene.Argument(graphene.List(graphene.ID,description="ID of store"), description=" List of stores for the product"
        )
    )
    translation = TranslationField(ProductTranslation, type_name="product")
    is_available_for_purchase = graphene.Boolean(
        description="Whether the product is available for purchase."
    )
    is_published = graphene.Boolean(
        required=True, description="Whether the product is published."
    )
    description = graphene.String(
        description="Description of the product.",
        deprecation_reason="Use the `descriptionJson` field instead.",
        required=True,
    )
    visits = graphene.Int(
        description="Product page visits for a particular store or all stores."
    )
    brand_barter = graphene.Boolean(description = "Brand Barter only when product and brand both are true ")
    too_many_orders = graphene.Boolean(description = "Too many Order for product depending on brand")
    available_for_cod = graphene.Boolean(description = "boolean value if product available for cod.")
    class Meta:
        description = "Represents an individual item for sale in the storefront."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Product
        only_fields = [
            "available_for_purchase",
            "category",
            "brand",
            "charge_taxes",
            "description_json",
            "id",
            "name",
            "slug",
            "has_custom_commission",
            "commission_percentage",
            "product_type",
            "publication_date",
            "seo_description",
            "seo_title",
            "updated_at",
            "weight",
            "visible_in_listings",
            "default_variant",
            "available_for_cod",
            "step_price"
        ]

    @staticmethod
    def resolve_default_variant(root: models.Product, info):
        default_variant_id = root.default_variant_id
        if default_variant_id is None:
            variant = root.variants.order_by('price_amount').first()
            if variant:
                root.default_variant = variant
                root.save()
            else:    
                return None

        return ProductVariantByIdLoader(info.context).load(root.default_variant_id)

    @staticmethod
    def resolve_category(root: models.Product, info):
        category_id = root.category_id
        if category_id is None:
            return None

        return CategoryByIdLoader(info.context).load(category_id)
    
    @staticmethod
    def resolve_brand(root: models.Product, info):
        brand_id = root.brand_id
        if brand_id is None:
            return None

        return BrandByIdLoader(info.context).load(brand_id)
    
    @staticmethod
    def resolve_available_for_cod(root: models.Product, info):
        brand_id = root.brand_id
        if brand_id is None:
            return False
        return root.brand.cod

    @staticmethod
    def resolve_tax_type(root: models.Product, info):
        tax_data = info.context.plugins.get_tax_code_from_object_meta(root)
        return TaxType(tax_code=tax_data.code, description=tax_data.description)

    @staticmethod
    def resolve_thumbnail(root: models.Product, info, *, size=1080):
        search_image = root.metadata.get('search_image')
        if search_image:
            if size > 1000:
                res = 1080
            elif size > 500:
                res = 600
            else:
                res = 400
            thumbnail_url = search_image.rsplit('.', 1)[0] + f'_{res}.jpeg' 
            return Image(url=thumbnail_url, alt='')

        def return_first_thumbnail(images):
            image = images[0] if images else None
            if image:
                url = get_product_image_thumbnail(image, size, method="thumbnail")
                alt = image.alt
                return Image(alt=alt, url=info.context.build_absolute_uri(url))
            return None

        return (
            ImagesByProductIdLoader(info.context)
            .load(root.id)
            .then(return_first_thumbnail)
        )

    @staticmethod
    def resolve_url(root: models.Product, *_args):
        return ""

    @staticmethod
    def resolve_pricing(root: models.Product, info):
        context = info.context
        variants = ProductVariantsByProductIdLoader(context).load(root.id)
        collections = CollectionsByProductIdLoader(context).load(root.id)

        def calculate_pricing_info(discounts):
            def calculate_pricing_with_variants(variants):
                def calculate_pricing_with_collections(collections):
                    availability = get_product_availability(
                        product=root,
                        variants=variants,
                        collections=collections,
                        discounts=discounts,
                        country=context.country,
                        local_currency=context.currency,
                        plugins=context.plugins,
                    )
                    return ProductPricingInfo(**asdict(availability))

                return collections.then(calculate_pricing_with_collections)

            return variants.then(calculate_pricing_with_variants)

        return (
            DiscountsByDateTimeLoader(context)
            .load(info.context.request_time)
            .then(calculate_pricing_info)
        )

    @staticmethod
    def resolve_is_available(root: models.Product, info):
        country = info.context.country
        in_stock = is_product_in_stock(root, country)
        return root.is_visible and in_stock

    @staticmethod
    def resolve_attributes(root: models.Product, info):
        return SelectedAttributesByProductIdLoader(info.context).load(root.id)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_purchase_cost(root: models.Product, *_args):
        purchase_cost, _ = get_product_costs_data(root)
        return purchase_cost

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_margin(root: models.Product, *_args):
        _, margin = get_product_costs_data(root)
        return Margin(margin[0], margin[1])

    @staticmethod
    def resolve_image_by_id(root: models.Product, info, id):
        pk = get_database_id(info, id, ProductImage)
        try:
            return root.images.get(pk=pk)
        except models.ProductImage.DoesNotExist:
            raise GraphQLError("Product image not found.")

    @staticmethod
    def resolve_images(root: models.Product, info, **_kwargs):
        return ImagesByProductIdLoader(info.context).load(root.id)

    @staticmethod
    def resolve_variants(root: models.Product, info, **_kwargs):
        return ProductVariantsByProductIdLoader(info.context).load(root.id)

    @staticmethod
    def resolve_collections(root: models.Product, *_args,stores=""):
        from saleor.graphql.store.types import Store
        if stores:
            types,store_ids = resolve_global_ids_to_primary_keys(stores,Store)
            return root.collections.filter(collection_store__store__in=store_ids)
        else:
            return root.collections.all()

    @classmethod
    def get_node(cls, info, pk):
        if info.context:
            requestor = get_user_or_app_from_context(info.context)
            qs = cls._meta.model.objects.visible_to_user(requestor)
            return qs.filter(pk=pk).first()
        return None

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_private_meta(root: models.Product, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.Product, _info):
        return resolve_meta(root, _info)

    @staticmethod
    def __resolve_reference(root, _info, **_kwargs):
        return graphene.Node.get_node_from_global_id(_info, root.id)

    @staticmethod
    def resolve_weight(root: models.Product, _info, **_kwargs):
        return convert_weight_to_default_weight_unit(root.weight)

    @staticmethod
    def resolve_is_available_for_purchase(root: models.Product, _info):
        return root.is_available_for_purchase()

    @staticmethod
    def resolve_product_type(root: models.Product, info):
        return ProductTypeByIdLoader(info.context).load(root.product_type_id)

    @staticmethod
    def resolve_is_published(root: models.Product, _info):
        return root.is_visible
    
    @staticmethod
    def resolve_brand_barter(root: models.Product ,_info):
        brand = root.brand

        if brand:
            if brand.brand_barter and root.brand_barter in (BarterType.ACTIVE_BARTER, BarterType.ACTIVE_ONLY_BARTER):
                return True
        
        return False
    
    @staticmethod
    def resolve_visits(root: models.Product, info):
        if not hasattr(root, 'visits'):
            store_id = RequestUtilities.get_store_id_from_headers(info.context)
            visits = 0
            for store in root.storeproductviews_set.filter(store=store_id).all():
                visits += store.views
            return visits
        return root.visits

    @staticmethod
    def resolve_too_many_orders(root: models.Product, info):
        brand = root.brand
        if brand:
            return brand.too_many_orders
        
        return False

@key(fields="id")
class ProductType(CountableDjangoObjectType):
    products = PrefetchingConnectionField(
        Product, description="List of products of this type."
    )
    tax_rate = TaxRateType(
        description="A type of tax rate.",
        deprecation_reason=(
            "Use the TaxType instead. It will be removed in Saleor 3.0."
        ),
    )
    tax_type = graphene.Field(
        TaxType, description="A type of tax. Assigned by enabled tax gateway"
    )
    variant_attributes = graphene.List(
        Attribute, description="Variant attributes of that product type."
    )
    product_attributes = graphene.List(
        Attribute, description="Product attributes of that product type."
    )
    available_attributes = FilterInputConnectionField(
        Attribute, filter=AttributeFilterInput()
    )

    class Meta:
        description = (
            "Represents a type of product. It defines what attributes are available to "
            "products of this type."
        )
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.ProductType
        only_fields = [
            "has_variants",
            "id",
            "is_digital",
            "is_shipping_required",
            "name",
            "slug",
            "weight",
            "tax_type",
        ]

    @staticmethod
    def resolve_tax_type(root: models.ProductType, info):
        tax_data = info.context.plugins.get_tax_code_from_object_meta(root)
        return TaxType(tax_code=tax_data.code, description=tax_data.description)

    @staticmethod
    def resolve_tax_rate(root: models.ProductType, _info, **_kwargs):
        # FIXME this resolver should be dropped after we drop tax_rate from API
        if not hasattr(root, "meta"):
            return None
        return root.get_value_from_metadata("vatlayer.code")

    @staticmethod
    def resolve_product_attributes(root: models.ProductType, info):
        return ProductAttributesByProductTypeIdLoader(info.context).load(root.pk)

    @staticmethod
    def resolve_variant_attributes(root: models.ProductType, info):
        return VariantAttributesByProductTypeIdLoader(info.context).load(root.pk)

    @staticmethod
    def resolve_products(root: models.ProductType, info, **_kwargs):
        return root.products.visible_to_user(info.context.user)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_available_attributes(root: models.ProductType, info, **kwargs):
        qs = models.Attribute.objects.get_unassigned_attributes(root.pk)
        return resolve_attributes(info, qs=qs, **kwargs)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_private_meta(root: models.ProductType, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.ProductType, _info):
        return resolve_meta(root, _info)

    @staticmethod
    def __resolve_reference(root, _info, **_kwargs):
        return graphene.Node.get_node_from_global_id(_info, root.id)

    @staticmethod
    def resolve_weight(root: models.ProductType, _info, **_kwargs):
        return convert_weight_to_default_weight_unit(root.weight)


@key(fields="id")
class Collection(CountableDjangoObjectType):
    products = FilterInputConnectionField(
        Product,
        filter=ProductFilterInput(description="Filtering options for products."),
        sort_by=ProductOrder(description="Sort products."),
        description="List of products in this collection.",
    )
    background_image = graphene.Field(
        Image, size=graphene.Int(description="Size of the image.")
    )
    description = graphene.String(
        description="Description of the collection.",
        deprecation_reason="Use the `descriptionJson` field instead.",
        required=True,
    )
    translation = TranslationField(CollectionTranslation, type_name="collection")
    is_published = graphene.Boolean(
        required=True, description="Whether the collection is published."
    )
    collection_views = graphene.Int(description="Collection views for a particular store")
    
    store = graphene.Field("saleor.graphql.store.types.Store", description="Store to which this collection is related")
    
    has_active_steal_deal = graphene.Boolean(description = "If collection has more than or equal to 25 products it will return true")

    latest_added_product_datetime = graphene.String(
        description="Latest added product datetime")

    is_collection_added_to_store = graphene.Boolean(description = "If collection is already added or not")

    total_number_of_products = graphene.Int(description = "Total number of products of a collection")

    shareable_link = graphene.String(description = "Link to share the collection")

    class Meta:
        description = "Represents a collection of products."
        only_fields = [
            "description_json",
            "id",
            "name",
            "publication_date",
            "seo_description",
            "seo_title",
            "slug",
            "created_at",
            "updated_at",
            "image_url",
            "is_default",
            "shop_look",
            "is_thrift",
            "media_type",
            "ideas",
            "redirect_url",
            "collection_type"
        ]
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Collection
    
    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)

        collection_products = models.Collection.objects.filter(id=OuterRef('id'))\
            .annotate(products_count = Count('collectionproduct', distinct=True, filter=Q(
                collectionproduct__created_at__gt=TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(), days=7)))
            ).values('products_count')[:1]
        
        qs = qs.annotate(total_collection_products=Subquery(collection_products))

        if info.variable_values.get('landing') == True or info.variable_values.get('valueDeal') == True:
            product_count_sq = models.CollectionProduct.objects.filter(collection_id=OuterRef('id'))\
                .annotate(total_product_count=Func('product_id', function='COUNT')).values('total_product_count')[:1]
            
            qs = qs.annotate(total_product_count=Subquery(product_count_sq)).filter(total_product_count__gt=15)

        return qs

    def resolve_collection_views(root, info, **_kwargs):
        views = 0
        if 'collection_views' in info.variable_values:
            views = info.variable_values['collection_views'].get(root.id, 0)
        return views

    def resolve_store(root: models.Collection, _info):
        if hasattr(root, 'store_name'):
            from saleor.graphql.store.types import Store
            return Store(store_name=root.store_name)

        return root.collection_store.first().store
    
    def resolve_latest_added_product_datetime(root: models.Collection, _info):

        latest_collection_product = root.collectionproduct.last()
        if latest_collection_product:
            return latest_collection_product.created_at

        return root.created_at

    @staticmethod
    def resolve_background_image(root: models.Collection, info, size=None, **_kwargs):
        if root.background_image:
            return Image.get_adjusted(
                image=root.background_image,
                alt=root.background_image_alt,
                size=size,
                rendition_key_set="background_images",
                info=info,
            )

    @staticmethod
    def resolve_products(root: models.Collection, info, first=None, **kwargs):
        return root.products.select_related("brand").visible_to_user(info.context.user)

    @classmethod
    def get_node(cls, info, id):
        if info.context:
            return cls._meta.model.objects.filter(id=id).first()
        
        return None

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_private_meta(root: models.Collection, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.Collection, _info):
        return resolve_meta(root, _info)

    @staticmethod
    def __resolve_reference(root, _info, **_kwargs):
        return graphene.Node.get_node_from_global_id(_info, root.id)

    @staticmethod
    def resolve_is_published(root: models.Collection, _info):
        return root.is_visible
    
    def resolve_media_type(root: models.Collection, _info):
        return root.media_type

    def resolve_has_active_steal_deal(root:models.Collection , info):

        num = None

        if 'product_count' in info.variable_values:
            num = info.variable_values['product_count'].get(root.id, 0)
            

        if not num:
            num = root.collectionproduct.all().count()

        val = NumberUtilities.convert_string_to_number(settings.STEAL_DEAL_LIMIT)
        if num >= val:
            return True
        else:
            return False

    def resolve_is_collection_added_to_store(root: models.Collection, info):
        store_id =  RequestUtilities.get_store_id_from_headers(info.context)
        stores = root.metadata.get('stores', [])

        return NumberUtilities.convert_string_to_number(store_id) in stores
   
    def resolve_total_number_of_products(root:models.Collection , info):

        return root.total_collection_products

    def resolve_shareable_link(root:models.Collection,info):
        store_id =  RequestUtilities.get_store_id_from_headers(info.context)
        if store_id:
            store_slug = resolve_store_slug(store_id)
            return "{}{}/collection/{}".format(settings.ZAAMO_ENV_LINK,store_slug,root.slug)
        else:
            return None


@key(fields="id")
class Category(CountableDjangoObjectType):
    ancestors = PrefetchingConnectionField(
        lambda: Category, description="List of ancestors of the category."
    )
    products = FilterInputConnectionField(
        Product,
        filter=ProductFilterInput(description="Filtering options for products."), 
        sort_by=ProductOrder(description="Sort products."),
        description="List of products in the category."
    )
    url = graphene.String(
        description="The storefront's URL for the category.",
        deprecation_reason="This field will be removed after 2020-07-31.",
    )
    description = graphene.String(
        description="Description of the category.",
        deprecation_reason="Use the `descriptionJson` field instead.",
        required=True,
    )
    children = PrefetchingConnectionField(
        lambda: Category, description="List of children of the category."
    )
    background_image = graphene.Field(
        Image, size=graphene.Int(description="Size of the image.")
    )
    translation = TranslationField(CategoryTranslation, type_name="category")

    class Meta:
        description = (
            "Represents a single category of products. Categories allow to organize "
            "products in a tree-hierarchies which can be used for navigation in the "
            "storefront."
        )
        only_fields = [
            "description_json",
            "id",
            "level",
            "name",
            "parent",
            "seo_description",
            "seo_title",
            "slug",
        ]
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Category
    
    @staticmethod
    def resolve_name(root: models.Category, info, **_kwargs):

        if root.metadata.get('alias', ''):
            return root.metadata.get('alias', '')
        return root.name


    @staticmethod
    def resolve_ancestors(root: models.Category, info, **_kwargs):
        return root.get_ancestors()

    @staticmethod
    def resolve_background_image(root: models.Category, info, size=None, **_kwargs):
        if root.background_image:
            return Image.get_adjusted(
                image=root.background_image,
                alt=root.background_image_alt,
                size=size,
                rendition_key_set="background_images",
                info=info,
            )

    @staticmethod
    def resolve_children(root: models.Category, info, **_kwargs):
        return root.children.all()

    @staticmethod
    def resolve_url(root: models.Category, _info):
        return ""

    @staticmethod
    def resolve_products(root: models.Category, info, **_kwargs):
        requestor = get_user_or_app_from_context(info.context)
        tree = root.get_descendants(include_self=True)
        qs = models.Product.objects.select_related("brand").published()
        if not qs.user_has_access_to_all(requestor):
            qs = qs.exclude(visible_in_listings=False)
        return qs.filter(category__in=tree)

    @staticmethod
    @permission_required(ProductPermissions.MANAGE_PRODUCTS)
    def resolve_private_meta(root: models.Category, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.Category, _info):
        return resolve_meta(root, _info)

    @staticmethod
    def __resolve_reference(root, _info, **_kwargs):
        return graphene.Node.get_node_from_global_id(_info, root.id)


@key(fields="id")
class ProductImage(CountableDjangoObjectType):
    url = graphene.String(
        required=True,
        description="The URL of the image.",
        size=graphene.Int(description="Size of the image."),
    )

    class Meta:
        description = "Represents a product image."
        only_fields = ["alt", "id", "sort_order"]
        interfaces = [relay.Node]
        model = models.ProductImage

    @staticmethod
    def resolve_url(root: models.ProductImage, info, *, size=1080):
        if size:
            url = get_thumbnail(root.image, size, method="thumbnail")
        else:
            url = root.image.url
        return info.context.build_absolute_uri(url)

    @staticmethod
    def __resolve_reference(root, _info, **_kwargs):
        return graphene.Node.get_node_from_global_id(_info, root.id)

@key(fields="id")
class BrandVariantZaamoMapping(CountableDjangoObjectType):

    class Meta:
        description = "Mapping between Brand Variant and Variant Created in Zaamo"
        model = models.BrandVariantZaamoMapping
        interfaces = [relay.Node]
        exclude = ()

@key(fields="id")
class LandingPageCategory(CountableDjangoObjectType):
    category = graphene.Field(Category, description="parent category")
    sub_categories = PrefetchingConnectionField(Category, description="sub-categories")
    

    class Meta:
        description = "landing page categories"
        model = models.LandingPageCategories
        interface = [relay.Node]

    def resolve_sub_categories(root: models.LandingPageCategories, *_args, **_kwargs):
        
        return [instance.sub_category for instance in root.through_landing_page_category.all()]

@key(fields="id")
class SourcingRequest(CountableDjangoObjectType):
    request_received = graphene.Int(description="no of sourcing request received.")
    brand_coupon_created = graphene.Int(description="no of brand coupon created.")
    brand_shared_deliverables = graphene.Int(description="no of brand shared deliverables.")
    influencer_content_created_for_brand = graphene.Int(description="no of influencer content created for Brand.")
    instagram_link = graphene.String(description = "instagram link.")
    store_status = graphene.String(description="store actions status.")
    order_id = graphene.ID(description="order ID.")
    order_status = graphene.String(description="order status for sourcing request")
    stop_source_with_zaamo = graphene.Boolean(description = "Stop Sourcing with Zaamo")
    days_since_products_delivered = graphene.Int(description="no of days since products delivered")
    delivery_date = graphene.String(description="order delivery date.")
    user_last_updated_email = graphene.String(description="email of user who last updated.")

    class Meta:
        description = "Product Sourcing Created by the Influencer"
        model = models.SourcingRequest
        interfaces = [relay.Node]
        exclude = ()

    @classmethod
    def get_queryset(cls, queryset, info):

        user_last_updated_subquery = User.objects.filter(id=OuterRef('user_last_updated_id'))\
                .filter(brand_members__brand__brand_emails__state=BrandEmailStateEnum.PRIMARY)\
                .values('brand_members__brand__brand_emails__brand_email')[:1]

        qs = super().get_queryset(queryset, info).select_related('store', 'brand', 'product', 'variant', 'user_last_updated')\
            .annotate(order_id = Cast(KeyTextTransform('order_id', 'metadata'), BigIntegerField())
            ).annotate(fulfillment_id = Cast(KeyTextTransform('fulfillment_id', 'metadata'), BigIntegerField())
            ).annotate(order_status=
                Case(
                    When(
                        Q(fulfillment_id__isnull=True), then=Value(SourcingRequestOrderStatusFilter.NO_ORDER_PLACED)
                    ),
                    default=Subquery(Fulfillment.objects.filter(id=OuterRef('fulfillment_id')).values('status')[:1]),
                    output_field=TextField()
                )
            ).annotate(delivery_date=
                    Case(
                        When(~Q(order_status=FulfillmentStatus.DELIVERED) & Q(order_status=FulfillmentStatus.SHIPPED), 
                            then=ExpressionWrapper(Subquery(Order.objects.filter(id=OuterRef('order_id')).values('created')[:1]), output_field=DateTimeField)
                        ),
                        default=Subquery(Fulfillment.objects.filter(order_id=OuterRef('order_id')).filter(status=FulfillmentStatus.DELIVERED).values('updated_at')[:1]),
                        output_field=DateTimeField()
                    )
            ).annotate(user_last_updated_email=Subquery(user_last_updated_subquery))
        
        requests = models.SourcingRequest.objects.all().values('store').annotate(
            request_received=Count('id', filter=Q(status=SourcingRequestStatus.REQUEST_RECIEVED), distinct=True),
            brand_coupon_created=Count('id', filter=Q(Q(status=SourcingRequestStatus.BRAND_COUPON_CREATED)|Q(status=SourcingRequestStatus.ZAAMO_COUPON_CREATED)|Q(status=SourcingRequestStatus.BRAND_COUPON_CLUBBED)|Q(status=SourcingRequestStatus.PRODUCT_EXCHANGE_RETURN_REQUESTED)), distinct=True),
            brand_shared_deliverables=Count('id', filter=Q(status=SourcingRequestStatus.BRAND_SHARED_DELIVERABLES), distinct=True),
            influencer_content_created_for_brand=Count('id', filter=Q(status=SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_BRAND), distinct=True),
            instagram_link = F('store__store_members__user__influencer__instagram_link'),
            store_status = F('store__actions__status'),
            )
        store_requests = {}
        for request in requests:
            store_requests[request['store']] = request

        info.variable_values['store_requests'] = store_requests

        return qs

    def resolve_request_received(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_requests = info.variable_values.get('store_requests', {})
        store = store_requests.get(root.store_id, {})
        request_received = store.get('request_received', 0)

        return request_received

    def resolve_brand_coupon_created(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_requests = info.variable_values.get('store_requests', {})
        store = store_requests.get(root.store_id, {})
        brand_coupon_created = store.get('brand_coupon_created', 0)
        
        return brand_coupon_created

    def resolve_brand_shared_deliverables(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_requests = info.variable_values.get('store_requests', {})
        store = store_requests.get(root.store_id, {})
        brand_shared_deliverables = store.get('brand_shared_deliverables', 0)
        
        return brand_shared_deliverables

    def resolve_influencer_content_created_for_brand(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_requests = info.variable_values.get('store_requests', {})
        store = store_requests.get(root.store_id, {})
        influencer_content_created_for_brand = store.get('influencer_content_created_for_brand', 0)

        return influencer_content_created_for_brand

    def resolve_instagram_link(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_requests = info.variable_values.get('store_requests', {})
        store = store_requests.get(root.store_id, {})
        instagram_link = store.get('instagram_link', '')

        return instagram_link

    def resolve_store_status(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_requests = info.variable_values.get('store_requests', {})
        store = store_requests.get(root.store_id, {})
        store_status = store.get('store_status')

        return store_status

    def resolve_order_id(root:models.SourcingRequest, info, *_args, **_kwargs):
        if root.order_id:
            order_id = graphene.Node.to_global_id("Order", root.order_id)
        else:
            order_id = ''

        return order_id
    

    def resolve_stop_source_with_zaamo(root:models.SourcingRequest, info, *_args, **_kwargs):
        store_metadata = root.store.metadata
        return not store_metadata.get("store_barter",False)

    def resolve_days_since_products_delivered(root:models.SourcingRequest, info, *_args, **_kwargs):
        days_since_products_delivered = None
        if root.delivery_date:
            days_since_products_delivered = (TimeUtilities.get_current_date_time() - root.delivery_date).days
        return days_since_products_delivered

    def resolve_delivery_date(root:models.SourcingRequest, info, *_args, **_kwargs):
        days = root.brand.order_shipping_days + root.brand.order_processing_days
        if root.delivery_date and root.order_status==FulfillmentStatus.SHIPPED:
            delivery_date = f"shipped_{TimeUtilities.add_time_in_timestamp(root.delivery_date, days)}"
        else:
            delivery_date = f"{root.delivery_date}"
        return delivery_date

    def resolve_user_last_updated_email(root:models.SourcingRequest, info, *_args, **_kwargs):
        return root.user_last_updated.email or root.user_last_updated_email
     
class ProductTag(CountableDjangoObjectType):
    products = PrefetchingConnectionField(
        Product,
        category_ids = graphene.List(
            graphene.ID,
            description="ids of category filter product"
        ),
         description="All products of collection"
        )

    class Meta:
        description = "Product Sourcing Created by the Influencer"
        model = models.ProductTag
        interfaces = [relay.Node]
        exclude = ()


    def resolve_products(root:models.ProductTag,info,**_kwargs):
        return resolve_tagged_products(root,info,**_kwargs)

class ProductTagMapping(CountableDjangoObjectType):

    class Meta:
        description = "Product Sourcing Created by the Influencer"
        model = models.ProductTagMapping
        interfaces = [relay.Node]
        exclude = ()

class ProductTypeForGrouping(graphene.ObjectType):
    id = graphene.ID(description = 'global id of product')
    name = graphene.String(description = 'name of product')
    slug = graphene.String(description = 'slug of product')
    too_many_orders = graphene.Boolean(description = 'Bool for whether brand has too many orders')
    metadata = graphene.List(
        'saleor.graphql.meta.types.MetadataItem',
        description=(
            "List of public metadata items. Can be accessed without permissions."
        ),
    )
    brand = graphene.Field(
        'saleor.graphql.meta.types.BrandForGrouping', description='brand info for the mapped product')
    
    thumbnail = graphene.Field('saleor.graphql.meta.types.ImageForGrouping', 
                                description='thumbnail object for mapped product',
                                size=graphene.Argument(graphene.Int, description="Size of thumbnail."))

    default_variant = graphene.Field('saleor.graphql.meta.types.ProductVariantForGrouping', description='default variant with the mapped product')



class ProductTypeForGroupingConnect(graphene.relay.Connection):

    class Meta:
        node = ProductTypeForGrouping


class ProductGrouping(CountableDjangoObjectType):

    products = graphene.relay.ConnectionField(
        ProductTypeForGroupingConnect,
        
        description="List of products in this collection.",
    )

    shareable_link = graphene.String(description = "Link to share the group of products")
    image = graphene.Field(
        Image, size=graphene.Int(description="Size of the image.")
    )

    
    class Meta:
        description = "Product Grouping type"
        model = models.ProductGrouping
        interfaces = [relay.Node]


    
    @staticmethod
    def resolve_image(root: models.ProductGrouping, info, size=None, **_kwargs):
        
        if root.image:
            return Image.get_adjusted(
                image=root.image,
                alt="NA",
                size=size,
                rendition_key_set="image",
                info=info,
            )


    @classmethod
    def get_queryset(cls, queryset, info,*args,**_kwargs):
        query_fields = get_requested_fields(info)

        try:
            if 'products' in query_fields['productGrouping']['edges']['node']:
                queryset = queryset.prefetch_related('through_product_grouping')

        except Exception:
            pass
        
        return super().get_queryset(queryset, info)

    def resolve_products(root:models.ProductGrouping,info,**_kwargs):

        qs = root.through_product_grouping.all()
        return [q.metadata.get('query_data') for q in qs]
    
    def resolve_shareable_link(root:models.ProductGrouping,info):

        store_id =  RequestUtilities.get_store_id_from_headers(info.context)
        if store_id:
            store_slug = resolve_store_slug(store_id)
            return "{}{}/group/{}".format(settings.ZAAMO_ENV_LINK,store_slug,root.slug)
        else:
            return None
        

class ProductGroupingMeta(graphene.ObjectType):
    
    brands = FilterInputConnectionField(
        'saleor.graphql.brand.types.Brand',
        description="List of the Brands.",
    )
    categories = FilterInputConnectionField(
        Category,
        description="List of the Categories.",
    )
    
    product_tags = FilterInputConnectionField(
        ProductTag,
        description="List of the Tags.",
    )
    
    brand_collections = FilterInputConnectionField(
        'saleor.graphql.brand.types.BrandCollection',
        description="List of the brand collections.",
    )

    @staticmethod
    def resolve_brands(root, _info,**kwargs):
        brand_ids = root.get('brand_ids')
        return Brand.objects.filter(id__in=brand_ids)
        
    @staticmethod
    def resolve_categories(root, _info,**kwargs):
        categories_ids = root.get('category_ids')
        return models.Category.objects.filter(id__in=categories_ids)
        
    @staticmethod
    def resolve_product_tags(root, _info,**kwargs):
        product_tags_ids = root.get('product_tag_ids')
        return models.ProductTag.objects.filter(id__in=product_tags_ids)
        
    @staticmethod
    def resolve_brand_collections(root, _info,**kwargs):
        brand_collections_ids = root.get('brand_collection_ids')
        return BrandCollection.objects.filter(id__in=brand_collections_ids)
