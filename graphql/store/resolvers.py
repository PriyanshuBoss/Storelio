import time
from saleor.external_services.google_analytics.constants import GA_COLLECTION_DETAIL_NAME, GA_COLLECTTION_NAME
from saleor.graphql.store.enums import StoreTypeEnums
from saleor.store.states import StoreCategoryPageLevels, StoreTypeEnum
from saleor.store.store_utilities import get_instance_for_store
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.store import models as store_models
from saleor.product import models as product_models
from saleor.brand import models as brand_models
from saleor.utilities.mongo_utilities import MongoConn
from django.db.models import  Q, Case, When, IntegerField,  Value, Count
from django.conf import settings
import graphene
import random
# from django.contrib.postgres.aggregates import ArrayAgg
# from saleor.product import SourcingRequestStatus

def resolve_store(store_id):
    try:
        store_id = int(store_id)
        return store_models.StoreInfo.objects.filter(id=store_id).first()
        # return store_models.StoreInfo.objects.filter(id=store_id).prefetch_related('product_sourcing', 'collection_store').annotate(
        #     brand_coupon_created_count = Count('id', Q(product_sourcing__status = SourcingRequestStatus.BRAND_COUPON_CREATED)),
        #     brand_content_delivered_count = Count('id', Q(product_sourcing__status = SourcingRequestStatus.BRAND_SHARED_DELIVERABLES)),
        #     collection_ids = ArrayAgg('collection_store__collection_id')
        # ).first()

    except Exception as e:
        return None

def resolve_default_collection(store_id, info):
    '''
    returns default collection details
    '''
    collection_list = product_models.CollectionStore.objects.filter(store=store_id).filter(collection__is_default=True).values_list('collection', flat=True)

    if collection_list:
        if 'collectionViews' in StringUtilities.convert_object_to_string(info.field_asts):
            collection_ids = [StringUtilities.convert_number_to_string(id) for id in collection_list]
            collections = MongoConn().sum_collection_views(collection_ids, GA_COLLECTION_DETAIL_NAME)
            collection_views = {NumberUtilities.convert_string_to_number(collection['_id']): collection['collection_views'] for collection in collections}
            
            if 'collection_views' in info.variable_values:
                info.variable_values['collection_views'].update(collection_views)
            else:
                info.variable_values['collection_views'] = collection_views
        
        return product_models.Collection.objects.filter(id__in=collection_list).first()


def resolve_collections(root, info, **kwargs):
    store_id = root.id
    store_instance = root

    if not store_instance:
        return product_models.Collection.objects.none()
    
    collection_list = product_models.CollectionStore.objects.filter(store=store_id).filter(collection__is_default=False).values_list('collection', flat=True)
    
    if collection_list:
        if 'collectionViews' in StringUtilities.convert_object_to_string(info.field_asts):
            collection_ids = [StringUtilities.convert_number_to_string(id) for id in collection_list]
            
            collections = MongoConn().sum_collection_views(collection_ids, GA_COLLECTION_DETAIL_NAME)
            
            collection_views = {NumberUtilities.convert_string_to_number(collection['_id']): collection['collection_views'] for collection in collections}
            
            if 'collection_views' in info.variable_values:
                info.variable_values['collection_views'].update(collection_views)
            else:
                info.variable_values['collection_views'] = collection_views
        
        if 'hasActiveStealDeal' in StringUtilities.convert_object_to_string(info.field_asts):
            
            collection_products  = product_models.CollectionProduct.objects.filter(collection_id__in=collection_list).annotate(product_count=Count('collection_id')).order_by('collection_id').values('collection_id','product_count')
            
            info.variable_values['product_count'] = {}
            for colp in collection_products:
                info.variable_values['product_count'][colp.get('collection_id')] = colp.get('product_count')

        qs = product_models.Collection.objects.filter(id__in=collection_list)

        return qs
    
    return product_models.Collection.objects.none()

def resolve_notifications(store_id):
    
    store_list = []
    store_list.append(store_id)
    default_store = store_models.StoreInfo.objects.filter(store_name = 'Zaamo_Default').first()

    if default_store:
        store_list.append(default_store.id)

    return store_models.StoreNotification.objects.filter(stores__in=store_list)

def resolve_stores(info, **kwargs):

    
    qs = store_models.StoreInfo.objects.filter(store_type=StoreTypeEnum.INFLUENCER)
    
    brand_id = None
    
    if kwargs.get('brand_id'):
        brand_id = graphene.Node.from_global_id(kwargs.get('brand_id'))[1]
        
    campaign_name = kwargs.get('campaign_name')

    exclude_stores = store_models.BrandSourcingRequest.objects.all()
    if brand_id:
        exclude_stores = exclude_stores.filter(brand_id=brand_id)
    if campaign_name:
        exclude_stores = exclude_stores.filter(campaign_name=campaign_name)

    if brand_id or campaign_name:
        exclude_stores = exclude_stores.values_list('store_id', flat=True)
        qs = qs.exclude(id__in=exclude_stores)
    
    seed = kwargs.get('shuffle')
    
    if not seed:
        return qs
    
    ps = list(qs.values_list("id",flat=True))
    random.Random(seed).shuffle(ps)
    cases = [When(id=x, then=Value(i)) for i,x in enumerate(ps)] 
    case = Case(*cases, output_field=IntegerField())
    qs = qs.annotate(randomize=case)
    return qs

def resolve_store_type(user_instance):
    
    if user_instance.is_user_influencer():
        return StoreTypeEnum.INFLUENCER

    elif user_instance.is_user_brand_part():
        return StoreTypeEnums.BRAND


def resolve_tiles(store_id):
    
    store_list = []
    store_list.append(store_id)
    default_store = store_models.StoreInfo.objects.filter(store_name = 'Zaamo_Default').first()

    if default_store:
        store_list.append(default_store.id)

    return store_models.StoreTile.objects.filter(stores__in=store_list)

def resolve_category_page(store_id):

    store_instance = get_instance_for_store(store_id)

    if not store_instance:
        return []
    
    if store_instance.store_category_page_level == StoreCategoryPageLevels.LEVEL_2:
        return store_models.StoreCategoryPage.objects.filter(store=store_id)

    if store_instance.store_category_page_level == StoreCategoryPageLevels.LEVEL_1:
        return store_models.StoreCategoryPage.objects.filter(store=store_id, is_added=True)

    return []

def resolve_store_members(store_id):
    
    store_instance = get_instance_for_store(store_id)

    if not store_instance:
        return []
    
    store_authorized_users = store_instance.staff_store_mappings.all().prefetch_related('user')
    
    user_list = []

    for data in store_authorized_users:
        user_instance = data.user
        user_instance.id = graphene.Node.to_global_id("User", user_instance.id)
        user_instance.email = user_instance.email
        user_instance.first_name = user_instance.first_name
        user_instance.last_name = user_instance.last_name

        user_list.append(user_instance)

    return user_list

def resolve_store_by_slug(slug):

    if not slug:
        return

    store_instance = store_models.StoreInfo.objects.filter(slug=slug).first()

    if not store_instance:
        return 
    
    return store_instance.id

def resolve_store_by_user(user_id):

    if not user_id:
        return
    
    store_member_instance = store_models.StoreMemberState.objects.filter(user_id=user_id).first()

    if not store_member_instance:
        return
    
    return store_member_instance.store_id

def resolve_store_by_host(host):

    if not host or host in settings.DEFAULT_STORE_URL:
        return 
    
    store_instance = store_models.StoreInfo.objects.filter(Q(store_url__contains=host)).first()

    if not store_instance:
        return
    
    return store_instance.id
    
def resolve_thrift_collection(store_id):

    store_id = NumberUtilities.convert_integer_to_hexadecimal(store_id)
    slug = "thrift-"+store_id
    thrift_collection = product_models.Collection.objects.filter(slug=slug).first()

    if thrift_collection:
        return thrift_collection
    else:
        return 

def resolve_thrift_status(store_id):
    store_id = NumberUtilities.convert_integer_to_hexadecimal(store_id)
    slug = "thrift-"+store_id
    thrift_collection = product_models.Collection.objects.filter(slug=slug).first()

    if thrift_collection:
        return thrift_collection.is_thrift
    else:
        return False

def resolve_payout_for_store(store_id):

    store_payout_instance = store_models.StorePayout.objects.filter(store_id = store_id)
    
    return store_payout_instance


def resolve_brands(root, info, distinct):
    from saleor.brand.models import Brand, BrandStatusEnum

    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    store_instance = get_instance_for_store(store_id)
    if store_instance.store_category_page_level == StoreCategoryPageLevels.LEVEL_3:
        qs = Brand.objects.filter(status = BrandStatusEnum.ACTIVE)
    else:
        store_filter = store_models.StoreCategoryPage.objects.select_related("brand").filter(store=store_id , brand__status__in=[BrandStatusEnum.ACTIVE])
        brands = store_filter.values_list("brand", flat=True)
        qs = Brand.objects.filter(id__in=brands)
    
    setattr(qs, "context", info.context)
    return qs

def resolve_categories(root, info, distinct = False,  **kwargs):
    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    store_instance = get_instance_for_store(store_id)
    if store_instance.store_category_page_level == StoreCategoryPageLevels.LEVEL_3:
        return product_models.Category.objects.all().select_related("parent")
    
    store_filter = store_models.StoreCategoryPage.objects.select_related('category').filter(store=store_id)    
    return product_models.Category.objects.filter(id__in=store_filter.values('category')).select_related("parent")
    
class InfluencerBrandClubbedResolvers:

    @staticmethod
    def resolve_inprocess(root, info):
        exclude_status = [
            product_models.SourcingRequestStatus.BRAND_COLLAB_APPROVED,
        ]
        include_status = [
            product_models.SourcingRequestStatus.BRAND_SHARED_DELIVERABLES,
            product_models.SourcingRequestStatus.INFLUENCER_HAS_SHARED_THE_DELIVERABLES,
            product_models.SourcingRequestStatus.REQUEST_RECIEVED,
            product_models.SourcingRequestStatus.REQUEST_CLUBBED,
        ]

        exclude_brands = brand_models.Brand.objects.filter(product_sourcing__store_id=root.id, product_sourcing__status__in=exclude_status).distinct()

        qs = brand_models.Brand.objects.all()
        qs = qs.exclude(id__in=exclude_brands)
        qs = qs.filter(product_sourcing__store_id=root.id, product_sourcing__status__in=include_status).distinct()
        qs = qs.annotate(no_of_requests=Count('product_sourcing', filter=Q(product_sourcing__store_id=root.id)))

        return qs

    @staticmethod
    def resolve_declined(root, info):
        exclude_status = [
            product_models.SourcingRequestStatus.BRAND_COLLAB_APPROVED,
        ]
        include_status = [
            product_models.SourcingRequestStatus.BRAND_NOT_INTERESTED,
            product_models.SourcingRequestStatus.ZAAMO_NOT_INTERESTED,
        ]

        exclude_brands = brand_models.Brand.objects.filter(product_sourcing__store_id=root.id, product_sourcing__status__in=exclude_status).distinct()

        qs = brand_models.Brand.objects.all()
        qs = qs.exclude(id__in=exclude_brands)
        qs = qs.filter(product_sourcing__store_id=root.id, product_sourcing__status__in=include_status).distinct()
        qs = qs.annotate(no_of_requests=Count('product_sourcing', filter=Q(product_sourcing__store_id=root.id)))

        return qs

    @staticmethod
    def resolve_total_brand_count(root, info):
        return brand_models.Brand.objects.filter(product_sourcing__store_id=root.id).values_list('product_sourcing').count()

    @staticmethod
    def resolve_brand_count(root, info):
        coupon_created = [product_models.SourcingRequestStatus.BRAND_COUPON_CREATED, product_models.SourcingRequestStatus.ZAAMO_COUPON_CREATED]
        
        qs = brand_models.Brand.objects.all()
        qs = qs.filter(product_sourcing__store_id=root.id)
        qs = qs.annotate(no_of_requests=Count('product_sourcing', filter=Q(product_sourcing__store_id=root.id)))
        qs = qs.annotate(coupon_created=Count('product_sourcing', filter=Q(product_sourcing__store_id=root.id, product_sourcing__status__in=coupon_created)))
        
        return qs

    @staticmethod
    def resolve_no_of_requests(root, info):
        count = 0
        if hasattr(root, 'no_of_requests'):
            count = root.no_of_requests
        
        return count
