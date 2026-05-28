from collections import defaultdict
import time
from saleor.external_services.acha_india_service.acha_india_impl import AchaIndiaImpl
from saleor.external_services.mydukaan_service.mydukaan_impl import MyDukaanImpl
from saleor.external_services.style_stree_service.style_stree_impl import StyleStreeImpl
from saleor.external_services.integrations.custom_brand import StyleStreeBrandIntegeration
from saleor.external_services.the_souled_store_service.the_souled_store_impl import TheSouledStoreImpl
from saleor.product.templatetags.product_images import get_thumbnail
from django.db.models.aggregates import Sum
from saleor.brand.states import BrandCollectionTypeEnum
from django.db.models import F , DecimalField, ExpressionWrapper, FloatField
from django.db.models import Count, DateField
from django.db.models.functions import Cast, Coalesce
from decimal import Decimal
import logging
import graphene
from django.db.models import Subquery,Q, Case, When
from saleor.graphql.brand.types import Brand
from saleor.graphql.order.enums import TimePeriod
from saleor.graphql.store.types import Store
from saleor.settings import PDP_PER_PAGE
from saleor.store.states import StoreStateEnum, StoreTypeEnum
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.utilities.dictionary_utilities import DictionaryUtilities
import saleor.store.models as store_models
from saleor.warehouse.models import Stock
import saleor.wishlist.models as wishlist_models
import saleor.account.models as account_models
from saleor.discount import models as discount_models
import saleor.order.models as order_models
from saleor.store import models as store_models
from saleor.brand import models as brand_models
from saleor.product import models as product_models
import saleor.checkout.models as checkout_models
from saleor.external_services.google_analytics.ga_impl import GoogleAnalyticsImpl
from saleor.external_services.google_analytics.constants import GA_COLLECTTION_NAME, GA_STORE_DETAIL_NAME
from saleor.external_services.google_analytics.ga_helper import set_time_date_ga, fetch_dashboard_store_metrics, fetch_store_landing_zaamo
import datetime
from saleor.order.utils import get_voucher_discount_for_orderline
from saleor.external_services.wix.wix_impl import WixImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.brand.states import BrandSourceEnum
from saleor.graphql.order.enums import TimePeriod
from saleor.order import FulfillmentStatus
from saleor.graphql.product.filters import product_search
from django.db.models import Q
from saleor.discount import VoucherOwner
from saleor.graphql.utils.filters import filter_range_field
from saleor.graphql.brand.tasks import explore_content_sync
logger = logging.getLogger(__name__)

def fetch_total_selling_price(start_date, end_date, datewise=False):
    queryset = order_models.OrderLine.objects.filter(order__created__gte=start_date, order__created__lt=end_date)
    if not datewise:
        queryset = queryset.aggregate(total=Coalesce(Sum(F('quantity')*F('unit_price_gross_amount'), output_field = DecimalField()), 0))
        return queryset.get('total')
    
    queryset = queryset\
        .annotate(date=Cast('order__created', DateField())).values('date').order_by('date')\
        .annotate(total=Coalesce(Sum(F('quantity')*F('unit_price_gross_amount'), output_field = DecimalField()), 0))\
        .values_list('date', 'total')
    
    return queryset

def fetch_total_net_gmv(start_date, end_date, datewise=False):
    queryset = order_models.Order.objects.filter(created__gte=start_date, created__lt=end_date, platform_code=PlatformTypeEnum.INFLUENCER_STORE)
    
    if not datewise:
        queryset = queryset.aggregate(total=Coalesce(Sum(F('total_net_amount')+F('discount_amount'), output_field = DecimalField()), 0))
        return queryset.get('total')
    
    queryset = queryset\
        .annotate(date=Cast('created', DateField())).values('date').order_by('date')\
        .annotate(total=Coalesce(Sum(F('total_net_amount')+F('discount_amount'), output_field = DecimalField()), 0))\
        .values_list('date', 'total')
    
    return queryset

def fetch_total_brand_discount(start_date, end_date, datewise=False):
    queryset = order_models.OrderLine.objects.filter(order__created__gte=start_date, order__created__lt=end_date)
    if not datewise:
        queryset = queryset.aggregate(total=Coalesce(Sum(F('quantity') * (F('variant__cost_price_amount') - F('unit_price_gross_amount')), output_field = DecimalField()), 0))
        return queryset.get('total')
    
    queryset = queryset\
        .annotate(date=Cast('order__created', DateField())).values('date').order_by('date')\
        .annotate(total=Coalesce(Sum(F('quantity') * (F('variant__cost_price_amount') - F('unit_price_gross_amount')), output_field = DecimalField()), 0))\
        .values_list('date', 'total')
    
    return queryset

def fetch_total_coupon_adjustments(start_date, end_date, datewise=False):
    queryset = order_models.Order.objects.filter(created__gte=start_date, created__lt=end_date)
    if not datewise:
        queryset = queryset.aggregate(total=Coalesce(Sum('discount_amount', output_field = DecimalField()), 0))
        return queryset.get('total')
    
    queryset = queryset\
        .annotate(date=Cast('created', DateField())).values('date').order_by('date')\
        .annotate(total=Coalesce(Sum('discount_amount', output_field = DecimalField()), 0))\
        .values_list('date', 'total')
    
    return queryset

def date_value_queryset_to_dict(queryset):
    res = dict()
    for date, value in queryset:
        res[date.strftime('%Y-%m-%d')] = value

    return res

def fetch_metric_for_dashboard(start_date, end_date):
    
    release_date = datetime.datetime(2022, 1, 4)

    if start_date < release_date:
        start_date = release_date
    metric = {}
    product_count = product_models.CollectionProduct.objects.filter(created_at__gte=release_date, created_at__lt=start_date).count()
    store_count = store_models.StoreInfo.objects.filter(store_type=StoreTypeEnum.INFLUENCER).filter(state=StoreStateEnum.ACTIVE).filter(updated_at__gte=release_date, updated_at__lt=start_date).count()
    wishlist_count = wishlist_models.Wishlist.objects.filter(updated_at__gte=release_date, updated_at__lt=start_date).count()
    signups_count = account_models.User.objects.filter(date_joined__gte=release_date, date_joined__lt=start_date).count()
    purchase_count = order_models.Order.objects.filter(created__gte=release_date, created__lt=start_date).aggregate(total=Coalesce(Sum('total_gross_amount'), 0)).get('total')
    abandoned_cart_count = checkout_models.Checkout.objects.filter(last_change__gte=release_date, last_change__lt=start_date).count()
    
    overall_store_metrics = fetch_dashboard_store_metrics(release_date, start_date).get('null', {})
    total_site_visits = overall_store_metrics.get("site_visits_total", 0)
    total_store_visits = overall_store_metrics.get("store_visits_total", 0)
    total_product_visits = overall_store_metrics.get("product_visits_total", 0)
    total_collection_visits = overall_store_metrics.get("collection_visits_total", 0)
    total_landing_page_visits = fetch_landing_page_metrics(release_date, start_date).get('store_landing_zaamo', 0)  
    total_selling_price = fetch_total_selling_price(release_date, start_date)
    total_brand_discount = fetch_total_brand_discount(release_date, start_date)
    total_coupon_adjustments = fetch_total_coupon_adjustments(release_date, start_date)
    total_net_gmv = fetch_total_net_gmv(release_date, start_date)

    
    landing_page_metrics = fetch_landing_page_metrics(start_date, end_date, datewise=True)
    store_metrics = fetch_dashboard_store_metrics(start_date, end_date, datewise=True)
    
    net_gmvs = fetch_total_net_gmv(start_date, end_date, datewise=True)
    selling_prices = fetch_total_selling_price(start_date, end_date, datewise=True)
    brand_discounts = fetch_total_brand_discount(start_date, end_date, datewise=True)
    coupon_adjustments = fetch_total_coupon_adjustments(start_date, end_date, datewise=True)

    net_gmvs = date_value_queryset_to_dict(net_gmvs)
    selling_prices = date_value_queryset_to_dict(selling_prices)
    brand_discounts = date_value_queryset_to_dict(brand_discounts)
    coupon_adjustments = date_value_queryset_to_dict(coupon_adjustments)
    
    product_counts = product_models.CollectionProduct.objects.filter(created_at__gte=start_date, created_at__lt=end_date)\
        .annotate(date=Cast('created_at', DateField())).values('date').order_by('date').annotate(cnt=Count('id')).values_list('date', 'cnt')
    store_counts = store_models.StoreInfo.objects.filter(updated_at__gte=start_date, updated_at__lt=end_date)\
        .annotate(date=Cast('updated_at', DateField())).values('date').order_by('date').annotate(cnt=Count('id')).values_list('date', 'cnt')
    wishlist_counts = wishlist_models.Wishlist.objects.filter(updated_at__gte=start_date, updated_at__lt=end_date)\
        .annotate(date=Cast('updated_at', DateField())).values('date').order_by('date').annotate(cnt=Count('id')).values_list('date', 'cnt')
    signups_counts = account_models.User.objects.filter(date_joined__gte=start_date, date_joined__lt=end_date)\
        .annotate(date=Cast('date_joined', DateField())).values('date').order_by('date').annotate(cnt=Count('id')).values_list('date', 'cnt')
    latest_purchase_counts = order_models.Order.objects.filter(created__gte=start_date, created__lt=end_date)\
        .annotate(date=Cast('created', DateField())).values('date').order_by('date')\
        .annotate(cnt=Coalesce(Sum('total_gross_amount', output_field=DecimalField()), 0)).values_list('date', 'cnt')
    abandoned_cart_counts = checkout_models.Checkout.objects.filter(last_change__gte=start_date, last_change__lt=end_date)\
        .annotate(date=Cast('last_change', DateField())).values('date').order_by('date').annotate(cnt=Count('token')).values_list('date', 'cnt')
    per_day_checkout_counts = checkout_models.Checkout.objects.filter(created__gte=start_date, created__lt=end_date)\
        .annotate(date=Cast('created', DateField())).values('date').order_by('date').annotate(cnt=Count('token')).values_list('date', 'cnt')
    per_day_order_counts = order_models.Order.objects.filter(created__gte=start_date, created__lt=end_date)\
        .annotate(date=Cast('created', DateField())).values('date').order_by('date').annotate(cnt=Count('id')).values_list('date', 'cnt')

    product_counts = date_value_queryset_to_dict(product_counts)
    store_counts = date_value_queryset_to_dict(store_counts)
    wishlist_counts = date_value_queryset_to_dict(wishlist_counts)
    signups_counts = date_value_queryset_to_dict(signups_counts)
    latest_purchase_counts = date_value_queryset_to_dict(latest_purchase_counts)
    abandoned_cart_counts = date_value_queryset_to_dict(abandoned_cart_counts)
    per_day_checkout_counts = date_value_queryset_to_dict(per_day_checkout_counts)
    per_day_order_counts = date_value_queryset_to_dict(per_day_order_counts)
    
    while(start_date < end_date):
        date = TimeUtilities.convert_datetime_to_string(start_date, '%Y-%m-%d')

        product_count               += product_counts.get(date, 0)
        store_count                 += store_counts.get(date, 0)
        wishlist_count              += wishlist_counts.get(date, 0)
        signups_count               += signups_counts.get(date, 0)
        purchase_count              += latest_purchase_counts.get(date, 0)
        abandoned_cart_count        += abandoned_cart_counts.get(date, 0)
        total_site_visits           += store_metrics.get(date, {}).get("site_visits_total", 0)
        total_store_visits          += store_metrics.get(date, {}).get("store_visits_total", 0)
        total_product_visits        += store_metrics.get(date, {}).get("product_visits_total", 0)
        total_collection_visits     += store_metrics.get(date, {}).get("collection_visits_total", 0)
        total_landing_page_visits   += landing_page_metrics.get(date, {}).get('store_landing_zaamo', 0)    
        total_selling_price         += selling_prices.get(date, 0)
        total_brand_discount        += brand_discounts.get(date, 0)
        total_coupon_adjustments    += coupon_adjustments.get(date, 0)
        total_net_gmv               += net_gmvs.get(date, 0)

        
        key_date = TimeUtilities.parse_date(start_date, "%d %b")
        metric[key_date] = {
            'products_added_in_collections': product_count,
            'influencer_store_count': store_count,
            'wishlist_count': wishlist_count,
            'signups_count': signups_count,
            'purchase_count': purchase_count,
            'abandoned_cart_count': abandoned_cart_count,
            'total_site_visit':total_site_visits,
            'total_store_visit':total_store_visits,
            'total_product_visit':total_product_visits,
            'total_collection_visit':total_collection_visits,
            'total_landing_page_visit':total_landing_page_visits,
            'total_selling_price': total_selling_price,
            'total_brand_discount': total_brand_discount,
            'total_coupon_adjustments': total_coupon_adjustments ,
            'total_net_gmv' : total_net_gmv,
            'per_day_checkout_count': per_day_checkout_counts.get(date, 0),
            'per_day_order_count': per_day_order_counts.get(date, 0)
        }
        start_date = TimeUtilities.add_time_in_timestamp(start_date, days=1)

    return metric

    

def resolve_overall_dashboard(page):
    from saleor.graphql.analytics.types import Dashboard

    start_date, end_date = TimeUtilities.get_datetime_between_duration(day=page)
    metric = fetch_metric_for_dashboard(start_date, end_date)
    dashboard_list = []    

    for key, values in metric.items():
        dashboard_list.append(Dashboard(
            date=key, 
            wishlist_count=values.get('wishlist_count', 0), 
            active_influencer_count = values.get('influencer_store_count', 0),
            signups_count = values.get('signups_count', 0),
            purchase_count = values.get('purchase_count', 0.0),
            abandoned_cart_count = values.get('abandoned_cart_count', 0),
            total_site_visits = values.get('total_site_visit',0),
            total_store_visits = values.get('total_store_visit',0),
            total_product_visits = values.get('total_product_visit',0),
            total_collection_visits = values.get('total_collection_visit',0),
            total_landing_page_visits = values.get('total_landing_page_visit',0),
            total_selling_price = values.get('total_selling_price',0),
            total_brand_discount = values.get('total_brand_discount',0),
            total_coupon_adjustments = values.get('total_coupon_adjustments',0),
            products_added_in_collections = values.get('products_added_in_collections',0),
            total_net_gmv = values.get('total_net_gmv',0),
            per_day_checkout_count = values.get('per_day_checkout_count',0),
            per_day_order_count = values.get('per_day_order_count',0)
        )
        )
    
    return  dashboard_list


def resolve_order_line(root, _info, brand_id,status,search_by_product):
    user = _info.context.user
    
    if status:
        fulfilment_status_filter = {'fulfillment_line__fulfillment__status__in' : status , 'product_name__icontains' : search_by_product}
    else:
        fulfilment_status_filter = {'product_name__icontains' : search_by_product}

    if user.is_superuser and not brand_id:
        return root.lines.filter(**fulfilment_status_filter)

    elif user.is_staff and not brand_id:
        brands = [data.id for data in _info.context.authorised_brands]
        return root.lines.brand_order_lines(brands).order_by("pk").filter(**fulfilment_status_filter)

    elif brand_id:

        if isinstance(brand_id, list):
            filter = set(brand_id).issubset(set([data.id for data in _info.context.authorised_brands]))
        else:
            filter = brand_id in [data.id for data in _info.context.authorised_brands]
        
        if filter:
            return root.lines.brand_order_lines(brand_id).order_by("pk").filter(**fulfilment_status_filter)
        else:
            return root.lines.none()
    else:
        return root.lines.none()

def resolve_fulfillments(root, _info, brand_id):
    user = _info.context.user
   
    if user.is_superuser and not brand_id:
        return root.fulfillments.all()
        
    elif user.is_staff and not brand_id:
        brands = [data.id for data in _info.context.authorised_brands]
        qs = root.fulfillments.all()
        fulfillments = [fulfillment for fulfillment in qs if fulfillment.brand_fulfillment_lines(brands).exists()]

        return fulfillments

    elif brand_id:
        if isinstance(brand_id, list):
            filter = set(brand_id).issubset(set([data.id for data in _info.context.authorised_brands]))
        else:
            filter = brand_id in [data.id for data in _info.context.authorised_brands]
        if filter:
            qs = root.fulfillments.all()
            fulfillments = [fulfillment for fulfillment in qs if fulfillment.brand_fulfillment_lines(brand_id).exists()]

            return fulfillments            
        else:
            return root.fulfillments.none()
    else:
        return root.fulfillments.none()


def variant_product_order_queryset():
    return order_models.OrderLine.objects.select_related("order", 
        "variant", "variant__product").values("order__created", "order__status", "variant",
         "variant__product", "quantity", "quantity_fulfilled", "unit_price_net_amount", 
         "unit_price_gross_amount", "tax_rate")

def product_wishlist_queryset():

    return wishlist_models.WishlistItem.objects.select_related("wishlist", "product", "wishlist__store").values('wishlist'
    , "product", "wishlist__store__id")

def check_staff_mapping_existence(userId):
    return store_models.StaffStoreMapping.objects.filter(user_id=userId).exists()
    
def check_store_member_mapping_existence(userId):
    return store_models.StoreMemberState.objects.filter(user_id=userId).exists()

def order_store_queryset():
    release_date = datetime.datetime(2022, 1, 4)    
    return order_models.OrderStore.objects.filter(created_at__gte=release_date).select_related("order", "store", "order__user").values("order", "order__status", 
    "order__total_net_amount", "order__total_gross_amount", "order__discount_amount", 
    "order__discount_name", "order__created", "store")

def get_google_analytics_from_mongo(date_range):
    mongo_client = MongoConn()
    docs = mongo_client.fetch_data({
            "date": { 
                "$gte":date_range.get("start_date"),
                "$lte": date_range.get("end_date")
            }
        }, collection_name=GA_COLLECTTION_NAME)
    res = {}
    for doc in docs:
        res = DictionaryUtilities.add_common_keys(res, doc, skip_keys=['_id', 'date'])
        res = DictionaryUtilities.merge_nested_dictionary(res, doc, skip_keys=['_id', 'date'])
    
    return res
    
def get_google_store_analytics_from_mongo(date_range):
    mongo_client = MongoConn()
    docs = mongo_client.sum_store_metrics(date_range=date_range, collection_name=GA_STORE_DETAIL_NAME)
    res = {}
    for doc in docs:
        res[doc.pop('_id')] = doc
    return res

def store_google_analytics_queryset(value):
    date_range = GoogleAnalyticsImpl._set_date_range_values(value = value)
    if value == TimePeriod.LASTHOUR:
        return GoogleAnalyticsImpl.get_metrics_for_store(date_range)
    return  get_google_store_analytics_from_mongo(date_range)

def product_google_analytics_queryset(value=''):
    # FIXME for now designs don't have filter for date in product and collection analytics page
    # included if in future it is required
    date_range = GoogleAnalyticsImpl._set_date_range_values(value = value)
    return  get_google_analytics_from_mongo(date_range)


def fetch_landing_page_queryset(start_date,end_date):
    date_range = set_time_date_ga(start_date, end_date)
    return get_google_analytics_from_mongo(date_range)

def fetch_landing_page_metrics(start_date, end_date, datewise=False):
    landing_page_docs = fetch_store_landing_zaamo(start_date, end_date, datewise=datewise)
    if not datewise:
        return landing_page_docs.get('null', {})
    return landing_page_docs

def brand_commission_queryset():
    return brand_models.Brand.objects.all().prefetch_related("commission", 
    "commission__commission_percentage").values(
        "commission__commission_percentage", "commission", "id")

def orderline_store_product_brand_queryset():
    release_date = datetime.datetime(2022, 1, 4)
    
    return order_models.OrderLine.objects.select_related(
        "variant__product__brand").prefetch_related("order__order_store").filter(order__created__gte=release_date).values(
        'variant__product__brand',"variant__product__brand__brand_name", "order__order_store__store", "order_id", "quantity", "unit_price_net_amount", "shipping_cost_amount",
        "unit_price_gross_amount", "variant_id", "id", "commission_percentage", "order__created", "metadata")

def collection_google_analytics_queryset(value="date_range"):
    date_range = GoogleAnalyticsImpl._set_date_range_values(value = {})
    return get_google_analytics_from_mongo(date_range)     

def order_wishlist_queryset():
    
    return wishlist_models.Wishlist.objects.select_related("store").values("store", "created_at", "updated_at")

def checkout_store_queryset():
    release_date = datetime.datetime(2022, 1, 4)
    return checkout_models.CheckoutStore.objects.filter(created_at__gte=release_date).select_related("store").values("store", "created_at")

def voucher_store_queryset():

    return discount_models.Voucher.objects.select_related("store").values("used", "usage_limit", "created_at",
    "start_date" , "store", "end_date", "discount_value", "min_spent_amount", "min_checkout_items_quantity",
    "max_discount_value")

def resolve_earnings_analytics(store_ids,_info):
    ids = []
    userId = _info.context.user.id

    if userId:
        user_staff_mapping = check_staff_mapping_existence(userId)
        user_member_mapping = check_store_member_mapping_existence(userId)

        if user_member_mapping or user_staff_mapping:
            
            for id in store_ids:
                store_id = graphene.Node.get_node_from_global_id(_info, id, Store)

                if store_id:
                    ids.append(store_id.id)
                
            return store_models.StoreInfo.objects.filter(id__in=ids)
    
    return store_models.StoreInfo.objects.none()

def resolve_earning_analytics_single_store(store_id,_info):
    
    userId = _info.context.user.id

    if userId:
        # user_staff_mapping = check_staff_mapping_existence(userId)
        # user_member_mapping = check_store_member_mapping_existence(userId)
            
        store = graphene.Node.get_node_from_global_id(_info, store_id, Store)
        
        if store:
            return store_models.StoreInfo.objects.filter(id=store.id).first()
    
    return None

def resolve_order_line_store(root, info):
    release_date = datetime.datetime(2022, 1, 4)

    return order_models.OrderLine.objects.filter(Q(order_id__in=Subquery(order_models.OrderStore.objects.filter(store_id=root.id).values('order_id'))) & Q(variant_id__isnull=False) & Q(created_at__gte=release_date)).select_related("order", 
        "variant", "variant__product").order_by("-pk")

def resolve_order_line_from_store_excluding_influencer(root,info):
    
    store_order_lines =  resolve_order_line_store(root, info)
    
    store_order_lines = store_order_lines.filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).filter(metadata__fake__isnull=True)

    return store_order_lines

def resolve_my_order_lines(root,info):
    
    store_order_lines =  resolve_order_line_store(root, info)

    if info.context.user.id:
        store_order_lines = store_order_lines.filter(order__user=info.context.user)

    return store_order_lines

def resolve_total_earning(root, info):
    
    order_lines = resolve_order_line_from_store_excluding_influencer(root, info)
    order_lines = order_lines.exclude(fulfillment_line__fulfillment__status__in = [
            FulfillmentStatus.RETURN_COMPLETED, 
            FulfillmentStatus.RETURN_INITIATED,
            FulfillmentStatus.CANCELLATION_PROCESSED,
            FulfillmentStatus.CANCELLATION_INITIATED
        ])
    
    total_earning=Decimal(0.00)

    for line in order_lines:

        total_earning += Decimal(line.metadata.get("influencer_commission", 0))

    return Decimal(total_earning)

def resolve_orders_count(root, info):

    return resolve_order_line_from_store_excluding_influencer(root, info).count()

def resolve_likes_count(root):

    likes = wishlist_models.WishlistItem.objects.filter(wishlist_id__in=Subquery(wishlist_models.Wishlist.objects.filter(store_id=root.id).values('id'))).count()
    return likes

def resolve_store_visits(root):
    
    return root.metadata.get('total_visitors',  0)

def aggregate_product_analytics(pid_analytics: dict,store_ids: list):
    val = 0
    for stores in store_ids:
        val_inc = pid_analytics.get(str(stores))
        if val_inc:
            val = val+int(val_inc)
    return val

def resolve_brand_for_pdp(brand_id,_info):
    
    userId = _info.context.user.id
    brand_obj = None

    if userId:
        
        brand = graphene.Node.from_global_id(brand_id)[1]
        
        if brand:
            brand_obj =  brand_models.Brand.objects.filter(id=brand).first()
        
            setattr(_info.context, 'collection_category_data', get_category_collections_data(brand_obj, _info))
    
    return brand_obj

def get_wix_category_collection_data(root, _info):
    wix_impl = WixImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name

    response = wix_impl.fetch_categories_tags(brand_name)

    return response

def get_woo_commerce_category_collection_data(root, _info):
    woo_impl = WooCommerceImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name

    response = woo_impl.fetch_categories_tags(brand_name)

    return response

def get_acha_category_collection_data(root, _info):
    acha_impl = AchaIndiaImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name

    response = acha_impl.fetch_categories_tags(brand_name)

    return response

def get_shopify_category_collection_data(root, _info):
    shopify_impl = ShopifyImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name

    response = shopify_impl.fetch_categories_tags_collections(brand_name)

    return response

def get_category_collections_data(root,_info):
    source = root.brand_source
    data = defaultdict(list)

    zaamo_categories_queryset = product_models.Product.objects.filter(brand=root).values_list('category__name',flat=True)
    zaamo_categories = []

    for category_name in zaamo_categories_queryset:

        if not category_name:
            continue
        
        if not category_name in zaamo_categories:
            zaamo_categories.append(category_name)

    brand_collection = brand_models.BrandCollection.objects.filter(brand_id=root.id)

    if brand_collection:

        for collection in brand_collection:
            if collection.type==BrandCollectionTypeEnum.COLLECTION:
                data['collection'].append(collection.name)
            if collection.type==BrandCollectionTypeEnum.CATEGORY:
                data['category'].append(collection.name)

    if not data['category'] and not data['collection']:

        if source==BrandSourceEnum.WIX:
            data = get_wix_category_collection_data(root, _info)

        elif source==BrandSourceEnum.WOOCOMMERCE:
            data = get_woo_commerce_category_collection_data(root, _info)

        elif source==BrandSourceEnum.SHOPIFY:
            data = get_shopify_category_collection_data(root, _info)

        elif source==BrandSourceEnum.ACHAINDIA:
            data = get_acha_category_collection_data(root, _info)
        
    zaamo_categories.extend(data['category'])

    data['category'] = zaamo_categories
    
    return data

def resolve_product_type_of_brand(root, _info):
    
    return product_models.ProductType.objects.filter(id__in=Subquery(product_models.Product.objects.filter(brand_id=root.id).values('product_type_id')))

def resolve_due_amount(root,_info):

    earnings = resolve_total_earning(root,_info)
    paid_amount_dict = store_models.StorePayout.objects.filter(store = root).aggregate(Sum('amount'))
    paid_amount = 0
    if paid_amount_dict.get('amount__sum'):
        paid_amount = paid_amount_dict['amount__sum']

    due_amount = earnings - paid_amount

    return Decimal(due_amount)

def fetch_number_of_brands(brand_ids):
    brands_count = brand_models.Brand.objects.filter(id__in=brand_ids, botd=True).count()
    return brands_count

def fetch_order_status(orderline_vals):
    order_status = {}
    total_received_order_count = 0
    total_shipped_order_count = 0
    total_delivered_order_count = 0
    
    total_received_order_count = orderline_vals.filter(Q(metadata__status = FulfillmentStatus.PLACED)).count()
    total_shipped_order_count = orderline_vals.filter(Q(metadata__status = FulfillmentStatus.SHIPPED)).count()
    total_delivered_order_count = orderline_vals.filter(Q(metadata__status = FulfillmentStatus.DELIVERED)).count()
    delayed_orders = fetch_delayed_orders(orderline_vals).count()
    
    order_status['received_order_count'] = total_received_order_count
    order_status['shipped_order_count'] = total_shipped_order_count
    order_status['delivered_order_count'] = total_delivered_order_count
    order_status['delayed_order_count'] = delayed_orders

    return order_status

def fetch_delayed_orders(qs: order_models.OrderLine):

    delayed_orders = qs.filter(metadata__brand_order_status='delayed')

    if delayed_orders:
        return delayed_orders
    
    before_shipping = {
            FulfillmentStatus.PLACED,
            FulfillmentStatus.INPROCESS,
            FulfillmentStatus.SHIPPED
        }
    qs = qs.annotate(difftime=(F('fulfillment_line__fulfillment__updated_at') - F('created_at')))\
        .annotate(
            days=Case(
                When(metadata__status__in=before_shipping, then=F('brand__order_shipping_days')),
                default=F('brand__order_processing_days')
            )
        ).exclude(difftime=None).exclude(days=None).filter(difftime__gte=datetime.timedelta(seconds=24*3600)*(F('days') + 1))

    return qs

def filter_delayed_orders(qs: order_models.FulfillmentLine):

    delayed_orders = qs.filter(order_line__metadata__brand_order_status='delayed')

    if delayed_orders:
        return delayed_orders

    before_shipping = {
            FulfillmentStatus.PLACED,
            FulfillmentStatus.INPROCESS,
            FulfillmentStatus.SHIPPED
        }
    todays_date_time = TimeUtilities.get_current_date_time_utc()
    qs = qs.annotate(difftime=Case(
                When(fulfillment__status__in=before_shipping, then=(todays_date_time - F('order_line__order__created'))),
                default=(F('fulfillment__updated_at') - F('order_line__order__created'))))\
        .annotate(
            days=Case(
                When(fulfillment__status__in=before_shipping, then=F('order_line__brand__order_shipping_days')),
                default=F('order_line__brand__order_processing_days')
            )
        ).exclude(difftime=None).exclude(days=None).filter(difftime__gte=datetime.timedelta(seconds=24*3600)*(F('days') + 1))
    
    
    return qs
    
def filter_ontime_orders(qs: order_models.FulfillmentLine):
    delayed_orders = filter_delayed_orders(qs)
    qs = qs.exclude(id__in=delayed_orders)

    return qs

def fetch_total_gross_amount(orderline_filter):

    total_gross_amount = Decimal("0.0")

    total_cost_price_amount = orderline_filter.aggregate(total=Sum(F('quantity')*F('unit_price_gross_amount'), output_field = DecimalField()))

    if total_cost_price_amount.get('total'):
        total_gross_amount += total_cost_price_amount.get('total')
    
    return total_gross_amount

def fetch_total_influencer_earnings(orderline_filter, _info):
    store_filter = {}
    if _info.context.user.is_staff:
        store_ids = [user_store.store.id for user_store in _info.context.user.staff_store_mappings.all()]
        if store_ids:
            store_filter = {'order__order_store__store_id__in': store_ids}

    if _info.context.user.id:
        orderline_filter = orderline_filter.exclude(order__user=_info.context.user)
    
    order_lines = orderline_filter.filter(**store_filter)\
        .filter(
            ~Q(metadata__status__in=[
                FulfillmentStatus.RETURN_COMPLETED, 
                FulfillmentStatus.CANCELLATION_PROCESSED, 
                FulfillmentStatus.RETURN_INITIATED
            ]) | Q(metadata__status__isnull = True) 
        ).select_related('brand').annotate(
                earnings = Case(
                    When(Q(brand_id__isnull=False) & Q(brand__brand_name="thrift_brand"), then=ExpressionWrapper(
                        ((F('unit_price_gross_amount')*F('quantity'))+F('shipping_cost_amount'))*(F('commission_percentage')/100), output_field = DecimalField()
                    )),
                    default=ExpressionWrapper(
                        (F('unit_price_gross_amount')*F('quantity'))*(F('commission_percentage')/100), output_field = DecimalField()
                    ),
                    output_field=FloatField()
                )
            )
    
    total_earnings = Decimal(0.00)
    
    total_earnings_amount = order_lines.aggregate(total=Sum(F('earnings'), output_field = DecimalField()))
    if total_earnings_amount.get('total'):
        total_earnings += total_earnings_amount.get('total')

    return Decimal(total_earnings)


def fetch_total_completed_sourcing_requests(brand_ids, time_period=TimePeriod.OVERALL):
    total_sourcing_request = ""
    product_sourcing_request_status = []
    product_sourcing_request_status.append(product_models.SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_BRAND)
    product_sourcing_request_status.append(product_models.SourcingRequestStatus.BRAND_COUPON_CREATED)
    date_range = TimePeriod.time_period_to_datetime(time_period)
    if not brand_ids:
        total_sourcing_request_count = product_models.SourcingRequest.objects.filter(updated_at__gte=date_range['gte'], updated_at__lte=date_range['lte']).count()
        count_of_brand_related = product_models.SourcingRequest.objects.filter(status__in=product_sourcing_request_status).filter(updated_at__gte=date_range['gte'], updated_at__lte=date_range['lte']).count()
    else:
        total_sourcing_request_count = product_models.SourcingRequest.objects.filter(brand_id__in=brand_ids).filter(updated_at__gte=date_range['gte'], updated_at__lte=date_range['lte']).count()
        count_of_brand_related = product_models.SourcingRequest.objects.filter(brand_id__in=brand_ids,status__in=product_sourcing_request_status).filter(updated_at__gte=date_range['gte'], updated_at__lte=date_range['lte']).count()
    
    total_sourcing_request += f"{total_sourcing_request_count}/{count_of_brand_related}"
    return total_sourcing_request

def fetch_store_gmv(order_line_filter, _info):
    user = _info.context.user
    platform_code='IS'
    store_gmv = Decimal("0.0")
    is_superuser = user.is_superuser
    if is_superuser:
        authorized_stores_by_user = store_models.StoreInfo.objects.all().values_list('id', flat=True)
    else:
        authorized_stores_by_user = store_models.StaffStoreMapping.objects.filter(user_id=user.id).values_list('store_id', flat=True)
    
    order_ids = list(order_line_filter.filter(order__order_store__store_id__in=authorized_stores_by_user).values_list('order_id', flat=True).distinct('order_id').order_by('order_id'))
    sales_sum = order_models.Order.objects.filter(id__in=order_ids, platform_code=platform_code).aggregate(total_gmv = Sum(F("total_net_amount") + F("discount_amount")))
    
    if sales_sum.get('total_gmv'):
        store_gmv = sales_sum.get('total_gmv')

    return store_gmv

def fetch_master_dashboard_kpi_data(order_line_filter, start_date, end_date, _info):
    release_date = datetime.datetime(2022, 1, 4)
    master_dashboard_kpi = {}

    if end_date < release_date: 
        return master_dashboard_kpi

    if end_date == release_date: 
        start_date = release_date

    if start_date < release_date:
        start_date = release_date



    orderline_vals = order_line_filter.filter(created_at__lte=end_date, created_at__gte=start_date)
    orderline_ids = orderline_vals.values_list('id', flat=True)
    total_of_total_gross_amount = fetch_total_gross_amount(orderline_vals)
    master_dashboard_kpi['gmv'] = total_of_total_gross_amount 
    
    master_dashboard_kpi['influencer_earning'] = fetch_total_influencer_earnings(orderline_vals, _info)

    master_dashboard_kpi['store_gmv'] = fetch_store_gmv(orderline_vals, _info)

    total_products_sold = order_line_filter.filter(id__in=orderline_ids).aggregate(Sum('quantity'))
    
    if total_products_sold['quantity__sum']:
        master_dashboard_kpi['products_sold'] = total_products_sold['quantity__sum']
    else:
        master_dashboard_kpi['products_sold'] = 0

    order_status = fetch_order_status(orderline_vals)
    master_dashboard_kpi.update(order_status)

    return master_dashboard_kpi
    

def fetch_master_dashboard_kpi_overall_data(order_line_filter, info):
    release_date = datetime.datetime(2022, 1, 4)
    master_dashboard_kpi = {}
    order_line_filter = order_line_filter.filter(created_at__gte=release_date)
    total_of_total_gross_amount = fetch_total_gross_amount(order_line_filter)
    orderline_ids = order_line_filter.values_list('id', flat=True)
    
    master_dashboard_kpi['gmv'] = total_of_total_gross_amount 
    
    master_dashboard_kpi['influencer_earning'] = fetch_total_influencer_earnings(order_line_filter, info)

    master_dashboard_kpi['store_gmv'] = fetch_store_gmv(order_line_filter, info)

    total_products_sold = order_line_filter.filter(id__in=orderline_ids).aggregate(Sum('quantity'))
    
    if total_products_sold['quantity__sum']:
        master_dashboard_kpi['products_sold'] = total_products_sold['quantity__sum']
    else:
        master_dashboard_kpi['products_sold'] = 0

    order_status = fetch_order_status(order_line_filter)

    master_dashboard_kpi.update(order_status)

    return master_dashboard_kpi


def fetch_kpi_data_by_timeperiod(order_line_filter, root, info, time_period):
    value = time_period
    time_utilities = TimeUtilities()
    
    if value:
        if value==TimePeriod.LASTHOUR:

           start_date = time_utilities.get_last_hour_date_time()
           end_date =  TimeUtilities.get_current_date_time()
           master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, start_date, end_date, info)
           return master_dashboard_kpi

        elif value==TimePeriod.TODAY:

            today_start = time_utilities.get_today_start()
            end_date =  TimeUtilities.get_current_date_time()
            master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, today_start, end_date, info)
            return master_dashboard_kpi

        elif value==TimePeriod.YESTERDAY:

            yesterday_start = time_utilities.get_yesterdays_date()
            today_start = time_utilities.get_today_start()
            master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, yesterday_start, today_start, info)
            return master_dashboard_kpi

        elif value==TimePeriod.TILLTODAYTHISWEEK: 
            this_week_start = time_utilities.get_current_week_start()
            end_date =  TimeUtilities.get_current_date_time()
            master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, this_week_start, end_date, info)
            return master_dashboard_kpi

        elif value==TimePeriod.LASTWEEK: 
            
            last_week_start, last_week_end = time_utilities.get_prev_week_boundaries()
            master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, last_week_start, last_week_end, info)
            return master_dashboard_kpi

        elif value==TimePeriod.TILLTODAYTHISMONTH:

            curr_month_start_date = time_utilities.get_current_month_start()
            end_date =  TimeUtilities.get_current_date_time()
            master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, curr_month_start_date, end_date, info)
            return master_dashboard_kpi

        elif value==TimePeriod.LASTMONTH:

            prev_month_start_date, prev_month_end_date = time_utilities.get_prev_month_boundaries()
            master_dashboard_kpi = fetch_master_dashboard_kpi_data(order_line_filter, prev_month_start_date, prev_month_end_date, info)
            return master_dashboard_kpi

        elif value==TimePeriod.OVERALL:
            return fetch_master_dashboard_kpi_overall_data(order_line_filter, info)
    return {}

def fetch_kpi_data_by_both_timeperiod_and_brand_id(root, info, time_period, brand_ids,fulfilment_status_filter):
    release_date = datetime.datetime(2022, 1, 4)
    
    order_line_filter = order_models.OrderLine.objects.filter(
        brand_id__in = brand_ids,
        created_at__gte = release_date
    ).select_related('order')
    
    order_status = fulfilment_status_filter.get('fulfillment_line__fulfillment__status__in')
    
    if order_status:
        order_line_filter = order_line_filter.filter(Q(metadata__status__in = order_status))
    
    master_dashboard_kpi = fetch_kpi_data_by_timeperiod(order_line_filter, root, info, time_period)

    return master_dashboard_kpi


def resolve_master_dashboard_kpi(root, info, time_period, brand_ids,order_status):
    
    if order_status:
        fulfilment_status_filter = {'fulfillment_line__fulfillment__status__in' : order_status}
    else:
        fulfilment_status_filter = {}

    if brand_ids:
        if time_period:
            master_dashboard_kpi = {}
            gmv = 0
            products_sold = 0
            total_received_order_count = 0
            total_shipped_order_count = 0
            total_delivered_order_count = 0
            total_delayed_order_count = 0
            total_influencer_earning = 0
            total_completed_sourcing_requests = ""
            number_of_botdTrueBrands = 0
            store_gmv = 0
            local_brand_ids = []
            for brand_id in brand_ids:
                brand_id = NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(brand_id)[1])
                local_brand_ids.append(brand_id)
        
            master_dashboard_kpi_for_each_brand_id = fetch_kpi_data_by_both_timeperiod_and_brand_id(root, info, time_period, local_brand_ids,fulfilment_status_filter)
            gmv += master_dashboard_kpi_for_each_brand_id['gmv']
            products_sold += master_dashboard_kpi_for_each_brand_id['products_sold']
            total_received_order_count += master_dashboard_kpi_for_each_brand_id['received_order_count']
            total_shipped_order_count += master_dashboard_kpi_for_each_brand_id['shipped_order_count']
            total_delivered_order_count += master_dashboard_kpi_for_each_brand_id['delivered_order_count']
            total_delayed_order_count += master_dashboard_kpi_for_each_brand_id['delayed_order_count']
            total_influencer_earning += master_dashboard_kpi_for_each_brand_id['influencer_earning']
            store_gmv += master_dashboard_kpi_for_each_brand_id['store_gmv']
            total_completed_sourcing_requests = fetch_total_completed_sourcing_requests(local_brand_ids, time_period)
            number_of_botdTrueBrands += fetch_number_of_brands(local_brand_ids)
        
            master_dashboard_kpi['gmv'] = gmv
            master_dashboard_kpi['products_sold'] = products_sold
            master_dashboard_kpi['received_order_count'] = total_received_order_count
            master_dashboard_kpi['shipped_order_count'] = total_shipped_order_count
            master_dashboard_kpi['delivered_order_count'] = total_delivered_order_count
            master_dashboard_kpi['delayed_order_count'] = total_delayed_order_count
            master_dashboard_kpi['influencer_earning'] = total_influencer_earning
            master_dashboard_kpi['completed_sourcing_requests'] = total_completed_sourcing_requests
            master_dashboard_kpi['number_of_botdTrueBrands'] = number_of_botdTrueBrands
            master_dashboard_kpi['store_gmv'] = store_gmv

            return master_dashboard_kpi
            
        else:
            master_dashboard_kpi = {}
            gmv = 0
            products_sold = 0
            total_received_order_count = 0
            total_shipped_order_count = 0
            total_delivered_order_count = 0
            total_delayed_order_count = 0
            total_influencer_earning = 0
            total_completed_sourcing_requests = ""
            number_of_botdTrueBrands = 0
            store_gmv = 0
            local_brand_ids = []
            for brand_id in brand_ids:
                brand_id = NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(brand_id)[1])
                local_brand_ids.append(brand_id)
            
            master_dashboard_kpi_for_each_brand_id = fetch_kpi_data_by_both_timeperiod_and_brand_id(root, info, TimePeriod.OVERALL ,local_brand_ids,fulfilment_status_filter)
            gmv += master_dashboard_kpi_for_each_brand_id['gmv']
            products_sold += master_dashboard_kpi_for_each_brand_id['products_sold']
            total_received_order_count += master_dashboard_kpi_for_each_brand_id['received_order_count']
            total_shipped_order_count += master_dashboard_kpi_for_each_brand_id['shipped_order_count']
            total_delivered_order_count += master_dashboard_kpi_for_each_brand_id['delivered_order_count']
            total_delayed_order_count += master_dashboard_kpi_for_each_brand_id['delayed_order_count']
            total_influencer_earning += master_dashboard_kpi_for_each_brand_id['influencer_earning']
            store_gmv += master_dashboard_kpi_for_each_brand_id['store_gmv']
            total_completed_sourcing_requests = fetch_total_completed_sourcing_requests(local_brand_ids)
            number_of_botdTrueBrands += fetch_number_of_brands(local_brand_ids)

            master_dashboard_kpi['gmv'] = gmv
            master_dashboard_kpi['products_sold'] = products_sold
            master_dashboard_kpi['received_order_count'] = total_received_order_count
            master_dashboard_kpi['shipped_order_count'] = total_shipped_order_count
            master_dashboard_kpi['delivered_order_count'] = total_delivered_order_count
            master_dashboard_kpi['delayed_order_count'] = total_delayed_order_count
            master_dashboard_kpi['influencer_earning'] = total_influencer_earning
            master_dashboard_kpi['completed_sourcing_requests'] = total_completed_sourcing_requests
            master_dashboard_kpi['number_of_botdTrueBrands'] = number_of_botdTrueBrands
            master_dashboard_kpi['store_gmv'] = store_gmv

            return master_dashboard_kpi
    else:
        order_line_filter = order_models.OrderLine.objects.all().select_related('order')
        
        order_status = fulfilment_status_filter.get('fulfillment_line__fulfillment__status__in')        
        if order_status:
            order_line_filter = order_line_filter.filter(Q(metadata__status__in = order_status))
        
        local_brand_ids = []

        if time_period:
            master_dashboard_kpi = fetch_kpi_data_by_timeperiod(order_line_filter, root, info, time_period)
            master_dashboard_kpi['number_of_botdTrueBrands'] = brand_models.Brand.objects.filter(botd=True).count()
            master_dashboard_kpi['completed_sourcing_requests'] = fetch_total_completed_sourcing_requests(local_brand_ids, time_period)

            return master_dashboard_kpi
        else:
            master_dashboard_kpi = fetch_master_dashboard_kpi_overall_data(order_line_filter, info)
            master_dashboard_kpi['number_of_botdTrueBrands'] = brand_models.Brand.objects.filter(botd=True).count()
            master_dashboard_kpi['completed_sourcing_requests'] = fetch_total_completed_sourcing_requests(local_brand_ids)

            return master_dashboard_kpi

def get_wix_product_data(root, _info):
    wix_impl = WixImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name
        
    response = wix_impl.get_mapped_product_from_brand_name(brand_name)

    return response

def get_woo_commerce_product_data(root, _info):
    woo_impl = WooCommerceImpl()
    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name
    response = woo_impl.get_mapped_product_from_brand_name(brand_name)

    return response

def get_shopify_product_data(root, _info):
    shopify_impl = ShopifyImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name
        
    response = shopify_impl.get_mapped_product_from_brand_name(brand_name)

    return response


def get_mydukaan_product_data(root, _info):
    mydukaan_impl = MyDukaanImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name
        
    response = mydukaan_impl.get_mapped_product_from_brand_name(brand_name)

    return response

def get_custom_product_data(root, _info):
    inst = StyleStreeImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name
        
    response = inst.get_mapped_product_from_brand_name(brand_name)

    return response

def get_acha_india_product_data(root, _info):
    acha_impl = AchaIndiaImpl()

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name
        
    response = acha_impl.get_mapped_product_from_brand_name(brand_name)

    return response

def get_images_url_list_from_product(image_product_dict,_info):

    image_url_list = []

    for image in image_product_dict:
        # try:
        #     url = image.url
        #     print("url",url)
        #     url = url.replace('.png','')
        #     url = url.replace('media/','media/__sized__/')
        #     image_url = f'{url}-thumbnail-255x255.png'
        #     image_url_list.append(image_url)
        
        # except Exception as e:
        #     print(e)
        url = get_thumbnail(image, 255, method="thumbnail")
       
        image_url_list.append(url)
    
    return image_url_list

def get_image_product_dict(images_product):
    images_product_dict = defaultdict(list)

    for image_inst in images_product:
        images_product_dict[image_inst.product_id].append(image_inst.image)
    
    return images_product_dict

def map_postgres_product_for_pdp(products,products_mappings,_info=None):
    variants = product_models.ProductVariant.objects.filter(product_id__in=products.values('id'))
    variant_stocks = Stock.objects.filter(product_variant_id__in=variants.values('id'))
    variant_stock_dict = defaultdict(int)

    for stock in variant_stocks:
        variant_stock_dict[stock.product_variant_id]+=stock.quantity

    variant_product_name_dict = defaultdict(list)
    
    for variant in variants:
        variant_product_name_dict[variant.product_id].append(variant)
    product_zaamo_id_list  = products.values('id')
    images_product = product_models.ProductImage.objects.filter(product_id__in=product_zaamo_id_list)
    
    images_product_dict = get_image_product_dict(images_product)

    order_id_count_dict = create_order_count_dictionary(product_zaamo_id_list)

    pdp_id_count_dict = create_pdp_views_count_dictionary(product_zaamo_id_list)
    
    wishlist_id_count_dict = create_wishlist_count_dictionary(product_zaamo_id_list)

    store_id_count_dict = create_store_count_dictionary(product_zaamo_id_list)
    
    storeview_id_count_dict = create_storeview_count_dictionary(product_zaamo_id_list)
    product_id_brand_zaamo_dict = defaultdict(str)
    variant_id_brand_zaamo_dict = defaultdict(list)
    
    for mapping in products_mappings:
        variant_id_brand_zaamo_dict[mapping.product_zaamo.id].append(mapping.variant_id_brand)
        product_id_brand_zaamo_dict[mapping.product_zaamo.id] = (mapping.product_id_brand)

    response = defaultdict(list)
    for product in products:
        
        image_url_list = []
        variant_data = [{'fields':{'name': variant.name,'track_inventory':variant.track_inventory},
                        'stock':{'quantity':variant_stock_dict[variant.id]}}
                         for variant in variant_product_name_dict[product.id]]
                         
        image_url_list = get_images_url_list_from_product(images_product_dict[product.id], _info)
        
        product_zaamo_id = graphene.Node.to_global_id("Product", product.id)
        brand_id = graphene.Node.to_global_id("Brand", product.brand_id)
        mapped_data = {
            "product.brand_variant_zaamomapping": {'product_id_brand': product_id_brand_zaamo_dict[product.id],
                                                'variant_id_brands': variant_id_brand_zaamo_dict[product.id]},
            "product.productimage": image_url_list,
            "product.product": {'fields': {
                                    'name': product.name,
                                    'description_json': product.description_json
                                    }},
            "product.productvariant": variant_data,
            "product_zaamo":product,
            "product_zaamo_id":product_zaamo_id,
            "slug":product.slug,
            "brand_id":brand_id,
            "product.created_at":product.publication_date or datetime.date(2022,1,4),
            "publication_date":product.publication_date or datetime.date(2022,1,4),
            "order_count": order_id_count_dict[product.id],
            "pdp_views": pdp_id_count_dict[product.id],
            'wishlist_count' : wishlist_id_count_dict[product.id],
            'store_count' : store_id_count_dict[product.id],
            'storeview_count': storeview_id_count_dict[product.id],
        }
        response[product.id]=[mapped_data]
    
    return response

def get_staff_product_data(root, _info):
    
    brand_name = root.private_metadata.get('source_name')

    if not brand_name:
        brand_name = root.brand_name
        
    products = product_models.Product.objects.filter(brand=root).select_related('brand', 'category')
    products_mappings = product_models.BrandVariantZaamoMapping.objects.filter(brand_name=brand_name).select_related('product_zaamo', 'product_zaamo__brand', 'product_zaamo__category')
    
    response = map_postgres_product_for_pdp(products,products_mappings,_info)
    return response

def get_product_type_list_from_global_id(product_type_global):
    product_type_id = []

    for g_id in product_type_global:
        id = graphene.Node.from_global_id(g_id)[-1]
        product_type_id.append(NumberUtilities.convert_string_to_number(id))
    
    return product_type_id

def get_product_from_brand_mapping(product_data):
    brand_mapping = product_data.get('product.brand_variant_zaamomapping')

    if not brand_mapping:
        return None

    product_id_brand = brand_mapping.get('product_id_brand')
    variant_id_brands = brand_mapping.get('variant_id_brands',[])
    brand_name = brand_mapping.get('brand_name')

    if not variant_id_brands or None in variant_id_brands:
        product_mapping = (product_models.BrandVariantZaamoMapping.objects.filter(brand_name=brand_name,
                                                                product_id_brand=product_id_brand))

    else:
        product_mapping = (product_models.BrandVariantZaamoMapping.objects.filter(brand_name=brand_name,
                                                                product_id_brand=product_id_brand,
                                                                variant_id_brand__in=variant_id_brands))
    
    if not product_mapping:
        return None

    product_zaamo = product_mapping.first().product_zaamo

    return product_zaamo

def create_order_count_dictionary(product_zaamo_id_list):
    order_id_count_dict = defaultdict(int)

    orders_count = order_models.OrderLine.objects.filter(
                        variant_id__in=Subquery(product_models.ProductVariant.objects.filter(
                        product_id__in=product_zaamo_id_list).values('id'))).annotate(
                        total=Count('variant_id')).order_by('variant_id').select_related('variant')
    
    for order_count in orders_count:

        if not order_count.variant:
            continue
        
        order_id_count_dict[order_count.variant.product_id]+=order_count.total

    return order_id_count_dict

def create_storeview_count_dictionary(product_zaamo_id_list):
    storeview_id_count_dict = defaultdict(int)
    
    storeview_counts = product_models.StoreProductViews.objects.filter(product_id__in = product_zaamo_id_list).values('product_id').annotate(total=Sum('views'))

    for w_count in storeview_counts:

        if not w_count.get('product_id'):
            continue

        storeview_id_count_dict[w_count.get('product_id')]+=w_count.get('total')

    return storeview_id_count_dict

def create_store_count_dictionary(product_zaamo_id_list):
    store_id_count_dict = defaultdict(int)
    
    store_counts = product_models.CollectionStore.objects.prefetch_related('collection__products').filter(collection__products__in=product_zaamo_id_list).values('collection__products').annotate(total=Count('collection__products'))

    for w_count in store_counts:

        if not w_count.get('collection__products'):
            continue

        store_id_count_dict[w_count.get('collection__products')]+=w_count.get('total')

    return store_id_count_dict

def create_wishlist_count_dictionary(product_zaamo_id_list):
    wishlist_id_count_dict = defaultdict(int)
    
    wishlist_count = wishlist_models.WishlistItem.objects.filter(product_id__in=product_zaamo_id_list).annotate(
                        total=Count('product_id')).order_by('product_id')

    for w_count in wishlist_count:

        if not w_count.product_id:
            continue

        wishlist_id_count_dict[w_count.product_id]+=w_count.total

    return wishlist_id_count_dict

def create_pdp_views_count_dictionary(product_zaamo_id_list):
    pdp_id_count_dict = defaultdict(int)

    pdp_views_count = product_models.StoreProductViews.objects.filter(product_id__in=product_zaamo_id_list).values('product_id').annotate(total=Sum('views'))

    for pdp_count in pdp_views_count:

        if not pdp_count.get('product_id'):
            continue

        pdp_id_count_dict[pdp_count.get('product_id')]+=pdp_count.get('total')

    return pdp_id_count_dict

def update_mapped_data_with_product_instance(data,brand_name,_info):

    products_mappings = (product_models.BrandVariantZaamoMapping.objects.filter(brand_name=brand_name))
    products = product_models.Product.objects.filter(id__in=products_mappings.values('product_zaamo_id')).select_related('category','brand').prefetch_related('variants')
    products_dict = {p.id:p for p in products}
    product_id_brand_zaamo_dict = defaultdict(list)
    variant_id_brand_zaamo_dict = defaultdict(str)

    if not products_mappings:

        for id,value in data.items():
            products = data[id]

            for i in range(len(products)):
                
                products[i]['order_count'] = 0
                products[i]['brand_order_count'] = 0
                products[i]['pdp_views'] = 0
                products[i]['publication_date'] = datetime.date(2022,1,4)

        return data
    
    data_value_list = []
    for value in data.values():
        data_value_list.extend(value)

    product_zaamo_id_list = []
    
    for mapping in products_mappings:

        variant_id_brand_zaamo_dict[mapping.variant_id_brand] = products_dict.get(mapping.product_zaamo_id)
        product_id_brand_zaamo_dict[mapping.product_id_brand].append(products_dict.get(mapping.product_zaamo_id))
        product_zaamo_id_list.append(mapping.product_zaamo_id)

    order_id_count_dict = create_order_count_dictionary(product_zaamo_id_list)
    brand_order_id_count_dict = fetch_brand_order_count_dict(brand_name)
    brand_order_id_last_week_count_dict = fetch_brand_order_last_weeek_count_dict(brand_name)
    
    pdp_id_count_dict = create_pdp_views_count_dictionary(product_zaamo_id_list)
    
    wishlist_id_count_dict = create_wishlist_count_dictionary(product_zaamo_id_list)
    store_id_count_dict = create_store_count_dictionary(product_zaamo_id_list)
    storeview_id_count_dict = create_storeview_count_dictionary(product_zaamo_id_list)
    images_product = product_models.ProductImage.objects.filter(product_id__in=products_mappings.values('product_zaamo_id'))
    images_product_dict = get_image_product_dict(images_product)
    
    product_data_dict = defaultdict(list)
    for product_data in data_value_list:

        product_zaamo = None
        brand_mapping = product_data.get('product.brand_variant_zaamomapping')

        if not brand_mapping:
            continue

        product_id_brand = StringUtilities.convert_object_to_string(brand_mapping.get('product_id_brand'))
        variant_id_brands = [StringUtilities.convert_object_to_string(variant_id) for variant_id in brand_mapping.get('variant_id_brands',[])]

        for variant_id_brand in variant_id_brands:
            
            product_zaamo = variant_id_brand_zaamo_dict[variant_id_brand]
            
            if product_zaamo:
                
                break
        
        if not product_zaamo:
            
            product_zaamo_l = product_id_brand_zaamo_dict[product_id_brand]
        
            if product_zaamo_l:
        
                product_zaamo = product_zaamo_l[0]

        product_data['product_zaamo'] = product_zaamo
        brand_order_count_last_week = 0
        
        brand_order_count_last_week = brand_order_id_last_week_count_dict[(product_id_brand,None)]

        for variant_id_brand in variant_id_brands:
            brand_order_count_last_week+=brand_order_id_last_week_count_dict[(product_id_brand,variant_id_brand)]

        brand_order_count_t= 0
        
        brand_order_count_t = brand_order_id_count_dict[(StringUtilities.convert_number_to_string(product_id_brand),None)]

        for variant_id_brand in variant_id_brands:
            brand_order_count_t+=brand_order_id_count_dict[(StringUtilities.convert_number_to_string(product_id_brand),StringUtilities.convert_number_to_string(variant_id_brand))]


        if product_zaamo:
            brand_id = graphene.Node.to_global_id("Brand", product_zaamo.brand_id)
            product_zaamo_id = graphene.Node.to_global_id("Product", product_zaamo.id)
            product_data['product_zaamo_id'] = product_zaamo_id
            product_data["slug"] = product_zaamo.slug
            product_data["brand_id"] = brand_id
            product_data['order_count'] = order_id_count_dict[product_zaamo.id]
            product_data['brand_order_count'] = brand_order_count_t
            product_data['brand_order_count_last_week'] = brand_order_count_last_week
            product_data['pdp_views'] = pdp_id_count_dict[product_zaamo.id]
            product_data['wishlist_count'] = wishlist_id_count_dict[product_zaamo.id]
            product_data['store_count'] = store_id_count_dict[product_zaamo.id]
            product_data['storeview_count'] = storeview_id_count_dict[product_zaamo.id]
            product_data['publication_date'] = product_zaamo.publication_date or datetime.date(2022,1,4),

            image_url_list = get_images_url_list_from_product(images_product_dict[product_zaamo.id], _info)
            product_data["product.productimage"] = image_url_list
            product_data["product.product"]['fields']['description_json'] = product_zaamo.description_json
        else:
            product_data['product_zaamo_id'] = ''
            product_data["slug"] = ''
            product_data["brand_id"] = ''
            product_data['order_count'] = 0
            product_data['brand_order_count'] = brand_order_count_t
            product_data['brand_order_count_last_week'] = brand_order_count_last_week
            product_data['pdp_views'] = 0
            product_data['publication_date'] = datetime.date(2022,1,4)
        
        product_data_dict[product_id_brand].append(product_data)
        
    return product_data_dict


def filter_product_list_from_is_publish_and_type(product_list, is_published, product_type_values, brand_name):
    product_list_new = []
    
    for product_data in product_list:
        product_zaamo = product_data.get('product_zaamo')    
        if not product_zaamo:
    
            if not is_published:
                product_list_new.append(product_data)
            
            continue
        
        if not is_published==None and product_type_values:
            if product_zaamo.is_published == is_published and product_zaamo.product_type_id in product_type_values:
                product_list_new.append(product_data)
                continue
        
        elif not is_published==None:
            if product_zaamo.is_published == is_published:
                product_list_new.append(product_data)
                continue

        elif product_type_values:
            if product_zaamo.product_type_id in product_type_values:
                product_list_new.append(product_data)
                continue

    return product_list_new

def paginated_resolve_product_of_brand(root, _info, args=dict(), page=1):
    
    
    product_list = resolve_product_of_brand(root, _info, args)

    per_page = NumberUtilities.convert_string_to_number(PDP_PER_PAGE)
    start = per_page*(page-1)
    end = per_page*(page)
    if start>len(product_list)-1:
        return []

    if per_page*(page)>len(product_list):
        end = len(product_list)
        
    return product_list[start:end]

def filter_product_list_from_data_source(product_list,data_source):
    postgres_product_list = []
    mongo_product_list = []

    for product in product_list:
        if product.get('product_zaamo_id'):
            postgres_product_list.append(product)
        
        else:
            mongo_product_list.append(product)
    
    if data_source=='mongo':
        return mongo_product_list
    
    elif data_source=='postgres':
        return postgres_product_list
    
    return product_list

def get_product_data_from_brand(root,_info, brand_name):
    source = root.brand_source

    if source==BrandSourceEnum.WIX:
        
        data = get_wix_product_data(root, _info)
        
    elif source==BrandSourceEnum.WOOCOMMERCE:
        
        data = get_woo_commerce_product_data(root, _info)
        
    elif source==BrandSourceEnum.SHOPIFY:

        data = get_shopify_product_data(root, _info)

    elif source==BrandSourceEnum.ACHAINDIA:

        data = get_acha_india_product_data(root, _info)
    
    elif source==BrandSourceEnum.CUSTOM:

        data = get_custom_product_data(root, _info)
    
    elif source==BrandSourceEnum.MYDUKAAN:                
        data = get_mydukaan_product_data(root, _info)
        
    elif source in [BrandSourceEnum.STAFF, BrandSourceEnum.MANUAL, BrandSourceEnum.UNICOMMERCE]:
        
        data = get_staff_product_data(root, _info)

    if not source in [BrandSourceEnum.STAFF, BrandSourceEnum.MANUAL, BrandSourceEnum.UNICOMMERCE]:
        data = update_mapped_data_with_product_instance(data,brand_name,_info)

    return data

def fetch_filtered_product_list(data,collection_values,category_values,source,
                                combined_product_ids,postgres_category_product_ids,
                                is_published,product_type_values, brand_name,data_source):
    
    
    product_list = []
    combined_product_ids = StringUtilities.convert_list_of_object_to_string(list(combined_product_ids))

    for id,value in data.items():
        
        if collection_values or category_values:

            if not source in [BrandSourceEnum.STAFF, BrandSourceEnum.MANUAL, BrandSourceEnum.UNICOMMERCE]:

                if StringUtilities.convert_object_to_string(id) in combined_product_ids:
                    
                    product_list.extend(value)
                    continue

            for product in value:

                if product.get('product_zaamo') and postgres_category_product_ids:
                    product_zaamo = product.get('product_zaamo')
                    
                    if product_zaamo.id in postgres_category_product_ids:
                        product_list.append(product)

            continue
            
        product_list.extend(value)

    if not is_published==None or product_type_values:
        
        product_list = filter_product_list_from_is_publish_and_type(product_list, is_published,product_type_values, brand_name)
    
    if data_source:
        product_list = filter_product_list_from_data_source(product_list,data_source)

    
    return product_list

def fetch_brand_order_count_dict(brand_name):
    brand_count_insts = brand_models.BrandOrderCount.objects.filter(brand_name=brand_name)
    order_count_dict = defaultdict(int)

    for inst in brand_count_insts:
        order_count_dict[(inst.product_id_brand,inst.variant_id_brand)] += inst.brand_order_count
        
    return order_count_dict

def fetch_brand_order_last_weeek_count_dict(brand_name):
    brand_count_insts = brand_models.BrandOrderCount.objects.filter(brand_name=brand_name)
    order_count_dict = defaultdict(int)

    for inst in brand_count_insts:
        order_count_dict[(inst.product_id_brand,inst.variant_id_brand)] += inst.brand_order_count_last_week
        
    return order_count_dict

def sort_product_list_for_pdp(product_list,commission,sort_args):

    sorting_product_dict = defaultdict(list)
    sort_flow = False
    
    if sort_args:
    
        for product in product_list:

            product['commission'] = commission

            if sort_args.get('order_counts'):
                
                sorting_product_dict[product['order_count']].append(product)
                sort_value = sort_args.get('order_counts')

                if sort_value=='desc':
                    sort_flow = True
            
            elif sort_args.get('brand_order_counts'):
                
                sorting_product_dict[product.get('brand_order_count',0)].append(product)
                sort_value = sort_args.get('brand_order_counts')

                if sort_value=='desc':
                    sort_flow = True

            elif sort_args.get('pdp_views'):
                
                sorting_product_dict[product['pdp_views']].append(product)
                sort_value = sort_args.get('pdp_views')
                
                if sort_value=='desc':
                    sort_flow = True
                
            elif sort_args.get('publication_date'):
                
                if isinstance(product['publication_date'],tuple):
                    product['publication_date'] = product['publication_date'][0]
                
                sorting_product_dict[product['publication_date']].append(product)
                sort_value = sort_args.get('publication_date')
                
                if sort_value=='desc':
                    sort_flow = True

    product_list_sorted = []
    
    if not sorting_product_dict:

        for product in product_list:
        
            sorting_product_dict[(product['product.created_at'],product.get('brand_order_count_last_week',0))].append(product)
            sort_flow = True
            
        for id in sorted(sorting_product_dict.keys(),key=lambda row: (row[1], row[0]),reverse=sort_flow):
            product_list_sorted.extend(sorting_product_dict[id])
        
        if not product_list_sorted:
                product_list_sorted = product_list

        return product_list_sorted
            
    for id in sorted(sorting_product_dict.keys(),reverse=sort_flow):
        product_list_sorted.extend(sorting_product_dict[id])
    
    if not product_list_sorted:
            product_list_sorted = product_list

    return product_list_sorted

def add_brand_order_count_data_in_name(brand_name,product_list):
    brand_order_count_dict = fetch_brand_order_count_dict(brand_name)

    for product in product_list:
        try:
            product_id_brand = product['product.brand_variant_zaamomapping'].get('product_id_brand')
            variant_id_brands = [StringUtilities.convert_object_to_string(variant_id) for variant_id in product['product.brand_variant_zaamomapping'].get('variant_id_brands',[])]
            count = 0

            if  product_id_brand:

                brand_order_count_t= 0
                
                brand_order_count_t = brand_order_count_dict[(StringUtilities.convert_number_to_string(product_id_brand),None)]

                for variant_id_brand in variant_id_brands:
                    brand_order_count_t+=brand_order_count_dict[(StringUtilities.convert_number_to_string(product_id_brand),StringUtilities.convert_number_to_string(variant_id_brand))]

                count = brand_order_count_t
                
            if product.get('product_zaamo'):
                count = product['product_zaamo'].metadata.get('brand_order_count') or count
                count = NumberUtilities.convert_string_to_number(count)
            
            if count>0:
                product['product.product']['fields']['name'] = f"{product['product.product']['fields']['name']} ({count})"
        
        except Exception as e:
            logger.exception(e)
            continue
        
    return product_list
        

def resolve_product_of_brand(root, _info, args=dict()):
    source = root.brand_source
    data = defaultdict(list)
    collection_values = args.get('brand_collection',[])
    category_values = args.get('brand_category',[])
    product_type_values = get_product_type_list_from_global_id(args.get('product_type',[]))
    is_published = args.get('is_published')
    data_source = args.get('data_source')
    commission_obj = root.commission.first()
    sort_args = args.get('sort')
    commission = 0.0

    brand_name = root.private_metadata.get('source_name')
    if not brand_name:
        brand_name = root.brand_name

    if commission_obj:
        commission = commission_obj.commission_percentage

    collection_product_ids = set()
    category_product_ids = set()

    combined_product_ids = []
    
    if collection_values:
        collection_product_ids = filter_brand_collections(root,collection_values)

    if category_values:
        category_product_ids = filter_brand_categories(root,category_values)
    
    if collection_product_ids and category_product_ids:
        combined_product_ids = set(collection_product_ids).intersection(set(category_product_ids))
    
    else:

        if collection_product_ids:
            combined_product_ids = collection_product_ids

        elif category_product_ids:
            combined_product_ids = category_product_ids

    combined_product_ids = [StringUtilities.convert_object_to_string(id) for id in combined_product_ids]
    
    data = get_product_data_from_brand(root, _info, brand_name)
    postgres_category_product_ids = []

    if category_values:
        postgres_category_product_ids = product_models.Product.objects.filter(category__name__in = category_values).values_list('id',flat=True)
    
    product_list = fetch_filtered_product_list(data,collection_values,category_values,source,
                                combined_product_ids,postgres_category_product_ids,
                                is_published,product_type_values, brand_name,data_source)

    product_list = sort_product_list_for_pdp(product_list,commission,sort_args)
    product_list = add_brand_order_count_data_in_name(brand_name,product_list)

    return product_list
    
def get_brand_name_from_ob(brand):
    brand_name = brand.private_metadata.get('source_name')

    if not brand_name:
        brand_name = brand.brand_name

    return brand_name

def filter_brand_collections(brand, value,for_pdp=True):
    product_id_brands = []

    if brand:
        brand_source = brand.brand_source
        brand_name = get_brand_name_from_ob(brand)
        
        if brand_source==BrandSourceEnum.WIX:
            wix_impl = WixImpl()
            product_id_brands = wix_impl.fetch_product_brand_ids_from_collections(value,brand_name,for_pdp=for_pdp)

        elif brand_source==BrandSourceEnum.SHOPIFY:
            shopify_impl = ShopifyImpl()
            product_id_brands = shopify_impl.fetch_product_brand_ids_from_collections(value,brand_name,for_pdp=for_pdp)

    return product_id_brands

def fetch_collection_product_id(product_id_brand, brand):
    product_id_brands = defaultdict(list)

    if brand:
        brand_source = brand.brand_source
        brand_name = get_brand_name_from_ob(brand)
    
        if brand_source==BrandSourceEnum.SHOPIFY:
            shopify_impl = ShopifyImpl()
            product_id_brands = shopify_impl.fetch_collections_from_product_id(product_id_brand, brand_name)

    return product_id_brands

def fetch_category_product_id(product_id_brand, brand):
    product_id_brands = defaultdict(list)
    
    if brand:
        brand_source = brand.brand_source
        brand_name = get_brand_name_from_ob(brand)
        
        if brand_source==BrandSourceEnum.WOOCOMMERCE:
            woo_impl = WooCommerceImpl()
            product_id_brands = woo_impl.fetch_categories_from_product_id(product_id_brand, brand_name)

        elif brand_source==BrandSourceEnum.SHOPIFY:
            shopify_impl = ShopifyImpl()
            product_id_brands = shopify_impl.fetch_categories_from_product_id(product_id_brand, brand_name)

        elif brand_source==BrandSourceEnum.ACHAINDIA:
            acha_impl = AchaIndiaImpl()
            product_id_brands = acha_impl.fetch_categories_from_product_id(product_id_brand, brand_name)
            
        elif brand_source==BrandSourceEnum.CUSTOM:
            inst = StyleStreeImpl()
            product_id_brands = inst.fetch_categories_from_product_id(product_id_brand, brand_name)
        
        elif brand.brand_source==BrandSourceEnum.MYDUKAAN:                
            mydukaan_impl = MyDukaanImpl()
            product_id_brands = mydukaan_impl.fetch_categories_from_product_id(product_id_brand, brand_name)
            
    return product_id_brands    

def filter_brand_categories(brand, value, for_pdp=True):
    product_id_brands = []
    
    if brand:
        brand_source = brand.brand_source
        brand_name = get_brand_name_from_ob(brand)
        
        if brand_source==BrandSourceEnum.WOOCOMMERCE:
            woo_impl = WooCommerceImpl()
            product_id_brands = woo_impl.fetch_product_brand_ids_from_categories(value,brand_name,for_pdp=for_pdp)

        elif brand_source==BrandSourceEnum.SHOPIFY:
            shopify_impl = ShopifyImpl()
            product_id_brands = shopify_impl.fetch_product_brand_ids_from_categories(value,brand_name,for_pdp=for_pdp)

        elif brand_source==BrandSourceEnum.ACHAINDIA:
            acha_impl = AchaIndiaImpl()
            product_id_brands = acha_impl.fetch_product_brand_ids_from_categories(value,brand_name,for_pdp=for_pdp)

        elif brand_source==BrandSourceEnum.CUSTOM:
            if brand_name=='stylestree' or brand_name=='shoetopia':
                cust_impl = StyleStreeImpl()
                product_id_brands = cust_impl.fetch_product_brand_ids_from_categories(value,brand_name,for_pdp=for_pdp)
            
            if brand_name=='thesouledstore':
                cust_impl = TheSouledStoreImpl()
                product_id_brands = cust_impl.fetch_product_brand_ids_from_categories(value,brand_name,for_pdp=for_pdp)
            
        elif brand_source==BrandSourceEnum.MYDUKAAN:
            mydukaan_impl = MyDukaanImpl()
            product_id_brands = mydukaan_impl.fetch_product_brand_ids_from_categories(value,brand_name,for_pdp=for_pdp)
            
    return product_id_brands

def filter_brand_sub_categories(brand, values):
    pass


def resolve_wishlist_count_product(root, _info):
    
    product = root.get('product_zaamo')
    if product:
        return wishlist_models.WishlistItem.objects.filter(product_id=product.id).count()
    
    return 0
    
def resolve_order_count_product(root, _info):
    
    product = root.get('product_zaamo')
    if product:
        return (order_models.OrderLine.objects.filter(variant_id__in=Subquery(
                product_models.ProductVariant.objects.filter(product_id=product.id).values('id'))).count())
    
    return 0
    
def resolve_store_count_product(root, _info):
    product = root.get('product_zaamo')
    if product:
        return (product_models.CollectionStore.objects.filter
                (collection_id__in=Subquery(product_models.CollectionProduct.objects.filter(product_id=product.id)
                .values('collection_id'))).count())
    return 0

def resolve_publication_date_product(root):
    product = root.get('product_zaamo')
    if product:
        
        return product.publication_date or None
    
    return None

def resolve_is_published_product(root):
    product = root.get('product_zaamo')
    if product:
        return product.is_published
    
    return False

def update_brand_collection_mapping_from_to_publish(to_publish,product_zaamo):
    
    if not to_publish:
        category_mapping = brand_models.BrandCollectionMapping.objects.filter(product_id=product_zaamo.id).delete()
    
    else:
        brand_mapping = product_models.BrandVariantZaamoMapping.objects.filter(product_zaamo_id = product_zaamo.id).first()
        if brand_mapping:
            product_id_brand = brand_mapping.product_id_brand
            from saleor.external_services.integrations import BrandCollectionCreate
            brand_collection_inst = BrandCollectionCreate()
            brand_collection_inst.add_brand_collection_by_publish(product_id_brand, product_zaamo.brand)
            brand_collection_inst.add_zaamo_collection_by_publish(product_zaamo, product_zaamo.brand)

def create_product_from_pdp_mutation(arg_data,category_id,commission,value_deal):
    brand_id = arg_data.get('brand_id')
    product_id_brand = arg_data.get('product_id_brand')
    variant_id_brands = arg_data.get('variant_id_brands')
    to_publish = arg_data.get('to_publish')
    brand = brand_models.Brand.objects.filter(id=brand_id).first()
    brand_name = brand.private_metadata.get('source_name')

    if not brand_name:
        brand_name = brand.brand_name
    data = None
    if brand.brand_source==BrandSourceEnum.WIX:
        wix_impl = WixImpl()
        data = wix_impl.create_product_from_product_variant_id(brand_name, product_id_brand, variant_id_brands)

    if brand.brand_source==BrandSourceEnum.WOOCOMMERCE:
        woo_impl = WooCommerceImpl()
        data = woo_impl.create_product_from_product_variant_id(brand_name, product_id_brand, variant_id_brands)

    if brand.brand_source==BrandSourceEnum.SHOPIFY:                
        shopify_impl = ShopifyImpl()
        data = shopify_impl.create_product_from_product_variant_id(brand_name, product_id_brand, variant_id_brands)
    
    if brand.brand_source==BrandSourceEnum.ACHAINDIA:                
        acha_impl = AchaIndiaImpl()
        data = acha_impl.create_product_from_product_variant_id(brand_name, product_id_brand, variant_id_brands)
    
    if brand.brand_source==BrandSourceEnum.CUSTOM:                
        cust_impl = StyleStreeImpl()
        data = cust_impl.create_product_from_product_variant_id(brand_name, product_id_brand, variant_id_brands)

    if brand.brand_source==BrandSourceEnum.MYDUKAAN:                
        mydukaan_impl = MyDukaanImpl()
        data = mydukaan_impl.create_product_from_product_variant_id(brand_name, product_id_brand, variant_id_brands)
    
    if brand.brand_source in [BrandSourceEnum.STAFF, BrandSourceEnum.MANUAL, BrandSourceEnum.UNICOMMERCE]:
        data = True
    if data:
        if not variant_id_brands or None in variant_id_brands:
            product_mapping = product_models.BrandVariantZaamoMapping.objects.filter(product_id_brand=product_id_brand, brand_name=brand_name).first()
            
        else:
            product_mapping = product_models.BrandVariantZaamoMapping.objects.filter(product_id_brand=product_id_brand,variant_id_brand__in=variant_id_brands, brand_name=brand_name).first()

        if product_mapping:
            product_zaamo = product_mapping.product_zaamo
            product_zaamo.is_published = to_publish

            if category_id and product_models.Category.objects.filter(id=category_id).exists():
                product_zaamo.category_id=category_id
            
            if commission:
                product_zaamo.commission_percentage=commission
                product_zaamo.has_custom_commission=True
            
            if value_deal:
                product_zaamo.metadata['value_deal'] = value_deal
                product_zaamo.metadata['value_updated_at'] = TimeUtilities.get_current_date_time()
            product_zaamo.save()
            update_brand_collection_mapping_from_to_publish(to_publish, product_zaamo)
            explore_content_sync.delay(product_id=product_zaamo.id)
    
def resolve_pdp_product_search(product_name, brand_name, _info):
    product_name = product_name.lower()
    product_search_res = product_search(product_name).values_list('id',flat=True)[:100]
    product_ids = [product_id for product_id in product_search_res]
    product_query_set = product_models.Product.objects.filter(id__in=product_ids).select_related('brand','category')
    product_mappings = product_models.BrandVariantZaamoMapping.objects.filter(product_zaamo_id__in=product_ids).select_related('product_zaamo')
    
    mapped_data_list = map_postgres_product_for_pdp(product_query_set,product_mappings,_info)
    product_response_list = []
    for p_data in mapped_data_list.values():
        product_response_list.extend(p_data)

    if not brand_name:
        return product_response_list

    brand = brand_models.Brand.objects.filter(Q(brand_name=brand_name) | Q(private_metadata__source_name=brand_name)).first()
    
    brand_name = get_brand_name_from_ob(brand)
    if not brand or brand.brand_source in [BrandSourceEnum.STAFF, BrandSourceEnum.MANUAL, BrandSourceEnum.UNICOMMERCE]:
        return product_response_list

    product_data = get_product_data_from_brand(brand,_info,brand_name)
    count = 0
    for product_list in product_data.values():
        if count>100:
            break
        for product in product_list:
            
            if product.get('product_zaamo'):
                continue

            product_name_map = product['product.product']['fields']['name'].lower()

            if product_name in product_name_map:
                product_response_list.append(product)
                count+=1
    product_response_list = add_brand_order_count_data_in_name(brand_name,product_response_list)
    return product_response_list

def paginated_resolve_product_search_pdp(product_name, brand_name, page, _info):
    
    product_list = resolve_pdp_product_search(product_name, brand_name, _info)

    per_page = NumberUtilities.convert_string_to_number(PDP_PER_PAGE)
    start = per_page*(page-1)
    end = per_page*(page)
    if start>len(product_list)-1:
        return []

    if per_page*(page)>len(product_list):
        end = len(product_list)

    return product_list[start:end]

def fetch_count_of_coupons_created_by_brand(brand_ids, start_date, end_date):
    qs = discount_models.Voucher.objects.all()
    count_of_coupons_created_by_brand = 0
    time_utilites = TimeUtilities()
    value = {}
    if start_date:
        value['gte'] = start_date
    else:
        value['gte'] = time_utilites.get_current_month_start().date()
    
    if end_date:
        value['lte'] = end_date
    else:
        value['lte'] = TimeUtilities.get_current_date_time().date()
    
    qs = filter_range_field(qs,"created_at",value)
    
    voucher_filter = {}
    voucher_filter['owner'] = VoucherOwner.BRAND

    if brand_ids is not None:

        local_brand_ids = []
        for brand_id in brand_ids:
            brand_id = NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(brand_id)[1])
            local_brand_ids.append(brand_id)

        voucher_filter['brands__id__in'] = local_brand_ids

    count_of_coupons_created_by_brand = qs.prefetch_related('voucher_brands').filter(**voucher_filter).count()
    
    return count_of_coupons_created_by_brand


def resolve_source_with_zaamo_kpi(root, info, brand_ids, start_date, end_date):
    source_with_zaamo_kpi = {}
    source_with_zaamo_kpi['count_of_coupons_created_by_brand'] = fetch_count_of_coupons_created_by_brand(brand_ids, start_date, end_date)
    return source_with_zaamo_kpi

