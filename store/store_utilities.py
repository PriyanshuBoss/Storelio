import uuid
from django.db.models import Count

from saleor.store.constants import UNCATEGORIZED_LIST
from saleor.store.models import StoreInfo, StoreManagerActions,BrandSourcingRequest
from saleor.product import models as product_models
from saleor.store.states import StoreMemberStatesEnum,StoreTypeEnum
from saleor.store.models import StoreInfo, StoreMemberState, StoreCategoryPage
from django.utils.text import slugify
from django.conf import settings
from ..celeryconf import app
from ..core.utils import generate_unique_slug
from saleor.notifications.utils import send_notifications


def create_default_collection_store(store_instance, user_instance,slug=False):

    slug = generate_unique_slug(product_models.Collection(),store_instance.store_name)

    collection_instance = product_models.Collection.create_instance({
        'name': store_instance.store_name,
        'slug': slug,
        'is_default': True,
        'is_published': True
    })

    product_models.CollectionStore.create_instance({
        'store_instance': store_instance,
        'user_instance': user_instance,
        'collection_instance': collection_instance

    })

def setup_store_for_influencer(user_instance, influencer_instance):
   
  store_context = {
      'store_name': influencer_instance.instagram_username,
      'store_url': settings.DEFAULT_STORE_URL,
      'store_type': StoreTypeEnum.INFLUENCER
  }
  
  if influencer_instance.instagram_username:
      slug =  generate_unique_slug(StoreInfo(), influencer_instance.instagram_username)
      store_context['slug'] = slug if slug else uuid.uuid4()
      store_context['description'] = {'title': influencer_instance.instagram_username}
      store_context['store_url'] = store_context['store_url']+ "/"+slug
  
  store_instance = StoreInfo.create_instance(store_context)
  StoreMemberState.create_instance({'user_instance': user_instance, 
  'store_instance': store_instance, 'state': StoreMemberStatesEnum.OWNER})
  manager_action_obj = StoreManagerActions(store=store_instance)
  manager_action_obj.save()

  return store_instance

  
def get_instance_for_store(store_id):
    
    return StoreInfo.objects.filter(id=store_id).first()


def set_relation_between_store_collection(store_id, collection_instance, user_instance):

    store_instance = get_instance_for_store(store_id)

    if not store_instance:
        return

    instance = product_models.CollectionStore.create_instance({
        'store_instance': store_instance,
        'user_instance': user_instance,
        'collection_instance': collection_instance

    })

    return instance


def is_user_have_store_access(store_id, user_id, perm_list):
    store_member_filter = StoreMemberState.objects.filter(user=user_id, store=store_id)
    if store_member_filter.exists():
        return store_member_filter.first().has_perms(perm_list)
    return False


def get_store_instances_by_ids(store_ids):

    return StoreInfo.objects.in_bulk(store_ids)


def setup_store_for_brand(user_instance, brand_instance):
   
  store_context = {
      'store_name': brand_instance.brand_name,
      'store_url': settings.DEFAULT_STORE_URL,
      'store_type': StoreTypeEnum.BRAND
  }

  if brand_instance.brand_name:
      slug = slugify(brand_instance.brand_name, allow_unicode=True)
      store_context['slug'] = slug if slug else uuid.uuid4()
      store_context['description'] = {'title': brand_instance.brand_name}
      store_context['store_url'] = store_context['store_url']+ "/"+slug
  
  store_instance = StoreInfo.create_instance(store_context)
  StoreMemberState.create_instance({'user_instance': user_instance, 
  'store_instance': store_instance, 'state': StoreMemberStatesEnum.OWNER})
  manager_action_obj = StoreManagerActions(store=store_instance)
  manager_action_obj.save()
  return store_instance

def setup_store_member_state_for_user(user_instance, store_instance):
    
    if not StoreMemberState.objects.filter(user=user_instance, store=store_instance):
        StoreMemberState.create_instance({'user_instance': user_instance, 
                                          'store_instance': store_instance, 
                                          'state': StoreMemberStatesEnum.OWNER})


def get_all_products(stores, qs=None):

    all_collection_ids = set()
    for store in stores:
        collection_ids = store.collection_store.all().values_list("collection",
        flat=True).distinct()
        all_collection_ids.update(list(collection_ids))
    
    if qs!=None:
        products = qs.filter(collections__id__in=all_collection_ids).distinct()
    else:

        products = product_models.Product.objects.filter(collections__id__in=all_collection_ids).distinct()

    return products

def get_all_collections(stores, qs = None):
    
    if isinstance(stores, (list, tuple , set)):
        stores = StoreInfo.objects.filter(id__in=[store.id for store in stores])

    collection_ids = stores.values_list("collection_store__collection", flat=True)
    if qs:
        qs=qs.filter(id__in=collection_ids)
    else:
        qs=product_models.Collection.objects.filter(id__in=collection_ids)
    return qs.annotate(total_products_count=Count("collectionproduct")).distinct()


def find_brandXcategory(brand_list, category_list):
 
    brandXcategory = []
    
    for brand_id in brand_list:
        for category_id in category_list:
            brandXcategory.append((brand_id, category_id))

    return brandXcategory


def save_brandXcategory(store_instance, brand_map, category_map, brandXcategory):
    
    for data in brandXcategory:
        brand_id = data[0]
        category_id = data[1]
        
        if brand_map.get(brand_id) and category_map.get(category_id):
             StoreCategoryPage.create_instance(
                {
                    'store_instance': store_instance,
                    'brand_instance': brand_map.get(brand_id),
                    'category_instance': category_map.get(category_id),
                    'is_added': False
                }
            )

def save_relationships_for_store_category_page(store_instance):
    
    brand_map = {}
    category_map= {}
    brand_list = []
    category_list = []

    page_filter = StoreCategoryPage.objects.filter(store=store_instance).prefetch_related('brand', 
    'category')

    for data in page_filter:
        
        if not brand_map.get(data.brand_id):
            brand_map[data.brand_id] = data.brand
            brand_list.append(data.brand_id)

        if not category_map.get(data.category_id):
            category_map[data.category_id] = data.category
            category_list.append(data.category_id)

    brandXcategory = find_brandXcategory(brand_list, category_list)
    save_brandXcategory(store_instance, brand_map, category_map, brandXcategory)

    
def save_brands_for_store_category_page(products, store_instance):

    for data in products:
        
        if data.category and data.category.name in UNCATEGORIZED_LIST:
            continue
        
        StoreCategoryPage.create_instance(
            {
                'store_instance': store_instance,
                'category_instance': data.category,
                'brand_instance': data.brand
            }
        )
    #save_relationships_for_store_category_page(store_instance)

def remove_brands_for_store_category_page(products, store_instance):
    
    for data in products:

        if data.category and data.category.name in UNCATEGORIZED_LIST:
            continue

        page_filter = StoreCategoryPage.objects.filter(
            store=store_instance, 
            category=data.category, 
            brand=data.brand)

        
        
        if page_filter:
            instance = page_filter[0]
            instance.add_count = instance.add_count - 1
            instance.save()

            if instance.add_count <= 0:
                instance.delete()

@app.task()
def save_brands_for_store_category_page_in_bulk(product_ids, store_id):
    products = product_models.Product.objects.filter(id__in=product_ids)
    store_instance = StoreInfo.objects.filter(id=store_id).first()
    
    if not store_instance:
        return

    save_brands_for_store_category_page(products, store_instance)


def get_default_zaamo_store():

    default_store = StoreInfo.objects.filter(store_name = 'Zaamo_Default').first()

    return default_store

def notification_brand_interested(brand_source_request_ids):
    brand_sourcing_requests = BrandSourcingRequest.objects.filter(id__in=brand_source_request_ids)
    for request in brand_sourcing_requests:
        brand_name = request.brand.brand_name
        if not brand_name:
            brand_name=""
        context_variables = dict()
        try:
            user = request.store.get_store_authorized_users()[0]
            user_id = user.id
        except:
            user = None

        if not user:
            continue
        context_variables[user_id] = {
            "brand_name":brand_name
        }
        return send_notifications([user],context_variables=context_variables,event_code="EV_brand_sourcing_interested")