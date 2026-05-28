import datetime
import django
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'saleor.settings'
django.setup()

from django.utils import timezone
from saleor.graphql.analytics.resolvers import order_store_queryset, store_google_analytics_queryset
from saleor.order.models import OrderStore
from saleor.store import models as store_models
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q, Case, Sum, Count, Avg
from saleor.utilities.request_utilities import PlatformTypeEnum
from django.db.models.functions import Coalesce
from saleor.product import SourcingRequestStatus
from django.conf import settings
from saleor.utilities.number_utilities import NumberUtilities

from saleor.utilities.time_utilities import TimeUtilities


class StoreAnalyticsPopulate:

    help = "Save daily store analytics data"

    def __init__(self) -> None:
    
        self.datetime_range = {
                "gte": store_models.StoreAnalytics.objects.last().created_at
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
            total_store_sales=Sum(F("order__total_net_amount") + F("order__discount_amount"), 
                                    filter=Q(
                                        order__created__gte=datetime_range["gte"], 
                                        order__created__lte=datetime_range["lte"])
                                        ),
            total_store_sales_after_discount=Sum(F("order__total_net_amount"), 
                                    filter=Q(
                                        order__created__gte=datetime_range["gte"], 
                                        order__created__lte=datetime_range["lte"])
                                        ),

            total_msp_sales=Sum("order__discount_amount", 
                                    filter=Q(
                                        order__created__gte=datetime_range["gte"], 
                                        order__created__lte=datetime_range["lte"])
                                            ), 

            ).filter(
            Q(total_store_sales__gt=0)| Q(total_store_sales_after_discount__gt=0) | Q(total_msp_sales__gt=0)
            ).values(
                "store", 
                "total_store_sales",
                "total_store_sales_after_discount", 
                "total_msp_sales")

        self.order_store_analytics = list(self.order_store_analytics)

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

        return self.store_orderline_analytics
    
    def get_store_analytics(self):
        qs = store_models.StoreInfo.objects.all()
        datetime_range = self.datetime_range
        self.store_analytics_qs = qs.annotate(
            total_orders=Count('order_store__order__id', distinct=True,
                filter=Q(
                    Q(order_store__created_at__gte=datetime_range["gte"], order_store__created_at__lte=datetime_range["lte"]),
                    Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),)
                    ),

            avg_order_value=Coalesce(
                Avg('order_store__order__total_net_amount',
                    filter=Q(
                        Q(order_store__created_at__gte=datetime_range["gte"], order_store__created_at__lte=datetime_range["lte"]) 
                        & Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE))), 0),

            wishlist_of_products=Count('wishlist__id', distinct=True,
                    filter=Q(wishlist__created_at__gte=datetime_range["gte"], wishlist__created_at__lte=datetime_range["lte"])
                ),
            no_of_sourcing_requests_initiated = Count('product_sourcing__id', distinct=True,
                                    filter=Q(
                                            Q(product_sourcing__created_at__gte=datetime_range["gte"], product_sourcing__created_at__lte=datetime_range["lte"]),
                                            )
                    ),

            no_of_sourcing_requests_brand_fullfilled = Count('product_sourcing__id', distinct=True,
                                    filter=Q(
                                            Q(product_sourcing__created_at__gte=datetime_range["gte"], product_sourcing__created_at__lte=datetime_range["lte"]),
                                            Q(product_sourcing__status__in=[
                                                SourcingRequestStatus.BRAND_COUPON_CREATED,
                                                SourcingRequestStatus.BRAND_COLLAB_APPROVED,
                                                SourcingRequestStatus.BRAND_CONTACT_INFLUENCER
                                            ])
                                            )
                    ),
            
        ).filter(
            Q(total_orders__gt=0) | Q(avg_order_value__gt=0) | Q(wishlist_of_products__gt=0) | 
            Q(no_of_sourcing_requests_initiated__gt=0) | Q(no_of_sourcing_requests_brand_fullfilled__gt=0)).values(
                "id", "total_orders",
                "avg_order_value", "wishlist_of_products", 
                "no_of_sourcing_requests_initiated", "no_of_sourcing_requests_brand_fullfilled")

        self.store_analytics_qs = list(self.store_analytics_qs)
        return self.store_analytics_qs

    def fetch_data(self):
        self.get_order_store_analytics()
        self.get_store_orderlines_analytics()
        self.get_store_analytics()

    def handle(self,analytics_date, **options):
        
        self.fetch_data()
        bulk_analytics_objects_dict = {}
        

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
                                analytics_date = analytics_date
                                )
            }

            for store in self.store_analytics_qs:
    
                if store.get('id') == store_id:
                    analytics_obj_dict[store_id].total_orders = store.get('total_orders')
                    analytics_obj_dict[store_id].wishlist_of_products = store.get('wishlist_of_products')
                    analytics_obj_dict[store_id].no_of_sourcing_requests_initiated = store.get('no_of_sourcing_requests_initiated')
                    analytics_obj_dict[store_id].no_of_sourcing_requests_brand_fullfilled = store.get('no_of_sourcing_requests_brand_fullfilled')
                   
        
            for store in self.store_orderline_analytics:

                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].number_of_products_sold = store.get('number_of_products_sold')
                    
            
            for store in self.order_store_analytics:
    
                if store.get('store') == store_id:
                    analytics_obj_dict[store_id].total_store_sales = store.get('total_store_sales')
                    analytics_obj_dict[store_id].total_store_sales_after_discount = store.get('total_store_sales_after_discount')
                    analytics_obj_dict[store_id].total_msp_sales = store.get('total_msp_sales')

                    
            
            bulk_analytics_objects_dict.update(analytics_obj_dict)


        store_models.StoreAnalytics.objects.bulk_create(list(bulk_analytics_objects_dict.values()))



def get_start(datetime):
        """
        :return: Start Date (YYYY-MM-DD HH:MM:SS): 2021-03-1 00:00:00
        """
        return datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    
def get_end(datetime1):
    """
    :return: End Date (YYYY-MM-DD HH:MM:SS): 2021-03-15 23:59:59
    """
    tomorrow = get_start(datetime1) + datetime.timedelta(days=1)
    return tomorrow - datetime.timedelta(microseconds=1)


def run():
    sdate = datetime.datetime(2022, 1, 4)

    edate = datetime.datetime.now()
    dates = [sdate+datetime.timedelta(days=x) for x in range((edate-sdate).days)]

    
    date_ranges = [(get_start(date), get_end(date))for date in dates]


    for day_start, day_end in date_ranges:

        print((day_start, day_end))

        command = StoreAnalyticsPopulate()
        command.datetime_range = {
            "gte": day_start,
            "lte": day_end,
            }
        analytics_date = day_start  + datetime.timedelta(minutes=1)
        command.handle(analytics_date)
    
    print("done")




run()
print("done")





