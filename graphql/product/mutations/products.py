import datetime
from collections import defaultdict
import uuid
from saleor.brand.states import BrandCollectionTypeEnum
from saleor.brand.states import BrandStatusEnum
from saleor.core.utils import generate_unique_slug
from saleor.external_services.shopify_service.shopify_impl import ZaamoShopifyImpl
from saleor.external_services.shopify_service.tasks import push_product_to_shopify_task, update_product_status_shopify_task
from saleor.graphql.integrations.enums import BarterTypeEnum
from saleor.graphql.product.types.products import ProductGrouping, ProductTag, ProductTagMapping
from saleor.graphql.utils import get_nodes
from saleor.product.emails import send_sourcing_request_email, sourcing_request_email_context
from saleor.product.utils import sourcing_request_status_update_notification,sourcing_request_coupon_created_notification
from saleor.product.states import ProductGroupingEnum
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.store.store_utilities import get_instance_for_store, remove_brands_for_store_category_page, save_brands_for_store_category_page, save_brands_for_store_category_page_in_bulk, set_relation_between_store_collection
from typing import Iterable, List, Tuple, Union
import graphene
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet,Subquery
from django.utils.text import slugify
from graphene.types import InputObjectType
from graphql_relay import from_global_id
from ..enums import CollectionMediaTypeEnum, CollectionType,SourcingRequestStatusTypeEnum,productgroupingenum
from ...core.types.common import AccountError
from ....core.exceptions import PermissionDenied
from ....core.permissions import ProductPermissions, ProductTypePermissions,InfluencerPermissions
from ....order import OrderStatus, models as order_models
from ....product import models
from ....account import models as account_models
from ....warehouse import models as warehouse_models
from ....product.error_codes import ProductErrorCode
from ....product.tasks import (
    update_product_minimal_variant_price_task,
    update_products_minimal_variant_prices_of_catalogues_task,
    update_variants_names,
    update_mapping_for_product_grouping_from_mutation

)
from ....brand import models as brand_models
from saleor.external_services.integrations.base import BaseIntegration
from ...account.types import User
from ....product.thumbnails import (
    create_category_background_image_thumbnails,
    create_collection_background_image_thumbnails,
    create_product_thumbnails,
)
from ....product.utils import delete_categories
from ....product.utils.attributes import (
    associate_attribute_values_to_instance,
    generate_name_for_variant,
)
from ...core.mutations import BaseMutation, ModelDeleteMutation, ModelMutation, StoreModelMutation, StoreBaseMutation
from ...core.scalars import PositiveDecimal, WeightScalar
from ...core.types import SeoInput, Upload
from ...core.types.common import ProductError
from ...core.utils import (
    clean_seo_fields,
    from_global_id_strict_type,
    get_duplicated_values,
    validate_image_file,
    validate_slug_and_generate_if_needed,
)
from ...core.utils.reordering import perform_reordering
from ...core.validators import validate_price_precision
from ...meta.deprecated.mutations import ClearMetaBaseMutation, UpdateMetaBaseMutation
from ...product.utils import parse_draftjs_content_to_string
from ...warehouse.types import Warehouse
from ..types import (
    Category,
    Collection,
    Product,
    ProductImage,
    ProductType,
    ProductVariant,
    SourcingRequest,
)
from ..utils import (
    create_stocks,
    get_used_attribute_values_for_variant,
    get_used_variants_attribute_values,
    update_msp_of_product_using_step_price,
    update_msp_of_variant_using_step_price,
    validate_attributes_input_for_product,
    validate_attributes_input_for_variant,
)
from .common import ReorderInput
from saleor.utilities.time_utilities import TimeUtilities
from saleor.external_services.integrations.base import BaseProductCreate
from saleor.store.models import BrandSourcingRequest
from saleor.product import SourcingRequestStatus
from saleor.product.tasks import save_image_with_celery
import time

class CategoryInput(graphene.InputObjectType):
    description = graphene.String(description="Category description (HTML/text).")
    description_json = graphene.JSONString(description="Category description (JSON).")
    name = graphene.String(description="Category name.")
    slug = graphene.String(description="Category slug.")
    seo = SeoInput(description="Search engine optimization fields.")
    background_image = Upload(description="Background image file.")
    background_image_alt = graphene.String(description="Alt text for an image.")


class CategoryCreate(ModelMutation):
    class Arguments:
        input = CategoryInput(
            required=True, description="Fields required to create a category."
        )
        parent_id = graphene.ID(
            description=(
                "ID of the parent category. If empty, category will be top level "
                "category."
            ),
            name="parent",
        )

    class Meta:
        description = "Creates a new category."
        model = models.Category
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def clean_input(cls, info, instance, data):
        cleaned_input = super().clean_input(info, instance, data)
        try:
            cleaned_input = validate_slug_and_generate_if_needed(
                instance, "name", cleaned_input
            )
        except ValidationError as error:
            error.code = ProductErrorCode.REQUIRED.value
            raise ValidationError({"slug": error})
        parent_id = data["parent_id"]
        if parent_id:
            parent = cls.get_node_or_error(
                info, parent_id, field="parent", only_type=Category
            )
            cleaned_input["parent"] = parent
        if data.get("background_image"):
            image_data = info.context.FILES.get(data["background_image"])
            validate_image_file(image_data, "background_image")
        clean_seo_fields(cleaned_input)
        return cleaned_input

    @classmethod
    def perform_mutation(cls, root, info, **data):
        parent_id = data.pop("parent_id", None)
        data["input"]["parent_id"] = parent_id
        return super().perform_mutation(root, info, **data)

    @classmethod
    def save(cls, info, instance, cleaned_input):
        instance.save()
        if cleaned_input.get("background_image"):
            create_category_background_image_thumbnails.delay(instance.pk)


class CategoryUpdate(CategoryCreate):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a category to update.")
        input = CategoryInput(
            required=True, description="Fields required to update a category."
        )

    class Meta:
        description = "Updates a category."
        model = models.Category
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"


class CategoryDelete(ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a category to delete.")

    class Meta:
        description = "Deletes a category."
        model = models.Category
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        if not cls.check_permissions(info.context):
            raise PermissionDenied()
        node_id = data.get("id")
        instance = cls.get_node_or_error(info, node_id, only_type=Category)

        db_id = instance.id

        delete_categories([db_id])

        instance.id = db_id
        return cls.success_response(instance)


class CollectionInput(graphene.InputObjectType):
    is_published = graphene.Boolean(
        description="Informs whether a collection is published."
    )
    name = graphene.String(description="Name of the collection.")
    slug = graphene.String(description="Slug of the collection.")
    description = graphene.String(
        description="Description of the collection (HTML/text)."
    )
    description_json = graphene.JSONString(
        description="Description of the collection (JSON)."
    )
    background_image = Upload(description="Background image file.")
    background_image_alt = graphene.String(description="Alt text for an image.")
    seo = SeoInput(description="Search engine optimization fields.")
    publication_date = graphene.Date(description="Publication date. ISO 8601 standard.")
    image_url = graphene.String(description="image_url of collection", required=False)
    shop_look = graphene.Boolean(description="shop look status of collection")
    media_type = CollectionMediaTypeEnum(description="media type for image/video",required=False)
    steal_deal = graphene.Boolean(description = "Steal Deal True or False " , required = False)
    redirect_url = graphene.String(description="redirect url for linktree")
    collection_type = CollectionType(description="collection type enum",required=False)


class CollectionCreateInput(CollectionInput):
    products = graphene.List(
        graphene.ID,
        description="List of products to be added to the collection.",
        name="products",
    )
    
class CollectionCreate(StoreModelMutation):
    class Arguments:
        input = CollectionCreateInput(
            required=True, description="Fields required to create a collection."
        )

    class Meta:
        description = "Creates a new collection."
        model = models.Collection
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"
        

    @classmethod
    def clean_input(cls, info, instance, data):
        cleaned_input = super().clean_input(info, instance, data)
        try:
            cleaned_input = validate_slug_and_generate_if_needed(
                instance, "name", cleaned_input
            )
        except ValidationError as error:
            error.code = ProductErrorCode.REQUIRED.value
            raise ValidationError({"slug": error})
        
        if data.get("background_image"):
            image_data = info.context.FILES.get(data["background_image"])
            validate_image_file(image_data, "background_image")
        
        if data.get("steal_deal") is not None:
            instance.metadata["steal_deal"] = data.get("steal_deal")
        
        is_published = cleaned_input.get("is_published")
        publication_date = cleaned_input.get("publication_date")
        
        if is_published and not publication_date:
            cleaned_input["publication_date"] = datetime.date.today()

        clean_seo_fields(cleaned_input)
        
        return cleaned_input

    @classmethod
    def fetch_collection_name_based_on_store_id(cls, store_id):
        fetch_collection_id_qs = models.CollectionStore.objects.filter(store_id=store_id).values_list('collection_id')
        fetch_collection_name = models.Collection.objects.filter(pk__in=fetch_collection_id_qs).values('name')
        collection_name_set = set()
        for collection_name in fetch_collection_name:
            collection_name_set.add(collection_name.get('name'))

        return collection_name_set

    @classmethod
    @transaction.atomic
    def save(cls, info, instance, cleaned_input):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        collection_name_set = cls.fetch_collection_name_based_on_store_id(store_id)

        if cleaned_input['name'] in collection_name_set:
            raise ValidationError(message="Collection Name already Exist, Please Use another Collection Name")
        else:
            instance.save()
        
        store_relation = set_relation_between_store_collection(store_id, instance, info.context.user)
        
        if not store_relation:
            raise ValidationError(message="In-valid store id in headers")
        if cleaned_input.get("background_image"):
            create_collection_background_image_thumbnails.delay(instance.pk)


class CollectionUpdate(CollectionCreate):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a collection to update.")
        input = CollectionInput(
            required=True, description="Fields required to update a collection."
        )

    class Meta:
        description = "Updates a collection."
        model = models.Collection
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def save(cls, info, instance, cleaned_input):
        cleaned_input['updated_at'] = TimeUtilities.current_time_in_milliseconds()
        if not cleaned_input.get('media_type'):
            cleaned_input['media_type'] = "image"
        if cleaned_input.get("background_image"):
            create_collection_background_image_thumbnails.delay(instance.pk)
        
        instance.save()


class CollectionDelete(ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a collection to delete.")

    class Meta:
        description = "Deletes a collection."
        model = models.Collection
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

class AddCollectionToStore(BaseMutation):
    
    class Arguments:
        collection_id = graphene.ID(required=True, description="ID of a collection to copy")

    class Meta:
        description = "collection to copy in store"
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    collection = graphene.Field(Collection, description="ID of a newly copied collection")

    @classmethod
    def add_relationship_of_source_collection_with_store(cls, source_collection_id, destination_store_id):
        
        source_collection_instance = models.Collection.objects.filter(id=source_collection_id).first()
        source_collection_metadata = source_collection_instance.metadata

        if source_collection_metadata.get('stores'):
            stores = source_collection_metadata.get('stores')
            
            if destination_store_id not in stores:
                stores.append(destination_store_id)
            
            source_collection_metadata['stores'] = stores
        else:
             source_collection_metadata['stores'] = [destination_store_id]
        
        source_collection_instance.metadata = source_collection_metadata
        source_collection_instance.save()

    @classmethod
    def add_collection_to_store(cls, collection_instance, destination_store, user_instance):
        source_collection_products = collection_instance.products.all()
        source_collection_id = collection_instance.id
        collection_instance.pk = None
        collection_instance.slug = collection_instance.slug + uuid.uuid4().hex[:4]
        collection_instance.metadata.update(
            {
                'source_products_count':len(source_collection_products), 
                'added_collection': True,
                'source_collection_id': source_collection_id,
                'landing': False
            })
        collection_instance.ideas = False
        collection_instance.save()
        collection_instance.products.add(*source_collection_products)
        
        if collection_instance.metadata.get('stores'):
            collection_instance.metadata.pop('stores')

        collection_instance.save()

        models.CollectionStore.objects.update_or_create(
            store=destination_store,
            collection=collection_instance,
            user=user_instance
        )

        cls.add_relationship_of_source_collection_with_store(source_collection_id, destination_store.id)

        product_ids = [data.id for data in source_collection_products]
        save_brands_for_store_category_page_in_bulk.delay(product_ids, destination_store.id)

        return collection_instance

    @classmethod
    def copy_collection_from_source_to_destination_store(cls, source_collection_instance, destination_store, user_instance):
        

        if not source_collection_instance:
            raise ValidationError(message="In-correct collection Id")
        
        collection_store_filter = models.CollectionStore.objects.filter(collection=source_collection_instance)

        if not collection_store_filter:
            raise ValidationError(message="In-correct collection Id")

        source_collection_store_instance = collection_store_filter[0]

        if destination_store.id == source_collection_store_instance.store_id:

            raise ValidationError(message="Unable to add collection as it already exists")
 
        destination_store_collection_ids = list(models.CollectionStore.objects.filter(store=destination_store).values_list('collection_id', flat=True))
        
        if models.Collection.objects.filter(id__in=destination_store_collection_ids, metadata__source_collection_id=source_collection_instance.id):
            raise ValidationError(message="Collection already added in store")
        
        return cls.add_collection_to_store(source_collection_instance, destination_store, user_instance)

    @classmethod
    def perform_mutation(cls, root, info, **data):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        source_collection_id = data.get('collection_id')
        source_collection_instance= graphene.Node.get_node_from_global_id(info, source_collection_id, Collection)
        collection = cls.copy_collection_from_source_to_destination_store(source_collection_instance, store_instance, info.context.user)

        return cls(collection=collection)


class MoveProductInput(graphene.InputObjectType):
    product_id = graphene.ID(
        description="The ID of the product to move.", required=True
    )
    sort_order = graphene.Int(
        description=(
            "The relative sorting position of the product (from -inf to +inf) "
            "starting from the first given product's actual position."
            "1 moves the item one position forward, -1 moves the item one position "
            "backward, 0 leaves the item unchanged."
        )
    )


class CollectionReorderProducts(BaseMutation):
    collection = graphene.Field(
        Collection, description="Collection from which products are reordered."
    )

    class Meta:
        description = "Reorder the products of a collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    class Arguments:
        collection_id = graphene.Argument(
            graphene.ID, required=True, description="ID of a collection."
        )
        moves = graphene.List(
            MoveProductInput,
            required=True,
            description="The collection products position operations.",
        )

    @classmethod
    def perform_mutation(cls, _root, info, collection_id, moves):
        pk = from_global_id_strict_type(
            collection_id, only_type=Collection, field="collection_id"
        )

        try:
            collection = models.Collection.objects.prefetch_related(
                "collectionproduct"
            ).get(pk=pk)
        except ObjectDoesNotExist:
            raise ValidationError(
                {
                    "collection_id": ValidationError(
                        f"Couldn't resolve to a collection: {collection_id}",
                        code=ProductErrorCode.NOT_FOUND,
                    )
                }
            )

        m2m_related_field = collection.collectionproduct

        operations = {}

        # Resolve the products
        for move_info in moves:
            product_pk = from_global_id_strict_type(
                move_info.product_id, only_type=Product, field="moves"
            )

            try:
                m2m_info = m2m_related_field.get(product_id=int(product_pk))
            except ObjectDoesNotExist:
                raise ValidationError(
                    {
                        "moves": ValidationError(
                            f"Couldn't resolve to a product: {move_info.product_id}",
                            code=ProductErrorCode.NOT_FOUND,
                        )
                    }
                )
            operations[m2m_info.pk] = move_info.sort_order

        with transaction.atomic():
            perform_reordering(m2m_related_field, operations)
        return CollectionReorderProducts(collection=collection)


class CollectionAddProducts(StoreBaseMutation):
    collection = graphene.Field(
        Collection, description="Collection to which products will be added."
    )

    class Arguments:
        collection_id = graphene.Argument(
            graphene.ID, required=True, description="ID of a collection."
        )
        products = graphene.List(
            graphene.ID, required=True, description="List of product IDs."
        )

    class Meta:
        description = "Adds products to a collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"


    @classmethod
    @transaction.atomic()
    def perform_mutation(cls, _root, info, collection_id, products):
        collection = cls.get_node_or_error(
            info, collection_id, field="collection_id", only_type=Collection
        )
        products = cls.get_nodes_or_error(products, "products", Product)
        collection.products.add(*products)
        collection.save()
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        save_brands_for_store_category_page(products, store_instance)
        
        if collection.sale_set.exists():
            # Updated the db entries, recalculating discounts of affected products
            update_products_minimal_variant_prices_of_catalogues_task.delay(
                product_ids=[p.pk for p in products]
            )
        return CollectionAddProducts(collection=collection)


class CollectionRemoveProducts(BaseMutation):
    collection = graphene.Field(
        Collection, description="Collection from which products will be removed."
    )

    class Arguments:
        collection_id = graphene.Argument(
            graphene.ID, required=True, description="ID of a collection."
        )
        products = graphene.List(
            graphene.ID, required=True, description="List of product IDs."
        )

    class Meta:
        description = "Remove products from a collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, collection_id, products):
        collection = cls.get_node_or_error(
            info, collection_id, field="collection_id", only_type=Collection
        )
        products = cls.get_nodes_or_error(products, "products", only_type=Product)
        collection.products.remove(*products)
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        remove_brands_for_store_category_page(products, store_instance)
        
        if collection.sale_set.exists():
            # Updated the db entries, recalculating discounts of affected products
            update_products_minimal_variant_prices_of_catalogues_task.delay(
                product_ids=[p.pk for p in products]
            )
        return CollectionRemoveProducts(collection=collection)


class CollectionUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.Collection
        description = "Update public metadata for collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class CollectionClearMeta(ClearMetaBaseMutation):
    class Meta:
        model = models.Collection
        description = "Clears public metadata for collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class CollectionUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.Collection
        description = "Update private metadata for collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class CollectionClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        model = models.Collection
        description = "Clears private metadata item for collection."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class CategoryUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.Category
        description = "Update public metadata for category."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class CategoryClearMeta(ClearMetaBaseMutation):
    class Meta:
        model = models.Category
        description = "Clears public metadata for category."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class CategoryUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.Category
        description = "Update private metadata for category."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class CategoryClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        model = models.Category
        description = "Clears private metadata for category."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class AttributeValueInput(InputObjectType):
    id = graphene.ID(description="ID of the selected attribute.")
    values = graphene.List(
        graphene.String,
        required=True,
        description=(
            "The value or slug of an attribute to resolve. "
            "If the passed value is non-existent, it will be created."
        ),
    )


class ProductInput(graphene.InputObjectType):
    attributes = graphene.List(AttributeValueInput, description="List of attributes.")
    publication_date = graphene.types.datetime.Date(
        description="Publication date. ISO 8601 standard."
    )
    category = graphene.ID(description="ID of the product's category.", name="category")
    brand = graphene.ID(description="ID of the product's brand.", name="brand", required=True)
    charge_taxes = graphene.Boolean(
        description="Determine if taxes are being charged for the product."
    )
    collections = graphene.List(
        graphene.ID,
        description="List of IDs of collections that the product belongs to.",
        name="collections",
    )
    description = graphene.String(description="Product description (HTML/text).")
    description_json = graphene.JSONString(description="Product description (JSON).")
    is_published = graphene.Boolean(
        description="Determines if product is visible to customers."
    )
    name = graphene.String(description="Product name.")
    slug = graphene.String(description="Product slug.")
    tax_code = graphene.String(description="Tax rate for enabled tax gateway.")
    seo = SeoInput(description="Search engine optimization fields.")
    weight = WeightScalar(description="Weight of the Product.", required=False)
    sku = graphene.String(
        description=(
            "Stock keeping unit of a product. Note: this field is only used if "
            "a product doesn't use variants."
        ), required=False
    )
    track_inventory = graphene.Boolean(
        description=(
            "Determines if the inventory of this product should be tracked. If false, "
            "the quantity won't change when customers buy this item. Note:   field "
            "is only used if a product doesn't use variants."
        )
    )
    base_price = PositiveDecimal(
        description=(
            "Default price for product variant. "
            "Note: this field is only used if a product doesn't use variants."
        )
    )
    visible_in_listings = graphene.Boolean(
        description=(
            "Determines if product is visible in product listings "
            "(doesn't apply to product collections)."
        )
    )
    has_custom_commission = graphene.Boolean(description = "Turn on or off Custom commission for product " ,required = False)
    custom_commission_percentage = graphene.Float(description = "Custom commission value for product" , required = False)
    brand_barter = BarterTypeEnum(description=(
                                    "Turn on or off Brand Barter option for Product"
                                ),)
    value_deal = graphene.Boolean(description = "Value deal true or false in metadata of product",required  = False)
    step_price = PositiveDecimal(description = "Step up price on product msp" , required = False)


class StockInput(graphene.InputObjectType):
    warehouse = graphene.ID(
        required=True, description="Warehouse in which stock is located."
    )
    quantity = graphene.Int(description="Quantity of items available for sell.")


class ProductCreateInput(ProductInput):
    product_type = graphene.ID(
        description="ID of the type that product belongs to.",
        name="productType",
        required=True,
    )
    stocks = graphene.List(
        graphene.NonNull(StockInput),
        description=(
            "Stocks of a product available for sale. Note: this field is "
            "only used if a product doesn't use variants."
        ),
        required=False,
    )


T_INPUT_MAP = List[Tuple[models.Attribute, List[str]]]
T_INSTANCE = Union[models.Product, models.ProductVariant]


class AttributeAssignmentMixin:
    """Handles cleaning of the attribute input and creating the proper relations.

    1. You should first call ``clean_input``, to transform and attempt to resolve
       the provided input into actual objects. It will then perform a few
       checks to validate the operations supplied by the user are possible and allowed.
    2. Once everything is ready and all your data is saved inside a transaction,
       you shall call ``save`` with the cleaned input to build all the required
       relations. Once the ``save`` call is done, you are safe from continuing working
       or to commit the transaction.

    Note: you shall never call ``save`` outside of a transaction and never before
    the targeted instance owns a primary key. Failing to do so, the relations will
    be unable to build or might only be partially built.
    """

    @classmethod
    def _resolve_attribute_nodes(
        cls,
        qs: QuerySet,
        *,
        global_ids: List[str],
        pks: Iterable[int],
        slugs: Iterable[str],
    ):
        """Retrieve attributes nodes from given global IDs and/or slugs."""
        qs = qs.filter(Q(pk__in=pks) | Q(slug__in=slugs))
        nodes = list(qs)  # type: List[models.Attribute]

        if not nodes:
            raise ValidationError(
                (
                    f"Could not resolve to a node: ids={global_ids}"
                    f" and slugs={list(slugs)}"
                ),
                code=ProductErrorCode.NOT_FOUND.value,
            )

        nodes_pk_list = set()
        nodes_slug_list = set()
        for node in nodes:
            nodes_pk_list.add(node.pk)
            nodes_slug_list.add(node.slug)

        for pk, global_id in zip(pks, global_ids):
            if pk not in nodes_pk_list:
                raise ValidationError(
                    f"Could not resolve {global_id!r} to Attribute",
                    code=ProductErrorCode.NOT_FOUND.value,
                )

        for slug in slugs:
            if slug not in nodes_slug_list:
                raise ValidationError(
                    f"Could not resolve slug {slug!r} to Attribute",
                    code=ProductErrorCode.NOT_FOUND.value,
                )

        return nodes

    @classmethod
    def _resolve_attribute_global_id(cls, global_id: str) -> int:
        """Resolve an Attribute global ID into an internal ID (int)."""
        graphene_type, internal_id = from_global_id(global_id)  # type str, str
        if graphene_type != "Attribute":
            raise ValidationError(
                f"Must receive an Attribute id, got {graphene_type}.",
                code=ProductErrorCode.INVALID.value,
            )
        if not internal_id.isnumeric():
            raise ValidationError(
                f"An invalid ID value was passed: {global_id}",
                code=ProductErrorCode.INVALID.value,
            )
        return int(internal_id)

    @classmethod
    def _pre_save_values(cls, attribute: models.Attribute, values: List[str]):
        """Lazy-retrieve or create the database objects from the supplied raw values."""
        get_or_create = attribute.values.get_or_create
        return tuple(
            get_or_create(
                attribute=attribute,
                slug=slugify(value, allow_unicode=True),
                defaults={"name": value},
            )[0]
            for value in values
        )

    @classmethod
    def _check_input_for_product(cls, cleaned_input: T_INPUT_MAP, qs: QuerySet):
        """Check the cleaned attribute input for a product.

        An Attribute queryset is supplied.

        - ensure all required attributes are passed
        - ensure the values are correct for a product
        """
        errors = validate_attributes_input_for_product(cleaned_input)

        supplied_attribute_pk = [attribute.pk for attribute, _ in cleaned_input]

        # Asserts all required attributes are supplied
        missing_required_attributes = qs.filter(
            Q(value_required=True) & ~Q(pk__in=supplied_attribute_pk)
        )

        if missing_required_attributes:
            ids = [
                graphene.Node.to_global_id("Attribute", attr.pk)
                for attr in missing_required_attributes
            ]
            error = ValidationError(
                "All attributes flagged as having a value required must be supplied.",
                code=ProductErrorCode.REQUIRED.value,
                params={"attributes": ids},
            )
            errors.append(error)

        if errors:
            raise ValidationError(errors)

    @classmethod
    def _check_input_for_variant(cls, cleaned_input: T_INPUT_MAP, qs: QuerySet):
        """Check the cleaned attribute input for a variant.

        An Attribute queryset is supplied.

        - ensure all attributes are passed
        - ensure the values are correct for a variant
        """
        if len(cleaned_input) != qs.count():
            raise ValidationError(
                "All attributes must take a value", code=ProductErrorCode.REQUIRED.value
            )

        errors = validate_attributes_input_for_variant(cleaned_input)
        if errors:
            raise ValidationError(errors)

    @classmethod
    def _validate_input(
        cls, cleaned_input: T_INPUT_MAP, attribute_qs, is_variant: bool
    ):
        """Check if no invalid operations were supplied.

        :raises ValidationError: when an invalid operation was found.
        """
        if is_variant:
            return cls._check_input_for_variant(cleaned_input, attribute_qs)
        else:
            return cls._check_input_for_product(cleaned_input, attribute_qs)

    @classmethod
    def clean_input(
        cls, raw_input: dict, attributes_qs: QuerySet, is_variant: bool
    ) -> T_INPUT_MAP:
        """Resolve and prepare the input for further checks.

        :param raw_input: The user's attributes input.
        :param attributes_qs:
            A queryset of attributes, the attribute values must be prefetched.
            Prefetch is needed by ``_pre_save_values`` during save.
        :param is_variant: Whether the input is for a variant or a product.

        :raises ValidationError: contain the message.
        :return: The resolved data
        """

        # Mapping to associate the input values back to the resolved attribute nodes
        pks = {}
        slugs = {}

        # Temporary storage of the passed ID for error reporting
        global_ids = []

        for attribute_input in raw_input:
            global_id = attribute_input.get("id")
            slug = attribute_input.get("slug")
            values = attribute_input["values"]

            if global_id:
                internal_id = cls._resolve_attribute_global_id(global_id)
                global_ids.append(global_id)
                pks[internal_id] = values
            elif slug:
                slugs[slug] = values
            else:
                raise ValidationError(
                    "You must whether supply an ID or a slug",
                    code=ProductErrorCode.REQUIRED.value,
                )

        attributes = cls._resolve_attribute_nodes(
            attributes_qs, global_ids=global_ids, pks=pks.keys(), slugs=slugs.keys()
        )
        cleaned_input = []
        for attribute in attributes:
            key = pks.get(attribute.pk, None)

            # Retrieve the primary key by slug if it
            # was not resolved through a global ID but a slug
            if key is None:
                key = slugs[attribute.slug]

            cleaned_input.append((attribute, key))
        cls._validate_input(cleaned_input, attributes_qs, is_variant)
        return cleaned_input

    @classmethod
    def save(cls, instance: T_INSTANCE, cleaned_input: T_INPUT_MAP):
        """Save the cleaned input into the database against the given instance.

        Note: this should always be ran inside a transaction.

        :param instance: the product or variant to associate the attribute against.
        :param cleaned_input: the cleaned user input (refer to clean_attributes)
        """
        for attribute, values in cleaned_input:
            attribute_values = cls._pre_save_values(attribute, values)
            associate_attribute_values_to_instance(
                instance, attribute, *attribute_values
            )


class ProductCreate(ModelMutation):
    class Arguments:
        input = ProductCreateInput(
            required=True, description="Fields required to create a product."
        )

    class Meta:
        description = "Creates a new product."
        model = models.Product
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def clean_attributes(
        cls, attributes: dict, product_type: models.ProductType
    ) -> T_INPUT_MAP:
        attributes_qs = product_type.product_attributes
        attributes = AttributeAssignmentMixin.clean_input(
            attributes, attributes_qs, is_variant=False
        )
        return attributes

    @classmethod
    def clean_input(cls, info, instance, data):
        cleaned_input = super().clean_input(info, instance, data)
        description = cleaned_input.get("description_json")
        cleaned_input["description_plaintext"] = (
            parse_draftjs_content_to_string(description) if description else ""
        )
        if "value_deal" in cleaned_input:
            instance.metadata["value_deal"] = cleaned_input.get("value_deal")
            instance.metadata["value_updated_at"] = TimeUtilities.get_current_date_time()


        weight = cleaned_input.get("weight")
        if weight and weight.value < 0:
            raise ValidationError(
                {
                    "weight": ValidationError(
                        "Product can't have negative weight.",
                        code=ProductErrorCode.INVALID.value,
                    )
                }
            )

        base_price = cleaned_input.get("base_price")
        try:
            validate_price_precision(base_price, instance.currency)
        except ValidationError as error:
            error.code = ProductErrorCode.INVALID.value
            raise ValidationError({"base_price": error})

        # Attributes are provided as list of `AttributeValueInput` objects.
        # We need to transform them into the format they're stored in the
        # `Product` model, which is HStore field that maps attribute's PK to
        # the value's PK.

        attributes = cleaned_input.get("attributes")
        product_type = (
            instance.product_type if instance.pk else cleaned_input.get("product_type")
        )  # type: models.ProductType

        try:
            cleaned_input = validate_slug_and_generate_if_needed(
                instance, "name", cleaned_input
            )
        except ValidationError as error:
            error.code = ProductErrorCode.REQUIRED.value
            raise ValidationError({"slug": error})

        # FIXME  tax_rate logic should be dropped after we remove tax_rate from input
        tax_rate = cleaned_input.pop("tax_rate", "")
        if tax_rate:
            info.context.plugins.assign_tax_code_to_object_meta(instance, tax_rate)

        if "tax_code" in cleaned_input:
            info.context.plugins.assign_tax_code_to_object_meta(
                instance, cleaned_input["tax_code"]
            )

        if attributes and product_type:
            try:
                cleaned_input["attributes"] = cls.clean_attributes(
                    attributes, product_type
                )
            except ValidationError as exc:
                raise ValidationError({"attributes": exc})

        is_published = cleaned_input.get("is_published")
        publication_date = cleaned_input.get("publication_date")
        if is_published and not publication_date:
            cleaned_input["publication_date"] = datetime.date.today()
            cleaned_input["available_for_purchase"] = datetime.date.today()
        category = cleaned_input.get("category")
        if not category and is_published:
            raise ValidationError(
                {
                    "category": ValidationError(
                        "You must select a category to be able to publish",
                        code=ProductErrorCode.REQUIRED,
                    )
                }
            )

        clean_seo_fields(cleaned_input)
        stocks = cleaned_input.get("stocks")
        if stocks:
            cls.check_for_duplicates_in_stocks(stocks)
        return cleaned_input

    @classmethod
    def clean_sku(cls, product_type, cleaned_input):
        """Validate SKU input field.

        When creating products that don't use variants, SKU is required in
        the input in order to create the default variant underneath.
        See the documentation for `has_variants` field for details:
        http://docs.getsaleor.com/en/latest/architecture/products.html#product-types
        """
        if product_type and not product_type.has_variants:
            input_sku = cleaned_input.get("sku")
            if not input_sku:
                raise ValidationError(
                    {
                        "sku": ValidationError(
                            "This field cannot be blank.",
                            code=ProductErrorCode.REQUIRED,
                        )
                    }
                )
            elif models.ProductVariant.objects.filter(sku=input_sku).exists():
                raise ValidationError(
                    {
                        "sku": ValidationError(
                            "Product with this SKU already exists.",
                            code=ProductErrorCode.ALREADY_EXISTS,
                        )
                    }
                )

    @classmethod
    def check_for_duplicates_in_stocks(cls, stocks_data):
        warehouse_ids = [stock["warehouse"] for stock in stocks_data]
        duplicates = get_duplicated_values(warehouse_ids)
        if duplicates:
            error_msg = "Duplicated warehouse ID: {}".format(duplicates.join(", "))
            raise ValidationError(
                {"stocks": ValidationError(error_msg, code=ProductErrorCode.UNIQUE)}
            )

    @classmethod
    def get_instance(cls, info, **data):
        """Prefetch related fields that are needed to process the mutation."""
        # If we are updating an instance and want to update its attributes,
        # prefetch them.

        object_id = data.get("id")
        if object_id and data.get("attributes"):
            # Prefetches needed by AttributeAssignmentMixin and
            # associate_attribute_values_to_instance
            qs = cls.Meta.model.objects.prefetch_related(
                "product_type__product_attributes__values",
                "product_type__attributeproduct",
            )
            return cls.get_node_or_error(info, object_id, only_type="Product", qs=qs)

        return super().get_instance(info, **data)

    @classmethod
    @transaction.atomic
    def save(cls, info, instance, cleaned_input):
        instance.save()
        if not instance.product_type.has_variants:
            site_settings = info.context.site.settings
            track_inventory = cleaned_input.get(
                "track_inventory", site_settings.track_inventory_by_default
            )
            try:
                latest_product_varient = models.ProductVariant.objects.latest('id').id
            except:
                latest_product_varient = 0

            cleaned_input["sku"] = graphene.Node.to_global_id("Product", instance.id) + '_' +  str(latest_product_varient+1)
            sku = cleaned_input.get("sku")

            variant_price = cleaned_input.get("base_price")

            variant = models.ProductVariant.objects.create(
                product=instance,
                track_inventory=track_inventory,
                sku=sku,
                price_amount=variant_price,
            )
            stocks = cleaned_input.get("stocks")
            if stocks:
                cls.create_variant_stocks(variant, stocks)

        attributes = cleaned_input.get("attributes")
        if attributes:
            AttributeAssignmentMixin.save(instance, attributes)

    @classmethod
    def create_variant_stocks(cls, variant, stocks):
        warehouse_ids = [stock["warehouse"] for stock in stocks]
        warehouses = cls.get_nodes_or_error(
            warehouse_ids, "warehouse", only_type=Warehouse
        )
        create_stocks(variant, stocks, warehouses)

    @classmethod
    def _save_m2m(cls, info, instance, cleaned_data):
        collections = cleaned_data.get("collections", None)
        if collections is not None:
            instance.collections.set(collections)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        response = super().perform_mutation(_root, info, **data)
        info.context.plugins.product_created(response.product)
        return response


class ProductUpdate(ProductCreate):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a product to update.")
        input = ProductInput(
            required=True, description="Fields required to update a product."
        )

    class Meta:
        description = "Updates an existing product."
        model = models.Product
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def clean_sku(cls, product_type, cleaned_input):
        input_sku = cleaned_input.get("sku")
        if (
            not product_type.has_variants
            and input_sku
            and models.ProductVariant.objects.filter(sku=input_sku).exists()
        ):
            raise ValidationError(
                {
                    "sku": ValidationError(
                        "Product with this SKU already exists.",
                        code=ProductErrorCode.ALREADY_EXISTS,
                    )
                }
            )
    
    @classmethod
    def update_brand_collection_mapping(cls,instance,updated_collection_id):
        brand_collections = brand_models.BrandCollection.objects.filter(brand_id=instance.brand_id,type=BrandCollectionTypeEnum.ZAAMOCATEGORY)
        
        if brand_collections:
            for brand_collection in brand_collections:
                brand_collection.product.remove(instance)

        brand_collection_inst = BrandCollectionCreate()
        brand_collection_inst.add_zaamo_collection_by_publish(instance, instance.brand, category_id=updated_collection_id)
            
    @classmethod
    def update_msp_of_product(cls,instance,step_price):
        update_msp_of_product_using_step_price(instance,step_price)

    @classmethod
    @transaction.atomic
    def save(cls, info, instance, cleaned_input):
        if "has_custom_commission" in cleaned_input:
            instance.has_custom_commission = cleaned_input["has_custom_commission"]
        if "custom_commission_percentage" in cleaned_input:
            instance.has_custom_commission = True
            instance.commission_percentage = cleaned_input["custom_commission_percentage"]
        if "brand_barter" in cleaned_input and instance.brand.brand_barter:
            instance.brand_barter = cleaned_input["brand_barter"]
        if "value_deal" in cleaned_input:
            instance.metadata["value_deal"] = cleaned_input["value_deal"]
            instance.metadata["value_updated_at"] = TimeUtilities.get_current_date_time()
        if "step_price" in cleaned_input:
            
            instance.step_price = cleaned_input["step_price"]
            
            cls.update_msp_of_product(instance,cleaned_input["step_price"])
        if "category" in cleaned_input:
            cls.update_brand_collection_mapping(instance,cleaned_input['category'].id)
            
        instance.save()
        if not instance.product_type.has_variants:
            variant = instance.variants.first()
            update_fields = []
            if "track_inventory" in cleaned_input:
                variant.track_inventory = cleaned_input["track_inventory"]
                update_fields.append("track_inventory")
            if "sku" in cleaned_input:
                variant.sku = cleaned_input["sku"]
                update_fields.append("sku")
            if "base_price" in cleaned_input:
                variant.price_amount = cleaned_input["base_price"]
                update_fields.append("price_amount")
            if update_fields:
                variant.save(update_fields=update_fields)
        # Recalculate the "minimal variant price"
        transaction.on_commit(lambda: update_product_minimal_variant_price_task.delay(instance.pk))
        attributes = cleaned_input.get("attributes")
        if attributes:
            AttributeAssignmentMixin.save(instance, attributes)
        info.context.plugins.product_updated(instance)


class ProductDelete(ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a product to delete.")

    class Meta:
        description = "Deletes a product."
        model = models.Product
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        node_id = data.get("id")
        instance = cls.get_node_or_error(info, node_id, only_type=Product)

        # get draft order lines for variant
        line_pks = list(
            order_models.OrderLine.objects.filter(
                variant__in=instance.variants.all(), order__status=OrderStatus.DRAFT
            ).values_list("pk", flat=True)
        )

        response = super().perform_mutation(_root, info, **data)

        # delete order lines for deleted variant
        order_models.OrderLine.objects.filter(pk__in=line_pks).delete()

        return response


class ProductUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.Product
        description = "Update public metadata for product."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductClearMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears public metadata item for product."
        model = models.Product
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Update private metadata for product."
        model = models.Product
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears private metadata item for product."
        model = models.Product
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductVariantInput(graphene.InputObjectType):
    attributes = graphene.List(
        AttributeValueInput,
        required=False,
        description="List of attributes specific to this variant.",
    )
    cost_price = PositiveDecimal(description="Cost price of the variant.")
    price = PositiveDecimal(description="Price of the particular variant.")
    sku = graphene.String(description="Stock keeping unit.", required=False)
    track_inventory = graphene.Boolean(
        description=(
            "Determines if the inventory of this variant should be tracked. If false, "
            "the quantity won't change when customers buy this item."
        )
    )
    weight = WeightScalar(description="Weight of the Product Variant.", required=False)


class ProductVariantCreateInput(ProductVariantInput):
    attributes = graphene.List(
        AttributeValueInput,
        required=True,
        description="List of attributes specific to this variant.",
    )
    product = graphene.ID(
        description="Product ID of which type is the variant.",
        name="product",
        required=True,
    )
    stocks = graphene.List(
        graphene.NonNull(StockInput),
        description=("Stocks of a product available for sale."),
        required=False,
    )


class ProductVariantCreate(ModelMutation):
    class Arguments:
        input = ProductVariantCreateInput(
            required=True, description="Fields required to create a product variant."
        )

    class Meta:
        description = "Creates a new variant for a product."
        model = models.ProductVariant
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"
        errors_mapping = {"price_amount": "price"}

    @classmethod
    def clean_attributes(
        cls, attributes: dict, product_type: models.ProductType
    ) -> T_INPUT_MAP:
        attributes_qs = product_type.variant_attributes
        attributes = AttributeAssignmentMixin.clean_input(
            attributes, attributes_qs, is_variant=True
        )
        return attributes

    @classmethod
    def validate_duplicated_attribute_values(
        cls, attributes, used_attribute_values, instance=None
    ):
        attribute_values = defaultdict(list)
        for attribute in attributes:
            attribute_values[attribute.id].extend(attribute.values)
        if attribute_values in used_attribute_values:
            raise ValidationError(
                "Duplicated attribute values for product variant.",
                ProductErrorCode.DUPLICATED_INPUT_ITEM,
            )
        else:
            used_attribute_values.append(attribute_values)

    @classmethod
    def clean_input(
        cls, info, instance: models.ProductVariant, data: dict, input_cls=None
    ):
        cleaned_input = super().clean_input(info, instance, data)
        weight = cleaned_input.get("weight")
        if weight and weight.value < 0:
            raise ValidationError(
                {
                    "weight": ValidationError(
                        "Product variant can't have negative weight.",
                        code=ProductErrorCode.INVALID.value,
                    )
                }
            )

        if "cost_price" in cleaned_input:
            cost_price = cleaned_input.pop("cost_price")
            try:
                validate_price_precision(cost_price, instance.currency)
            except ValidationError as error:
                error.code = ProductErrorCode.INVALID.value
                raise ValidationError({"cost_price": error})
            cleaned_input["cost_price_amount"] = cost_price

        price = cleaned_input.get("price")
        if price is None and instance.price is None:
            raise ValidationError(
                {
                    "price": ValidationError(
                        "Variant price is required.",
                        code=ProductErrorCode.REQUIRED.value,
                    )
                }
            )

        if "price" in cleaned_input:
            try:
                validate_price_precision(price, instance.currency)
            except ValidationError as error:
                error.code = ProductErrorCode.INVALID.value
                raise ValidationError({"price": error})
            cleaned_input["price_amount"] = price

        stocks = cleaned_input.get("stocks")
        if stocks:
            cls.check_for_duplicates_in_stocks(stocks)

        if instance.pk:
            # If the variant is getting updated,
            # simply retrieve the associated product type
            product_type = instance.product.product_type
            used_attribute_values = get_used_variants_attribute_values(instance.product)
        else:
            # If the variant is getting created, no product type is associated yet,
            # retrieve it from the required "product" input field
            product_type = cleaned_input["product"].product_type
            used_attribute_values = get_used_variants_attribute_values(
                cleaned_input["product"]
            )

        # Run the validation only if product type is configurable
        if product_type.has_variants:
            # Attributes are provided as list of `AttributeValueInput` objects.
            # We need to transform them into the format they're stored in the
            # `Product` model, which is HStore field that maps attribute's PK to
            # the value's PK.
            attributes = cleaned_input.get("attributes")
            try:
                if attributes:
                    cls.validate_duplicated_attribute_values(
                        attributes, used_attribute_values, instance
                    )
                    cleaned_input["attributes"] = cls.clean_attributes(
                        attributes, product_type
                    )
                elif not instance.pk and not attributes:
                    # if attributes were not provided on creation
                    raise ValidationError(
                        "All attributes must take a value.",
                        ProductErrorCode.REQUIRED.value,
                    )
            except ValidationError as exc:
                raise ValidationError({"attributes": exc})
        try:
            latest_product_varient = models.ProductVariant.objects.latest('id').id
        except:
            latest_product_varient = 0
        if 'product' in cleaned_input:
            cleaned_input["sku"] = graphene.Node.to_global_id("Product", cleaned_input['product'].id) + '_' +  str(latest_product_varient+1)
        return cleaned_input

    @classmethod
    def check_for_duplicates_in_stocks(cls, stocks_data):
        warehouse_ids = [stock["warehouse"] for stock in stocks_data]
        duplicates = get_duplicated_values(warehouse_ids)
        if duplicates:
            error_msg = "Duplicated warehouse ID: {}".format(", ".join(duplicates))
            raise ValidationError(
                {"stocks": ValidationError(error_msg, code=ProductErrorCode.UNIQUE)}
            )

    @classmethod
    def get_instance(cls, info, **data):
        """Prefetch related fields that are needed to process the mutation.

        If we are updating an instance and want to update its attributes,
        # prefetch them.
        """

        object_id = data.get("id")
        if object_id and data.get("attributes"):
            # Prefetches needed by AttributeAssignmentMixin and
            # associate_attribute_values_to_instance
            qs = cls.Meta.model.objects.prefetch_related(
                "product__product_type__variant_attributes__values",
                "product__product_type__attributevariant",
            )
            return cls.get_node_or_error(
                info, object_id, only_type="ProductVariant", qs=qs
            )

        return super().get_instance(info, **data)

    @classmethod
    @transaction.atomic()
    def save(cls, info, instance, cleaned_input):        
       
        instance.save()
        
        if not instance.product.default_variant:
            instance.product.default_variant = instance
            instance.product.save(update_fields=["default_variant", "updated_at"])
        # Recalculate the "minimal variant price" for the parent product
        transaction.on_commit(lambda: update_product_minimal_variant_price_task.delay(instance.product_id))
        stocks = cleaned_input.get("stocks")
        price_amount = cleaned_input.get("price_amount")
        if stocks:
            cls.create_variant_stocks(instance, stocks)
        
        if price_amount:
            update_msp_of_variant_using_step_price(instance)
            
        attributes = cleaned_input.get("attributes")
        if attributes:
            AttributeAssignmentMixin.save(instance, attributes)
            instance.name = generate_name_for_variant(instance)
            instance.save(update_fields=["name"])
        info.context.plugins.product_updated(instance.product)

    @classmethod
    def create_variant_stocks(cls, variant, stocks):
        warehouse_ids = [stock["warehouse"] for stock in stocks]
        warehouses = cls.get_nodes_or_error(
            warehouse_ids, "warehouse", only_type=Warehouse
        )
        create_stocks(variant, stocks, warehouses)


class ProductVariantUpdate(ProductVariantCreate):
    class Arguments:
        id = graphene.ID(
            required=True, description="ID of a product variant to update."
        )
        input = ProductVariantInput(
            required=True, description="Fields required to update a product variant."
        )

    class Meta:
        description = "Updates an existing variant for product."
        model = models.ProductVariant
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"
        errors_mapping = {"price_amount": "price"}

    @classmethod
    def validate_duplicated_attribute_values(
        cls, attributes, used_attribute_values, instance=None
    ):
        # Check if the variant is getting updated,
        # and the assigned attributes do not change
        if instance.product_id is not None:
            assigned_attributes = get_used_attribute_values_for_variant(instance)
            input_attribute_values = defaultdict(list)
            for attribute in attributes:
                input_attribute_values[attribute.id].extend(attribute.values)
            if input_attribute_values == assigned_attributes:
                return
        # if assigned attributes is getting updated run duplicated attribute validation
        super().validate_duplicated_attribute_values(attributes, used_attribute_values)


class ProductVariantDelete(ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(
            required=True, description="ID of a product variant to delete."
        )

    class Meta:
        description = "Deletes a product variant."
        model = models.ProductVariant
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def success_response(cls, instance):
        # Update the "minimal_variant_prices" of the parent product
        update_product_minimal_variant_price_task.delay(instance.product_id)
        product = models.Product.objects.get(id=instance.product_id)
        # if the product default variant has been removed set the new one
        if not product.default_variant:
            product.default_variant = product.variants.first()
            product.save(update_fields=["default_variant"])
        return super().success_response(instance)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        node_id = data.get("id")
        variant_pk = from_global_id_strict_type(node_id, ProductVariant, field="pk")

        # get draft order lines for variant
        line_pks = list(
            order_models.OrderLine.objects.filter(
                variant__pk=variant_pk, order__status=OrderStatus.DRAFT
            ).values_list("pk", flat=True)
        )

        response = super().perform_mutation(_root, info, **data)

        # delete order lines for deleted variant
        order_models.OrderLine.objects.filter(pk__in=line_pks).delete()

        return response


class ProductVariantUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.ProductVariant
        description = "Update public metadata for product variant."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductVariantClearMeta(ClearMetaBaseMutation):
    class Meta:
        model = models.ProductVariant
        description = "Clears public metadata for product variant."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductVariantUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.ProductVariant
        description = "Update private metadata for product variant."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductVariantClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        model = models.ProductVariant
        description = "Clears private metadata for product variant."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductTypeInput(graphene.InputObjectType):
    name = graphene.String(description="Name of the product type.")
    slug = graphene.String(description="Product type slug.")
    has_variants = graphene.Boolean(
        description=(
            "Determines if product of this type has multiple variants. This option "
            "mainly simplifies product management in the dashboard. There is always at "
            "least one variant created under the hood."
        )
    )
    product_attributes = graphene.List(
        graphene.ID,
        description="List of attributes shared among all product variants.",
        name="productAttributes",
    )
    variant_attributes = graphene.List(
        graphene.ID,
        description=(
            "List of attributes used to distinguish between different variants of "
            "a product."
        ),
        name="variantAttributes",
    )
    is_shipping_required = graphene.Boolean(
        description="Determines if shipping is required for products of this variant."
    )
    is_digital = graphene.Boolean(
        description="Determines if products are digital.", required=False
    )
    weight = WeightScalar(description="Weight of the ProductType items.")
    tax_code = graphene.String(description="Tax rate for enabled tax gateway.")


class ProductTypeCreate(ModelMutation):
    class Arguments:
        input = ProductTypeInput(
            required=True, description="Fields required to create a product type."
        )

    class Meta:
        description = "Creates a new product type."
        model = models.ProductType
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def clean_input(cls, info, instance, data):
        cleaned_input = super().clean_input(info, instance, data)

        weight = cleaned_input.get("weight")
        if weight and weight.value < 0:
            raise ValidationError(
                {
                    "weight": ValidationError(
                        "Product type can't have negative weight.",
                        code=ProductErrorCode.INVALID,
                    )
                }
            )

        try:
            cleaned_input = validate_slug_and_generate_if_needed(
                instance, "name", cleaned_input
            )
        except ValidationError as error:
            error.code = ProductErrorCode.REQUIRED.value
            raise ValidationError({"slug": error})

        # FIXME  tax_rate logic should be dropped after we remove tax_rate from input
        tax_rate = cleaned_input.pop("tax_rate", "")
        if tax_rate:
            instance.store_value_in_metadata(
                {"vatlayer.code": tax_rate, "description": tax_rate}
            )
            info.context.plugins.assign_tax_code_to_object_meta(instance, tax_rate)

        tax_code = cleaned_input.pop("tax_code", "")
        if tax_code:
            info.context.plugins.assign_tax_code_to_object_meta(instance, tax_code)

        return cleaned_input

    @classmethod
    def _save_m2m(cls, info, instance, cleaned_data):
        super()._save_m2m(info, instance, cleaned_data)
        product_attributes = cleaned_data.get("product_attributes")
        variant_attributes = cleaned_data.get("variant_attributes")
        if product_attributes is not None:
            instance.product_attributes.set(product_attributes)
        if variant_attributes is not None:
            instance.variant_attributes.set(variant_attributes)


class ProductTypeUpdate(ProductTypeCreate):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a product type to update.")
        input = ProductTypeInput(
            required=True, description="Fields required to update a product type."
        )

    class Meta:
        description = "Updates an existing product type."
        model = models.ProductType
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def save(cls, info, instance, cleaned_input):
        variant_attr = cleaned_input.get("variant_attributes")
        if variant_attr:
            variant_attr = set(variant_attr)
            variant_attr_ids = [attr.pk for attr in variant_attr]
            #update_variants_names.delay(instance.pk, variant_attr_ids)
        super().save(info, instance, cleaned_input)


class ProductTypeDelete(ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a product type to delete.")

    class Meta:
        description = "Deletes a product type."
        model = models.ProductType
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        node_id = data.get("id")
        product_type_pk = from_global_id_strict_type(node_id, ProductType, field="pk")
        variants_pks = models.Product.objects.filter(
            product_type__pk=product_type_pk
        ).values_list("variants__pk", flat=True)
        # get draft order lines for products
        order_line_pks = list(
            order_models.OrderLine.objects.filter(
                variant__pk__in=variants_pks, order__status=OrderStatus.DRAFT
            ).values_list("pk", flat=True)
        )

        response = super().perform_mutation(_root, info, **data)

        # delete order lines for deleted variants
        order_models.OrderLine.objects.filter(pk__in=order_line_pks).delete()

        return response


class ProductTypeUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        model = models.ProductType
        description = "Update public metadata for product type."
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductTypeClearMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears public metadata for product type."
        model = models.ProductType
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        public = True
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductTypeUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Update private metadata for product type."
        model = models.ProductType
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductTypeClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears private metadata for product type."
        model = models.ProductType
        permissions = (ProductTypePermissions.MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,)
        public = False
        error_type_class = ProductError
        error_type_field = "product_errors"


class ProductImageCreateInput(graphene.InputObjectType):
    alt = graphene.String(description="Alt text for an image.")
    image = Upload(
        required=True, description="Represents an image file in a multipart request."
    )
    product = graphene.ID(
        required=True, description="ID of an product.", name="product"
    )


class ProductImageCreate(BaseMutation):
    product = graphene.Field(Product)
    image = graphene.Field(ProductImage)

    class Arguments:
        input = ProductImageCreateInput(
            required=True, description="Fields required to create a product image."
        )

    class Meta:
        description = (
            "Create a product image. This mutation must be sent as a `multipart` "
            "request. More detailed specs of the upload format can be found here: "
            "https://github.com/jaydenseric/graphql-multipart-request-spec"
        )
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        data = data.get("input")
        product = cls.get_node_or_error(
            info, data["product"], field="product", only_type=Product
        )
        image_data = info.context.FILES.get(data["image"])
        validate_image_file(image_data, "image")

        image = product.images.create(image=image_data, alt=data.get("alt", ""))
        create_product_thumbnails.delay(image.pk)
        return ProductImageCreate(product=product, image=image)


class ProductImageUpdateInput(graphene.InputObjectType):
    alt = graphene.String(description="Alt text for an image.")


class ProductImageUpdate(BaseMutation):
    product = graphene.Field(Product)
    image = graphene.Field(ProductImage)

    class Arguments:
        id = graphene.ID(required=True, description="ID of a product image to update.")
        input = ProductImageUpdateInput(
            required=True, description="Fields required to update a product image."
        )

    class Meta:
        description = "Updates a product image."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        image = cls.get_node_or_error(info, data.get("id"), only_type=ProductImage)
        product = image.product
        alt = data.get("input").get("alt")
        if alt is not None:
            image.alt = alt
            image.save(update_fields=["alt"])
        return ProductImageUpdate(product=product, image=image)


class ProductImageReorder(BaseMutation):
    product = graphene.Field(Product)
    images = graphene.List(ProductImage)

    class Arguments:
        product_id = graphene.ID(
            required=True,
            description="Id of product that images order will be altered.",
        )
        images_ids = graphene.List(
            graphene.ID,
            required=True,
            description="IDs of a product images in the desired order.",
        )

    class Meta:
        description = "Changes ordering of the product image."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, product_id, images_ids):
        product = cls.get_node_or_error(
            info, product_id, field="product_id", only_type=Product
        )
        if len(images_ids) != product.images.count():
            raise ValidationError(
                {
                    "order": ValidationError(
                        "Incorrect number of image IDs provided.",
                        code=ProductErrorCode.INVALID,
                    )
                }
            )

        images = []
        for image_id in images_ids:
            image = cls.get_node_or_error(
                info, image_id, field="order", only_type=ProductImage
            )
            if image and image.product != product:
                raise ValidationError(
                    {
                        "order": ValidationError(
                            "Image %(image_id)s does not belong to this product.",
                            code=ProductErrorCode.NOT_PRODUCTS_IMAGE,
                            params={"image_id": image_id},
                        )
                    }
                )
            images.append(image)

        for order, image in enumerate(images):
            image.sort_order = order
            image.save(update_fields=["sort_order"])

        return ProductImageReorder(product=product, images=images)


class ProductVariantSetDefault(BaseMutation):
    product = graphene.Field(Product)

    class Arguments:
        product_id = graphene.ID(
            required=True,
            description="Id of a product that will have the default variant set.",
        )
        variant_id = graphene.ID(
            required=True, description="Id of a variant that will be set as default.",
        )

    class Meta:
        description = (
            "Set default variant for a product. "
            "Mutation triggers PRODUCT_UPDATED webhook."
        )
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, product_id, variant_id):
        product = cls.get_node_or_error(
            info, product_id, field="product_id", only_type=Product
        )
        variant = cls.get_node_or_error(
            info,
            variant_id,
            field="variant_id",
            only_type=ProductVariant,
            qs=models.ProductVariant.objects.select_related("product"),
        )
        if variant.product != product:
            raise ValidationError(
                {
                    "variant_id": ValidationError(
                        "Provided variant doesn't belong to provided product.",
                        code=ProductErrorCode.NOT_PRODUCTS_VARIANT,
                    )
                }
            )
        product.default_variant = variant
        product.save(update_fields=["default_variant", "updated_at"])
        info.context.plugins.product_updated(product)
        return ProductVariantSetDefault(product=product)


class ProductVariantReorder(BaseMutation):
    product = graphene.Field(Product)

    class Arguments:
        product_id = graphene.ID(
            required=True,
            description="Id of product that variants order will be altered.",
        )
        moves = graphene.List(
            ReorderInput,
            required=True,
            description="The list of variant reordering operations.",
        )

    class Meta:
        description = (
            "Reorder the variants of a product. "
            "Mutation updates updated_at on product and "
            "triggers PRODUCT_UPDATED webhook."
        )
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, product_id, moves):
        pk = from_global_id_strict_type(product_id, only_type=Product, field="id")

        try:
            product = models.Product.objects.prefetch_related("variants").get(pk=pk)
        except ObjectDoesNotExist:
            raise ValidationError(
                {
                    "product_id": ValidationError(
                        (f"Couldn't resolve to a product type: {product_id}"),
                        code=ProductErrorCode.NOT_FOUND,
                    )
                }
            )

        variants_m2m = product.variants
        operations = {}

        for move_info in moves:
            variant_pk = from_global_id_strict_type(
                move_info.id, only_type=ProductVariant, field="moves"
            )

            try:
                m2m_info = variants_m2m.get(id=int(variant_pk))
            except ObjectDoesNotExist:
                raise ValidationError(
                    {
                        "moves": ValidationError(
                            f"Couldn't resolve to a variant: {move_info.id}",
                            code=ProductErrorCode.NOT_FOUND,
                        )
                    }
                )
            operations[m2m_info.pk] = move_info.sort_order

        with transaction.atomic():
            perform_reordering(variants_m2m, operations)

        product.save(update_fields=["updated_at"])
        info.context.plugins.product_updated(product)
        return ProductVariantReorder(product=product)


class ProductImageDelete(BaseMutation):
    product = graphene.Field(Product)
    image = graphene.Field(ProductImage)

    class Arguments:
        id = graphene.ID(required=True, description="ID of a product image to delete.")

    class Meta:
        description = "Deletes a product image."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        image = cls.get_node_or_error(info, data.get("id"), only_type=ProductImage)
        image_id = image.id
        image.delete()
        image.id = image_id
        return ProductImageDelete(product=image.product, image=image)


class VariantImageAssign(BaseMutation):
    product_variant = graphene.Field(ProductVariant)
    image = graphene.Field(ProductImage)

    class Arguments:
        image_id = graphene.ID(
            required=True, description="ID of a product image to assign to a variant."
        )
        variant_id = graphene.ID(required=True, description="ID of a product variant.")

    class Meta:
        description = "Assign an image to a product variant."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, image_id, variant_id):
        image = cls.get_node_or_error(
            info, image_id, field="image_id", only_type=ProductImage
        )
        variant = cls.get_node_or_error(
            info, variant_id, field="variant_id", only_type=ProductVariant
        )
        if image and variant:
            # check if the given image and variant can be matched together
            image_belongs_to_product = variant.product.images.filter(
                pk=image.pk
            ).first()
            if image_belongs_to_product:
                image.variant_images.create(variant=variant)
            else:
                raise ValidationError(
                    {
                        "image_id": ValidationError(
                            "This image doesn't belong to that product.",
                            code=ProductErrorCode.NOT_PRODUCTS_IMAGE,
                        )
                    }
                )
        return VariantImageAssign(product_variant=variant, image=image)


class VariantImageUnassign(BaseMutation):
    product_variant = graphene.Field(ProductVariant)
    image = graphene.Field(ProductImage)

    class Arguments:
        image_id = graphene.ID(
            required=True,
            description="ID of a product image to unassign from a variant.",
        )
        variant_id = graphene.ID(required=True, description="ID of a product variant.")

    class Meta:
        description = "Unassign an image from a product variant."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, image_id, variant_id):
        image = cls.get_node_or_error(
            info, image_id, field="image_id", only_type=ProductImage
        )
        variant = cls.get_node_or_error(
            info, variant_id, field="variant_id", only_type=ProductVariant
        )

        try:
            variant_image = models.VariantImage.objects.get(
                image=image, variant=variant
            )
        except models.VariantImage.DoesNotExist:
            raise ValidationError(
                {
                    "image_id": ValidationError(
                        "Image is not assigned to this variant.",
                        code=ProductErrorCode.NOT_PRODUCTS_IMAGE,
                    )
                }
            )
        else:
            variant_image.delete()

        return VariantImageUnassign(product_variant=variant, image=image)


class ProductSetAvailabilityForPurchase(BaseMutation):
    product = graphene.Field(Product)

    class Arguments:
        product_id = graphene.ID(
            required=True,
            description=(
                "Id of product that availability for purchase should be changed."
            ),
        )
        is_available = graphene.Boolean(
            description="Determine if product should be available for purchase.",
            required=True,
        )
        start_date = graphene.Date(
            description=(
                "A start date from which a product will be available for purchase. "
                "When not set and isAvailable is set to True, "
                "the current day is assumed."
            ),
            required=False,
        )

    class Meta:
        description = "Set product availability for purchase date."
        permissions = (ProductPermissions.MANAGE_PRODUCTS,)
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        product = cls.get_node_or_error(info, data.get("product_id"), only_type=Product)
        is_available = data.get("is_available")
        start_date = data.get("start_date")

        if start_date and not is_available:
            raise ValidationError(
                {
                    "start_date": ValidationError(
                        "Cannot set start date when isAvailable is false.",
                        code=ProductErrorCode.INVALID,
                    )
                }
            )

        if not is_available:
            product.available_for_purchase = None
        elif is_available and not start_date:
            product.available_for_purchase = datetime.date.today()
        else:
            product.available_for_purchase = start_date

        product.save(update_fields=["available_for_purchase", "updated_at"])
        info.context.plugins.product_updated(product)
        return ProductSetAvailabilityForPurchase(product=product)


class ToggleThriftStoreInput(graphene.InputObjectType):
    mobile_no = graphene.String(description = "mobile_no of influencer",
                                required = True)
    is_thrift = graphene.Boolean(desciption="toggle thrift store" ,required = True)

class ToggleThriftStore(StoreBaseMutation):
    class Arguments:
        input = ToggleThriftStoreInput(description = "id of account whose thrift needs to be activated")

    class Meta:
        description = "activating thirft collection"
        error_type_class = AccountError
        error_type_field = "account_errors"
        permissions = (InfluencerPermissions.MANAGE_INFLUENCER,)

    user = graphene.Field(User,description ="user data")

    @classmethod
    def create_thrift_collection_instance(cls,store_instance,user_instance):
        collection_instance = models.Collection.create_instance({
        'name': store_instance.store_name+"'s"+" Thrift",
        'slug': 'thrift-'+NumberUtilities.convert_integer_to_hexadecimal(store_instance.id),
        'is_default': False,
        'is_published': True,
        'is_thrift':True
        })
        models.CollectionStore.create_instance({
        'store_instance': store_instance,
        'user_instance': user_instance,
        'collection_instance': collection_instance

    })

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        user_instance = account_models.User.get_user_instance_by_mobile(
            data.get('input').get('mobile_no'))

        if not user_instance:
            raise ValidationError(message = "In-valid mobile number")

        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        collection_qs = models.Collection.objects.filter(collection_store__store=store_instance)

        slug = "thrift-"+ NumberUtilities.convert_integer_to_hexadecimal(store_id)
        if data.get('input').get('is_thrift'):

            if not collection_qs.filter(is_thrift=True).exists():

                if models.Collection.is_collection_exists(slug):
                    collection_instance = models.Collection.objects.filter(slug = slug).first()
                    collection_instance.is_thrift = True
                    collection_instance.save()

                else:
                    cls.create_thrift_collection_instance(store_instance,user_instance)
        else:

            if models.Collection.is_collection_exists(slug):
                    collection_instance = models.Collection.objects.filter(slug = slug).first()
                    collection_instance.is_thrift = False
                    collection_instance.save()


        return cls(user = user_instance)

class ThriftProductCreateInput(graphene.InputObjectType):
    product_brand_name = graphene.String(description="Brand name of the product which is added. ")
    product_name = graphene.String(description="Name of the product. ",required=True)
    cost_price = PositiveDecimal(description=("cost price for product. "),required=True)
    price_amount = PositiveDecimal(description=("selling price for prodcut. "),required=True)
    product_detail = graphene.String(description="Product description.")
    images_url_list = graphene.List(graphene.String)
    quantity = graphene.Int(description="quantity of stock")

class ThriftProductCreate(ModelMutation):
    product = graphene.Field(Product,description="Product instance")

    class Arguments:
        input = ThriftProductCreateInput(
            required=True, description="Fields required to create a product."
        )
    class Meta:
        description = "Creates a new product."
        model = models.Product
        permissions = (InfluencerPermissions.MANAGE_INFLUENCER,)
        error_type_class = ProductError
        error_type_field = "product_errors"

         
    @classmethod
    def get_product_type(cls):
        product_type = "thrift_product_type"
        product_type_data = {
        "fields": {
          "name": product_type,
          "slug": slugify(product_type, allow_unicode=True),
          "has_variants": True,
          "is_shipping_required": True,
          "is_digital": False
            }
        }
        base_product_create_instance = BaseProductCreate()
        final_product_type = base_product_create_instance.get_or_create_product_types(product_type_data)
        return final_product_type.id

    @classmethod
    def prepare_data(cls,info,data):
        
        store_id =  graphene.Node.to_global_id("Store",RequestUtilities.get_store_id_from_headers(info.context))
        brand = brand_models.Brand.objects.filter(brand_name="thrift_brand").first()
        category = models.Category.objects.filter(slug=slugify("thrift_category")).first()
        product_type_id = cls.get_product_type()
        product_attributes = {
        "size": {
            "values":[],
            "is_variant_attribute":True
        },
        "color": {
            "values":[],
            "is_variant_attribute":True
        }
        }
        brand_variant_zaamomapping = { 
            "product_id_brand": data.get('input').get('product_name')+store_id + StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds()),
            "brand_name": brand.brand_name,
            "source": "thrift"
        }
        product = {
            "fields": {
                "brand": brand.id,
                "private_metadata": {},
                "metadata": { "product_brand_name":data.get('input').get('product_brand_name','')},
                "name": data.get('input').get('product_name'),
                "description_json":{"description_text": data.get('input').get('product_detail','')},
                "minimal_variant_price_amount":data.get('input').get('price_amount'),
                "is_published":True
            }
        }

        brand_mapping = dict()
        brand_mapping['product_id_brand'] = brand_variant_zaamomapping['product_id_brand']
        brand_mapping['brand_name'] = brand_variant_zaamomapping['brand_name']
        brand_mapping['source'] = brand_variant_zaamomapping['source']
        brand_mapping['variant_id_brands'] = "variant" + store_id + StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds())

        variants = [{
            "attributes":product_attributes,
            "fields" :{
                "variant_id_brand":"variant" + store_id + StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds()),
                "private_metadata": {},
                "metadata": { "product_brand_name":data.get('input').get('product_brand_name','')},
                "sku_id_brand": store_id + StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds()),
                "name":data.get('input').get('product_name') ,
                "price_amount": data.get('input').get('price_amount') ,
                "cost_price_amount": data.get('input').get('cost_price'),
                "default":True

            },
          "stock": {  "quantity": data.get('input').get('quantity',1) }
        }]



        mapped_data = {
            "product.category" : category.id,
            "product.producttype":product_type_id,
            "brand.brand": brand.id,
            "product.attribute": product_attributes,
            "product.brand_variant_zaamomapping": brand_mapping,
            "product.productimage": data.get('input').get('images_url_list',[]),
            "product.product": product,
            "product.productvariant":variants,
            "upload_images_to_ecom": False,
            "upload_to_content_service":False
        }

        return mapped_data

    @classmethod
    def perform_mutation(cls, _root, info, **data):

        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        product_create_dict = cls.prepare_data(info,data)
        collection_store_instance =  models.CollectionStore.objects.filter(collection__is_thrift=True,store_id = store_id).first()
        if not collection_store_instance:
            raise Exception("User has not opted for Thrift")

        collection_instance = collection_store_instance.collection
        base_product_create = BaseProductCreate()
        prepared_json = base_product_create.prepare_db_items(product_create_dict)
        product_instance = base_product_create.create_or_update_db_item(prepared_json,product_needed=True)
        
        for url in product_create_dict["product.productimage"]:
                
                image_data = base_product_create.retrieve_image_in_base64_encoded(url)
                save_image_with_celery.delay(image_data,product_instance.id)
        collection_product,_ = models.CollectionProduct.objects.update_or_create(collection = collection_instance,product = product_instance)


        return cls(product=product_instance)

class ThriftProductUpdateInput(graphene.InputObjectType):
    product_brand_name = graphene.String(description="Brand name of the product which is added. ")
    product_name = graphene.String(description="Name of the product. ")
    cost_price = PositiveDecimal(description=("cost price for product. "))
    price_amount = PositiveDecimal(description=("selling price for prodcut. "))
    product_detail = graphene.String(description="Product description.")
    images_url_list = graphene.List(graphene.String)
    quantity = graphene.Int(description="quantity of stock")

class ThriftProductUpdate(ModelMutation):
    product = graphene.Field(Product,description="Product instance")

    class Arguments:
        id = graphene.ID(required=True, description="ID of a product to update.")
        input = ThriftProductUpdateInput(
            required=True, description="Fields required to create a product."
        )
    class Meta:
        description = "Updates a new product."
        model = models.Product
        permissions = (InfluencerPermissions.MANAGE_INFLUENCER,)
        error_type_class = ProductError
        error_type_field = "product_errors"


    @classmethod
    def prepare_updated_data(cls,data):
        brand = brand_models.Brand.objects.filter(brand_name="thrift_brand").first()
        category = models.Category.objects.filter(slug=slugify("thrift_category")).first()
        product_id = graphene.Node.from_global_id(data.get('id'))[1]
        try:
            warehouse = warehouse_models.Warehouse.objects.get(slug="zaamo-master-warehouse")
        except:
            warehouse = warehouse_models.Warehouse.objects.none()
        product_instance = models.Product.objects.filter(pk=product_id).first()
        variant_instance = models.ProductVariant.objects.filter(product_id = product_id).first()
        variant_stock_instance = warehouse_models.Stock.objects.filter(warehouse=warehouse, product_variant=variant_instance).first()
        product_type_id = product_instance.product_type.id
        brand_variant_zaamomapping_instance = models.BrandVariantZaamoMapping.objects.filter(product_zaamo_id=product_id, variant_zaamo_id=variant_instance.id).first()
        product_attributes = {
        "size": {
            "values":[],
            "is_variant_attribute":True
        },
        "color": {
            "values":[],
            "is_variant_attribute":True
        }
        }
        brand_variant_zaamomapping = { 
            "product_id_brand":brand_variant_zaamomapping_instance.product_id_brand ,
            "brand_name": brand.brand_name,
            "source": "thrift",
            "variant_zaamo_id": brand_variant_zaamomapping_instance.variant_zaamo_id
        }
        prev_description = product_instance.description_json.get("description_text")
        product = {
            "fields": {
                "brand": brand.id,
                "private_metadata": {},
                "metadata": { "product_brand_name":data.get('input').get('product_brand_name',product_instance.metadata.get('product_brand_name'))},
                "name": data.get('input').get('product_name',product_instance.name),
               "description_json":{"description_text": data.get('input').get('product_detail',prev_description)},
                "minimal_variant_price_amount":data.get('input').get('price_amount',variant_instance.price_amount),
            }
        }

        brand_mapping = dict()
        brand_mapping['product_id_brand'] = brand_variant_zaamomapping['product_id_brand']
        brand_mapping['brand_name'] = brand_variant_zaamomapping['brand_name']
        brand_mapping['source'] = brand_variant_zaamomapping['source']
        brand_mapping['variant_zaamo_id'] = brand_variant_zaamomapping['variant_zaamo_id']

        variants = [{
            "attributes":product_attributes,
            "fields" :{
                "variant_id_brand":brand_variant_zaamomapping_instance.variant_id_brand,
                "private_metadata": {},
                "metadata": { "product_brand_name":data.get('input').get('product_brand_name',product_instance.metadata.get('product_brand_name'))},
                "sku_id_brand":brand_variant_zaamomapping_instance.sku_id_brand,
                "name":data.get('input').get('product_name',product_instance.name) ,
                "price_amount": data.get('input').get('price_amount',variant_instance.price_amount) ,
                "cost_price_amount": data.get('input').get('cost_price',variant_instance.cost_price_amount),
                "default":False

            },
            "stock": { "quantity":data.get('input').get('quantity',variant_stock_instance.quantity)}
        }]
        mapped_data = {
            "product.category" : category.id,
            "product.producttype":product_type_id,
            "brand.brand": brand.id,
            "product.attribute": product_attributes,
            "product.brand_variant_zaamomapping": brand_mapping,
            "product.productimage": data.get('input').get('images_url_list',[]),
            "product.product": product,
            "product.productvariant":variants,
            "upload_images_to_ecom": False,
            "upload_to_content_service":False
        }

        return mapped_data

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        product_create_dict = cls.prepare_updated_data(data)
        base_product_create = BaseProductCreate()
        prepared_json = base_product_create.prepare_db_items(product_create_dict)
        product_instance = base_product_create.create_or_update_db_item(prepared_json,product_needed=True)
        for url in product_create_dict["product.productimage"]:
                image_data = base_product_create.retrieve_image_in_base64_encoded(url)
                save_image_with_celery.delay(image_data,product_instance.id)

        return cls(product=product_instance)

class SourcingRequestCreate(BaseMutation):

    sourcing_request = graphene.Field(SourcingRequest,description = "Product Sourcing Request instance")

    class Arguments:
        variant_id = graphene.ID(required=True, description="ID of variant for sourcing.")


    class Meta:
        description = "Updates a new product."
        model = models.SourcingRequest
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def sending_email(cls,sourcing_instance,data):

        data['brand_collab'] = sourcing_instance.brand_collab
        souring_request_text = sourcing_request_email_context(data)
        # cc= data["influencer_managers"].split(',') + data["brand_managers"].split(',')
        # cc = [email for email in cc if email]
        cc=[]
   
        send_sourcing_request_email.delay('New Sourcing Request - {}'.format(sourcing_instance.id), 
                                          souring_request_text, cc=cc)

    @classmethod
    def check_for_existance_of_brand_sourcing_request(cls, brand_instance, store_instance, user_instance):
        brand_sourcing_request = BrandSourcingRequest.objects.filter(
            store = store_instance,
            brand = brand_instance,
            created_by = user_instance
        )

        if brand_sourcing_request:
            return True
        else:
            return False

    @classmethod
    def perform_mutation(cls, root, info, **data):

        user_instance = info.context.user
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        try:
            variant_id = graphene.Node.from_global_id(data.get('variant_id'))[1]
        except Exception as e:
            print("Invalid Variant ID")
            return
        
        variant_instance = None
        product_instance = None
        brand_instance = None

        variant_instance = models.ProductVariant.objects.filter(pk=variant_id).first()
        if variant_instance:
            product_instance = variant_instance.product
            if product_instance:
                brand_instance = product_instance.brand

        store_barter = store_instance.metadata.get('store_barter')
        if store_barter is not None:
            if not store_barter:
                if not cls.check_for_existance_of_brand_sourcing_request(brand_instance, store_instance, user_instance):
                    raise ValidationError("Sourcing Request creation is not allowed.") 

        if brand_instance:
            if not brand_instance.status in [BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER]:
                raise ValidationError("Product is not for sourcing.")

        store_managers = ""
        for data in store_instance.staff_store_mappings.all().prefetch_related('user'):
            user = data.user
            
            if user.email:
                store_managers+=(user.email+",")
        
        brand_managers = ""
        
        for data in brand_instance.staff_brand_mappings.all().prefetch_related('user'):
            user = data.user
            if user.email:
                brand_managers+=(user.email+",")

        sourcing_data = {
            "store":store_instance,
            "influencer_managers":store_managers,
            "product":product_instance,
            "variant":variant_instance,
            "brand":brand_instance,
            "brand_managers":brand_managers,
            "user_last_updated": user_instance
        }

        brand_sourcing_request = BrandSourcingRequest.objects.filter(
            store=store_instance, 
            brand=brand_instance,
            created_at__gt = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(), days=30)
        )

        if brand_sourcing_request:
            brand_sourcing_request_instance = brand_sourcing_request.first()
            sourcing_data["brand_collab"] = brand_sourcing_request_instance.brand_collab
            sourcing_data["content"] = brand_sourcing_request_instance.terms_and_conditions

        check = models.SourcingRequest.objects.filter(store=store_instance , product = product_instance)
        if check.exists():
            sourcing_instance = check.first()
        else:
            sourcing_instance =models.SourcingRequest.objects.create(**sourcing_data)
            if brand_instance:
                sourcing_data["brand_barter_guidelines"] = brand_instance.brand_barter_guidelines
                sourcing_data["brand_active"] = "active" if brand_instance.status == BrandStatusEnum.ACTIVE else "in-active"
                sourcing_data["brand_barter"] = "barter" if brand_instance.brand_barter else "not-barter"
                sourcing_data["brand_tmo"] = "tmo" if brand_instance.too_many_orders else "not-tmo"
            else:
                sourcing_data["brand_barter_guidelines"] = ""
                sourcing_data["brand_active"] = ""
                sourcing_data["brand_barter"] = ""
                sourcing_data["brand_tmo"] = ""
            
            if user_instance:
                sourcing_data["user_last_updated"] = user_instance.email
            else:
                sourcing_data["user_last_updated"] = ""

            # cls.sending_email(sourcing_instance,sourcing_data)            

        return cls(sourcing_request=sourcing_instance)

class SourcingRequestUpdate(SourcingRequestCreate):

    sourcing_request = graphene.Field(SourcingRequest,description = "Product Sourcing Request instance")
    class Arguments:
        id = graphene.ID(description = "Sourcing Request Id" ,required = True)
        status = SourcingRequestStatusTypeEnum(description="Sourcing request status enum",required = False)
        content = graphene.String(required = False , description = "content link in sourcing request")
        recommended = graphene.Boolean(required = False , description = "recommended in sourcing request")
        next_task = graphene.String(required = False , description = "next_task in sourcing request")
        next_date = graphene.Date(required = False , description = "next_date in sourcing request")

    class Meta:
        description = "Updates a new product."
        model = models.SourcingRequest
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        
        user = info.context.user
        sourcing_id = graphene.Node.from_global_id(data.get('id'))[1]
        sourcing_instance = models.SourcingRequest.objects.filter(id = sourcing_id).first()

        if data.get('status'):
            sourcing_instance.status = data.get('status')
            if data.get('status') == SourcingRequestStatus.BRAND_SHARED_DELIVERABLES:
                sourcing_request_status_update_notification(sourcing_instance)
            if data.get('status') == SourcingRequestStatus.ZAAMO_COUPON_CREATED or data.get('status') == SourcingRequestStatus.BRAND_COUPON_CREATED:
                sourcing_request_coupon_created_notification(sourcing_instance)
            
        
        if data.get('content'):
            sourcing_instance.content = data.get('content')

        if data.get('recommended') is not None:
            sourcing_instance.recommended = data.get('recommended')

        if data.get('next_task'):
            sourcing_instance.next_task = data.get('next_task')
        
        if data.get('next_date'):
            sourcing_instance.next_date = data.get('next_date')

        
        sourcing_instance.user_last_updated = user
        sourcing_instance.save()

        return cls(sourcing_request =sourcing_instance)


class ProductTagCreate(BaseMutation):

    product_tag = graphene.Field(ProductTag,description = "Product Tag instance")

    class Arguments:
        name = graphene.String(description = "Name of tag" ,required = True)

    class Meta:
        description = "Create Tag"
        model = models.ProductTag
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls,root, info, **data):
        name = data.get('name').lower()

        product_tag_inst = models.ProductTag.objects.update_or_create(name=name)

        return cls(product_tag = product_tag_inst[0])

class ProductTagUpdate(BaseMutation):

    product_tag_mapping = graphene.List(ProductTagMapping,description = "Product Tag mapping instance")
    
    class Arguments:
        product_id = graphene.ID(description = "product Id" ,required = True)
        tags = graphene.List(graphene.ID, description="List of Tags",required = True)
        weight = graphene.Int(description = "weight of the tag", required=False)

    class Meta:
        description = "Attach tags to a product"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        
        product_id = graphene.Node.from_global_id(data.get('product_id'))[1]
        tags_global = data.get('tags')
        weight = data.get('weight',0)
        product = models.Product.objects.filter(id=product_id).first()

        if weight>2 or weight<0:
            raise ValidationError(message="Weight should be in range of [0,2].")
            
        if product.brand.brand_name=="thrift_brand":
            raise ValidationError(message="Not applicable for thrift brand")

        tags_id = []
        defaults = dict()
        defaults['weight'] = weight
        defaults['brand_id'] = product.brand_id
        for tag_global in tags_global:
            tags_id.append(graphene.Node.from_global_id(tag_global)[1])

        for tag in tags_id:
            models.ProductTagMapping.objects.update_or_create(product_id=product_id,product_tag_id=tag,defaults=defaults)
        
        models.ProductTagMapping.objects.filter(product_id=product_id).exclude(product_tag_id__in=tags_id).delete()
        
        product_mapping_inst = models.ProductTagMapping.objects.filter(product_id=product_id).select_related('product','product_tag')
        return cls(product_tag_mapping = product_mapping_inst)


class ProductGroupCreateOrUpdate(BaseMutation):

    product_group = graphene.Field(ProductGrouping,description = "Product Group instance")

    class Arguments:
        name = graphene.String(description = "Name of group" ,required = True)
        type = productgroupingenum(description = "type of group" )
        rule = graphene.JSONString(description = "rule of group" ,required = True)
        image = Upload(description = 'image for grouping')

    class Meta:
        description = "Create Product Group"
        model = models.ProductGrouping
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def clean_rule(cls,rule):
        rule_price = rule.get('price',{})
        rule_discount = rule.get('discount',{})
        price = {
                    "gtequal": NumberUtilities.convert_string_to_float(rule_price.get("gte",0)),
                    "ltequal": NumberUtilities.convert_string_to_float(rule_price.get("lte",10**5))
                    }
        discount = {
                    "gtequal": NumberUtilities.convert_string_to_float(rule_discount.get("gte",0)),
                    "ltequal": NumberUtilities.convert_string_to_float(rule_discount.get("lte",10**5))
                    }
        
        categories_list  = []
        if rule.get("categories"):
            categories = get_nodes(rule.get("categories",[]), "Category", models.Category)
            
            categories = [
                category.get_descendants(include_self=True) for category in categories
            ]
            ids = {graphene.Node.to_global_id("Category",category.id) for tree in categories for category in tree}
            categories_list.extend(list(ids))

        clean_rule = {
            "categories": categories_list,
            "brands": rule.get("brands",[]),
            "productTags": rule.get("productTags",[]),
            "brandCollection": rule.get("brandCollection",[]),
            "price": price,
            "discount": discount,
            "field": rule.get("field","TAG_STRENGTH"),
            "direction": rule.get("direction","DESC"),
        }

        if not rule.get("valueDeal")==None:
            clean_rule['valueDeal'] = rule.get("valueDeal")
            
        if not rule.get("stealDeal")==None:
            clean_rule['stealDeal'] = rule.get("stealDeal")

        return clean_rule

    @classmethod
    def perform_mutation(cls,root, info, **data):
        name = data.get('name').lower()
        
        if not data.get('rule'):
        
            raise ValidationError(message="No rule found!")
        
        rule = cls.clean_rule(data.get('rule'))

        type = data.get('type',ProductGroupingEnum.TAGGED_COLLECTION)

        image_data = None

        if data.get("image"):
            image_data = info.context.FILES.get(data["image"])
            validate_image_file(image_data, "image")

        default = {
            "name":name,
            "type":type,
            "slug":generate_unique_slug(models.ProductGrouping(),name),
            "rule":rule,
            "image":image_data}

        product_grouping = models.ProductGrouping.objects.update_or_create(name=name,defaults=default)
        
        update_mapping_for_product_grouping_from_mutation.delay(new_grouping_id=product_grouping[0].id)

        return cls(product_group = product_grouping[0])


class pushProductToShopify(BaseMutation):

    product = graphene.Field(Product,description = "Product instance")
    message = graphene.String(description = "message")

    class Arguments:
        product_id = graphene.ID(description = "product Id" ,required = True)
        status = graphene.Boolean(description = "status of instance",required = True)

    class Meta:
        description = "Push product to zaamo shopify"
        model = models.Product
        error_type_class = ProductError
        error_type_field = "product_errors"

    @classmethod
    def perform_mutation(cls,root, info, product_id,status):
        product_id = graphene.Node.from_global_id(product_id)[1]

        product = models.Product.objects.filter(id=product_id,is_published=True,brand__status__in=[BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER]).select_related('brand').prefetch_related('variants','variants__stocks').first()

        if not product:
            return cls(product = None,message="product is unpublished or brand is inactive")
        
        if not product.metadata.get('instock'):
            return cls(product = product,message="product is not in stock")

        if models.RejectedShopifyProduct.objects.filter(product_id=product_id).exists():
            return cls(product = product, message="unable to push (SHOPIFY_REJECTED)")
        
        already_existing = models.ZaamoShopifyProductMapping.objects.filter(product_zaamo_id=product.id)
        is_already_existing = already_existing.exists()

        product.metadata['shopify']=status
        product.save()

        if is_already_existing:
            product_id_brand = already_existing.first().product_id_brand
            prev_status = already_existing.first().status
            shopify_status = 'active' if status else 'draft'

            if shopify_status!=prev_status:
                update_product_status_shopify_task.delay(product_id_brand,status,product.id)

            return cls(product = product,message="Product is already on shopify")

        if status:

            if not product:
                return cls(product = product,message="No product found")
            
            category_mapping = models.ZaamoShopifyCategoryMapping.objects.filter(zaamo_category_id=product.category_id).first()
            category_name = ''
            
            if category_mapping:
                category_name=category_mapping.shopify_category_name

            push_product_to_shopify_task.delay(product.id,category_name)

            return cls(product = product,message="Product will be pushed shortly!")

        return cls(product = product,message="product updated")
