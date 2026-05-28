from django.db.models import Q, Max, Count, F
from email.policy import default
from unicodedata import category
from saleor.discount.models import Voucher
from saleor.graphql.brand.filters import BrandFilterInput
from saleor.graphql.brand.sorters import BrandSortingInput
from saleor.graphql.core.types.common import Image
from saleor.graphql.product.sorters import CollectionSortingInput
from saleor.graphql.product.filters import CollectionFilterInput
from saleor.graphql.core.fields import FilterInputConnectionField, PrefetchingConnectionField
import graphene
from graphene import relay
from saleor.graphql.core.connection import CountableDjangoObjectType
from saleor.graphql.store.enums import StoreTypeEnums
from saleor.store import models as store_models
from saleor.graphql.product.types import Collection
from graphene_federation import key

from saleor.graphql.warehouse.resolvers import resolve_warehouse

from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.time_utilities import TimeUtilities
from .resolvers import resolve_brands, resolve_categories, resolve_collections, resolve_default_collection, resolve_store_members,resolve_thrift_collection,resolve_thrift_status
from .resolvers import InfluencerBrandClubbedResolvers
from saleor.product import SourcingRequestStatus
from saleor.product.models import CollectionProduct
from django.contrib.postgres.aggregates import ArrayAgg

class StoreMember(graphene.ObjectType):
    id = graphene.ID(description="store member id")
    email = graphene.String(description="store member emailId")
    first_name = graphene.String(description="store member first name")
    last_name = graphene.String(description="store member last name")
   
    class Meta:
        description = "Represents store member address data."

class BrandOfTheDay(graphene.ObjectType):
    brand = graphene.Field("saleor.graphql.brand.types.Brand")
    voucher_code = graphene.String(description="voucher code")
    voucher_name = graphene.String(description="voucher name")
    bio_text = graphene.String(description="BOTD bio text")
    message_text = graphene.String(description = "Message text for botd")
    expiration_time = graphene.String(description="Expiration time for BOTD")
    
    class Meta:
        description = "Brand of the day"

@key(fields="id")
class Store(CountableDjangoObjectType):

    warehouse = graphene.ID(description="ID of warehouse for store")

    default_collection = graphene.Field(Collection, description="default collection details")
    collections = FilterInputConnectionField(
        Collection,
        filter=CollectionFilterInput(description="Filtering options for collections."),
        sort_by=CollectionSortingInput(description="Sort collections."),
        description="List of the shop's collections.",
    )
    thrift_collection = graphene.Field(Collection,description = "thrift collection")
    is_thrift = graphene.Boolean(description = "User opted for thrift or not")
    brand_of_the_day = graphene.Field(BrandOfTheDay,  description="Brand of the day for store.")
    streak_live = graphene.Boolean(description="Tells if a streak is maintained on the store")
    instagram_link = graphene.String(description="Instagram link.")
    stop_source_with_zaamo = graphene.Boolean(description="Stop Source with zaamo boolean Field")
    store_managers = graphene.List(StoreMember,description = "store managers")
    store_barter_inprocess = FilterInputConnectionField("saleor.graphql.brand.types.Brand", 
                                filter=BrandFilterInput(description="filtering options for brands."),
                                sort_by=BrandSortingInput(description="Sorting options for brands."),
                                description="Brands with whom barter requests in process."
                            )
    store_barter_declined = FilterInputConnectionField("saleor.graphql.brand.types.Brand", 
                                filter=BrandFilterInput(description="filtering options for brands."),
                                sort_by=BrandSortingInput(description="Sorting options for brands."),
                                description="Brands with whom barter requests are declined only."
                            )
    store_barter_brand_count = FilterInputConnectionField(
                                "saleor.graphql.brand.types.Brand", 
                                filter=BrandFilterInput(description="filtering options for brands."),
                                sort_by=BrandSortingInput(description="Sorting options for brands."),
                                description="no of requests with individual brands."
                                )
    store_barter_total_brand_count = graphene.Int(description="total barter requests count.")
    no_of_requests = graphene.Int(description="no of requests with a specific brand.")
    count_of_brand_coupon_created = graphene.Int(description="count of brand coupon created of store.")
    count_of_brand_content_delivered = graphene.Int(description="count of brand content delivered of store.")
    last_product_added_timestamp = graphene.DateTime(description="last product added timestamp of store.")

    class Meta:
        description = "meta data of store"
        model = store_models.StoreInfo
        
        only_fields = [
           "store_name",
           "actions",
           "store_url",
           "state",
           "created_at",
           "updated_at",
           "slug",
           "description",
           "store_type",
           "store_category_page_level",
           "metadata",
           "content"
        ]
        interfaces = [relay.Node]

    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)
        # qs = qs.prefetch_related('product_sourcing', 'collection_store').annotate(
        #     brand_coupon_created_count = Count('id', Q(product_sourcing__status = SourcingRequestStatus.BRAND_COUPON_CREATED)),
        #     brand_content_delivered_count = Count('id', Q(product_sourcing__status = SourcingRequestStatus.BRAND_SHARED_DELIVERABLES)),
        #     collection_ids = ArrayAgg('collection_store__collection_id')
        # )
        
        return qs

    def resolve_count_of_brand_coupon_created(root, info, **kwargs):
        # if root.brand_coupon_created_count:
        #     brand_coupon_created_count = root.brand_coupon_created_count
        # else:
        #     brand_coupon_created_count = 0
        brand_coupon_created_count = 0
        return brand_coupon_created_count

    def resolve_count_of_brand_content_delivered(root, info, **kwargs):
        # if root.brand_content_delivered_count:
        #     brand_content_delivered_count = root.brand_content_delivered_count
        # else:
        #     brand_content_delivered_count = 0
        brand_content_delivered_count = 0
        return brand_content_delivered_count

    def resolve_last_product_added_timestamp(root, info, **kwargs):
        
        # if root.collection_ids:
        #     collection_ids = root.collection_ids
        # else:
        #     collection_ids = []

        # last_product_added_timestamp = CollectionProduct.objects.filter(collection_id__in = collection_ids).aggregate(Max('created_at'))

        return root.created_at
    
    def resolve_warehouse(self, info, **data):
        
        return resolve_warehouse(info, **data)

    def resolve_default_collection(root, _info):
        return resolve_default_collection(root.id, _info)

    def resolve_collections(root, info, **kwargs):
        return resolve_collections(root, info, **kwargs)
    
    def resolve_thrift_collection(root,info,**kwargs):

        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        return resolve_thrift_collection(store_id)
    
    def resolve_is_thrift(root,info,**kwargs):

        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        return resolve_thrift_status(store_id)

    def resolve_brand_of_the_day(root, info, **kwargs):
        
        voucher = Voucher.objects.filter(store=root, name='BOTD').active(TimeUtilities.get_current_date_time()).first()
        if voucher:
            brand = voucher.brands.first()
            return BrandOfTheDay(
                brand=brand, voucher_code=voucher.code, 
                voucher_name=voucher.name, 
                bio_text=voucher.metadata.get('BOTD_BIO', ''),
                expiration_time=voucher.end_date
                )

    def resolve_streak_live(root, info, **kwargs):
        return root.is_streak_live()

    def resolve_instagram_link(root, info, **kwargs):
        store_member = root.store_members.all().values('user__influencer__instagram_link')
        store_influencer = store_member.first()
        
        if store_influencer:
            return store_influencer.get('user__influencer__instagram_link', "")
        
        return ""
    
    def resolve_stop_source_with_zaamo(root,info):
        
        return not root.metadata.get('store_barter',False)

    def resolve_store_barter_inprocess(root, info, **_kwargs):
        return InfluencerBrandClubbedResolvers.resolve_inprocess(root, info)

    def resolve_store_barter_declined(root, info, **_kwargs):
        return InfluencerBrandClubbedResolvers.resolve_declined(root, info)

    def resolve_store_barter_total_brand_count(root, info, **_kwargs):
        return InfluencerBrandClubbedResolvers.resolve_total_brand_count(root, info)

    def resolve_store_barter_brand_count(root, info, **_kwargs):
        return InfluencerBrandClubbedResolvers.resolve_brand_count(root, info)

    def resolve_no_of_requests(root, info, **_kwargs):
        return InfluencerBrandClubbedResolvers.resolve_no_of_requests(root, info)
    
    def resolve_store_managers(root,info):

        user_list = []

        authorized_user_instance = root.staff_store_mappings.all().prefetch_related('user')
        
        for data in authorized_user_instance:
            user_instance = data.user
            user_instance.id = graphene.Node.to_global_id("User", user_instance.id)
            user_instance.email = user_instance.email
            user_instance.first_name = user_instance.first_name
            user_instance.last_name = user_instance.last_name

            user_list.append(user_instance)

        return user_list

class StoreNotification(CountableDjangoObjectType):

    store = graphene.Field(Store, description="store in which notification is created")

    class Meta:
        description = "meta data of store notification"
        model = store_models.StoreNotification
        only_fields = [
           "id",
           "text",
           "image_url",
           "created_at",
           "route"
        ]
        interfaces = [relay.Node]

    def resolve_store(root, info):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)

        return store_models.StoreInfo.objects.filter(id=store_id).first()

class StoreTile(CountableDjangoObjectType):

    image = graphene.Field(
        Image, size=graphene.Int(description="Size of the image.")
    )

    class Meta:
        description = "meta data of store tiles"
        model = store_models.StoreTile
        interfaces = [relay.Node]


    def resolve_image(root: store_models.StoreTile, info, size=None, **_kwargs):
        
        if root.image:
            return Image.get_adjusted(
                image=root.image,
                alt="NA",
                size=size,
                rendition_key_set="image",
                info=info,
            )


class StoreCategoryPage(CountableDjangoObjectType):
    class Meta:
        description = "store category page details"
        model = store_models.StoreCategoryPage
        interfaces = [relay.Node]
        exclude = ()

class StoreCategoryField(graphene.ObjectType):
    brands = FilterInputConnectionField("saleor.graphql.brand.types.Brand", 
    sort_by=BrandSortingInput(description="Sort brands."),
    description="brands of store category page", distinct=graphene.Argument(graphene.Boolean, description="get distinct brand"))

    categories = PrefetchingConnectionField("saleor.graphql.product.types.Category", 
    description="categories of store category page", distinct=graphene.Argument(graphene.Boolean, description="get distinct category"))

    class Meta:
        description = "store category page details"
      

    def resolve_brands(root, info, distinct = False,  **kwargs):
        return resolve_brands(root, info, distinct)


    def resolve_categories(root, info, distinct = False,  **kwargs):
        
        
        return resolve_categories(root, info, distinct = distinct)


class StoreRetrievalState(graphene.ObjectType):
    store_id = graphene.Int(description="Store id")
    success = graphene.Boolean(description = "Query was successful or not")
    error = graphene.String(description = "Possible errors")

class StorePayout(CountableDjangoObjectType):
    class Meta:
        description = "store payout details"
        model = store_models.StorePayout
        interfaces = [relay.Node]
        exclude = ()


class StoreManagerActions(CountableDjangoObjectType):
    
    class Meta:
        description = "Store Manager Actions"
        model = store_models.StoreManagerActions
        interfaces = [relay.Node]
        exclude = ()


class StoreManagerComment(CountableDjangoObjectType):
    
    class Meta:
        description = "Store Manager's Comments"
        model = store_models.StoreManagerComment
        interfaces = [relay.Node]
        exclude = ()

@key(fields="id")
class BrandSourceRequest(CountableDjangoObjectType):

    class Meta:
        description = "Brand Sourcing Requests"
        model = store_models.BrandSourcingRequest
        interfaces = [relay.Node]
        exclude = ()

    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)

        if not info.context.user.is_superuser:
            if info.context.user.is_staff:
                stores = info.context.user.staff_store_mappings.all().values_list('store', flat=True)
                brands = info.context.user.staff_brand_mappings.all().values_list('brand', flat=True)
            else:
                stores = info.context.user.store_members.all().values_list('store', flat=True)
                brands = info.context.user.brand_members.all().values_list('brand', flat=True)
        
            qs = qs.filter(Q(store__in=stores) | Q(brand__in=brands))
        
        return qs

@key(fields="id")
class Linktree(CountableDjangoObjectType):

    class Meta:
        description = "Linktree"
        model = store_models.Linktree
        interfaces = [relay.Node]
        exclude = ()

    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        qs = qs.filter(store_id=store_id)

        return qs

    def resolve_image(root, info, **_kwargs):
        if root.image:
            return root.image.url
        return root.image
