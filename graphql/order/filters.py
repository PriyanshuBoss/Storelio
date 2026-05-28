import django_filters
from django.db.models import Sum, IntegerField
from django.db.models.expressions import Q, Subquery, OuterRef

from graphene_django.filter.filterset import GlobalIDMultipleChoiceFilter, GlobalIDFilter
from saleor.graphql.store.enums import PlatformTypeEnums
import graphene
from saleor.graphql.utils import get_nodes, resolve_global_ids_to_primary_keys
from saleor.utilities.time_utilities import TimeUtilities

from ...order.models import Fulfillment, Order, FulfillmentLine
from ..core.filters import EnumFilter, ListObjectTypeFilter, ObjectTypeFilter
from ..core.types.common import DateRangeInput
from ..core.utils import from_global_id_strict_type
from ..payment.enums import PaymentChargeStatusEnum
from ..utils.filters import filter_by_query_param, filter_range_field
from .enums import OrderStatusFilter, TimePeriod, OrderFullfillmentStatusEnum, BrandOrderStatusEnum
from saleor.graphql.analytics.enums import BrandOrderStatus
from saleor.graphql.analytics.resolvers import filter_delayed_orders, filter_ontime_orders
from saleor.store import models as store_models


def filter_payment_status(qs, _, value):
    if value:
        qs = qs.filter(payments__is_active=True, payments__charge_status__in=value)
    return qs

def filter_order_by_brands(qs, _, brands):

    if brands:
        type, brand_ids = resolve_global_ids_to_primary_keys(brands)
        qs = qs.filter(id__in=qs.filter(lines__brand_id__in=brand_ids).values_list('id', flat=True))

    return qs

def filter_by_cod(qs,_,value):

    if not value==None:
        qs = qs.filter(id__in=qs.filter(lines__cod=value).values_list('id', flat=True))
        
    return qs

def filter_by_fk(qs,_,value):

    if value == True:
        qs = qs.filter(id__in=qs.filter(lines__metadata__fake='true').values_list('id', flat=True))
    else:
        qs = qs.exclude(id__in=qs.filter(lines__metadata__fake='true').values_list('id', flat=True))

    return qs

def filter_by_checkout_token(qs, _, value):
    
    if value:
        #checkout_token = graphene.Node.from_global_id(value)[1]
        qs = qs.filter(checkout_token=value)

    return qs

def get_payment_id_from_query(value):
    try:
        return from_global_id_strict_type(value, only_type="Payment", field="pk")
    except Exception:
        return None


def filter_order_by_payment(qs, payment_id):
    if payment_id:
        qs = qs.filter(payments__pk=payment_id)
    return qs

def filter_platform_code(qs, _, value):

    if value:
        qs = qs.filter(platform_code__in=value)
    
    return qs

def filter_status(qs, _, value):
    query_objects = qs.none()

    if value:
        query_objects |= qs.filter(status__in=value)

    if OrderStatusFilter.READY_TO_FULFILL in value:
        # to use & between queries both of them need to have applied the same
        # annotate
        qs = qs.annotate(amount_paid=Sum("payments__captured_amount"))
        query_objects |= qs.ready_to_fulfill()

    if OrderStatusFilter.READY_TO_CAPTURE in value:
        qs = qs.distinct()
        query_objects = query_objects.distinct()
        query_objects |= qs.ready_to_capture()

    return qs & query_objects

def filter_by_search_product(qs,_,value):

    menu_fields = ["lines__product_name"]
    if value:
        qs = filter_by_query_param(qs, value, menu_fields)
    
    return qs
    
def filter_brand_order_status(qs, _, value):

    if BrandOrderStatus.DELAYED in value:
        fulfillment_line = qs.values_list('fulfillments__lines__id', flat=True)
        fulfillment_line_qs = FulfillmentLine.objects.filter(id__in=fulfillment_line)
        delayed = filter_delayed_orders(fulfillment_line_qs).values_list('order_line__order_id', flat=True)
        qs = qs.filter(id__in=delayed)
    
    elif BrandOrderStatus.ON_TIME in value:
        fulfillment_line = qs.values_list('fulfillments__lines__id', flat=True)
        fulfillment_line_qs = FulfillmentLine.objects.filter(id__in=fulfillment_line)
        delayed = filter_ontime_orders(fulfillment_line_qs).values_list('order_line__order_id', flat=True)
        qs = qs.filter(id__in=delayed)

    return qs

def filter_fulfillment_status(qs, _, value):
    if value:
        qs = qs.filter(fulfillments__status__in=value).distinct()
    return qs 


def filter_customer(qs, _, value):
    customer_fields = [
        "user_email",
        "user__first_name",
        "user__last_name",
        "user__email",
    ]
    qs = filter_by_query_param(qs, value, customer_fields)
    return qs


def filter_created_range(qs, _, value):
    return filter_range_field(qs, "created__date", value)

def filter_by_user_email(qs, _, value):
    if value:
        qs = qs.filter(Q(user__email=value) | Q(user_email=value)).distinct()
    return qs

def filter_by_user_mobile_no(qs, _, value):
    if value:
        qs = qs.filter(
            Q(user__mobile_no=value) | Q(shipping_address__phone=value) | Q(billing_address__phone=value)
            ).distinct()
    return qs

def filter_order_search(qs, _, value):
    order_fields = [
        "pk",
        "discount_name",
        "translated_discount_name",
        "user__email",
        "user__mobile_no",
        "shipping_address__phone",
        "billing_address__phone",
        "user__first_name",
        "user__last_name",
        "payments__transactions__searchable_key",
        "user_email"
    ]
    payment_id = get_payment_id_from_query(value)
    if payment_id:
        return filter_order_by_payment(qs, payment_id)

    try:
        order_id  = graphene.Node.from_global_id(value)[1]
        if order_id:
            order_fields = ["pk"]
            return filter_by_query_param(qs, order_id, order_fields, lookup="iexact")
    except Exception as e:
        order_id = None       

    qs = filter_by_query_param(qs, value, order_fields)
    return qs

def filter_by_voucher_startswith(qs, _, value):
    if value:
        qs = qs.filter(voucher__code__startswith=value)
    
    return qs

def filter_by_store(qs, _, stores: list):
    stores = get_nodes(stores, "Store", store_models.StoreInfo)
    return qs.store_orders(stores)

def time_period(qs, _, value, field = "created"):
    time_utilities = TimeUtilities()
    if value:
        if value==TimePeriod.LASTHOUR:
           date_range = {"gte": time_utilities.get_last_hour_date_time()}
           qs = filter_range_field(qs,field, date_range)
        
        elif value==TimePeriod.TODAY: 
            today_start = time_utilities.get_today_start()
            date_range = {"gte": today_start}
            qs = filter_range_field(qs,field, date_range)

        elif value==TimePeriod.YESTERDAY: 
            yesterday_start = time_utilities.get_yesterdays_date()
            today_start = time_utilities.get_today_start()
            date_range = {"gte": yesterday_start, "lte": today_start}
            qs = filter_range_field(qs,field, date_range)

        elif value==TimePeriod.TILLTODAYTHISWEEK: 
            
            this_week_start = time_utilities.get_current_week_start()
            date_range = {"gte": this_week_start}
            qs = filter_range_field(qs,field, date_range)

        elif value==TimePeriod.LASTWEEK: 
            
            last_week_start, last_week_end = time_utilities.get_prev_week_boundaries()
            date_range = {"gte": last_week_start, "lte": last_week_end}
            qs = filter_range_field(qs,field, date_range)

        elif value==TimePeriod.TILLTODAYTHISMONTH: 
            curr_month_start_date = time_utilities.get_current_month_start()
            date_range = {"gte": curr_month_start_date}
            qs = filter_range_field(qs,field, date_range)

        elif value==TimePeriod.LASTMONTH: 
            prev_month_start_date, prev_month_end_date = time_utilities.get_prev_month_boundaries()
            date_range = {"gte": prev_month_start_date, "lte": prev_month_end_date}
            qs = filter_range_field(qs,field, date_range)

        elif value==TimePeriod.OVERALL:
            return qs
    return qs


class DraftOrderFilter(django_filters.FilterSet):
    customer = django_filters.CharFilter(method=filter_customer)
    created = ObjectTypeFilter(input_class=DateRangeInput, method=filter_created_range)
    search = django_filters.CharFilter(method=filter_order_search)
    stores = GlobalIDMultipleChoiceFilter(method=filter_by_store)
    time_period = EnumFilter(
        input_class=TimePeriod, method=time_period
    )

    class Meta:
        model = Order
        fields = ["customer", "created", "search", "stores", "time_period"]


class OrderFilter(DraftOrderFilter):
    payment_status = ListObjectTypeFilter(
        input_class=PaymentChargeStatusEnum, method=filter_payment_status
    )
    status = ListObjectTypeFilter(input_class=OrderStatusFilter, method=filter_status)
    brand_order_status = ListObjectTypeFilter(input_class=BrandOrderStatusEnum, method=filter_brand_order_status)
    platform_code = ListObjectTypeFilter(input_class=PlatformTypeEnums, method=filter_platform_code)
    fulfillment_status = ListObjectTypeFilter(input_class=OrderFullfillmentStatusEnum, method=filter_fulfillment_status)
    customer = django_filters.CharFilter(method=filter_customer)
    created = ObjectTypeFilter(input_class=DateRangeInput, method=filter_created_range)
    search = django_filters.CharFilter(method=filter_order_search)
    email = django_filters.CharFilter(method=filter_by_user_email)
    mobile_no = django_filters.CharFilter(method=filter_by_user_mobile_no)
    voucher_startswith = django_filters.CharFilter(method=filter_by_voucher_startswith)
    brands = GlobalIDMultipleChoiceFilter(method=filter_order_by_brands)
    search_by_product = django_filters.CharFilter(method = filter_by_search_product)
    cod = django_filters.BooleanFilter(method = filter_by_cod)
    fk = django_filters.BooleanFilter(method = filter_by_fk)
    checkout_token = GlobalIDFilter(method = filter_by_checkout_token)

    class Meta:
        model = Order
        fields = ["payment_status", "status", "customer", "created", "search", "stores", "time_period"]

    @property
    def qs(self):
        qs = super().qs
        
        if self.data.get("fulfillment_status") and self.data.get("brands"):
            type, brands = resolve_global_ids_to_primary_keys(self.data.get("brands"))

            qs = qs.filter(fulfillments__status__in=self.data.get("fulfillment_status"), 
                         lines__brand__in=brands)

            qs = qs.annotate(filter_brand_status=Subquery(
                Fulfillment.objects.filter(order_id=OuterRef("id")).filter(
                            Q(lines__order_line__brand_id__in=brands) & 
                            Q(status__in=self.data.get("fulfillment_status"))).values('id')[:1], 
                            output_field=IntegerField()
                        )
                    )
            qs = qs.filter(filter_brand_status__isnull=False)
        
        return qs
