from saleor.graphql.analytics.resolvers import order_store_queryset, orderline_store_product_brand_queryset, store_google_analytics_queryset
from saleor.order import FulfillmentStatus
from saleor.order.models import OrderStore
import logging
from saleor.shipping.models import Zipcode
from saleor.store import models as store_models
from django.db.models import F, Q, Case, Sum, Count, Avg, OuterRef, Subquery, FloatField, Func, Value
from django.db.models.functions import Coalesce, Cast
from saleor.product import SourcingRequestStatus
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.conf import settings
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.checkout import models as checkout_models
from saleor.discount import models as discount_models
from saleor.product import models as product_models
from saleor.order import models as order_models
from collections import OrderedDict, defaultdict

from saleor.utilities.time_utilities import TimeUtilities
from datetime import datetime, timedelta                                                                                                                                                            


logger = logging.getLogger(__name__)


class SavedStoreAnalytics:

    help = "Save daily store analytics data"

    def __init__(self, datetime_range=None) -> None:
        if datetime_range:
            self.datetime_range = datetime_range
        elif store_models.StoreAnalytics.objects.last():
            self.datetime_range = {
                    "gte": store_models.StoreAnalytics.objects.last().created_at,
                    "lte": TimeUtilities.get_current_date_time()
                    }
        else:
            self.datetime_range = {
                    "gte": datetime(2022, 1, 4),
                    "lte": TimeUtilities.get_current_date_time()
                    }


    def get_orderstore_queryset(self):
        return OrderStore.objects.select_related("order", "store").filter(
            order__platform_code=PlatformTypeEnum.INFLUENCER_STORE
            )

    def get_order_store_analytics(self):
        datetime_range = self.datetime_range
        order_store_queryset = self.get_orderstore_queryset()
        self.order_store_analytics = order_store_queryset.values("store"
        ).annotate(
            total_store_sales=Coalesce(Sum(F("order__total_net_amount") + F("order__discount_amount"), 
                                    filter=Q(
                                        order__created__gte=datetime_range["gte"]),
                                        order__created__lte=datetime_range["lte"]
                                        ), 0),

            total_store_sales_after_discount=Coalesce(Sum(F("order__total_net_amount"), 
                                        filter=Q(
                                            order__created__gte=datetime_range["gte"],
                                            order__created__lte=datetime_range["lte"]
                                            )
                                            
                                            
                                            ),0),

            total_msp_sales=Coalesce(Sum("order__discount_amount", 
                                    filter=Q(
                                        order__created__gte=datetime_range["gte"],
                                        order__created__lte=datetime_range["lte"]
                                        )
                                            ),0), 

            ).filter(
            Q(total_store_sales__gt=0) | Q(total_store_sales_after_discount__gt=0)| Q(total_msp_sales__gt=0)
            ).values(
                "store", 
                "total_store_sales", 
                "total_store_sales_after_discount",
                "total_msp_sales")

        self.order_store_analytics = list(self.order_store_analytics)
        logger.info(
            "order_store_analytics for date_range :: %s is :: %s ", 
            datetime_range, self.order_store_analytics
        )

        return self.order_store_analytics
    
    def get_store_orderlines_analytics(self):
        datetime_range = self.datetime_range
        order_store_queryset = self.get_orderstore_queryset()

        self.store_orderline_analytics = order_store_queryset.values("store").annotate(
            number_of_products_sold=Sum(
                                        "order__lines__quantity",
                                        filter=Q(
                                                order__created__gte=datetime_range["gte"],
                                                order__created__lte=datetime_range["lte"]
                                                )
                                    )).filter(number_of_products_sold__gt=0).values("store", "number_of_products_sold")
        
        self.store_orderline_analytics = list(self.store_orderline_analytics)
        logger.info(
            "store_orderline_analytics for date_range :: %s  is :: %s ", 
            datetime_range, self.store_orderline_analytics
        )

        return self.store_orderline_analytics
    
    def get_store_analytics(self):
        release_date = datetime(2022, 1, 4)
        qs = store_models.StoreInfo.objects.all()
        store_members = store_models.StoreMemberState.objects.filter(store=OuterRef("store_id")).values('user')
        datetime_range = self.datetime_range

        zipcodes = Zipcode.objects.all().values('pincode','district')
        zipcodes_dict = {zip_c['pincode']: zip_c['district'] for zip_c in zipcodes}

        self.total_orders = qs.annotate(
                                    total_orders=Count('order_store__order__id', distinct=True,
                                        filter=Q(
                                            Q(order_store__created_at__gte=datetime_range["gte"], order_store__created_at__lte=datetime_range["lte"]),
                                            Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),)
                                            )).filter(Q(total_orders__gt=0)).values("id", "total_orders")
        
        
        order_zipcode_qs = qs.filter(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_HOME).order_by('-order_store__order__created').values('id','order_store__order__billing_address__postal_code','order_store__order__billing_address__city')
        self.store_order_city_dict = defaultdict(list)

        for code_order in order_zipcode_qs:
            if len(self.store_order_city_dict[code_order['id']])>=3:
                continue
            
            city_for_order = zipcodes_dict.get(code_order['order_store__order__billing_address__postal_code']) or code_order['order_store__order__billing_address__city']

            if city_for_order:
                self.store_order_city_dict[code_order['id']].append(city_for_order)
                
        self.wishlist_of_products = qs.annotate( wishlist_of_products=Count('wishlist__id', distinct=True,
                                        filter=Q(wishlist__created_at__gte=datetime_range["gte"], wishlist__created_at__lte=datetime_range["lte"])
                                    )).filter(Q(wishlist_of_products__gt=0)).values('id', 'wishlist_of_products')

        self.no_of_sourcing_requests_initiated =  qs.annotate( no_of_sourcing_requests_initiated = Count('product_sourcing__id', distinct=True,
                                                    filter=Q(
                                                            Q(product_sourcing__created_at__gte=datetime_range["gte"], product_sourcing__created_at__lte=datetime_range["lte"]),
                                                            )
                                                    )).filter(Q(no_of_sourcing_requests_initiated__gt=0)).values('id', 'no_of_sourcing_requests_initiated')

        
        self.no_of_sourcing_requests_brand_fullfilled =  qs.annotate( no_of_sourcing_requests_brand_fullfilled = Count('product_sourcing__id', distinct=True,
                                                                    filter=Q(
                                                                            Q(product_sourcing__created_at__gte=datetime_range["gte"], product_sourcing__created_at__lte=datetime_range["lte"]),
                                                                            Q(product_sourcing__status__in=[
                                                                                SourcingRequestStatus.BRAND_COUPON_CREATED,
                                                                                SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_BRAND,SourcingRequestStatus.BRAND_COUPON_CLUBBED
                                                                            ])
                                                                            )
                                                            )).filter(Q(no_of_sourcing_requests_brand_fullfilled__gt=0)).values('id', 'no_of_sourcing_requests_brand_fullfilled')
        
        
        
        self.lines_count = OrderStore.objects.filter(created_at__gte=release_date).select_related(
            "order", "store", "order__user").filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).exclude(order__user__in=Subquery(store_members)).values(
                'store').annotate(
                lines_count=Coalesce(Count('order__lines__id', distinct=True, filter=(
                    Q(created_at__gte=datetime_range["gte"], created_at__lte=datetime_range["lte"])
                )),0)
            ).filter(lines_count__gt=0).values(
                'store', 'lines_count')
        
        
        store_voucher_qs = discount_models.Voucher.objects.filter(store=OuterRef('store_id')).values('id')

        self.resolve_no_of_coupons_used = OrderStore.objects.filter(created_at__gte=release_date).exclude(order__user__in=Subquery(store_members)).values('store').annotate(
            no_of_coupons_used =Coalesce(Count('id', filter=Q(
                Q(order__voucher__in=Subquery(store_voucher_qs)),
                Q(created_at__gte=datetime_range["gte"], created_at__lte=datetime_range["lte"]))),0)).filter(no_of_coupons_used__gt=0).values(
            'store', 'no_of_coupons_used'
        )


        self.resolve_average_abandoned_cart = checkout_models.CheckoutStore.objects.filter(
            created_at__gte=release_date).exclude(token__user__in=Subquery(store_members)).values('store').annotate(
                abandoned_cart_count=Coalesce(Count('token', distinct=True, filter=Q(
                    Q(created_at__gte=datetime_range["gte"], created_at__lte=datetime_range["lte"])
                )),0)).filter(abandoned_cart_count__gt=0).values(
                    'store', 'abandoned_cart_count')


        store_orderline_filter = order_models.OrderLine.objects.filter(created_at__gte=release_date).filter(
            order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).filter(
            order__order_store__store=OuterRef('id'))\
                .exclude(fulfillment_line__fulfillment__status__in = [
                FulfillmentStatus.RETURN_COMPLETED, FulfillmentStatus.RETURN_INITIATED ,
                FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLATION_INITIATED])\
                    .annotate(
                    influencer_commission=Coalesce(Cast(KeyTextTransform('influencer_commission', 'metadata'), FloatField()), 0))\
                        .order_by().values('order__order_store__store')\
                        .annotate(total_influencer_commission = Sum("influencer_commission")).values('total_influencer_commission')[:1]
        

        self.resolve_earnings_and_payouts = qs.annotate(total_earnings = Coalesce(Subquery(store_orderline_filter),0)
                                        ).annotate(total_store_payout=Coalesce(Cast(Sum('store_payout__amount'), output_field=FloatField()),0)).annotate(
                                                    net_payout_due=Coalesce(F('total_earnings')- F('total_store_payout'), 0)).filter(
                                                        ~Q(total_earnings=0) | ~Q(total_store_payout=0) | ~Q(net_payout_due=0)
                                                    ).values('id', 
                                                    'total_earnings',
                                                    'total_store_payout', 
                                                    'net_payout_due'
                
                                            )
        

        last_payout = store_models.StorePayout.objects.filter(store=OuterRef('id')).order_by('-date').values('amount')[:1]

        last_product_added = product_models.CollectionProduct.objects.filter(collection__collection_store__store_id=OuterRef('id'))\
            .order_by('-created_at').values('created_at')[:1]
        
        mobile_no = store_models.StoreMemberState.objects.filter(store=OuterRef('id')).values('user__mobile_no')[:1]
        self.basic_store_details = qs.annotate(
                                                last_payout=Coalesce(Subquery(last_payout), 0)).annotate(
                                                last_product_added= Coalesce(Subquery(last_product_added), Value('2022-01-04 00:51:32.639377+05:30'))).annotate(
                                                mobile_no = Coalesce(Subquery(mobile_no), Value('NULL'))
                                                ).values('id',
                                                    'last_product_added',
                                                    'last_payout',
                                                    'mobile_no')


        
        return None

    def fetch_data(self):
        self.get_order_store_analytics()
        self.get_store_orderlines_analytics()
        self.get_store_analytics()

    def handle(self):
        self.fetch_data()

        bulk_analytics_objects_dict = {}
        
        self.total_orders = list(self.total_orders)
        self.wishlist_of_products = list(self.wishlist_of_products)
        self.no_of_sourcing_requests_initiated = list(self.no_of_sourcing_requests_initiated)
        self.no_of_sourcing_requests_brand_fullfilled = list(self.no_of_sourcing_requests_brand_fullfilled)
        self.store_orderline_analytics= list(self.store_orderline_analytics)
        self.order_store_analytics = list(self.order_store_analytics)
        self.lines_count = list(self.lines_count)
        self.resolve_no_of_coupons_used = list(self.resolve_no_of_coupons_used)
        self.resolve_average_abandoned_cart = list(self.resolve_average_abandoned_cart)
        self.resolve_earnings_and_payouts = list(self.resolve_earnings_and_payouts)
        self.basic_store_details = list(self.basic_store_details)
        self.store_order_city_dict  = self.store_order_city_dict

        for store_id in store_models.StoreInfo.objects.values_list("id", flat=True):

            analytics_obj_dict = {
                store_id: store_models.StoreAnalytics(
                                store_id=store_id, 
                                total_orders=0,
                                total_store_sales_after_discount=0, 
                                wishlist_of_products=0, 
                                no_of_sourcing_requests_initiated=0, 
                                no_of_sourcing_requests_brand_fullfilled=0, 
                                number_of_products_sold=0, 
                                total_store_sales=0, 
                                total_msp_sales=0,
                                orderlines_count=0,
                                no_of_coupons_used=0,
                                abandoned_cart_count=0,
                                total_earnings=0,
                                total_store_payout=0,
                                net_payout_due=0,
                                last_payout=0,
                                mobile_no='',
                                last_product_added='',
                                analytics_date = self.datetime_range['gte'],
                                last_3_order_cities = ', '.join(list(OrderedDict.fromkeys(self.store_order_city_dict.get(store_id,[]))))
                                )
            }

            for store in self.total_orders:
    
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].total_orders = store.get('total_orders')
            
            for store in self.wishlist_of_products:
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].wishlist_of_products = store.get('wishlist_of_products')

            for store in self.no_of_sourcing_requests_initiated:
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].no_of_sourcing_requests_initiated = store.get('no_of_sourcing_requests_initiated')

            for store in self.no_of_sourcing_requests_brand_fullfilled:
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].no_of_sourcing_requests_brand_fullfilled = store.get('no_of_sourcing_requests_brand_fullfilled')
                   
    
            for store in self.store_orderline_analytics:

                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].number_of_products_sold = store.get('number_of_products_sold')
                    
            
            for store in self.order_store_analytics:
    
                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].total_store_sales = store.get('total_store_sales', 0)
                    analytics_obj_dict[store_id].total_store_sales_after_discount = store.get('total_store_sales_after_discount', 0)
                    analytics_obj_dict[store_id].total_msp_sales = store.get('total_msp_sales', 0)
            
            
            for store in self.lines_count:
    
                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].orderlines_count = store.get('lines_count', 0)
            print('after lines_count')
            for store in self.resolve_no_of_coupons_used:
        
                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].no_of_coupons_used = store.get('no_of_coupons_used', 0)
            print('resolve_no_of_coupons_used')
            for store in self.resolve_average_abandoned_cart:
            
                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].abandoned_cart_count = store.get('abandoned_cart_count', 0)
            print('resolve_average_abandoned_cart')
            
            for store in self.resolve_earnings_and_payouts:
        
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].total_earnings = store.get('total_earnings', 0)
                    analytics_obj_dict[store_id].total_store_payout = store.get('total_store_payout', 0)
                    analytics_obj_dict[store_id].net_payout_due = store.get('net_payout_due', 0)
            
            print('resolve_earnings_and_payouts')
            for store in self.basic_store_details:
            
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].last_payout = store.get('last_payout', 0)
                    analytics_obj_dict[store_id].last_product_added = store.get('last_product_added', '')
                    analytics_obj_dict[store_id].mobile_no = store.get('mobile_no', '')


            print('resolve_earnings_and_payouts')       
            
            bulk_analytics_objects_dict.update(analytics_obj_dict)
        store_models.StoreAnalytics.objects.bulk_create(list(bulk_analytics_objects_dict.values()))




def populate_store_analytics(date=datetime(2022, 12, 9)):
    release_date = datetime(2022, 1, 4)
    release_date_end = date-timedelta(microseconds=1)
    date_list = []
    while date<=datetime.now():
        day_start = date
        date = date+timedelta(days=1)
        day_end= date-timedelta(microseconds=1)
        date_list.append((day_start, day_end))

    date_list = [(release_date,release_date_end)] + date_list
    print(date_list)
    for date in date_list:
        obj = SavedStoreAnalytics()
        obj.datetime_range = {
                    "gte": date[0],
                    "lte":date[1]
                    }
        print("-----start------------------########################_______________")
        obj.handle()
        print("---------------------------########################_______________")
        print(date[0])
        print("---------------------------########################_______________")

