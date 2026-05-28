from collections import defaultdict
import math
from django.conf import settings
import graphene
import openpyxl
from io import BytesIO
import re
import csv
import logging
from itertools import zip_longest
from saleor.celeryconf import app
from saleor.discount import VoucherOwner
from saleor.external_services.shopify_service.shopify_impl import ZaamoShopifyImpl
from saleor.product.models import BrandPriceRecord, CollectionProduct, CollectionStore, ReelUpMedia, ReelUpProductMap, SourcingRequest, SourcingRequestStatus, Product, ProductImage, ProductVariant, ZaamoShopifyProductMapping
from saleor.shipping.models import Zipcode
from saleor.store.models import StoreMemberState, StaffStoreMapping
from saleor.utilities.api_client import ApiClient
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.external_services.google_analytics.ga_helper import get_store_visits, set_time_date_ga, get_top_products_by_views, get_product_views
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.graphql.analytics.resolvers import filter_delayed_orders
from saleor.graphql.analytics.enums import BrandOrderStatus
from saleor.order.models import FulfillmentLine, Order, OrderLine, OrderStore, OrderBrandZaamoMapping, Voucher, Fulfillment,OrderLineCashgram
from saleor.brand.models import Brand, BrandEmail, BrandEmailStateEnum, BrandOrderCount, BrandPayout, Arrear, ArrearTypeEnum, BrandShippingData, StaffBrandMapping, Commission, BrandMemberState
from saleor.store.models import StoreInfo, BrandSourcingRequest, StoreBrandSourcingRequestEnum, StorePayout
from saleor.checkout.models import CheckoutLine
from saleor.store.states import PlatformTypeEnum, StoreTypeEnum
from saleor.brand.states import BrandStatusEnum
from saleor.discount.models import Voucher
from django.db.models.aggregates import Sum
from django.db.models import F , DecimalField, Q, FloatField, Value, Subquery, OuterRef, Count, Case, When, IntegerField, DateTimeField
from decimal import Decimal
import datetime
from saleor.order import FulfillmentStatus
from saleor.order.utils import get_brand_order_price_cod_paid, get_orderline_shopify_price, get_shipping_or_cod_charge, get_voucher_discount_for_orderline, get_zaamo_order_line_price,get_taxable_amount
from django.db.models import Max,When
from django.db.models.aggregates import Sum
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Concat, ExtractDay
from saleor.warehouse.models import Stock

logger = logging.getLogger(__name__)

def ZaamoShopifyOrder(start_date, end_date):
    zaamo_impl = ZaamoShopifyImpl()
    response = zaamo_impl.fetch_placed_order_csv(start_date, end_date)
    header = ['zaamo_order_id','zaamo_shopify_order_id','zaamo_shopify_brand_ids','is placed','created_at','product_names','brand_names','brand_source']
    data = [header]
    data.extend(response)

    return data
    

def reel_up_details_by_brand(brand_name=None):
    if brand_name:

        reels_map = ReelUpProductMap.objects.filter(reel_up_media__shopify_store_name=brand_name)
    
    else:
        reels_map = ReelUpProductMap.objects.all()
        
        
    reels_map = reels_map.values('reel_up_media__shopify_store_name','shopify_product_url','product_name','shopify_product_id','shopify_product_slug').annotate(max_modified_date=Max('reel_up_media__updated_at')).order_by('reel_up_media__shopify_store_name','shopify_product_url','product_name','shopify_product_id','shopify_product_slug')
    
    header = ['brand_name', 'product_url', 'product_name','shopify_product_id','slug', 'date_modified']
    data = [header]

    for ins in reels_map:
        row = list(ins.values())
        data.append(row)

    return data

class OrderCsvContext:
    
    order_id_list = []
    order_line_list = []
    order_store_dict = {}
    order_streakorder_dict = {}
    order_line_fulfilment_dict = {}
    order_store_users_dict = {}
    order_id_brand_dict = {}
    postal_code_state_dict = {}
    zaamo_commission = {}
    delayed_orders = set()
    order_brand_cod_count = dict()
    orderline_count = dict()
    query_set = []

    def __init__(self, start_date, end_date, brand_ids=None, store_names=None, exclude_fake=None):
        query_set = OrderLine.objects.select_related('order', 'brand', 'variant', 'order__billing_address', 'order__shipping_address', 'order__voucher', 'order__user').filter(order__created__gte=start_date, order__created__lte=end_date)
        if brand_ids:
            query_set = query_set.filter(brand_id__in=brand_ids)
        if store_names:
            query_set = query_set.filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).filter(order__order_store__store__store_name__in=store_names)
        if exclude_fake:
            query_set = query_set.filter(metadata__fake__isnull=True)

        self.query_set = query_set
        self.order_id_list = list(set(query_set.values_list('order_id', flat=True)))
        self.order_line_list = list(query_set.values_list('id', flat=True))
        self.orderline_count = {order['id']: order['line_count'] for order in Order.objects.filter(id__in=self.order_id_list).values('id').annotate(line_count=Count('lines', distinct=True))}
        self.order_brand_cod_count = {(order['id'], order['lines__brand_id']): order['line_count'] for order in Order.objects.filter(id__in=self.order_id_list).values('id', 'lines__brand_id').annotate(line_count=Count('lines', filter=Q(lines__cod=True), distinct=True))}

        self.prepare_order_store_dict()
        self.prepare_ordeline_fulfilment_dict()
        self.prepare_order_store_users_dict()
        self.prepare_order_id_brand_dict()
        self.prepare_delayed_orders_set()
        self.prepare_zaamo_commission()
        self.prepare_postal_code_state_dict()


    def __del__(self):
        self.order_id_list.clear()
        self.order_line_list.clear()
        self.order_store_dict.clear()
        self.order_streakorder_dict.clear()
        self.order_line_fulfilment_dict.clear()
        self.order_store_users_dict.clear()
        self.order_id_brand_dict.clear()
        self.postal_code_state_dict.clear()
        self.zaamo_commission.clear()
        self.delayed_orders.clear()
        self.order_brand_cod_count.clear()
        self.orderline_count.clear()
        self.query_set = []
        
    def get_queryset(self):
        return self.query_set

    def prepare_postal_code_state_dict(self):
        zipcodes = Zipcode.objects.all().values_list('pincode', 'state')
        self.postal_code_state_dict = {pincode: state for pincode, state in zipcodes}
        
    def prepare_order_store_dict(self):
        order_store_queryset = OrderStore.objects.filter(order__in=self.order_id_list).select_related('store')

        for data in order_store_queryset:

            if data.order_id not in self.order_store_dict:
                self.order_store_dict[data.order_id] = data.store
                self.order_streakorder_dict[data.order_id] = data.streak_order

    def prepare_ordeline_fulfilment_dict(self):

        fulfilment_line_filter = FulfillmentLine.objects.filter(order_line__in= self.order_line_list).select_related('fulfillment')

        for data in fulfilment_line_filter:

            if data.order_line_id not in self.order_line_fulfilment_dict:
                self.order_line_fulfilment_dict[data.order_line_id] = data

    def prepare_order_store_users_dict(self):
        store_id_list = []
        
        for key, value in self.order_store_dict.items():
            store_id_list.append(value.id)

        user_filter = StoreMemberState.objects.filter(store__in=store_id_list)

        for data in user_filter:

            if data.store_id in self.order_store_users_dict.get(data.store_id, []):
                self.order_store_users_dict[data.store_id].append(data.user_id)
            
            else:
                self.order_store_users_dict[data.store_id] = [data.user_id]

    def prepare_order_id_brand_dict(self):
        order_mappings = OrderBrandZaamoMapping.objects.filter(order_line_zaamo__in=self.order_line_list)\
                .values_list("brand__brand_name", "order_line_zaamo_id", "order_id_brand")

        for brand_name, order_line_id, order_id_brand in order_mappings:
            if not brand_name in self.order_id_brand_dict:
                self.order_id_brand_dict[brand_name] = {}
            self.order_id_brand_dict[brand_name][order_line_id] = order_id_brand

    def prepare_delayed_orders_set(self):
        qs = FulfillmentLine.objects.filter(order_line__in=self.order_line_list)
        qs = filter_delayed_orders(qs)
        self.delayed_orders = set(qs.values_list('order_line_id', flat=True))

    def prepare_zaamo_commission(self):
        commission = Commission.objects.all().values_list('brand_id', 'zaamo_commission')
        commission = {brand_id: comm for brand_id, comm in commission}
        self.zaamo_commission = commission

    def get_headers_of_order_for_csv(self):
        return [
            "Date",
            "Timestamp",
            "Brand Name",
            "Product Name",
            "Order Id",
            "Customer Id",
            "Quantity",
            "Customer MSP",
            "MRP",
            "MSP",
            "Final Price Paid",
            "Postpay Brand Payment Due",
            "Shipping Price",
            "Coupon Code",
            "Zaamo_discount_amount",
            "Brand_discount_amount",
            "Influencer Commission",
            "zaamo_commission(setup in commission table)",
            "Customer Name",
            "Customer Email",
            "Customer Phone Number",
            "Store Name",
            "Order Status",
            "Brand Order Status",
            "Store App",
            "Streak Order",
            "Coupon Owner",
            "User is Store Owner",
            "Brand Order ID",
            "Platform Fees",
            "Penalty",
            "COD amount",
            "Is COD",
            "App Code",
            "orderline_id",
            "order_fk",
            "Revenue",
            # "Revenue (with shopify markup)",
            "Order Note",
            "Fulfillment Updated At",
            "is_shopify_order",
            "lost_revenue"
        ]

    def get_orderline_id(seld, orderline_instance):
        return orderline_instance.id
    
    def get_user_id(self,orderline_instance):

        return orderline_instance.order.user_id

    def get_date(self, orderline_instance):
        
        return StringUtilities.convert_number_to_string(
            TimeUtilities.parse_date(orderline_instance.order.created))
    
    def get_brand_discount_amount(self,orderline_instance):

        return orderline_instance.metadata.get("brand_discount_amount",None)

    def get_zaamo_discount_amount(self,orderline_instance):

        return orderline_instance.metadata.get("zaamo_discount_amount",None)

    def get_timestamp(self, orderline_instance):
        return StringUtilities.convert_number_to_string(orderline_instance.order.created)
    
    def get_order_id(self,orderline_instance):
        
        return graphene.Node.to_global_id("Order",orderline_instance.order_id)

    def get_brand_name(self, orderline_instance):

        if orderline_instance.brand:
            return orderline_instance.brand.brand_name
        
        return ""

    def get_product_name(self, orderline_instance):
        return orderline_instance.product_name

    def get_mrp(self, orderline_instance):
        
        if orderline_instance.variant:
            return orderline_instance.variant.cost_price_amount * orderline_instance.quantity

        return 0

    def get_true_msp(self, orderline_instance):

        if orderline_instance.metadata.get('true_msp'):
            unit_msp = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('true_msp'))
            return unit_msp * orderline_instance.quantity

        else:
            return orderline_instance.unit_price_net_amount * orderline_instance.quantity

    def get_msp(self, orderline_instance):
        
        voucher = orderline_instance.order.voucher

        if voucher and voucher.owner ==VoucherOwner.BRAND:
            return self.get_true_msp(orderline_instance)

        return orderline_instance.unit_price_net_amount * orderline_instance.quantity

    def get_shipping_price(self,orderline_instance):
        return orderline_instance.shipping_cost_amount

    def get_shipping_or_cod_charge(self, orderline_instance):
        if StringUtilities.convert_object_to_string(orderline_instance.metadata.get('zaamo_shipping')).lower() == 'true':
            shipping = 0
        else:
            shipping = self.get_shipping_price(orderline_instance)

        is_cod = self.get_if_cod(orderline_instance)
        shipping_or_cod_charge = shipping if not is_cod else self.get_cod_amount(orderline_instance)

        return shipping_or_cod_charge

    def get_final_price_paid(self, orderline_instance):

        line_price_undiscounted = orderline_instance.unit_price_net_amount * orderline_instance.quantity
        line_price_undiscounted+=orderline_instance.shipping_cost_amount
        
        if not orderline_instance.metadata.get('discount_amount'):
            line_discount_amount = get_voucher_discount_for_orderline(orderline_instance).amount
        else:
            line_discount_amount = Decimal(orderline_instance.metadata.get('discount_amount'))

        return "{0:.3f}".format(line_price_undiscounted - line_discount_amount)
    
    def get_is_discounted(self, orderline_instance):
        discount_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('discount_amount'))
        voucher_code = orderline_instance.metadata.get('voucher_code')
        is_discounted = "Yes" if discount_amount and voucher_code else "No"
        return is_discounted
    
    def get_shopify_charge(self, orderline_instance):
        return Decimal(orderline_instance.metadata.get('extra_shopify_charge', '0'))
    
    def get_tax_order_value(self, orderline_instance):
        order_value = self.get_true_msp(orderline_instance) + NumberUtilities.convert_string_to_decimal(self.get_shipping_or_cod_charge(orderline_instance))
        return order_value
    
    def get_order_processed_value(self, orderline_instance):
        order_value = Decimal(0)
        order_value = self.get_orderline_shopify_price(orderline_instance)
        
        order_value = order_value or NumberUtilities.convert_string_to_decimal(self.get_final_price_paid(orderline_instance))
        
        # calculated_shopify_price = NumberUtilities.convert_string_to_decimal(orderline_instance.unit_price_net_amount*orderline_instance.quantity) + NumberUtilities.convert_string_to_decimal(get_shipping_or_cod_charge(orderline_instance)) + NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('extra_shopify_charge', '0')) - NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('discount_amount', '0'))
        
        # unit_price = NumberUtilities.convert_string_to_decimal(orderline_instance.unit_price_net_amount)
        # with_out_calculated_shopify_price = NumberUtilities.convert_string_to_decimal(unit_price*orderline_instance.quantity) + NumberUtilities.convert_string_to_decimal(get_shipping_or_cod_charge(orderline_instance))
        
        # if orderline_instance.cod:
        #     return NumberUtilities.convert_string_to_decimal(calculated_shopify_price)
        # else:
        #     return NumberUtilities.convert_string_to_decimal(with_out_calculated_shopify_price)

        order_value = Decimal(0)
        line_count = self.orderline_count.get(orderline_instance.order_id)
        if line_count > 1:
            order_value = self.get_orderline_shopify_price(orderline_instance)
        else:
            order_value = self.get_order_shopify_price(orderline_instance)

        order_value = order_value or NumberUtilities.convert_string_to_decimal(self.get_final_price_paid(orderline_instance))

        return order_value
    
    def get_orderline_shopify_price(self, orderline_instance):
        shopify_price = self.get_msp(orderline_instance) + Decimal(self.get_shipping_or_cod_charge(orderline_instance)) + Decimal(orderline_instance.metadata.get('extra_shopify_charge', '0')) - Decimal(orderline_instance.metadata.get('discount_amount', '0'))
        return shopify_price
    
    def get_order_shopify_price(self, orderline_instance):
        shopify_price = NumberUtilities.convert_string_to_decimal(orderline_instance.order.metadata.get('zaamo_shopify_order_price', '0.00'))
        return shopify_price

    def get_post_pay_brand_due_amount(self, orderline_instance):
        postpay_amount = 0
        postpay = self.get_if_orderline_postpay(orderline_instance)
        if postpay:
            postpay_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('brand_due_amount', '0'))
        return postpay_amount

    def get_coupon_code(self, orderline_instance):
        
        if orderline_instance.order.voucher:
            return orderline_instance.order.voucher.code

        return ""

    def get_influencer_commission(self, orderline_instance):
        
        if orderline_instance.commission_percentage:
            return orderline_instance.commission_percentage

        return ""
    
    def get_overall_commission(self, orderline_instance):
        influencer_commission = NumberUtilities.convert_string_to_decimal(orderline_instance.commission_percentage or '0')

        zaamo_commission = self.get_zaamo_commission(orderline_instance.brand_id)
        commission = influencer_commission + NumberUtilities.convert_string_to_decimal(zaamo_commission)

        return commission
    
    def get_zaamo_commission(self, brand_id):
        return self.zaamo_commission.get(brand_id)

    def get_customer_name(self, orderline_instance):
        
        customer_name = ""
        
        try:
            customer_name = orderline_instance.order.shipping_address.first_name

        except Exception as e:
            pass
        
        return customer_name

    def get_customer_email(self, orderline_instance):
        
        customer_email = ""
        
        try:
            customer_email = orderline_instance.order.user_email

        except Exception as e:
            pass
        
        return customer_email

    def get_customer_phone_number(self, orderline_instance):
        
        customer_phone_number = ""
        
        try:
            customer_phone_number = orderline_instance.order.user.mobile_no

        except Exception as e:
            pass
        
        return customer_phone_number

    def get_customer_address(self, orderline_instance):
        
        customer_address = ""

        try:
            address = orderline_instance.order.shipping_address
            customer_address = f"{address.street_address_1}\n{address.city}\n{address.postal_code}"
        except Exception as e:
            pass
        
        return customer_address
    
    def get_customer_state(self, orderline_instance):
        state = 'unknown'
        try:
            if orderline_instance.order.billing_address:
                pincode = orderline_instance.order.billing_address.postal_code
            else:
                pincode = orderline_instance.order.shipping_address.postal_code

            state = self.postal_code_state_dict.get(pincode)
        except Exception as e:
            logger.info(f'customer state :: {e} :: orderline id {orderline_instance.id}')

        return state

    def get_store_name(self, orderline_instance):
        
        order_store = self.order_store_dict.get(orderline_instance.order_id)

        if order_store:
            return order_store.store_name

        return ""
    
    def get_if_order_streakorder(self, orderline_instance):

        return self.order_streakorder_dict.get(orderline_instance.order_id)

    def get_order_status(self, orderline_instance):
        
        fulfilment_line = self.order_line_fulfilment_dict.get(orderline_instance.id)

        if fulfilment_line:
            return fulfilment_line.fulfillment.status

        return orderline_instance.order.status

    def get_order_note(self, orderline_instance):
        fulfilment_line = self.order_line_fulfilment_dict.get(orderline_instance.id)

        if fulfilment_line:
            return fulfilment_line.note

        return ''

    def get_order_note_timestamp(self, orderline_instance):
        fulfilment_line = self.order_line_fulfilment_dict.get(orderline_instance.id)

        if fulfilment_line:
            return fulfilment_line.updated_at

        return ''

    def get_brand_order_status(self, orderline_instance):

        if orderline_instance.id in self.delayed_orders:
            return BrandOrderStatus.DELAYED
        else:
            return BrandOrderStatus.ON_TIME

    def get_store_app(self, orderline_instance):
        return orderline_instance.order.platform_code

    def get_quantity(self, orderline_instance):
        return orderline_instance.quantity

    def get_coupon_owner(self, orderline_instance):
        
        if orderline_instance.order.voucher:
            return orderline_instance.order.voucher.owner

        return ""

    def get_if_user_store_owner(self, orderline_instance):
        user_id = orderline_instance.order.user_id
        store = self.order_store_dict.get(orderline_instance.order_id)
        store_users = []
        if store:
            store_users = self.order_store_users_dict.get(store.id, [])
        
        return user_id in store_users

    def get_if_thrift(self, orderline_instance):
        return orderline_instance.brand and orderline_instance.brand.brand_name == 'thrift_brand'

    def get_brand_discount_amount(self, orderline_instance):
        return orderline_instance.metadata.get('brand_discount_amount', '')
    
    def get_brand_pay(self, orderline_instance):
        brand_pay = orderline_instance.metadata.get('brand_due_amount', '0')
        brand_pay = NumberUtilities.convert_string_to_decimal(brand_pay)

        return brand_pay

    def get_if_orderline_postpay(self, orderline_instance):
        postpay = ''
        if orderline_instance.brand and StringUtilities.convert_object_to_string(orderline_instance.brand.metadata.get('postpay')).lower() == 'true':
            status = self.get_order_status(orderline_instance)
            not_delivered = [
                FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS, FulfillmentStatus.SHIPPED
            ]
            postpay_type = orderline_instance.brand.metadata.get('postpay_type', '').lower()
            if postpay_type == 'shipping':
                not_delivered.remove(FulfillmentStatus.SHIPPED)
            if status in not_delivered:
                postpay = True
        return postpay

    def get_if_cod(self, orderline_instance):
        return orderline_instance.cod

    def get_brand_order_id(self, orderline_instance):
        brand_name = self.get_brand_name(orderline_instance)
        return self.order_id_brand_dict.get(brand_name, {}).get(orderline_instance.id, '')

    def get_platform_fees(self,orderline_instance):
        return orderline_instance.metadata.get("platform_fees", 'NA')

    def get_penalty(self,orderline_instance):
        if orderline_instance.metadata.get("penalty"):
            penalty = "Yes"
        else:
            penalty = "No"

        return penalty
    
    def get_cod_amount(self,orderline_instance):

        if orderline_instance.cod:
            cod_lines_same_brand = self.order_brand_cod_count.get((orderline_instance.order_id, orderline_instance.brand_id))
            cod_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('cod_price'))/cod_lines_same_brand
            cod_amount = "{0:.3f}".format(cod_amount)
        else:
            cod_amount = '0'

        return cod_amount

    def get_app_code(self,orderline_instance):
        order_instance = orderline_instance.order
        
        return order_instance.app_code
    
    def get_is_fake(self, orderline_instance):
        return orderline_instance.metadata.get('fake')
    
    
    def get_shopify_order_bool(self, orderline_instance):
        return True if orderline_instance.metadata.get('shopify') else False

    
    def get_lost_revenue_bool(self, orderline_instance):
        order_status = self.get_order_status(orderline_instance)
        return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER, FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)
        
        if order_status in return_or_cancel:
            return True

        return False
    
    def get_revenue(self, orderline_instance):
        order_status = self.get_order_status(orderline_instance)
        return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER, FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)
        
        final_price_paid = NumberUtilities.convert_string_to_float(self.get_final_price_paid(orderline_instance))
        brand_due_amount = NumberUtilities.convert_string_to_float(orderline_instance.metadata.get('brand_due_amount'))
        inf_commission = NumberUtilities.convert_string_to_float(orderline_instance.metadata.get('influencer_commission'))
        
        if self.get_store_name(orderline_instance) == 'zaamo':
            inf_commission = 0
        if orderline_instance.cod or order_status in return_or_cancel:
            final_price_paid = 0

        revenue = final_price_paid - brand_due_amount - inf_commission
            
        return "{0:.3f}".format(revenue)  
    
    def get_shopify_markup_revenue(self, orderline_instance):
        order_status = self.get_order_status(orderline_instance)
        return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER, FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)
        
        order_value = NumberUtilities.convert_string_to_float(self.get_order_processed_value(orderline_instance))
        brand_due_amount = NumberUtilities.convert_string_to_float(orderline_instance.metadata.get('brand_due_amount'))
        inf_commission = NumberUtilities.convert_string_to_float(orderline_instance.metadata.get('influencer_commission'))
        
        if self.get_store_name(orderline_instance) == 'zaamo':
            inf_commission = 0
        if orderline_instance.cod or order_status in return_or_cancel:
            order_value = 0

        revenue = order_value - brand_due_amount - inf_commission
            
        return "{0:.3f}".format(revenue)  
class TaxReport:
    
    order_id_list = []
    order_line_list = []
    order_store_dict = {}
    location_state_dict = {}
    brand_state_dict = {}
    order_line_fulfilment_dict = {}
    order_store_users_dict = {}
    order_id_brand_dict = {}
    delayed_orders = set()
    query_set = []

    def __init__(self, start_date, end_date):
        query_set = OrderLine.objects.select_related('order', 'brand', 'variant', 'order__shipping_address', 'order__voucher', 'order__user').filter(fulfillment_line__updated_at__gte=start_date, fulfillment_line__updated_at__lte=end_date,metadata__fake__isnull=True)
        
        self.query_set = query_set
        self.order_id_list = list(set(query_set.values_list('order_id', flat=True)))
        self.order_line_list = list(query_set.values_list('id', flat=True))
        self.prepare_ordeline_fulfilment_dict()
        self.prepare_order_id_brand_dict()
        self.prepare_location_dict()
        self.prepare_brand_state_dict()
        self.update_tax_data_in_meta()
        query_set = OrderLine.objects.select_related('order', 'brand', 'variant', 'order__shipping_address', 'order__voucher', 'order__user').filter(fulfillment_line__updated_at__gte=start_date, fulfillment_line__updated_at__lte=end_date,metadata__fake__isnull=True)
        self.query_set = query_set

    
    def update_tax_data_in_meta(self):
        to_update = []
        count = 0
        order_lines = self.query_set.exclude(metadata__status__in=['placed','inprocess'])

        for line in order_lines:

            tax_amt, tax = get_taxable_amount(line.metadata.get('status','placed'),line,True)
            line.metadata['taxable_amount'] = tax_amt
            line.metadata['tax'] = tax
            to_update.append(line)
            count+=1

            if count > 500:
                count=0
                OrderLine.objects.bulk_update(to_update,['metadata'])
        
        OrderLine.objects.bulk_update(to_update,['metadata'])


    def get_queryset(self):
        return self.query_set


    def prepare_ordeline_fulfilment_dict(self):

        fulfilment_line_filter = FulfillmentLine.objects.filter(order_line__in= self.order_line_list).select_related('fulfillment')

        for data in fulfilment_line_filter:

            if data.order_line_id not in self.order_line_fulfilment_dict:
                self.order_line_fulfilment_dict[data.order_line_id] = data

    def prepare_order_id_brand_dict(self):
        order_mappings = OrderBrandZaamoMapping.objects.filter(order_line_zaamo__in=self.order_line_list)\
                .values_list("brand__brand_name", "order_line_zaamo_id", "order_id_brand")

        for brand_name, order_line_id, order_id_brand in order_mappings:
            if not brand_name in self.order_id_brand_dict:
                self.order_id_brand_dict[brand_name] = {}
            self.order_id_brand_dict[brand_name][order_line_id] = order_id_brand

    def prepare_location_dict(self):
        zipcodes = Zipcode.objects.filter().only('state', 'pincode', 'country')
        
        for zipcode in zipcodes:
            self.location_state_dict[zipcode.pincode] = zipcode.state

    def prepare_brand_state_dict(self):
        brands = Brand.objects.all()

        for brand in brands:
            if brand.metadata.get('State'):
                self.brand_state_dict[brand.id] = brand.metadata.get('State')

        brand_shippings = BrandShippingData.objects.all().only('home_state_pincode','brand_id')

        for brand_shipping in brand_shippings:
            state = self.location_state_dict.get(brand_shipping.home_state_pincode)

            if state and not self.brand_state_dict.get(brand_shipping.brand_id):
                self.brand_state_dict[brand_shipping.brand_id] = state

    def get_headers_of_order_for_csv(self):
        return [
            "Brand Pay",
            "TDS",
            "Date",
            "Timestamp",
            "Brand Name",
            "Product Name",
            "Order Id",
            "Customer Id",
            "Quantity",
            "Customer MSP",
            "MRP",
            "MSP",
            "Final Price Paid",
            "Postpay Brand Payment Due",
            "Shipping Price",
            "Customer Name",
            "Customer Email",
            "Customer State",
            "Brand State",
            "Brand_GST_number",
            "CGST",
            "SGST/UTGST",
            "IGST",
            "brand status",
            "Order Status",
            "Fulfillment Updated At",
            "Brand Order ID",
            "Orderline ID",
            "is_cod",
            "Brand Pan Number",
            "Brand due amount",
            "Zaamo commission",
            "Influencer commission",
            "extra shopify charge",
            "TAX deducted",
        ]

    def get_orderline_id(seld, orderline_instance):
        return orderline_instance.id
    
    def get_brand_pay(self,orderline_instance):
        brand_pay = orderline_instance.metadata.get('brand_due_amount', '0')
        return NumberUtilities.convert_string_to_decimal(brand_pay)

    def get_customer_state(self,orderline_instance):
        try:

            address = orderline_instance.order.shipping_address or orderline_instance.order.billing_address

            if address and address.country_area:
                return address.country_area
            
            customer_pin = address.postal_code
            return self.location_state_dict.get(customer_pin,'')

        except:
            return ''

    def get_brand_state(self,orderline_instance):
        brand_state = self.brand_state_dict.get(orderline_instance.brand_id,'')

        if not brand_state and orderline_instance.brand_id:
            return orderline_instance.brand.metadata.get('State','')
        
        return brand_state
    
    def get_brand_status(self,orderline_instance):
        
        if orderline_instance.brand:
            return orderline_instance.brand.status

        return ''    

    def get_brand_gst_number(self,orderline_instance):
        if orderline_instance.brand:
            return orderline_instance.brand.metadata.get("GSTIN")
        
        return ''

    def get_taxable_amount(self,orderline_instance):
        
        taxable_amt = orderline_instance.metadata.get('taxable_amount')

        if taxable_amt:
            return NumberUtilities.convert_string_to_decimal(taxable_amt)
        
        placed_or_shipped = (FulfillmentStatus.SHIPPED, 
                FulfillmentStatus.DELIVERED,FulfillmentStatus.INPROCESS)
        
        if orderline_instance.metadata.get('status') not in placed_or_shipped:

            return 0
        
        return NumberUtilities.convert_string_to_decimal(self.get_final_price_paid(orderline_instance))

    def get_is_cod(self,orderline_instance):
        return orderline_instance.cod

    def get_brand_pan_number(self,orderline_instance):
    
        if orderline_instance.brand:
            return orderline_instance.brand.metadata.get('PAN','')
        
        return ''

    def get_cgst(self,orderline_instance):

        if self.get_customer_state(orderline_instance)==self.get_brand_state(orderline_instance):
            taxable_amt = self.get_taxable_amount(orderline_instance)
            return taxable_amt*Decimal(0.005)

        return 0
    
    def get_sgst(self,orderline_instance):
    
        if self.get_customer_state(orderline_instance)==self.get_brand_state(orderline_instance):
            taxable_amt = self.get_taxable_amount(orderline_instance)
            return taxable_amt*Decimal(0.005)

        return 0
    
    def get_igst(self,orderline_instance):

        if self.get_customer_state(orderline_instance)!=self.get_brand_state(orderline_instance):
            taxable_amt = self.get_taxable_amount(orderline_instance)
            return taxable_amt*Decimal(0.01)

        return 0
    
    def get_tax_deducted_bool(self,orderline_instance):
        return orderline_instance.metadata.get('tax',False)

    def get_tds(self,orderline_instance):
        shipped_or_exchange = (FulfillmentStatus.SHIPPED, FulfillmentStatus.DELIVERED, FulfillmentStatus.EXCHANGE_COMPLETED, FulfillmentStatus.EXCHANGE_INITIATED, FulfillmentStatus.EXCHANGE_REQUESTED)

        if orderline_instance.metadata.get('status','placed') not in shipped_or_exchange:
            return 0 
        
        brand_pay = self.get_brand_pay(orderline_instance)
        if brand_pay>0:
            return Decimal(0.01)*self.get_brand_pay(orderline_instance)
        else:
            return abs(Decimal(0.01)*self.get_brand_pay(orderline_instance))

    def get_user_id(self,orderline_instance):

        return orderline_instance.order.user_id

    def get_date(self, orderline_instance):
        
        return StringUtilities.convert_number_to_string(
            TimeUtilities.parse_date(orderline_instance.order.created))
    
    def get_timestamp(self, orderline_instance):
        return StringUtilities.convert_number_to_string(orderline_instance.order.created)
    
    def get_order_id(self,orderline_instance):
        
        return graphene.Node.to_global_id("Order",orderline_instance.order_id)

    def get_brand_name(self, orderline_instance):

        if orderline_instance.brand:
            return orderline_instance.brand.brand_name
        
        return ""

    def get_product_name(self, orderline_instance):
        return orderline_instance.product_name

    def get_mrp(self, orderline_instance):
        
        if orderline_instance.variant:
            return orderline_instance.variant.cost_price_amount * orderline_instance.quantity

        return 0

    def get_true_msp(self, orderline_instance):

        if orderline_instance.metadata.get('true_msp'):
            unit_msp = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('true_msp'))
            return unit_msp * orderline_instance.quantity

        else:
            return orderline_instance.unit_price_net_amount * orderline_instance.quantity

    def get_msp(self, orderline_instance):
        
        voucher = orderline_instance.order.voucher

        if voucher and voucher.owner ==VoucherOwner.BRAND:
            return self.get_true_msp(orderline_instance)

        return orderline_instance.unit_price_net_amount * orderline_instance.quantity

    def get_shipping_price(self,orderline_instance):
        return orderline_instance.shipping_cost_amount

    def get_final_price_paid(self, orderline_instance):

        line_price_undiscounted = orderline_instance.unit_price_net_amount * orderline_instance.quantity
        line_price_undiscounted+=orderline_instance.shipping_cost_amount
        
        if not orderline_instance.metadata.get('discount_amount'):
            line_discount_amount = get_voucher_discount_for_orderline(orderline_instance).amount
        else:
            line_discount_amount = Decimal(orderline_instance.metadata.get('discount_amount'))

        return "{0:.3f}".format(line_price_undiscounted - line_discount_amount)

    def get_post_pay_brand_due_amount(self, orderline_instance):
        postpay_amount = 0
        postpay = self.get_if_orderline_postpay(orderline_instance)

        if postpay:
            postpay_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('brand_due_amount', '0'))
        
        return postpay_amount

    def get_if_orderline_postpay(self, orderline_instance):
        postpay = ''
        if orderline_instance.brand and StringUtilities.convert_object_to_string(orderline_instance.brand.metadata.get('postpay')).lower() == 'true':
            status = self.get_order_status(orderline_instance)
            not_delivered = [
                FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS, FulfillmentStatus.SHIPPED
            ]
            postpay_type = orderline_instance.brand.metadata.get('postpay_type', '').lower()
            if postpay_type == 'shipping':
                not_delivered.remove(FulfillmentStatus.SHIPPED)
            if status in not_delivered:
                postpay = True
        return postpay
    
    def get_customer_name(self, orderline_instance):
        
        customer_name = ""
        
        try:
            customer_name = orderline_instance.order.shipping_address.first_name

        except Exception as e:
            pass
        
        return customer_name

    def get_customer_email(self, orderline_instance):
        
        customer_email = ""
        
        try:
            customer_email = orderline_instance.order.user_email

        except Exception as e:
            pass
        
        return customer_email

    def get_customer_address(self, orderline_instance):
        
        customer_address = ""

        try:
            address = orderline_instance.order.shipping_address
            customer_address = f"{address.street_address_1}\n{address.city}\n{address.postal_code}"
        except Exception as e:
            pass
        
        return customer_address

    def get_order_status(self, orderline_instance):
        
        fulfilment_line = self.order_line_fulfilment_dict.get(orderline_instance.id)

        if fulfilment_line:
            return fulfilment_line.fulfillment.status

        return orderline_instance.order.status


    def get_order_note_timestamp(self, orderline_instance):
        fulfilment_line = self.order_line_fulfilment_dict.get(orderline_instance.id)

        if fulfilment_line:
            return fulfilment_line.updated_at

        return ''
    
    def get_quantity(self, orderline_instance):
        return orderline_instance.quantity

    def get_brand_order_id(self, orderline_instance):
        brand_name = self.get_brand_name(orderline_instance)
        return self.order_id_brand_dict.get(brand_name, {}).get(orderline_instance.id, '')

    def get_brand_due_amount(seld, orderline_instance):
        return orderline_instance.metadata.get('brand_due_amount')

    def get_zaamo_commission(seld, orderline_instance):
        return orderline_instance.metadata.get('platform_fees')
    
    def get_influencer_commission(seld, orderline_instance):
        return orderline_instance.metadata.get('influencer_commission')
    
    def get_extra_shopify_charge(seld, orderline_instance):
        return NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('extra_shopify_charge',0))


class BrandPaymentCsvContext:

    query_set = []
    end_date = TimeUtilities.get_current_date()

    def __init__(self,end_date):
        query_set = Brand.objects.all()
        self.query_set = query_set
        self.end_date = end_date

    def get_queryset(self):
        return self.query_set

    def get_headers_of_upi_payment_for_csv(self):
        return [
            "TransferId",
            "UpiId",
            "Name",
            "Email",
            "Phone",
            "Amount",
            "Remarks",
            "BrandId"
        ]


    def get_headers_of_neft_payment_for_csv(self):
        return [
            "TransferId",
            "BankAccount",
            "IFSC",
            "Name",
            "Email",
            "Phone",
            "Amount",
            "Remarks",
            "BrandId"
        ]
    

    def get_brand_account(self,brand_instance):
        bank_account = brand_instance.bank_accounts.filter(active = True).first()
        ac_number = "=\"" + bank_account.ac_number + "\""
        return ac_number

    def get_ifsc_code(self,brand_instance):
        bank_account = brand_instance.bank_accounts.filter(active = True).first()
        return bank_account.ac_ifsc_code


    def get_brand_name(self,brand_instance):
        id_date = self.end_date.strftime("%d%m")
        brand_name = brand_instance.brand_name
        brand_name = brand_name.replace(' ','_')
        return brand_name+id_date

    
    def get_upi_id(self,brand_instance):
        upi_instance = brand_instance.upi_ids.filter(active = True).first()
        return upi_instance.upi_id
    
    def get_brand_account_holder_name(self,brand_instance):
        bank_account = brand_instance.bank_accounts.filter(active = True).first()
        return bank_account.ac_name

    def get_brand_owner_name(self,brand_instance):
        return brand_instance.brand_contact_name

    def get_brand_email(self,brand_instance):
        brand_email = brand_instance.brand_emails.first()
        if brand_email:
            return brand_email.brand_email
    
    def get_contact_number(self,brand_instance):
        return brand_instance.brand_contact_number
    
    def get_due_amount(self,brand_instance):
        release_date = datetime.datetime(2022, 1, 4)
        final_total_earning = 0
        final_total_payout = 0
        brand_arrear_amount = 0

        total_earning = OrderLine.objects.filter(brand_id=brand_instance.id, order__created__gte=release_date, order__created__lte=self.end_date)\
            .exclude(metadata__brand_due_amount=None)\
                .annotate(brand_due_amount=Cast(KeyTextTransform('brand_due_amount', 'metadata'), FloatField()))\
                    .aggregate(total_due_amount=Sum('brand_due_amount')).get('total_due_amount')
        
        if total_earning:
            final_total_earning = Decimal(total_earning)

        brand_arrear = Arrear.objects.filter(brand_id = brand_instance.id).aggregate(Sum('amount'))
        if brand_arrear.get('amount__sum'):
            brand_arrear_amount = brand_arrear.get('amount__sum')
        
        final_total_earning = final_total_earning + brand_arrear_amount
        
        total_payout = brand_instance.brand_payout.filter(created_at__lte = self.end_date).aggregate(Sum('amount'))

        if total_payout.get('amount__sum'):
            final_total_payout = total_payout.get('amount__sum')

        postpay_amount = Decimal(self.get_postpay_amount(brand_instance))
        due_amount = (final_total_earning - postpay_amount) - final_total_payout

        return round(due_amount,3)

    def get_postpay_amount(self, brand_instance):
        postpay_amount = 0
        if StringUtilities.convert_object_to_string(brand_instance.metadata.get('postpay')).lower() == 'true':
            not_delivered = [
                    FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS, FulfillmentStatus.SHIPPED
                ]
            postpay_type = brand_instance.metadata.get('postpay_type', '').lower()
            if postpay_type == 'shipping':
                not_delivered.remove(FulfillmentStatus.SHIPPED)

            release_date = datetime.datetime(2022, 1, 4)
            postpay_amount = OrderLine.objects.filter(brand_id=brand_instance.id, order__created__gte=release_date, order__created__lte=self.end_date)\
                .filter(fulfillment_line__fulfillment__status__in=not_delivered)\
                    .annotate(brand_due_amount=Cast(KeyTextTransform('brand_due_amount', 'metadata'), FloatField()))\
                    .aggregate(postpay_amount=Coalesce(Sum('brand_due_amount'), 0)).get('postpay_amount')

        return Decimal(postpay_amount)

    def get_remarks(self):
        return "Zaamo pay till {}".format(self.end_date.strftime("%d-%m-%Y"))

class InfluencerPaymentCsvContext:

    query_set = []
    end_date = TimeUtilities.get_current_date()

    def __init__(self,end_date):
        query_set = StoreInfo.objects.prefetch_related('staff_members').filter(store_type =  StoreTypeEnum.INFLUENCER)
        self.query_set = query_set
        self.end_date = end_date

    def get_queryset(self):
        return self.query_set

    def get_headers_of_upi_payment_for_csv(self):
        return [
            "TransferId",
            "UpiId",
            "Name",
            "Email",
            "Phone",
            "Amount",
            "Remarks",
            "StoreId"
        ]


    def get_headers_of_neft_payment_for_csv(self):
        return [
            "TransferId",
            "BankAccount",
            "IFSC",
            "Name",
            "Email",
            "Phone",
            "Amount",
            "Remarks",
            "StoreId"
        ]
    

    def get_influencer_account(self,influencer):
        try:
            bank_account = influencer.bank_accounts.filter(active = True).first()
            ac_number = "=\"" + bank_account.ac_number + "\""
            return ac_number
        except Exception as e:
            return

    def get_ifsc_code(self,influencer):
        try:
            bank_account = influencer.bank_accounts.filter(active = True).first()
            return bank_account.ac_ifsc_code
        except Exception as e:
            return
    
    def get_bank_account_holder_name(self,influencer):
        try:
            bank_account = influencer.bank_accounts.filter(active = True).first()
            return bank_account.ac_name
        except Exception as e:
            return


    def get_store_name(self,store_instance):
        id_date = self.end_date.strftime("%d%m")
        store_name = store_instance.store_name
        store_name.replace(' ','_')
        return store_name+id_date
    
    def get_upi_id(self,influencer):
        try:
            upi_instance = influencer.upi_ids.filter(active = True).first()
            return upi_instance.upi_id
        except Exception as e:
            return
    
    def get_influencer_name(self,user):
        try:
            name = user.get_full_name()
            if not name or name == user.email:
                influencer = user.influencer.first()
                name = influencer.name or influencer.instagram_username
            return name
        except Exception as e:
            return   

    def get_influencer_email(self,user):
        try:
            return user.email
        except Exception as e:
            return   
    
    def get_contact_number(self,user):
        try:
            return user.mobile_no
        except Exception as e:
            return
    
    def get_due_amount(self,store_instance):

        final_total_payout = 0
        total_earning = 0
        release_date = datetime.datetime(2022, 1, 4)
        store_members = store_instance.get_store_authorized_users()
        orderlines = OrderLine.objects.select_related(
        "variant__product__brand").prefetch_related("order__order_store").filter(order__created__gte=release_date, order__created__lte = self.end_date).values(
        'variant__product__brand',"variant__product__brand__brand_name", "order__order_store__store", "order_id", "quantity", "unit_price_net_amount", "shipping_cost_amount",
        "unit_price_gross_amount", "variant_id", "id", "commission_percentage", "order__created", "metadata")

        final_orderlines = orderlines.exclude(order__user__in=store_members).filter(
                            order__order_store__store=store_instance.id).exclude(
                            fulfillment_line__fulfillment__status__in = [FulfillmentStatus.RETURN_COMPLETED,  
                            FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED,  
                            FulfillmentStatus.CANCELLATION_INITIATED])

        for line in final_orderlines:

            total_earning += Decimal(line["metadata"].get("influencer_commission", 0))


        total_payout = store_instance.store_payout.filter(created_at__lte = self.end_date).aggregate(Sum('amount'))

        if total_payout.get('amount__sum'):
            final_total_payout = total_payout.get('amount__sum')

        due_amount = total_earning-final_total_payout

        return round(due_amount,0)

    def get_remarks(self):
        return "Zaamo pay till {}".format(self.end_date.strftime("%d-%m-%Y"))


class StoreGMVCsvContext:

    def __init__(self, days) -> None:
        
        self.today_date = TimeUtilities.get_current_date_time()
        
        brand_related_request_status = [    SourcingRequestStatus.BRAND_COLLAB_APPROVED,
                                            SourcingRequestStatus.BRAND_COUPON_CREATED,
                                            SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_BRAND]
        zaamo_related_request_status = [    SourcingRequestStatus.ZAAMO_COUPON_CREATED, 
                                            SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_ZAAMO]
        
        self.queryset = StoreInfo.objects.filter(store_type=StoreTypeEnum.INFLUENCER)\
            .annotate(product_last_added=Subquery(
                CollectionProduct.objects.filter(collection__collection_store__store_id=OuterRef('id')).order_by('-created_at').values_list('created_at', flat=True)[:1], 
                output_field=DateTimeField()))\
            .annotate(total_sourcing_requests=Count('product_sourcing'))\
            .annotate(total_brand_related_sourcing=Count('product_sourcing', filter=Q(product_sourcing__status__in=brand_related_request_status)))\
            .annotate(total_zaamo_related_sourcing=Count('product_sourcing', filter=Q(product_sourcing__status__in=zaamo_related_request_status)))\
            .annotate(instagram=Subquery(StoreMemberState.objects.filter(store_id=OuterRef('id')).values_list('user__influencer__instagram_link', flat=True)[:1]))\
            .annotate(user_last_login=Subquery(StoreMemberState.objects.filter(store_id=OuterRef('id')).values_list('user__last_login', flat=True)[:1]))\
            .prefetch_related('staff_store_mappings__user').select_related('actions').order_by('-id')

        self.sourcing_requests_status_count = self.prepare_sourcing_requests_status_count()

        self.brands_interested = self.prepare_brands_interested()

        self.overall_gmv = self.prepare_overall_gmv()

        self.n_days_gmv = self.prepare_n_days_gmv(days)

    def get_queryset(self):
        return self.queryset

    def get_headers_of_store_gmv_for_csv(self):
        
        return ["store_name","store_managers","last_product_added_timestamp","gmv_past_7_days_IS",
                "gmv_overall_store_IS", "gmv_past_7_days_IH", "gmv_overall_store_IH", "status", "next_actions", 
                "visits_1_to_3_days", "visits_4_to_10_days", "visits_11_to_40_days", "visits_before_40_days",
                "total_sourcing_requests", "count_of_brand_related_requests", "count_of_zaamo_related_requests",
                "Request Received", "Brand Shared Deliverables", "Brand Will Contact the Influencer", 
                "Brand Collaboration Approved", "Brand Coupon Created", "Brand Not Interested", "Zaamo Will Fulfill Request",
                "Zaamo Coupon Created", "Zaamo Not Interested", "Influencer Content Created For Zaamo",
                "Influencer Content Created For Brand", "Product exchange or return Requested", "Request Cancelled By Influencer", 
                "Brand Interested In Influencer",
                "instagram_link",
                "store_barter",
                "Stop Source With Zaamo",
                "days_since_sign_up",
                "Last IH Login Timestamp"
                ]
    
    def prepare_sourcing_requests_status_count(self):
        sourcing_requests_qs = SourcingRequest.objects.filter(store__store_type=StoreTypeEnum.INFLUENCER).values('store_id', 'status').order_by('store_id', 'status')\
            .annotate(count=Count('id')).values_list('store_id', 'status', 'count')
        
        sourcing_requests_status_count = dict()
        for store_id, status, count in sourcing_requests_qs:
            if not store_id in sourcing_requests_status_count:
                sourcing_requests_status_count[store_id] = dict()
            sourcing_requests_status_count[store_id][status] = count
        
        return sourcing_requests_status_count

    def prepare_brands_interested(self):
        brands_interested_qs = BrandSourcingRequest.objects.filter(store__store_type=StoreTypeEnum.INFLUENCER).values('store_id').order_by('store_id')\
            .annotate(count=Count('id', filter=Q(state__in=[StoreBrandSourcingRequestEnum.REQUEST_RECEIVED, StoreBrandSourcingRequestEnum.ACCEPT])))\
                .values_list('store_id', 'count')
        
        brands_interested = dict()
        for store_id, count in brands_interested_qs:
            brands_interested[store_id] = count

        return brands_interested

    def prepare_overall_gmv(self):
        gmv_queryset = Order.objects.filter(order_store__store__store_type=StoreTypeEnum.INFLUENCER).values('order_store__store_id', 'platform_code')\
            .order_by('order_store__store_id', 'platform_code')\
            .annotate(total_gmv=Sum(F("total_net_amount") + F("discount_amount"))).values_list('order_store__store_id', 'platform_code', 'total_gmv')
        
        overall_gmv = dict()
        for store_id, platform, gmv in gmv_queryset:
            if not store_id in overall_gmv:
                overall_gmv[store_id] = dict()
            overall_gmv[store_id][platform] = gmv

        return overall_gmv

    def prepare_n_days_gmv(self, days):
        days = NumberUtilities.convert_string_to_number(days)
        created_at = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(), days=days)
        queryset = Order.objects.filter(created__gt=created_at, order_store__store__store_type=StoreTypeEnum.INFLUENCER).values('order_store__store_id', 'platform_code')\
                .order_by('order_store__store_id', 'platform_code')\
            .annotate(total_gmv=Sum(F("total_net_amount") + F("discount_amount"))).values_list('order_store__store_id', 'platform_code', 'total_gmv')
        
        n_days_gmv = dict()
        for store_id, platform, gmv in queryset:
            if not store_id in n_days_gmv:
                n_days_gmv[store_id] = dict()
            n_days_gmv[store_id][platform] = gmv

        return n_days_gmv

    def get_store_name(self, store_instance):
        return store_instance.store_name
    
    def get_store_status(self, store_instance):
        if hasattr(store_instance, "actions"):
            return store_instance.actions.status
        return ''
    
    def get_store_next_actions(self, store_instance):
        if hasattr(store_instance, "actions"):
            return store_instance.actions.next_actions
        return ''
    
    def get_store_managers(self, store_instance):
        store_managers = ""
        user_filters = store_instance.staff_store_mappings.all()
  
        for data in user_filters:
            store_managers = store_managers + data.user.email + ", "
        
        return store_managers


    def get_last_product_added_timestamp(self, store_instance):
            
        return store_instance.product_last_added


    def get_n_days_gmv(self, store_instance, platform_code='IS'):
        
        return self.n_days_gmv.get(store_instance.id, {}).get(platform_code, 0)
        

    def get_overall_gmv(self, store_instance, platform_code='IS'):
        
        return self.overall_gmv.get(store_instance.id, {}).get(platform_code, 0)

    def get_store_visits(self, store_ids):
        release_date = datetime.datetime(2022, 1, 4)
        today = TimeUtilities().get_today_start()
        
        lt = TimeUtilities.parse_date(today, date_format="%Y-%m-%d")
        gte = TimeUtilities.parse_date(TimeUtilities.subtract_time_from_timestamp(today, days=3), date_format="%Y-%m-%d")
        visits_1_to_3_days = {store['_id']: store['visits'] for store in get_store_visits(store_ids, gte, lt)}

        lt = TimeUtilities.parse_date(TimeUtilities.subtract_time_from_timestamp(today, days=3), date_format="%Y-%m-%d")
        gte = TimeUtilities.parse_date(TimeUtilities.subtract_time_from_timestamp(today, days=10), date_format="%Y-%m-%d")
        visits_4_to_10_days = {store['_id']: store['visits'] for store in get_store_visits(store_ids, gte, lt)}

        lt = TimeUtilities.parse_date(TimeUtilities.subtract_time_from_timestamp(today, days=11), date_format="%Y-%m-%d")
        gte = TimeUtilities.parse_date(TimeUtilities.subtract_time_from_timestamp(today, days=40), date_format="%Y-%m-%d")
        visits_11_to_40_days = {store['_id']: store['visits'] for store in get_store_visits(store_ids, gte, lt)}

        lt = TimeUtilities.parse_date(TimeUtilities.subtract_time_from_timestamp(today, days=40), date_format="%Y-%m-%d")
        gte = TimeUtilities.parse_date(release_date, date_format="%Y-%m-%d")
        visits_before_40_days = {store['_id']: store['visits'] for store in get_store_visits(store_ids, gte, lt)}
        
        store_visits = {
            'visits_1_to_3_days': visits_1_to_3_days,
            'visits_4_to_10_days': visits_4_to_10_days,
            'visits_11_to_40_days': visits_11_to_40_days,
            'visits_before_40_days': visits_before_40_days,
        }

        return store_visits

    def get_total_sourcing_requests(self, store_instance):
        
        return store_instance.total_sourcing_requests
    
    def get_count_of_brand_related_requests(self, store_instance):
        
        return store_instance.total_brand_related_sourcing
    
    def get_count_of_zaamo_related_requests(self, store_instance):
        
        return store_instance.total_zaamo_related_sourcing

    def get_store_sourcing_requests_status_count(self, store_instance):
        
        return self.sourcing_requests_status_count.get(store_instance.id, {})
    
    def get_brand_interested_in_influencer(self, store_instance):
        
        return self.brands_interested.get(store_instance.id, 0)

    def get_store_barter(self, store_instance):

        return store_instance.metadata.get('store_barter', False)

    def get_stop_source_with_zaamo(self, store_instance):

        return not store_instance.metadata.get('store_barter',False)
        
    def get_instagram_link(self, store_instance):

        return store_instance.instagram

    def get_user_last_login(self, store_instance):
        
        return store_instance.user_last_login
        
    def get_days_since_sign_up(self, store_instance):

        store_create_date = store_instance.created_at

        return (self.today_date-store_create_date).days

class BrandPriceRecordCSV:
    
    query_set = []

    def __init__(self, start_date):

        query_set = BrandPriceRecord.objects.filter(updated_at__gte=start_date)

        if query_set:
            self.query_set = query_set

    def get_query_set(self):
        return self.query_set
    
    def get_headers_for_brand_price_record(self):
        return [
                'brand_name',
                'product_name',
                'variant_name',
                'is_published',
                'data_source',
                'current_cost_price',
                'current_selling_price',
                'prev_cost_price',
                'prev_selling_price',
                'updated_at'
                ]

class SourcingRequestCSV:

    queryset = []
    sourcing_delivery_date = {}

    def __init__(self, start_date, end_date):
        queryset = SourcingRequest.objects.all()
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)

        if queryset:
            self.queryset = queryset
            self.sourcing_delivery_date = self.prepare_sourcing_delivery_date()
            self.store_last_order_city = self.prepare_store_last_order_city()
            self.sheeko_data, self.store_username = self.prepare_sheeko_data()

    def get_queryset(self):
        return self.queryset

    @staticmethod
    def get_headers():
        return [
           "Sourcing Request Id","Store", "Influencer Managers", "Product", "Variant", "Brand", "Brand Managers", "Status", "Store Status", "Content", 
            "Stop Source with Zaamo","Availability", "Delivery Date", "Days Since Products Delivered", "Created at", "Updated at", "Recommended", "Order Status", "Order CreatedAt", "City",
            "Influencer Notes", "Barter Guidelines", "Sheeko O1", "Sheeko status", "Sheeko text 1", "Sheeko text 2", "Sheeko date"
        ]

    @staticmethod
    def get_header_field_mapping():
        return {
            "Sourcing Request Id":              'id',
            "Store":                            'store__store_name', 
            "Influencer Managers":              'influencer_managers', 
            "Product":                          'product__name', 
            "Variant":                          'variant__name', 
            "Brand":                            'brand__brand_name', 
            "Brand Managers":                   'brand_managers', 
            "Status":                           'status', 
            "Store Status":                     'store__actions__status', 
            "Content":                          'content',
            "Stop Source with Zaamo":           'store__metadata__store_barter', 
            "Availability":                     'store__metadata__store_barter',
            "Delivery Date":                    'delivery_date', 
            "Days Since Products Delivered":    'days_since_products_delivered', 
            "Created at":                       'created_at', 
            "Updated at":                       'updated_at',
            "Recommended":                      'recommend',
            "Order Status":                     'order_status',
            "Order CreatedAt":                  'order_created_at',
            "City":                             'city',
            "Influencer Notes":                 'store__metadata__influencer_notes',
            "Barter Guidelines":                'store__metadata__barter_guidelines',
            "Sheeko O1":                        'sheeko_owner1',
            "Sheeko status":                    'sheeko_status',
            "Sheeko text 1":                    'sheeko_text_1',
            "Sheeko text 2":                    'sheeko_text_2',
            "Sheeko date":                      'sheeko_date'
        }

    @staticmethod
    def prepare_sourcing_delivery_date():
        vouchers = Voucher.objects.filter(code__startswith='SZ_')\
                .annotate(status=F('+__fulfillments__status'), delivery_date=F('+__fulfillments__updated_at'))\
                .filter(status=FulfillmentStatus.DELIVERED).values('code', 'delivery_date')
        
        code_date = {}
        for voucher in vouchers:
            codes = voucher['code'].split('_')[1:]
            for code in codes:
                code_date[code] = voucher['delivery_date']
        
        return code_date
    
    def prepare_store_last_order_city(self):
        store_ids = self.queryset.values_list('store_id', flat=True).distinct()
        qs = StoreInfo.objects.filter(id__in=store_ids).values_list('store_name', 'order_store__order__billing_address__city').order_by('store_name', '-order_store__order__created').distinct('store_name')        
        cities = dict()
        for store_name, city in qs:
            cities[store_name] = city
        return cities
    
    def prepare_sheeko_data(self):
        stores = self.queryset.values_list('store__store_name', 'store__metadata__sheeko_influencer_info').distinct()
        usernames = list()
        store_username = dict()
        for store_name, info_link in stores:
            if info_link:
                username = info_link.split('name=')[-1]
                usernames.append(username)
                store_username[store_name] = username

        url = 'https://www.sheeko.in/support/creators/info'
        api_client = ApiClient(url=url)
        
        sheeko_data = dict()
        max_count = 100000
        limit = 5000
        for offset in range(0, max_count, limit):
            api_client.body = {'usernames': usernames, 'offset': offset, 'limit': limit}
            api_client.post()
            data = api_client.fetch_response().get('data', {})
            sheeko_data.update(data)
            
            if len(data.keys()) < limit:
                break
        return sheeko_data, store_username

    def get_sheeko_data(self, store_name):
        username = self.store_username.get(store_name)
        if username:
            return self.sheeko_data.get(username, {})
        return {}
    
    def get_order_delivery_date(self, sourcing_id):
        return self.sourcing_delivery_date.get(StringUtilities.convert_number_to_string(sourcing_id))

    def get_last_order_city(self, store_name):
        return self.store_last_order_city.get(store_name)

    def get_days_since_products_delivered(self, sourcing_id):
        days = ''
        current_datetime = TimeUtilities.get_current_date_time()
        
        delivery_date = self.get_order_delivery_date(sourcing_id)
        if delivery_date:
            days = (current_datetime - delivery_date).days
        
        return days

class BrandSourcingRequestCSV:

    queryset = []

    def __init__(self, start_date, end_date):
        queryset = BrandSourcingRequest.objects.all()
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lt=end_date)

        if queryset:
            self.queryset = queryset.values('id', 'store__store_name', 'brand__brand_name', 'terms_and_conditions', 'campaign_name', 
                        'brand_collab', 'brand_managers', 'state', 'store_bucket', 'store_managers', 'created_at', 'created_by__email')

    def get_queryset(self):
        return self.queryset
    
    @staticmethod
    def get_headers():
        return ['Brand Sourcing Request ID', 'Store Name', 'Brand Name', 'Terms and Conditions', 'Campaign Name', 
                'Brand Collab', 'Brand Managers', 'State', 'Store Bucket', 'Store Managers', 'Created At', 'Created By']

    @staticmethod
    def get_header_field_mapping():
        return {
            "Brand Sourcing Request ID":    "id", 
            "Store Name":                   "store__store_name", 
            "Brand Name":                   "brand__brand_name", 
            "Terms and Conditions":         "terms_and_conditions", 
            "Campaign Name":                "campaign_name", 
            "Brand Collab":                 "brand_collab", 
            "Brand Managers":               "brand_managers", 
            "State":                        "state", 
            "Store Bucket":                 "store_bucket", 
            "Store Managers":               "store_managers", 
            "Created At":                   "created_at", 
            "Created By":                   "created_by__email"
        }

class BrandManagerCSVhelper:
    
    def update_pending_delvery_count_for_brand_list(self):

        self.brand_count_of_pending_delivery_IS = dict()
        self.brand_count_of_pending_delivery_IH = dict()
        self.zaamo_order_count_30_days = dict()
        self.zaamo_order_count_7_days = dict()
        self.zaamo_order_count_1_day = dict()
        self.brandshippingdata_details = dict()
        self.brandshippingwarehouse = dict()
        self.placed_or_in_process_order_count = dict()
        
        pending_delivery_IH = OrderLine.objects.filter(created_at__gte=TimeUtilities.get_n_days_before_date(90),order__platform_code='IH').exclude(metadata__status__in=[FulfillmentStatus.DELIVERED,FulfillmentStatus.SHIPPED]).exclude(metadata__fake='true',metadata__fake__isnull=False).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))

        for pd in pending_delivery_IH:
            self.brand_count_of_pending_delivery_IH[pd['brand_id']] = pd['order_counts']

        pending_delivery_IS = OrderLine.objects.filter(created_at__gte=TimeUtilities.get_n_days_before_date(90),order__platform_code='IS').exclude(metadata__status__in=[FulfillmentStatus.DELIVERED,FulfillmentStatus.SHIPPED]).exclude(metadata__fake='true',metadata__fake__isnull=False).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))
        
        for pd in pending_delivery_IS:
            self.brand_count_of_pending_delivery_IS[pd['brand_id']] = pd['order_counts']

        brandshippingdata = BrandShippingData.objects.all()

        for i in brandshippingdata:
            self.brandshippingdata_details[i.brand_id]=i

        zip_codes =Zipcode.objects.all()

        for i in zip_codes:
            self.brandshippingwarehouse[i.pincode]=i.city

        
        order_30_days = OrderLine.objects.filter(created_at__gte=TimeUtilities.get_n_days_before_date(30)).exclude(metadata__fake='true',metadata__fake__isnull=False).filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))

        self.zaamo_order_count_30_days = {oc['brand_id']:oc['order_counts'] for oc in order_30_days}

        
        order_7_days = OrderLine.objects.filter(created_at__gte=TimeUtilities.get_n_days_before_date(7)).exclude(metadata__fake='true',metadata__fake__isnull=False).filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))

        self.zaamo_order_count_7_days = {oc['brand_id']:oc['order_counts'] for oc in order_7_days}

        
        order_1_days = OrderLine.objects.filter(created_at__gte=TimeUtilities.get_n_days_before_date(1)).exclude(metadata__fake='true',metadata__fake__isnull=False).filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))

        self.zaamo_order_count_1_day = {oc['brand_id']:oc['order_counts'] for oc in order_1_days}

        placed_or_in_process = OrderLine.objects.filter(metadata__status__in=[FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS]).exclude(metadata__fake='true', metadata__fake__isnull=False).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))
        self.placed_or_in_process_order_count = {oc['brand_id']:oc['order_counts'] for oc in placed_or_in_process}

    @staticmethod
    def get_headers_for_brand_price_record():
        return [
                'brand_name',
                'product_name',
                'variant_name',
                'data_source',
                'current_selling_price',
                'prev_selling_price',
                'drop_percentage',
                'updated_at',
                'stores_count',
                'stores_with_same_brand_category',
                'brand_status'
                ]
    
    @staticmethod
    def get_headers_for_brand_discount_coupon_csv():
        return [
                'brand_name', 
                'brand_source', 
                'code', 
                'value', 
                'discount_type',
                'free_shipping',
                'minimum_order_amount',
                'product_names',
                'starts_at',
                'expires_at',
                'limitPerCustomer',
                'usageLimit'
                ]
    

    @staticmethod
    def get_headers_for_new_product_csv():
        return [
                'brand_name',
                'product_name',
                'variant_name',
                'data_source',
                'msp',
                'mrp',
                'is_published',
                'stock',
                'stores_with_same_brand_category',
                'brand_status'
                ]
    
    @staticmethod
    def get_headers_for_unpublish_product_csv():
        return [
                'brand_name',
                'product_name',
                'in_zaamo',
                'sales_count',
                'sales_count_last_month',
                'date',
                'brand_status'
                ]
    

    @staticmethod
    def get_headers_for_oos_product_csv():
        return [
                'brand_name',
                'product_name',
                'minimum variant price',
                'is_published',
                'publication date',
                'stock_last_updated',
                'brand_status'
                ]

    @staticmethod
    def get_headers_for_brand_uncategorized_csv():
        return [
                'product_name',
                'brand_name',
                'brand_source',
                'category_name',
                'publication_date',
                'brand_status'
                ]

    @staticmethod
    def fetch_brand_orders_count(brand, days=1):
        time_range = TimeUtilities.get_n_days_before_date(days=days)
        
        return OrderLine.objects.filter(brand=brand, order__created__gte=time_range).exclude(metadata__fake='true',metadata__fake__isnull=False).count()

    @staticmethod
    def fetch_count_of_sourcing_request_received(brand):
        
        time_range = TimeUtilities.get_n_days_before_date(days=30)
        sourcing_request_received_count = SourcingRequest.objects.filter(
            brand=brand,
            status=SourcingRequestStatus.REQUEST_RECIEVED,
            created_at__gte=time_range
        ).count()
        
        return sourcing_request_received_count

    # @staticmethod
    # def fetch_count_of_influencer_shared_deliverables(brand):
    #     influencer_shared_deliverables_count = SourcingRequest.objects.filter(
    #         brand=brand,
    #         status=SourcingRequestStatus.INFLUENCER_HAS_SHARED_THE_DELIVERABLES 
    #     ).count()
        
    #     return influencer_shared_deliverables_count

    # @staticmethod
    # def fetch_count_of_pending_delivery(brand):
    #     order_lines = OrderLine.objects.filter(
    #         Q(metadata__status__in=[
    #             FulfillmentStatus.PLACED,
    #             FulfillmentStatus.SHIPPED,
    #             FulfillmentStatus.INPROCESS
    #         ]) & Q(metadata__voucher_code__startswith='SZ_'),
    #         brand_id=brand.id
    #     ).distinct('order_id').order_by('order_id').values('metadata__voucher_code', 'order_id')
        
    #     sourcing_request_ids = []

    #     for order_line in order_lines:
    #         sourcing_voucher_code = order_line.get('metadata__voucher_code').split('_')
    #         for sourcing_id in sourcing_voucher_code:
    #             if sourcing_id != 'SZ':
    #                 if not sourcing_id in sourcing_request_ids:
    #                     source_id_int = NumberUtilities.convert_string_to_number(re.sub(",","",sourcing_id))

    #                     if not source_id_int:
    #                         continue

    #                     sourcing_request_ids.append(re.sub(",","",sourcing_id))
                        
    #     sourcing_request = SourcingRequest.objects.filter(
    #         id__in = sourcing_request_ids,
    #         status = SourcingRequestStatus.BRAND_COUPON_CREATED
    #     )
        
    #     return sourcing_request.count()

    @staticmethod
    def get_headers_for_brand_list_csv():
        return [
                'brand_name',
                'active',
                'importance',
                'cod',
                'has_shopify_product_active_in',
                'number_of_active_products_in_shopify',
                'instagram_link',
                'content_tagging',
                'total_commission',
                'brand_barter',
                'brand_barter_guidelines',
                'too_many_orders',
                'delayed_orders',
                'order note empty (delayed_orders)',
                'orders_yesterday',
                'orders_7_days',
                'orders_30_days',
                'count_of_sourcing_request_received',
                'count_of_pending_delivery_IH',
                'count_of_pending_delivery_IS',
                'last_app_login',
                'shipping_policy',
                'return_policy',
                'shipping_days',
                'shipping_cost_same_state',
                'shipping_cost_other_state',
                'free_shipping',
                'quick_ship',
                'quality_assured',
                'city_of_warehouse',
                'last_updated_barter_status',
                'step_active',
                'brand_owner',
                'history_notes',
                'brand_source',
                'postpay_type',
                'pending_amount',
                'placed_or_in_process_order_count',
                'pending_amount + postpay_amount',
                'brand_last_month_order_count'
                ]

    @staticmethod
    def get_headers_for_brand_shopify_active_csv():
        return [
                'brand_name',
                'status',
                'cod',
                'has_shopify_product_active_in',
                'brand_source'
                ]

    @staticmethod
    def get_headers_for_brand_validation_csv():
        return [
                'brand_name',
                'brand_source',
                'are_keys_valid',
                'write_order_permission',
                'order_count_last_30_days',
                'status',
                'total_zaamo_orders',
                'brand_last_week_order_count',
                'history_notes'
                ]
    
    @staticmethod
    def get_headers_for_brand_collection_csv():
        return [
                'brand_name',
                'collection',
                'product_count',
                'brand_status',
                'type',
                'created_at',
                'updated_at',
                'collection_link'
                ]

    @staticmethod
    def create_attachment_dict_for_email(filename,base_encoded_file):
        return {"content": base_encoded_file, "type": "application/csv", "filename": f"{filename}.csv"}
    
    @staticmethod
    def brand_owner_brand_list_csv(brand_obj_list, return_rows=False):
        rows = defaultdict(list)
        exportrows = []
        exportrows.append(BrandManagerCSVhelper.get_headers_for_brand_list_csv())
        brands = Brand.objects.filter(id__in=brand_obj_list)

        brand_owners = defaultdict(list)
        brand_owners_qs = brands.values_list('id', 'staff_brand_mappings__user__email')
        for brand_id, owner in brand_owners_qs:
            if owner:
                brand_owners[brand_id].append(owner)

        shopify_products_qs = brands.values('id').annotate(shopify_product_count=Count('products__id', filter=Q(products__metadata__shopify=True))).values_list('id', 'shopify_product_count')
        shopify_products = {brand_id: product_count for brand_id, product_count in shopify_products_qs}

        delayed_orders_qs = brands.values('id').annotate(delayed_orders_count=Count('order_lines__id', filter=Q(order_lines__metadata__status__in=[FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS], order_lines__metadata__brand_order_status='delayed'))).values_list('id', 'delayed_orders_count')
        delayed_orders = {brand_id: order_count for brand_id, order_count in delayed_orders_qs}
        
        delayed_orders_note_qs = brands.values('id').annotate(delayed_orders_count=Count('order_lines__id', filter=Q(order_lines__metadata__status__in=[FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS], order_lines__metadata__brand_order_status='delayed', order_lines__fulfillment_line__note=''))).values_list('id', 'delayed_orders_count')
        delayed_orders_note = {brand_id: order_count for brand_id, order_count in delayed_orders_note_qs}

        brand_commissions = Commission.objects.all().annotate(total_commission=F('zaamo_commission')+F('commission_percentage')).values('brand_id','total_commission')
        brand_commission_dict = {comm['brand_id']:comm['total_commission'] for comm in brand_commissions}
        
        member_last_login = BrandMemberState.objects.filter(brand_id__in=brands.values('id')).select_related('user').values('brand_id').annotate(last_login=Max('user__last_login')).values('brand_id','last_login')

        member_last_login_dict = {member['brand_id']:member['last_login'] for member in member_last_login}
        brand_manager_inst = BrandManagerCSVhelper()
        brand_manager_inst.update_pending_delvery_count_for_brand_list()
        
        brands_with_shopify_active_product = list(ZaamoShopifyProductMapping.objects.filter(status='active',product_zaamo__brand_id__in=brand_obj_list).order_by('product_zaamo__brand_id').values_list('product_zaamo__brand_id',flat=True).distinct())

        brand_order_monthly_count = BrandOrderCount.objects.filter(brand_name__in=list(brands.values_list('private_metadata__source_name',flat=True))).values('brand_name').order_by('brand_name').annotate(order_counts=Sum('brand_order_count_last_month'))

        brand_order_monthly_count_dict = {order_c['brand_name']:order_c['order_counts'] for order_c in brand_order_monthly_count}
        
        for brand in brands:
            
            brand_name = brand.private_metadata.get('source_name')

            if not brand_name:
                brand_name = brand.brand_name

            shipping_data = brand_manager_inst.brandshippingdata_details.get(brand.id)
            
            shipping_cost_same_state_amount = 0
            shipping_cost_other_state_amount = 0
            min_order_value_free_cost_amount = 0
            warehouse_city = ''
            quick_ship=True
            if shipping_data:

                quick_ship = False

                shipping_cost_same_state_amount = shipping_data.shipping_cost_same_state_amount
                shipping_cost_other_state_amount = shipping_data.shipping_cost_other_state_amount
                min_order_value_free_cost_amount = shipping_data.min_order_value_free_cost_amount
                warehouse_city = brand_manager_inst.brandshippingwarehouse.get(shipping_data.home_state_pincode,'')
            
                if not shipping_cost_same_state_amount or not shipping_cost_other_state_amount:
                    quick_ship = True

            end_date = TimeUtilities.get_current_date(False)
            due_amount = BrandPaymentCsvContext(end_date=end_date).get_due_amount(brand)

            is_shopify_active = True if brand.id in brands_with_shopify_active_product else False
            rows[brand_manager_inst.zaamo_order_count_30_days.get(brand.id,0)].append(
            [
                brand.brand_name, 
                brand.status,
                brand.importance,
                brand.cod,
                is_shopify_active,
                shopify_products.get(brand.id),
                brand.metadata.get('instagram_link'),
                brand.metadata.get('content_tagging'),
                brand_commission_dict.get(brand.id,0),
                brand.brand_barter,
                brand.brand_barter_guidelines,
                brand.too_many_orders, 
                delayed_orders.get(brand.id),
                delayed_orders_note.get(brand.id),
                brand_manager_inst.zaamo_order_count_1_day.get(brand.id,0),
                brand_manager_inst.zaamo_order_count_7_days.get(brand.id,0),
                brand_manager_inst.zaamo_order_count_30_days.get(brand.id,0),
                BrandManagerCSVhelper.fetch_count_of_sourcing_request_received(brand),
                brand_manager_inst.brand_count_of_pending_delivery_IH.get(brand.id,0),
                brand_manager_inst.brand_count_of_pending_delivery_IS.get(brand.id,0),
                member_last_login_dict.get(brand.id),
                brand.shipping_return_policy.get('shipping_policy'),
                brand.shipping_return_policy.get('return_policy'),
                brand.order_shipping_days+brand.order_processing_days,
                shipping_cost_same_state_amount,
                shipping_cost_other_state_amount,
                min_order_value_free_cost_amount,
                quick_ship,
                brand.metadata.get('quality_assured',False),
                warehouse_city,
                brand.metadata.get('brand_barter_active_date',''),
                brand.metadata.get('step_active',False),
                ','.join(brand_owners.get(brand.id, [])),
                brand.history_notes,
                brand.brand_source,
                brand.metadata.get('postpay_type', 'delivered'),
                "{0:.3f}".format(due_amount),
                brand_manager_inst.placed_or_in_process_order_count.get(brand.id, 0),
                "{0:.3f}".format(due_amount + BrandPaymentCsvContext(end_date=end_date).get_postpay_amount(brand)),
                brand_order_monthly_count_dict.get(brand_name) or 0
            ])
        
        sorted_row_dict = {k: rows[k] for k in sorted(rows,reverse=True)}

        for row in sorted_row_dict.values():
            exportrows.extend(row)

        if return_rows:
            return exportrows

        mail = MailImpl()
        filename = f"brand_list_{TimeUtilities.get_current_date_time()}.csv"
        attachment_json = mail.get_csv_attachment_dict(filename, exportrows)

        return attachment_json
    
    @staticmethod
    @app.task(queue='priority_queue')
    def send_brand_list_csv_to_email(brand_ids, recipient_email):
        if not recipient_email:
            recipient_email = 'rachit@zaamo.co'

        mail = MailImpl()
        attachments = [BrandManagerCSVhelper.brand_owner_brand_list_csv(brand_ids)]
        mail.send_mail_with_attachment('brand_owner_csv', 'Hi, Please find the attached csv', 'brand list csv', attachments, recipient_email)



class AllCollectionsDumpCSVContext:

    @staticmethod
    def get_headers_for_all_collections_dump():
        return [
                'store_id',
                'store_name',
                'store_url',
                'status',
                'store_creation_date',
                'collection_id',
                'collection_name',
                'is_default',
                'collection_info',
                'image_url', 
                'collection_admin_link',
                'collection_link',
                'on_zaamo_page',
                'is_steal_deal',
                'ideas',
                'collection_created_date',
                'last_modified_date',
                'product_count',
                'total_live_products_count(published/brand_active)',
                'shop_the_look',
                'steal_deal_products'
                ]
    
    @staticmethod
    def create_attachment_dict_for_email(filename,base_encoded_file):
        return {"content": base_encoded_file, "type": "application/csv", "filename": filename}

class BrandDashboardCsvContext:
    queryset = []

    def __init__(self, brand_id):

        if brand_id:
            queryset = SourcingRequest.objects.filter(brand=brand_id)

        else:
            queryset = SourcingRequest.objects.all()
        if settings.DEBUG:
            base_url = "https://betaistore.zaamo.co/product_view/"
        else:
            base_url = "https://zaamo.co/product_view/"

        self.queryset = queryset.annotate(product_url = Concat(Value(base_url), F('product__slug') ))

    def get_queryset(self):
        return self.queryset

    def get_headers_of_brand_dashboard_for_csv(self):
        
        return [
            'Sourcing Request Id',
            'Sourcing Request Status',
            'Influencer Instagram',
            'Brand Collab',
            'Availabitlity', 
            'Recommended',
            'Product Name',
            'Variant Name',
            'Variant MSP',
            'Created At',
            'Content',
            'Product Url' 
        ]

class BrandLedgerXLSX:
    sheets = None
    postpay_amount = dict()
    postpay_order_count = dict()
    opening_balance = dict()
    payable = dict()
    order_value = dict()
    brand_ids = set()
    brand_names = dict()
    brand_states = dict()
    release_date = datetime.datetime(2022, 1, 4)
    start_date = None
    end_date = None


    def __init__(self, brand_ids, start_date=None, end_date=None) -> None:
        ids = Brand.objects.filter(Q(id__in=brand_ids)|Q(metadata__updated_brand_id__in=brand_ids)).values_list('id', flat=True)
        self.brand_ids = set(ids)

        self.prepare_new_brand_names()
        self.prepare_brand_states()

        if len(brand_ids) == 1:
            brand_orders = self.brand_ledger_orders(start_date, end_date)
            brand_payouts = self.brand_ledger_payouts(start_date, end_date)
            brand_name = self.get_new_brand_name(NumberUtilities.convert_string_to_number(brand_ids[0]))

            sheets = {
                'Payout': brand_payouts.get(brand_name, []),
                'Orders': brand_orders.get(brand_name, [])
            }
            self.sheets = sheets
            self.brand_name = brand_name

    def prepare_brand_states(self):
        brands = Brand.objects.filter(id__in=self.brand_ids).values_list('id', 'metadata__State')
        brand_states = {brand_id: state for brand_id, state in brands}

        old_brands = Brand.objects.filter(id__in=self.brand_ids).values_list('id', 'metadata__updated_brand_id')
        for brand_id, updated_brand_id in old_brands:

            if updated_brand_id:
                brand_states[brand_id] = brand_states[updated_brand_id]

        self.brand_states = brand_states

    def prepare_new_brand_names(self):
        brands = Brand.objects.filter(id__in=self.brand_ids).values_list('id', 'brand_name')
        brand_names = {brand_id: brand_name for brand_id, brand_name in brands}

        old_brands = Brand.objects.filter(id__in=self.brand_ids).values_list('id', 'metadata__updated_brand_id')
        for brand_id, updated_brand_id in old_brands:

            if updated_brand_id:
                brand_names[brand_id] = brand_names[updated_brand_id]

        self.brand_names = brand_names
    
    def get_ledger(self):
        if self.sheets:
            return self.get_xlsx_file(self.sheets)
        return None

    @staticmethod
    def get_xlsx_file(sheets):
        f = BytesIO()
        workbook = openpyxl.Workbook()

        for sheet_name, rows in sheets.items():
            workbook.create_sheet(sheet_name)
            sheet = workbook[sheet_name]
            for i, row in enumerate(rows, start=1):
                for j, val in enumerate(row, start=1):
                    sheet.cell(row=i, column=j).value = val
        
        workbook.remove(workbook['Sheet'])
        workbook.save(f)
        f.seek(0)

        return f

    @staticmethod
    def get_tax_start_date():
        return datetime.datetime(2024, 4, 1)
    
    def get_new_brand_name(self, brand_id):
        brand_name = self.brand_names.get(brand_id)
        return brand_name
    
    def get_brand_arrear(self):
        arrear = dict()
        brand_arr = Arrear.objects.filter(brand_id__in=self.brand_ids).filter(arrear_type=ArrearTypeEnum.BRAND)\
                .values('brand_id').order_by('brand_id').annotate(arrear_amount=Sum('amount'))
        
        for arr in brand_arr:
            brand_name = self.get_new_brand_name(arr['brand_id'])
            if not brand_name in arrear:
                arrear[brand_name] = 0
            arrear[brand_name] += arr['arrear_amount']

        return arrear

    def brand_ledger_payouts(self, start_date=None, end_date=None):
        headers = [("Type", "Name", "Transaction ID", "Amount", "Date")]
        tax_start = self.get_tax_start_date()
        if not start_date:
            start_date = self.release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()

        self.start_date = start_date
        self.end_date = end_date
        if isinstance(self.start_date, str):
            self.start_date = datetime.datetime.strptime(self.start_date, '%Y-%m-%d')
        if isinstance(self.end_date, str):
            self.end_date = datetime.datetime.strptime(self.end_date, '%Y-%m-%d')

        arrear = self.get_brand_arrear()

        brands = dict()
        for brand_id in self.brand_ids:

            brand_name = self.get_new_brand_name(brand_id)
            if not brand_name in brands:
                brands[brand_name] = []
            if not brand_name in self.opening_balance:
                self.opening_balance[brand_name] = Decimal(0)
            if not brand_name in self.payable:
                self.payable[brand_name] = Decimal(0)

        payouts = BrandPayout.objects.filter(brand_id__in=self.brand_ids).filter(date__gte=start_date, date__lte=end_date)\
            .values_list('brand_id', 'transaction_details', 'amount', 'date')
        
        for brand_id, transaction_id, amount, payout_date in payouts:

            brand_name = self.get_new_brand_name(brand_id)
            row = [brand_name, transaction_id, amount, payout_date]
            if payout_date < tax_start:
                self.opening_balance[brand_name] -= amount
            else:
                self.payable[brand_name] -= amount
            if self.end_date > tax_start and payout_date < tax_start:
                continue
            brands[brand_name].append(row)

        brand_payouts = dict()
        for brand_name, payouts in brands.items():

            balance = self.opening_balance.get(brand_name, 0)
            total_payable = balance + self.payable.get(brand_name) + self.postpay_amount.get(brand_name, 0) + arrear.get(brand_name, 0) 

            rows = []
            title = [
                ['Ledger Summary'], 
                ['Brand Name', brand_name], [], 
                [f'Opening Balance as on 31.03.{tax_start.year}', "{0:.2f}".format(balance)], [], 
                ['Arrear', "{0:.2f}".format(arrear.get(brand_name, 0))], [],
                ['Receivables/Payables without Post Pay as on date', "{0:.2f}".format(self.payable.get(brand_name))], [],
                ['Amount Pending on Post Pay Orders as on date', "{0:.2f}".format(self.postpay_amount.get(brand_name, 0))], [],
                ['Total Receivables/Payables With Post Pay as on date', "{0:.2f}".format(total_payable)], [],
                ['No. of Order pending on Post Pay', self.postpay_order_count.get(brand_name, 0)], [],
                ['Payout Transactions'], []
            ]
            for payout in payouts:
                rows.append(['Brand'] + list(payout))
            
            if payouts:
                total_amount = sum(NumberUtilities.convert_string_to_float(row[3]) for row in rows)
                total_row = [""] * len(rows[0])
                total_row[0] = "Total"
                total_row[3] = total_amount
                rows.append([])
                rows.append(total_row)

            rows = title + headers + rows
            brand_payouts[brand_name] = rows

        return brand_payouts
    
    def get_columns(self):
        columns = {
            "brand_name":           "Brand Name",
            "product_name":         "Product Name",
            "order_id":             "Order ID",
            "quantity":             "QTY",
            "mrp":                  "MRP",
            "msp":                  "MSP", 
            "customer_msp":         "Customer MSP", 
            "shipping_charge":      "Shipping Charge/COD",
            "shopify_charge":       "MarkUp Price/Step Price",
            "order_value":          "Order Processed Value",
            "discounted":           "Discounted",
            "IGST_TCS":             "IGST_TCS 1%_if the Brand and the Customer state of Different",
            "CGST_TCS":             "CGST_TCS 0.5%_If Brand and the customer State are same",
            "SGST_TCS":             "SGST_TCS_0.5%_If Brand and the customer State are same",
            "TDS":                  "TDS_1%",
            "commission_percent":   "Commission %",
            "order_status":         "Order Status", 
            "date":                 "Date",
            "month":                "Month",
            "customer_name":        "Customer Name", 
            "customer_address":     "Customer Address",
            "cod":                  "COD",
            "commission":           "Influencer Commission",
            "gateway_fees":         "Platform Fees",
            "penalty":              "Penalty",
            "postpay":              "PostPay",
            "brand_pay":            "Brand Pay", 
            "voucher_owner":        "Voucher Owner Brand", 
            "brand_discount_amount":"Brand Discount Amount",
            "order_id_brand":       "order_id_brand",
            "order_notes":          "Order Notes",
            "IGST":                 "IGST_ 18%=If Brand State is different from the Zaamo State",
            "CGST":                 "CGST_9%_If Brand State is Delhi",
            "UTGST/SGST":           "UTGST/SGST_9%_If Brand State is Delhi",
        }
        return columns
    
    def get_headers(self):
        columns = self.get_columns()
        headers = [ columns["brand_name"], columns["product_name"], columns["order_id"], columns["quantity"], columns["mrp"], columns["msp"], columns["customer_msp"], columns["shipping_charge"], 
                    columns["shopify_charge"], columns['order_value'], columns["discounted"], columns["IGST_TCS"], columns["CGST_TCS"], columns["SGST_TCS"], columns["TDS"],
                    columns["commission_percent"], columns["order_status"], columns["date"], columns["month"], columns["customer_name"], 
                    columns["customer_address"], columns['cod'], columns["commission"], columns["gateway_fees"], columns["penalty"], columns["postpay"], 
                    columns["brand_pay"], columns["voucher_owner"], columns["brand_discount_amount"], columns["order_id_brand"], columns["order_notes"],
                    columns["IGST"], columns["CGST"], columns["UTGST/SGST"]
        ]
        return headers

    def brand_ledger_orders(self, start_date=None, end_date=None):
        """
        """
        if not start_date:
            start_date = self.release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()

        self.start_date = start_date
        self.end_date = end_date
        if isinstance(self.start_date, str):
            self.start_date = datetime.datetime.strptime(self.start_date, '%Y-%m-%d')
        if isinstance(self.end_date, str):
            self.end_date = datetime.datetime.strptime(self.end_date, '%Y-%m-%d')


        order_csv = OrderCsvContext(start_date, end_date, self.brand_ids, exclude_fake=True)

        brand_orders = self.get_brand_orders(order_csv)
        brand_orders = self.sum_total(brand_orders, order_csv)
        return brand_orders

    def get_brand_orders(self, order_csv: OrderCsvContext):
        columns = self.get_columns()
        tax_start = self.get_tax_start_date()
        return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER,  
                        FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)
        brands = dict()
        order_filter = order_csv.get_queryset()

        for orderline_instance in order_filter:

            brand_name = self.get_new_brand_name(orderline_instance.brand_id)
            if not brand_name in brands:
                brands[brand_name] = []
                self.postpay_amount[brand_name] = Decimal(0)
                self.opening_balance[brand_name] = Decimal(0)
                self.payable[brand_name] = Decimal(0)
                self.order_value[brand_name] = Decimal(0)
                self.postpay_order_count[brand_name] = 0

            order_date = orderline_instance.order.created
            if order_date < tax_start:
                self.opening_balance[brand_name] += order_csv.get_brand_pay(orderline_instance)
                if self.end_date > tax_start:
                    continue
            order_instance = orderline_instance.order
            commission_percent = order_csv.get_overall_commission(orderline_instance) or 0.0
            brand_discount_amount = order_csv.get_brand_discount_amount(orderline_instance)
            order_status = order_csv.get_order_status(orderline_instance)
            order_note = order_csv.get_order_note(orderline_instance)
            if StringUtilities.convert_object_to_string(orderline_instance.metadata.get('zaamo_shipping')).lower() == 'true':
                shipping = 0
            else:
                shipping = order_csv.get_shipping_price(orderline_instance)
            msp = order_csv.get_msp(orderline_instance)
            
            streak = Decimal("1.5") if order_csv.get_if_order_streakorder(orderline_instance) else Decimal("1.0")

            influencer_commission = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('influencer_commission', '0'))/streak
            if orderline_instance.order.platform_code == PlatformTypeEnum.INFLUENCER_HOME:
                zaamo_commission = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('zaamo_commission', '0'))
                if zaamo_commission:
                    influencer_commission = zaamo_commission / streak
            zaamo_commission = order_csv.get_zaamo_commission(orderline_instance.brand_id)

            is_voucher_owner_brand = ""
            try:
                if order_instance.voucher.owner == VoucherOwner.BRAND:
                    is_voucher_owner_brand = True
            except Exception as e:
                pass
            if is_voucher_owner_brand == True:
                zaamo_commission_percentage = Decimal("0.02")
            elif zaamo_commission:
                zaamo_commission_percentage = Decimal(zaamo_commission)/100
            else:
                zaamo_commission_percentage = Decimal("0.02")
            
            if orderline_instance.metadata.get("platform_fees"):
                gateway_fees = orderline_instance.metadata.get("platform_fees")
            elif brand_discount_amount:
                gateway_fees = (msp - NumberUtilities.convert_string_to_decimal(brand_discount_amount) + shipping) * zaamo_commission_percentage
            else:
                gateway_fees = (msp + shipping) * zaamo_commission_percentage

            penalty_percentage = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('penalty', '0'))
            penalty = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('brand_due_amount')) * penalty_percentage / (100 - penalty_percentage)

            row = {
                columns["brand_name"]: brand_name,
                columns["product_name"]: order_csv.get_product_name(orderline_instance),
                columns["order_id"]: order_csv.get_order_id(orderline_instance),
                columns["quantity"]: order_csv.get_quantity(orderline_instance),
                columns["mrp"]: order_csv.get_mrp(orderline_instance),
                columns["msp"]: order_csv.get_true_msp(orderline_instance), # msp from brand side
                columns["customer_msp"]: msp, # msp at which product is sold
                columns["shipping_charge"]: order_csv.get_shipping_or_cod_charge(orderline_instance),
                columns["shopify_charge"]: order_csv.get_shopify_charge(orderline_instance),
                columns["order_value"]: "{:.2f}".format(order_csv.get_order_processed_value(orderline_instance)),
                columns["discounted"]: order_csv.get_is_discounted(orderline_instance),
                columns["commission_percent"]: "{:.2f}%".format(commission_percent),
                columns["order_status"]: order_status,
                columns["date"]: orderline_instance.order.created,
                columns["month"]: orderline_instance.order.created.strftime('%b-%y'),
                columns["customer_name"]: order_csv.get_customer_name(orderline_instance),
                columns["customer_address"]: order_csv.get_customer_address(orderline_instance),
                columns["cod"]: order_csv.get_if_cod(orderline_instance),
                columns["commission"]: NumberUtilities.convert_string_to_decimal(influencer_commission),
                columns["gateway_fees"]: NumberUtilities.convert_string_to_decimal(gateway_fees),
                columns["penalty"]: penalty,
                columns["postpay"]: order_csv.get_if_orderline_postpay(orderline_instance),
                columns["brand_pay"]: order_csv.get_brand_pay(orderline_instance),
                columns["voucher_owner"]: is_voucher_owner_brand,
                columns["order_notes"]: order_note,
                columns["brand_discount_amount"]: brand_discount_amount

            }
            if brand_name in order_csv.order_id_brand_dict:
                row[columns["order_id_brand"]] = order_csv.get_brand_order_id(orderline_instance)

            if order_date > tax_start:
                customer_state = order_csv.get_customer_state(orderline_instance)
                brand_state = self.brand_states.get(orderline_instance.brand_id)
                zaamo_state = 'Delhi'

                tax_order_value = NumberUtilities.convert_string_to_float(order_csv.get_tax_order_value(orderline_instance))
                if row[columns["order_status"]] in return_or_cancel:
                    tax_order_value = 0
                row[columns["TDS"]] = 0.01 * tax_order_value
                if customer_state == brand_state:
                    row[columns["IGST_TCS"]] = 0.01 * tax_order_value
                else:
                    row[columns["CGST_TCS"]] = 0.005 * tax_order_value
                    row[columns["SGST_TCS"]] = 0.005 * tax_order_value

                if brand_state == zaamo_state:
                    row[columns["CGST"]] = ((row[columns["commission"]] + row[columns["gateway_fees"]] + row[columns["penalty"]]) * 9 / 118)
                    row[columns["UTGST/SGST"]] = ((row[columns["commission"]] + row[columns["gateway_fees"]] + row[columns["penalty"]]) * 9 / 118)
                else:
                    row[columns["IGST"]] = (row[columns["commission"]] + row[columns["gateway_fees"]] + row[columns["penalty"]]) * 18 / 118

                
                tax = NumberUtilities.convert_string_to_decimal(row.get(columns["IGST_TCS"], 0)) + NumberUtilities.convert_string_to_decimal(row.get(columns["CGST_TCS"], 0))
                tax += NumberUtilities.convert_string_to_decimal(row.get(columns["SGST_TCS"], 0)) + NumberUtilities.convert_string_to_decimal(row.get(columns["TDS"], 0))
                row[columns["brand_pay"]] -= tax

                brand_pay = row[columns["brand_pay"]]
                postpay = order_csv.get_if_orderline_postpay(orderline_instance)

                if postpay:
                    postpay_amt = brand_pay
                    self.postpay_amount[brand_name] += postpay_amt
                    self.postpay_order_count[brand_name] += 1
                else:
                    self.payable[brand_name] += brand_pay

                self.order_value[brand_name] += brand_pay
            
            brands[brand_name].append(row)

        return brands    
        
    def sum_total(self, brand_orders, order_csv):
        columns = self.get_columns()
        headers = self.get_headers()
        total = dict()
        for brand_name, orders in brand_orders.items():
            
            total_influencer_commission = sum(order[columns["commission"]] for order in orders)
            total_gateway_fees = sum(order[columns["gateway_fees"]] for order in orders)
            total_penalty = sum(order[columns["penalty"]] for order in orders)
            total_brand_pay = sum(order[columns["brand_pay"]] for order in orders)
            
            total_row = {}
            total_row[columns["brand_name"]]    = "Total"
            total_row[columns["commission"]]    = "{:.2f}".format(total_influencer_commission)
            total_row[columns["gateway_fees"]]  = "{:.2f}".format(total_gateway_fees)
            total_row[columns["penalty"]]       = "{:.2f}".format(total_penalty)
            total_row[columns["brand_pay"]]     = "{:.2f}".format(total_brand_pay)

            if brand_name in order_csv.order_id_brand_dict:
                column_names = headers
            else:
                column_names = [header for header in headers if header != columns["order_id_brand"]]

            final_rows = [column_names]
            for order in orders:
                row = [order.get(column_name, '') for column_name in column_names]
                final_rows.append(row)
            
            final_rows.append([])
            final_rows.append([total_row.get(column_name, '') for column_name in column_names])
            
            total[brand_name] = final_rows

        return total

class BrandLedgerOld:
    sheets = None

    def __init__(self, brand_id, start_date=None, end_date=None) -> None:
        
        brand_primary_email = BrandEmail.objects.filter(brand_id=brand_id, state=BrandEmailStateEnum.PRIMARY).values_list('brand_id__brand_name', 'brand_email')
        if brand_primary_email:
            brand_name, brand_email = brand_primary_email[0]
        else:
            brand_name, brand_email = brand_id, settings.BETA_RECIPIENT_EMAIL
        
        primary_email = {brand_name: brand_email}

        brand_payouts = self.brand_ledger_payouts(primary_email, start_date, end_date)
        brand_orders = self.brand_ledger_orders(primary_email, start_date, end_date)

        sheets = {
            'Payout': brand_payouts.get(brand_name, []),
            'Orders': brand_orders.get(brand_name, [])
        }
        self.sheets = sheets
        self.brand_name = brand_name
    
    def get_ledger(self):
        if self.sheets:
            return self.get_xlsx_file(self.sheets)
        return None

    @staticmethod
    def get_xlsx_file(sheets):
        f = BytesIO()
        workbook = openpyxl.Workbook()

        for sheet_name, rows in sheets.items():
            workbook.create_sheet(sheet_name)
            sheet = workbook[sheet_name]
            for i, row in enumerate(rows, start=1):
                for j, val in enumerate(row, start=1):
                    sheet.cell(row=i, column=j).value = val
        
        workbook.remove(workbook['Sheet'])
        workbook.save(f)
        f.seek(0)

        return f

    @staticmethod
    def brand_ledger_payouts(primary_emails, start_date=None, end_date=None):
        headers = [("Type", "Name", "Transaction ID", "Amount", "Date")]
        
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()

        brands = dict()
        brand_names = set(primary_emails.keys())
        payouts = BrandPayout.objects.filter(brand__brand_name__in=brand_names).filter(date__gte=start_date, date__lte=end_date)\
            .values_list('brand__brand_name', 'transaction_details', 'amount', 'date')
        for payout in payouts:
            brand_name = payout[0]
            if not brand_name in brands:
                brands[brand_name] = []
            brands[brand_name].append(payout)

        brand_arr = Arrear.objects.filter(brand__brand_name__in=brands).filter(arrear_type=ArrearTypeEnum.BRAND)\
            .filter(created_at__gte=start_date, created_at__lte=end_date)\
                .values('brand__brand_name').order_by('brand__brand_name').annotate(arrear_amount=Sum('amount'))
        
        arrear = {brand_arrear['brand__brand_name']: brand_arrear['arrear_amount'] for brand_arrear in brand_arr}

        brand_payouts = dict()
        for brand_name, payouts in brands.items():
            brand_email = primary_emails.get(brand_name)
            if not brand_email:
                continue
            rows = []
            title = [['Brand Name', brand_name], [], ['Arrear', arrear.get(brand_name, '-')], []]
            for payout in payouts:
                rows.append(['Brand'] + list(payout))
            
            total_amount = sum(NumberUtilities.convert_string_to_float(row[3]) for row in rows)
            total_row = [""] * len(rows[0])
            total_row[0] = "Total"
            total_row[3] = total_amount

            rows = title + headers + rows
            rows.append([])
            rows.append(total_row)
            brand_payouts[brand_name] = rows

        return brand_payouts

    @staticmethod
    def brand_ledger_orders(primary_emails, start_date=None, end_date=None):
        """
        primary_emails: {"brand_name":brand_primary_email, ...}
        """
        columns = {
            "brand_name":           "Brand Name",
            "product_name":         "Product Name",
            "order_id":             "Order ID",
            "quantity":             "QTY",
            "mrp":                  "MRP",
            "msp":                  "MSP", 
            "customer_msp":         "Customer MSP", 
            "shipping_charge":      "Shipping Charge/COD",
            "commission_percent":   "Influencer Commission %",
            "order_status":         "Order Status", 
            "date":                 "Date",
            "customer_name":        "Customer Name", 
            "customer_address":     "Customer Address",
            "cod":                  "COD",
            "commission":           "Influencer Commission",
            "gateway_fees":         "Platform Fees",
            "penalty":              "Penalty",
            "postpay":              "PostPay",
            "brand_pay":            "Brand Pay", 
            "voucher_owner":        "Voucher Owner Brand", 
            "brand_discount_amount":"Brand Discount Amount",
            "order_id_brand":       "order_id_brand",
            "order_notes":       "Order Notes"
        }
        headers = [ columns["brand_name"], columns["product_name"], columns["order_id"], columns["quantity"], columns["mrp"], columns["msp"], columns["customer_msp"],
                    columns["shipping_charge"], columns["commission_percent"], columns["order_status"], columns["date"], columns["customer_name"], 
                    columns["customer_address"], columns['cod'], columns["commission"], columns["gateway_fees"], columns["penalty"], columns["postpay"], 
                    columns["brand_pay"], columns["voucher_owner"], columns["brand_discount_amount"], columns["order_id_brand"], columns["order_notes"]
        ]
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()

        brand_names = set(primary_emails.keys())
        brand_ids = Brand.objects.filter(brand_name__in=brand_names).values_list('id', flat=True)
        order_csv = OrderCsvContext(start_date, end_date, brand_ids, exclude_fake=True)

        brands = dict()
        order_filter = order_csv.get_queryset()

        for orderline_instance in order_filter:
            order_instance = orderline_instance.order
            commission_percent = order_csv.get_influencer_commission(orderline_instance) or 0.0
            brand_discount_amount = order_csv.get_brand_discount_amount(orderline_instance)
            order_status = order_csv.get_order_status(orderline_instance)
            order_note = order_csv.get_order_note(orderline_instance)
            brand_name = order_csv.get_brand_name(orderline_instance)
            if StringUtilities.convert_object_to_string(orderline_instance.metadata.get('zaamo_shipping')).lower() == 'true':
                shipping = 0
            else:
                shipping = order_csv.get_shipping_price(orderline_instance)
            msp = order_csv.get_msp(orderline_instance)
            
            streak = Decimal("1.5") if order_csv.get_if_order_streakorder(orderline_instance) else Decimal("1.0")

            influencer_commission = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('influencer_commission', '0'))/streak
            if orderline_instance.order.platform_code == PlatformTypeEnum.INFLUENCER_HOME:
                zaamo_commission = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('zaamo_commission', '0'))
                if zaamo_commission:
                    influencer_commission = zaamo_commission / streak
            brand_commission = orderline_instance.brand.commission.first()

            is_voucher_owner_brand = ""
            try:
                if order_instance.voucher.owner == VoucherOwner.BRAND:
                    is_voucher_owner_brand = True
            except Exception as e:
                pass
            if is_voucher_owner_brand == True:
                zaamo_commission_percentage = Decimal("0.02")
            elif brand_commission:
                zaamo_commission_percentage = Decimal(brand_commission.zaamo_commission)/100
            else:
                zaamo_commission_percentage = Decimal("0.02")
            
            if orderline_instance.metadata.get("platform_fees"):
                gateway_fees = orderline_instance.metadata.get("platform_fees")
            elif brand_discount_amount:
                gateway_fees = (msp - NumberUtilities.convert_string_to_decimal(brand_discount_amount) + shipping) * zaamo_commission_percentage
            else:
                gateway_fees = (msp + shipping) * zaamo_commission_percentage

            brand_pay = orderline_instance.metadata.get('brand_due_amount', '0')
            postpay = order_csv.get_if_orderline_postpay(orderline_instance)
            if postpay:
                brand_pay = 0

            penalty_percentage = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('penalty', '0'))
            penalty = NumberUtilities.convert_string_to_decimal(brand_pay) * penalty_percentage / (100 - penalty_percentage)

            is_cod = order_csv.get_if_cod(orderline_instance)
            shipping_or_cod_charge = shipping if not is_cod else order_csv.get_cod_amount(orderline_instance)

            row = {
                columns["brand_name"]: brand_name,
                columns["product_name"]: order_csv.get_product_name(orderline_instance),
                columns["order_id"]: order_csv.get_order_id(orderline_instance),
                columns["quantity"]: order_csv.get_quantity(orderline_instance),
                columns["mrp"]: order_csv.get_mrp(orderline_instance),
                columns["msp"]: order_csv.get_true_msp(orderline_instance), # msp from brand side
                columns["customer_msp"]: msp, # msp at which product is sold
                columns["shipping_charge"]: shipping_or_cod_charge,
                columns["commission_percent"]: "{:.2f}%".format(commission_percent),
                columns["order_status"]: order_status,
                columns["date"]: order_csv.get_date(orderline_instance),
                columns["customer_name"]: order_csv.get_customer_name(orderline_instance),
                columns["customer_address"]: order_csv.get_customer_address(orderline_instance),
                columns["cod"]: is_cod,
                columns["commission"]: NumberUtilities.convert_string_to_decimal(influencer_commission),
                columns["gateway_fees"]: NumberUtilities.convert_string_to_decimal(gateway_fees),
                columns["penalty"]: penalty,
                columns["postpay"]: postpay,
                columns["brand_pay"]: NumberUtilities.convert_string_to_decimal(brand_pay),
                columns["voucher_owner"]: is_voucher_owner_brand,
                columns["order_notes"]: order_note,
                columns["brand_discount_amount"]: brand_discount_amount

            }
            if brand_name in order_csv.order_id_brand_dict:
                row[columns["order_id_brand"]] = order_csv.get_brand_order_id(orderline_instance)

            if not brand_name in brands:
                brands[brand_name] = []
            brands[brand_name].append(row)
            

        brand_orders = dict()
        for brand_name, orders in brands.items():
            brand_email = primary_emails.get(brand_name)
            if not brand_email:
                continue
            total_influencer_commission = sum(order[columns["commission"]] for order in orders)
            total_gateway_fees = sum(order[columns["gateway_fees"]] for order in orders)
            total_penalty = sum(order[columns["penalty"]] for order in orders)
            total_brand_pay = sum(order[columns["brand_pay"]] for order in orders)
            
            total_row = {}
            total_row[columns["brand_name"]]    = "Total"
            total_row[columns["commission"]]    = "{:.2f}".format(total_influencer_commission)
            total_row[columns["gateway_fees"]]  = "{:.2f}".format(total_gateway_fees)
            total_row[columns["penalty"]]       = "{:.2f}".format(total_penalty)
            total_row[columns["brand_pay"]]     = "{:.2f}".format(total_brand_pay)

            if brand_name in order_csv.order_id_brand_dict:
                column_names = headers
            else:
                column_names = [header for header in headers if header != columns["order_id_brand"]]

            final_rows = [column_names]
            for order in orders:
                row = [order.get(column_name, '') for column_name in column_names]
                final_rows.append(row)
            
            final_rows.append([])
            final_rows.append([total_row.get(column_name, '') for column_name in column_names])
            
            brand_orders[brand_name] = final_rows
        return brand_orders

class BrandManagerWiseGMV:
    queryset = []
    gmvs = {}

    def __init__(self, start_date=None, end_date=None) -> None:
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()
        
        orderlines = OrderLine.objects.filter(created_at__gte=start_date, created_at__lt=end_date).values('brand')\
            .annotate(
                IH_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME), output_field=DecimalField()), 0), 
                IS_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE), output_field=DecimalField()), 0),
                IH_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME)), 0),
                IS_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE)), 0),
            ).order_by('brand')
        orderlines = {orderline["brand"]: orderline for orderline in orderlines}
        
        staff_brand = StaffBrandMapping.objects.all().values_list('user__email', 'brand')
        gmvs = {}
        for staff_email, brand in staff_brand:
            if not staff_email in gmvs:
                gmvs[staff_email] = {
                    "staff_email": staff_email,
                    "IH_gmv": 0,
                    "IS_gmv": 0,
                    "IH_discount": 0,
                    "IS_discount": 0
                }
            gmvs[staff_email]["IH_gmv"] += orderlines.get(brand, {}).get("IH_gmv", 0)
            gmvs[staff_email]["IS_gmv"] += orderlines.get(brand, {}).get("IS_gmv", 0)
            gmvs[staff_email]["IH_discount"] += orderlines.get(brand, {}).get("IH_discount", 0)
            gmvs[staff_email]["IS_discount"] += orderlines.get(brand, {}).get("IS_discount", 0)

        self.gmvs = gmvs

    @staticmethod
    def get_headers():
        columns = BrandManagerWiseGMV.get_columns_dict()
        headers = [
            columns["staff_email"], columns["IH_gmv"], columns["IS_gmv"], columns["gmv"], columns["IH_discount"], columns["IS_discount"]
        ]
        
        return headers

    @staticmethod
    def get_columns_dict():
        columns = {
            "staff_email"   : "Staff Email",
            "IH_gmv"        : "GMV (IH)",
            "IS_gmv"        : "GMV (IS)",
            "gmv"           : "GMV Total",
            "IH_discount"   : "Total Discount (IH)",
            "IS_discount"   : "Total Discount (IS)"
        }

        return columns

    def get_rows(self):
        columns = self.get_columns_dict()
        headers = self.get_headers()
        rows = []
        for gmv in self.gmvs.values():
            row = {
                columns["staff_email"]  : gmv["staff_email"],
                columns["IH_gmv"]       : gmv["IH_gmv"],
                columns["IS_gmv"]       : gmv["IS_gmv"],
                columns["gmv"]          : gmv["IH_gmv"] + gmv["IS_gmv"],
                columns["IH_discount"]  : gmv["IH_discount"],
                columns["IS_discount"]  : gmv["IS_discount"]
            }
            rows.append(row)

        final_rows = [headers]
        for row in rows:
            final_rows.append([row.get(header, "") for header in headers])
        
        return final_rows


class ManagerAndBrandWiseGMV:
    queryset = []
    gmvs = {}

    def __init__(self, start_date=None, end_date=None) -> None:
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()
        
        orderlines = OrderLine.objects.filter(created_at__gte=start_date, created_at__lt=end_date).values('brand__brand_name')\
            .annotate(
                IH_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME), output_field=DecimalField()), 0), 
                IS_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE), output_field=DecimalField()), 0),
                IH_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME)), 0),
                IS_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE)), 0),
            ).order_by('brand__brand_name')
        orderlines = {orderline["brand__brand_name"]: orderline for orderline in orderlines}
        
        staff_brand = StaffBrandMapping.objects.all().values_list('user__email', 'brand__brand_name')
        gmvs = {}
        for staff_email, brand_name in staff_brand:
            if not staff_email in gmvs:
                gmvs[staff_email] = []
            gmvs[staff_email].append({
                "staff_email": staff_email,
                "brand__brand_name": brand_name,
                "IH_gmv": orderlines.get(brand_name, {}).get("IH_gmv", 0),
                "IS_gmv": orderlines.get(brand_name, {}).get("IS_gmv", 0),
                "IH_discount": orderlines.get(brand_name, {}).get("IH_discount", 0),
                "IS_discount": orderlines.get(brand_name, {}).get("IS_discount", 0)
            })

        self.gmvs = gmvs

    @staticmethod
    def get_headers():
        columns = ManagerAndBrandWiseGMV.get_columns_dict()
        headers = [
            columns["staff_email"], columns["brand__brand_name"], columns["IH_gmv"], columns["IS_gmv"], columns["gmv"], columns["IH_discount"], columns["IS_discount"]
        ]
        
        return headers

    @staticmethod
    def get_columns_dict():
        columns = {
            "staff_email"       : "Staff Email",
            "brand__brand_name" : "Brand Name",
            "IH_gmv"            : "GMV (IH)",
            "IS_gmv"            : "GMV (IS)",
            "gmv"               : "GMV Total",
            "IH_discount"       : "Total Discount (IH)",
            "IS_discount"       : "Total Discount (IS)"
        }

        return columns

    def get_rows(self):
        columns = self.get_columns_dict()
        headers = self.get_headers()
        rows = []
        for manager_gmvs in self.gmvs.values():
            for gmv in manager_gmvs:
                row = {
                    columns["staff_email"]          : gmv["staff_email"],
                    columns["brand__brand_name"]    : gmv["brand__brand_name"],
                    columns["IH_gmv"]               : gmv["IH_gmv"],
                    columns["IS_gmv"]               : gmv["IS_gmv"],
                    columns["gmv"]                  : gmv["IH_gmv"] + gmv["IS_gmv"],
                    columns["IH_discount"]          : gmv["IH_discount"],
                    columns["IS_discount"]          : gmv["IS_discount"]
                }
                rows.append(row)

        final_rows = [headers]
        for row in rows:
            final_rows.append([row.get(header, "") for header in headers])
        
        return final_rows


class InfluencerManagerWiseGMV:
    queryset = []
    gmvs = {}

    def __init__(self, start_date=None, end_date=None) -> None:
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()
        
        orderlines = OrderLine.objects.filter(created_at__gte=start_date, created_at__lt=end_date).values('order__order_store__store')\
            .annotate(
                IH_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME), output_field=DecimalField()), 0), 
                IS_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE), output_field=DecimalField()), 0),
                IH_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME)), 0),
                IS_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE)), 0),
            ).order_by('order__order_store__store')
        orderlines = {orderline["order__order_store__store"]: orderline for orderline in orderlines}

        staff_store = StaffStoreMapping.objects.all().values_list('user__email', 'store')
        gmvs = {}
        for staff_email, store in staff_store:
            if not staff_email in gmvs:
                gmvs[staff_email] = {
                    "staff_email": staff_email,
                    "IH_gmv": 0,
                    "IS_gmv": 0,
                    "IH_discount": 0,
                    "IS_discount": 0
                }
            gmvs[staff_email]["IH_gmv"] += orderlines.get(store, {}).get("IH_gmv", 0)
            gmvs[staff_email]["IS_gmv"] += orderlines.get(store, {}).get("IS_gmv", 0)
            gmvs[staff_email]["IH_discount"] += orderlines.get(store, {}).get("IH_discount", 0)
            gmvs[staff_email]["IS_discount"] += orderlines.get(store, {}).get("IS_discount", 0)

        self.gmvs = gmvs

    @staticmethod
    def get_headers():
        columns = InfluencerManagerWiseGMV.get_columns_dict()
        headers = [
            columns["staff_email"], columns["IH_gmv"], columns["IS_gmv"], columns["gmv"], columns["IH_discount"], columns["IS_discount"]
        ]
        
        return headers

    @staticmethod
    def get_columns_dict():
        columns = {
            "staff_email"   : "Staff Email",
            "IH_gmv"        : "GMV (IH)",
            "IS_gmv"        : "GMV (IS)",
            "gmv"           : "GMV Total",
            "IH_discount"   : "Total Discount (IH)",
            "IS_discount"   : "Total Discount (IS)"
        }

        return columns

    def get_rows(self):
        columns = self.get_columns_dict()
        headers = self.get_headers()
        rows = []
        for gmv in self.gmvs.values():
            row = {
                columns["staff_email"]  : gmv["staff_email"],
                columns["IH_gmv"]       : gmv["IH_gmv"],
                columns["IS_gmv"]       : gmv["IS_gmv"],
                columns["gmv"]          : gmv["IH_gmv"] + gmv["IS_gmv"],
                columns["IH_discount"]  : gmv["IH_discount"],
                columns["IS_discount"]  : gmv["IS_discount"]
            }
            rows.append(row)

        final_rows = [headers]
        for row in rows:
            final_rows.append([row.get(header, "") for header in headers])
        
        return final_rows

class ManagerAndInfluencerWiseGMV:
    queryset = []
    gmvs = {}

    def __init__(self, start_date=None, end_date=None) -> None:
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()
        
        orderlines = OrderLine.objects.filter(created_at__gte=start_date, created_at__lt=end_date).values('order__order_store__store__store_name')\
            .annotate(
                IH_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME), output_field=DecimalField()), 0), 
                IS_gmv=Coalesce(Sum((F('unit_price_net_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE), output_field=DecimalField()), 0),
                IH_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME)), 0),
                IS_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE)), 0),
            ).order_by('order__order_store__store__store_name')
        orderlines = {orderline["order__order_store__store__store_name"]: orderline for orderline in orderlines}
        
        staff_brand = StaffStoreMapping.objects.all().values_list('user__email', 'store__store_name')
        gmvs = {}
        for staff_email, store_name in staff_brand:
            if not staff_email in gmvs:
                gmvs[staff_email] = []
            gmvs[staff_email].append({
                "staff_email": staff_email,
                "order__order_store__store__store_name": store_name,
                "IH_gmv": orderlines.get(store_name, {}).get("IH_gmv", 0),
                "IS_gmv": orderlines.get(store_name, {}).get("IS_gmv", 0),
                "IH_discount": orderlines.get(store_name, {}).get("IH_discount", 0),
                "IS_discount": orderlines.get(store_name, {}).get("IS_discount", 0)
            })

        self.gmvs = gmvs

    @staticmethod
    def get_headers():
        columns = ManagerAndInfluencerWiseGMV.get_columns_dict()
        headers = [
            columns["staff_email"], columns["order__order_store__store__store_name"], columns["IH_gmv"], columns["IS_gmv"], columns["gmv"], columns["IH_discount"], columns["IS_discount"]
        ]
        
        return headers

    @staticmethod
    def get_columns_dict():
        columns = {
            "staff_email"       : "Staff Email",
            "IH_gmv"            : "GMV (IH)",
            "IS_gmv"            : "GMV (IS)",
            "gmv"               : "GMV Total",
            "IH_discount"       : "Total Discount (IH)",
            "IS_discount"       : "Total Discount (IS)",
            "order__order_store__store__store_name" : "Store Name",
        }

        return columns

    def get_rows(self):
        columns = self.get_columns_dict()
        headers = self.get_headers()
        rows = []
        for manager_gmvs in self.gmvs.values():
            for gmv in manager_gmvs:
                row = {
                    columns["staff_email"]  : gmv["staff_email"],
                    columns["IH_gmv"]       : gmv["IH_gmv"],
                    columns["IS_gmv"]       : gmv["IS_gmv"],
                    columns["gmv"]          : gmv["IH_gmv"] + gmv["IS_gmv"],
                    columns["IH_discount"]  : gmv["IH_discount"],
                    columns["IS_discount"]  : gmv["IS_discount"],
                    columns["order__order_store__store__store_name"]: gmv["order__order_store__store__store_name"],
                }
                rows.append(row)

        final_rows = [headers]
        for row in rows:
            final_rows.append([row.get(header, "") for header in headers])
        
        return final_rows

class InfluencerAndMrpWiseGMV:
    queryset = []
    gmvs = {}

    def __init__(self, start_date=None, end_date=None) -> None:
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()
        
        orderlines = OrderLine.objects.filter(created_at__gte=start_date, created_at__lt=end_date).values('order__order_store__store__store_name')\
            .annotate(
                IH_gmv=Coalesce(Sum((F('variant__cost_price_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME), output_field=DecimalField()), 0), 
                IS_gmv=Coalesce(Sum((F('variant__cost_price_amount')*F('quantity')) + F('shipping_cost_amount'), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE), output_field=DecimalField()), 0),
                IH_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_HOME)), 0),
                IS_discount=Coalesce(Sum(Cast(KeyTextTransform('discount_amount', 'metadata'), FloatField()), filter=Q(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE)), 0),
            ).order_by('order__order_store__store__store_name')
        orderlines = {orderline["order__order_store__store__store_name"]: orderline for orderline in orderlines}

        gmvs = {}
        for store_name, orderline in orderlines.items():
            gmvs[store_name] = {
                "store_name"    : store_name,
                "IH_gmv"        : orderline["IH_gmv"],
                "IS_gmv"        : orderline["IS_gmv"],
                "IH_discount"   : orderline["IH_discount"],
                "IS_discount"   : orderline["IS_discount"]
            }

        self.gmvs = gmvs

    @staticmethod
    def get_headers():
        columns = InfluencerAndMrpWiseGMV.get_columns_dict()
        headers = [
            columns["store_name"], columns["IH_gmv"], columns["IS_gmv"], columns["gmv"], columns["IH_discount"], columns["IS_discount"]
        ]
        
        return headers

    @staticmethod
    def get_columns_dict():
        columns = {
            "store_name"    : "Store Name",
            "IH_gmv"        : "GMV (IH)",
            "IS_gmv"        : "GMV (IS)",
            "gmv"           : "GMV Total",
            "IH_discount"   : "Total Discount (IH)",
            "IS_discount"   : "Total Discount (IS)"
        }

        return columns

    def get_rows(self):
        columns = self.get_columns_dict()
        headers = self.get_headers()
        rows = []
        for gmv in self.gmvs.values():
            row = {
                columns["store_name"]   : gmv["store_name"],
                columns["IH_gmv"]       : gmv["IH_gmv"],
                columns["IS_gmv"]       : gmv["IS_gmv"],
                columns["gmv"]          : gmv["IH_gmv"] + gmv["IS_gmv"],
                columns["IH_discount"]  : gmv["IH_discount"],
                columns["IS_discount"]  : gmv["IS_discount"]
            }
            rows.append(row)

        final_rows = [headers]
        for row in rows:
            final_rows.append([row.get(header, "") for header in headers])
        
        return final_rows


class InfluencerLedgerXLSX:
    sheets = None

    def __init__(self, store_name, start_date=None, end_date=None) -> None:

        store_name, email = StoreMemberState.objects.filter(store__store_name=store_name)\
            .values_list('store__store_name', 'user__email').first()

        influencer_email = {store_name: email}

        influencer_payouts = self.influencer_ledger_payouts(influencer_email, start_date, end_date)
        influencer_orders = self.influencer_ledger_orders(influencer_email, start_date, end_date)

        sheets = {
            'Payout': influencer_payouts.get(store_name, []),
            'Orders': influencer_orders.get(store_name, [])
        }
        self.sheets = sheets

    def get_ledger(self):
        if self.sheets:
            return self.get_xlsx_file(self.sheets)
        return None

    @staticmethod
    def get_xlsx_file(sheets):
        f = BytesIO()
        workbook = openpyxl.Workbook()

        for sheet_name, rows in sheets.items():
            workbook.create_sheet(sheet_name)
            sheet = workbook[sheet_name]
            for i, row in enumerate(rows, start=1):
                for j, val in enumerate(row, start=1):
                    sheet.cell(row=i, column=j).value = val

        workbook.remove(workbook['Sheet'])
        workbook.save(f)
        f.seek(0)

        return f

    @staticmethod
    def influencer_ledger_payouts(influencer_emails, start_date=None, end_date=None):
        headers = [("Transaction ID", "Amount", "Date", "Payment Method")]

        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()

        stores = dict()
        store_names = set(influencer_emails.keys())
        payouts = StorePayout.objects.filter(store__store_name__in=store_names).filter(date__gte=start_date, date__lt=end_date)\
            .values_list('store__store_name', 'transaction_details', 'amount', 'date', 'modeofpayment')
        for payout in payouts:
            store_name = payout[0]
            if not store_name in stores:
                stores[store_name] = []
            stores[store_name].append(payout[1:])

        store_arr = Arrear.objects.filter(store__store_name__in=stores).filter(arrear_type=ArrearTypeEnum.INFLUENCER)\
            .filter(created_at__gte=start_date, created_at__lt=end_date)\
                .values('store__store_name').order_by('store__store_name').annotate(arrear_amount=Sum('amount'))

        arrear = {store_arrear['store__store_name']: store_arrear['arrear_amount'] for store_arrear in store_arr}

        store_payouts = dict()
        for store_name, payouts in stores.items():
            store_email = influencer_emails.get(store_name)
            if not store_email:
                continue
            rows = []
            title = [['Store Name', store_name], [], ['Arrear', arrear.get(store_name, '-')], []]
            for payout in payouts:
                rows.append(payout)

            total_amount = sum(NumberUtilities.convert_string_to_float(row[1]) for row in rows)
            total_row = [""] * len(rows[0])
            total_row[0] = "Total"
            total_row[1] = total_amount

            rows = title + headers + rows
            rows.append([])
            rows.append(total_row)
            store_payouts[store_name] = rows

        return store_payouts

    @staticmethod
    def influencer_ledger_orders(influencer_emails, start_date=None, end_date=None):
        """
        influencer_emails: {"store_name":influencer_email, ...}
        """
        columns = {
            "date":                 "Date",
            "brand_name":           "Brand Name",
            "product_name":         "Product Name",
            "commission_percent":   "Commission %",
            "msp":                  "MSP", 
            "order_status":         "Order Status", 
            "streak_order":         "Streak Order",
            "commission":           "Commission = Commission % * MSP",
        }
        headers = [ columns["date"], columns["brand_name"], columns["product_name"], columns["commission_percent"], 
                    columns["msp"], columns["order_status"], columns["streak_order"], columns["commission"]
        ]
        release_date = '2022-01-04'
        if not start_date:
            start_date = release_date
        if not end_date:
            end_date = TimeUtilities.get_current_date_time()

        store_names = set(influencer_emails.keys())
        order_csv = OrderCsvContext(start_date, end_date, store_names=store_names)

        stores = dict()
        order_filter = order_csv.get_queryset()

        for orderline_instance in order_filter:

            is_voucher_owner_brand = False
            try:
                if orderline_instance.order.voucher.owner == VoucherOwner.BRAND:
                    is_voucher_owner_brand = True
            except Exception as e:
                pass
            if is_voucher_owner_brand:
                continue

            commission_percent = order_csv.get_influencer_commission(orderline_instance) or 0.0
            influencer_commission = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('influencer_commission', '0'))

            streak_order = order_csv.get_if_order_streakorder(orderline_instance)
            thrift = order_csv.get_if_thrift(orderline_instance)
            if streak_order and not thrift:
                commission_percent *= 1.5

            store_name = order_csv.get_store_name(orderline_instance)

            row = {
                columns["date"]: order_csv.get_date(orderline_instance),
                columns["brand_name"]: order_csv.get_brand_name(orderline_instance),
                columns["product_name"]: order_csv.get_product_name(orderline_instance),
                columns["commission_percent"]: "{:.2f}%".format(commission_percent),
                columns["msp"]: order_csv.get_msp(orderline_instance),
                columns["order_status"]: order_csv.get_order_status(orderline_instance),
                columns["streak_order"]: order_csv.get_if_order_streakorder(orderline_instance),
                columns["commission"]: NumberUtilities.convert_string_to_decimal(influencer_commission),

            }
            if not store_name in stores:
                stores[store_name] = []
            stores[store_name].append(row)

        store_orders = dict()
        for store_name, orders in stores.items():
            influencer_email = influencer_emails.get(store_name)
            if not influencer_email:
                continue
            total_influencer_commission = sum(order[columns["commission"]] for order in orders)

            total_row = {}
            total_row[columns["date"]] = "Total"
            total_row[columns["commission"]] = "{:.2f}".format(total_influencer_commission)

            column_names = headers
            final_rows = [column_names]
            for order in orders:
                row = [order.get(column_name, '') for column_name in column_names]
                final_rows.append(row)

            final_rows.append([])
            final_rows.append([total_row.get(column_name, '') for column_name in column_names])

            store_orders[store_name] = final_rows

        return store_orders


class BotdStoresCSV:

    @staticmethod
    def get_headers():
        return [
            "Store Name", "Store Url", "BOTD", "Start Date", "Expiry Date", "Brand Name"
        ]
    

class CouponsCSV:

    @staticmethod
    def get_headers():
        return [
            "Voucher Type", "Voucher Name","Voucher Code","Voucher Usage Limit", "Voucher Used","Voucher Start Date","Voucher End Date",
            "Voucher Discount Value Type", "Voucher Discount Value","Voucher Min Spent Amount","Apply Once per Order", "Voucher Min Checkout Items Quantity","Apply Once per Customer","Max Discount Value",
            "Store Name", "Store Url","Owner","Brand Name", "Products","Collections"
        ]


class AllBrandDetailsCSV:

    def __init__(self) -> None:
        self.queryset = Brand.objects.all().select_related('updated_by').prefetch_related('staff_members', 'brand_emails', 'brand_shipping', 'mobiles', 'commission')

    @staticmethod
    def get_headers():
        return ["Brand Global ID","Image", "Brand Name", "Brand Source", "Brand Barter", "BOTD", "Brand Commission", "Status", "Too Many Orders", "Brand Staff Members", 
            "Brand Emails", "Brand Shipping", "Updated By", "Brand Order Info", "Short Description", "Order Processing Days", "Order Shipping Days", 
            "Brand Barter Guidelines", "Return Policy", "Shipping Policy", "Download Sourcing", "Ledger", "Contact", "Duplicate Brand","GSTIN", "PAN", "Constitution_of_Business", "State", "GST_State_Code", "GST_PAN_Verified"
        ]

    def get_rows(self):
        rows = []
        for brand in self.queryset:
            row = dict()
            row["Brand Global ID"] = graphene.Node.to_global_id('Brand', brand.id)
            row["Image"] = brand.image.url if brand.image else ''
            row["Brand Name"] = brand.brand_name
            row["Brand Source"] = brand.brand_source
            row["Brand Barter"] = brand.brand_barter
            row["BOTD"] = brand.botd
            row["Brand Commission"] = self.get_commission_percentage(brand)
            row["Status"] = brand.status
            row["Too Many Orders"] = brand.too_many_orders
            row["Brand Staff Members"] = ',\n'.join(set(member.email for member in brand.staff_members.all() if member.email))
            row["Brand Emails"] = ',\n'.join(set(email.brand_email for email in brand.brand_emails.all() if email.brand_email))
            row["Brand Shipping"] = self.get_brand_shipping_text(brand)
            row["Updated By"] = brand.updated_by.email if brand.updated_by else ''
            row["Brand Order Info"] = brand.brand_order_info
            row["Short Description"] = brand.short_description
            row["Order Processing Days"] = brand.order_processing_days
            row["Order Shipping Days"] = brand.order_shipping_days
            row["Brand Barter Guidelines"] = brand.brand_barter_guidelines
            row["Return Policy"] = brand.shipping_return_policy.get('return_policy') if isinstance(brand.shipping_return_policy, dict) else brand.shipping_return_policy
            row["Shipping Policy"] = brand.shipping_return_policy.get('shipping_policy') if isinstance(brand.shipping_return_policy, dict) else brand.shipping_return_policy
            row["Download Sourcing"] = f"{settings.BACKEND_URL}/csv/export_csv_for_brand_dashboard?brand_id={graphene.Node.to_global_id('Brand', brand.id)}"
            row["Ledger"] = f"{settings.BACKEND_URL}/csv/export_csv_for_brand_ledger?brand_id={graphene.Node.to_global_id('Brand', brand.id)}"
            row["Contact"] = self.get_contact_text(brand)
            row["Duplicate Brand"] = brand.private_metadata.get('duplicate_brand') if isinstance(brand.private_metadata, dict) else brand.private_metadata
            row["GSTIN"] = brand.metadata.get("GSTIN")
            row["PAN"] = brand.metadata.get("PAN")
            row["Constitution_of_Business"] = brand.metadata.get("Constitution_of_Business")
            row["State"] = brand.metadata.get("State")
            row["GST_State_Code"] = brand.metadata.get("GST_State_Code")
            row["GST_PAN_Verified"] = brand.metadata.get("GST_PAN_Verified")
            rows.append(row)

        return rows

    @staticmethod
    def get_brand_shipping_text(brand):
        brand_shipping = ''
        if brand.brand_shipping.all():
            brand_shipping = brand.brand_shipping.all()[0]
        
        brand_shipping_text = ''
        if brand_shipping:
            brand_shipping_text += f"Home State Pincode: {brand_shipping.home_state_pincode}\n"
            brand_shipping_text += f"Shipping Cost - Same State: {brand_shipping.shipping_cost_same_state_amount}\n"
            brand_shipping_text += f"Shipping Cost - Other State: {brand_shipping.shipping_cost_other_state_amount}\n"
            brand_shipping_text += f"Min Order Value Free Cost: {brand_shipping.min_order_value_free_cost_amount}\n"

        return brand_shipping_text

    @staticmethod
    def get_contact_text(brand):
        contact = ''
        if brand.mobiles.all():
            contact = brand.mobiles.all()[0]
        if contact:
            return f"Contact Name: {contact.user_name}\nContact Number: {contact.mobile_no}"
        return ""

    @staticmethod
    def get_commission_percentage(brand):
        commission = ''
        if brand.commission.all():
            commission = brand.commission.all()[0]
        if commission:
            return commission.commission_percentage
        return 0


class ExploreProductCSV:

    def __init__(self, filters=None) -> None:
        if not filters:
            filters = {}
        self.filters = filters.copy()
        self.state = filters.get('state')
        if self.state:
            self.state = [StringUtilities.convert_object_to_string(state).strip().lower() for state in self.state.split(',')]
        self.source = filters.get('source')
        if self.source:
            self.source = [StringUtilities.convert_object_to_string(src).strip().lower() for src in self.source.split(',')]
        self.media_url = filters.get('media_url')
        if self.media_url:
            self.media_url = [StringUtilities.convert_object_to_string(img).strip().lower() for img in self.media_url.split(',')]
        pdp_views_gt = filters.get('pdp_views_gt') 
        pdp_views_lt = filters.get('pdp_views_lt') 
        
        duplicate_brands = Brand.objects.filter(private_metadata__duplicate_brand=True)
        
        queryset = Product.objects.all().exclude(brand__in=duplicate_brands)
        queryset = self.apply_queryset_filters(queryset)
        queryset = queryset.annotate(pdp_views=Sum('storeproductviews__views'))
            
        if pdp_views_gt:
            queryset = queryset.filter(pdp_views__gte=int(pdp_views_gt))
        if pdp_views_lt:
            queryset = queryset.filter(pdp_views__lt=int(pdp_views_lt))
        
        
        out_of_stock_qs = Stock.objects.select_related("product_variant")\
                .values("product_variant__product_id","product_variant__name")\
                .annotate(
                    total_quantity_allocated=Coalesce(Sum("allocations__quantity_allocated"), 0)\
                )\
                .annotate(total_quantity=Coalesce(Sum("quantity",distinct=True), 0))\
                .annotate(total_available=Case(When(product_variant__track_inventory=False, then=1),\
                default=(F("total_quantity") - F("total_quantity_allocated"))))\
                .filter(product_variant__product_id__in=queryset.values('id'), total_available__lte=0)

        self.out_of_stock_variants = defaultdict(list)

        for out_of_stock_v in out_of_stock_qs:
            self.out_of_stock_variants[out_of_stock_v['product_variant__product_id']].append(out_of_stock_v['product_variant__name'])

        self.queryset = queryset.values('id', 'name', 'brand__brand_name', 'brand_id', 'brand__status', 'is_published', 'brand__brand_source', 'metadata__shopify', 
                                        'publication_date', 'category__name', 'pdp_views','metadata__brand_order_count','metadata__brand_order_count_weekly', 'images__image')


    @staticmethod
    def get_headers():
        headers = ['brand name', 'product name', 'publish status of brand', 'publish status of product', 'date of product publish in zaamo', 
            'pdp views', 'last_30_days pdp views', 'coming from', 'zaamo category', 'product_id', 'content ID', 'explore state', 'content url','brand order count', 
            'brand order count weekly','out of stock variants', 'shortlisted for shopify', 'tagged at', 'updated at']

        return headers

    @staticmethod
    @app.task
    def send_csv_email(filters):
        products = ExploreProductCSV(filters)
        mail = MailImpl()
        attachment = mail.get_csv_attachment_dict('explore.csv', products.get_rows(), fieldnames=products.get_headers())
        attachments = [attachment]
        mail.send_mail_with_attachment('explore_csv', 'Hi, Please find the attached file explore.csv', 'Explore products csv', attachments, recipient_email='rachit@zaamo.co')


    def get_rows(self):
        data = self.get_combined_data()
        rows = []
        while len(data) > 0:
            product = data.pop()
            row = {
                'brand name': product.get('brand__brand_name'),
                'product name': product.get('name'),
                'publish status of brand': product.get('brand__status'),
                'publish status of product': product.get('is_published'),
                'date of product publish in zaamo': product.get('publication_date'),
                'pdp views': product.get('pdp_views'),
                'last_30_days pdp views': product.get('last_30_days_pdp_views'),
                'coming from': product.get('brand__brand_source'),
                'zaamo category': product.get('category__name'),
                'product_id': product.get('product_id'),
                'content ID': product.get('content_id'),
                'explore state': product.get('state'),
                'content url': product.get('media_url'),
                'brand order count': NumberUtilities.convert_string_to_number(product.get('metadata__brand_order_count')),
                'brand order count weekly': NumberUtilities.convert_string_to_number(product.get('metadata__brand_order_count_weekly')),
                'out of stock variants' : ', '.join(self.out_of_stock_variants[product.get('id')]),
                'shortlisted for shopify': product.get('metadata__shopify') or 'FALSE',
                'tagged at': product.get('tagged_at'),
                'updated at': product.get('updated_at')
            }
            rows.append(row)
        if self.state:
            rows = [row for row in rows if StringUtilities.convert_object_to_string(row.get('explore state')).lower() in self.state]
        if self.source:
            rows = [row for row in rows if StringUtilities.convert_object_to_string(row.get('coming from')).lower() in self.source]
        if self.media_url:
            rows = [row for row in rows if StringUtilities.convert_object_to_string(row.get('content url')).lower() in self.media_url]
        
        rows.sort(key=lambda x: (x['brand order count weekly'], x['brand order count']), reverse=True)
        limit = NumberUtilities.convert_string_to_number(self.filters.get('limit', 0))
        if limit:
            offset = NumberUtilities.convert_string_to_number(self.filters.get('offset', 0))
            rows = rows[offset: offset + limit]

        return rows

    def apply_queryset_filters(self, queryset):
        filters = self.filters
        product_status = filters.get('product_status')
        brand_status = filters.get('brand_status')
        brand_name = filters.get('brand_name')
        start_date = filters.get('start_date')
        end_date = filters.get('end_date')
        brand_id = filters.get('brand_id')
        category = filters.get('category')
        
        if brand_name:
            brand_names = brand_name.split(',')
            brand_q = Q()
            for brand_name in brand_names:
                brand_q |= Q(brand_name__icontains=brand_name)
            brand_ids = Brand.objects.filter(brand_q).values_list('id', flat=True)
            brand_id = ','.join(graphene.Node.to_global_id('Brand', id) for id in brand_ids)
            self.filters['brand_id'] = brand_id
        if brand_id:
            brand_ids = []
            for _id in brand_id.split(','):
                bid = NumberUtilities.convert_string_to_number(_id) or graphene.Node.from_global_id(_id)[1]
                brand_ids.append(bid)
            self.filters['brand_gid'] = ','.join([graphene.Node.to_global_id('Brand', _id) for _id in brand_ids])
            queryset = queryset.filter(brand_id__in=brand_ids)
        if brand_status:
            brand_status = brand_status.split(',')
            queryset = queryset.filter(brand__status__in=brand_status)
        if product_status:
            product_status = True if product_status.lower() == 'true' else False
            queryset = queryset.filter(is_published=product_status)
        if category:
            category = category.split(',')
            category_q = Q()
            for name in category:
                cid = NumberUtilities.convert_string_to_number(name)
                if not cid:
                    try:
                        cid = graphene.Node.from_global_id(name)[1]
                    except Exception:
                        pass
                if cid:
                    category_q |= Q(category_id=cid)
                else:
                    category_q |= Q(category__name__icontains=name)
            queryset = queryset.filter(category_q)
        if start_date:
            queryset = queryset.filter(publication_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(publication_date__lt=end_date)

        return queryset

    def get_combined_data(self):
        content_data = self.get_explore_data()
        pdp_views = self.get_last_30_days_pdp_views()
        rows = []
        processed_products = set()
        processed_content = set()
        if self.state and len(self.state) == 1 and self.state[0] == 'show':
            pids = [graphene.Node.from_global_id(key)[1] for key in content_data.keys()]
            self.queryset = self.queryset.filter(id__in=pids)
        for product in self.queryset:
            pid = graphene.Node.to_global_id('Product', product['id'])
            product['product_id'] = pid
            if not pid in processed_products:
                processed_products.add(pid)
                for content in content_data.get(pid, []):
                    row = product.copy()
                    row.update(content)
                    row['last_30_days_pdp_views'] = pdp_views.get(product['id'])
                    if (row['media_url'], pid) in processed_content:
                        continue
                    if content.get('tagged'):
                        if content.get('media_type') == 'IMAGE':
                            row['brand__brand_source'] = 'photo content tag' 
                        elif content.get('media_type') == 'VIDEO':
                            row['brand__brand_source'] = 'video content tag' 
                    rows.append(row)
                    processed_content.add((row['media_url'], pid))

            if not product['images__image']:
                continue
            # media_url = f"https://{settings.AWS_MEDIA_BUCKET_NAME}.s3.amazonaws.com/{settings.AWS_LOCATION}/{product['images__image']}"
            # media_url = f"https://storage.googleapis.com/{settings.GS_MEDIA_BUCKET_NAME}/{settings.GS_LOCATION}/{product['images__image']}"
            media_url = f"https://{settings.AZURE_ACCOUNT_NAME}.blob.core.windows.net/{settings.AZURE_CONTAINER}/{settings.AZURE_LOCATION}/{product['images__image']}"
            if (media_url, pid) in processed_content:
                continue
            processed_content.add((media_url, pid))
            row = product.copy()
            row['media_url'] = media_url
            row['last_30_days_pdp_views'] = pdp_views.get(product['id'])
            rows.append(row)

        return rows

    def get_explore_data(self):
        host = settings.CONTENT_SERVICE_URL
        path = 'streaming/api/explore/product/'
        service_token = settings.CONTENT_SERVICE_TOKEN
        
        data = []
        has_next_page = True
        after_explore_id = 0
        after_content_id = 0
        page_count = 0
        while has_next_page and page_count < 1000:
            page_count += 1
            start = TimeUtilities.get_current_date_time()
            api_client = ApiClient(host=host, path=path, schema='http')
            api_client.add_header('SERVICE-TOKEN', service_token)
            api_client.update_url_params({
                'after_explore_id': after_explore_id,
                'after_content_id': after_content_id
            })
            if self.filters.get('brand_gid'):
                api_client.update_url_params({'brand_id': self.filters.get('brand_gid')})
            if self.filters.get('state'):
                api_client.update_url_params({'state': self.filters.get('state')})
            api_client.get()
            end = TimeUtilities.get_current_date_time() 
            
            code = api_client.fetch_response_code()
            res = api_client.fetch_response()
            has_next_page = res.get('meta').get('has_next_page', False)
            after_explore_id = res.get('meta').get('after_explore_id')
            after_content_id = res.get('meta').get('after_content_id')
            
            if res.get('data'):
                data += res.get('data')
            logger.info(f'get_explore_data response code: {code} data length: {len(res.get("data"))} started at: {start} took: {end - start}')
    
        _data = {}
        for product in data:
            pid = product['product_id']
            if not pid in _data:
                _data[pid] = []
            _data[pid].append(product)
        return _data
    
    def get_last_30_days_pdp_views(self):
        date_range = {
            'start_date': TimeUtilities.get_n_days_before_date(days=30).strftime('%Y-%m-%d'),
            'end_date': TimeUtilities.get_n_days_before_date(days=0).strftime('%Y-%m-%d')
        }
        product_views = dict()
        docs = get_product_views(date_range=date_range, group_by='product')
        for product in docs:
            product_views[NumberUtilities.convert_string_to_number(product['_id'])] = product['views']
        
        return product_views

class ExploreProductUploadCSV:

    def __init__(self, csv_file) -> None:
        rows = csv_file.read().decode('utf-8').splitlines()
        rows[0] = ','.join(column.strip().lower() for column in rows[0].split(','))
        header = []
        columns = rows[0].split(',')
        for column in columns:
            if 'state' in column.lower():
                column = 'state'
            elif 'url' in column.lower():
                column = 'media_url'
            header.append(column)
        rows[0] = ','.join(header)
        
        self.rows = rows

    def get_headers(self):
        if self.rows:
            return self.rows[0].split(',')
        return []

    def get_rows(self):
        if self.rows:
            return self.rows
        return []

    @staticmethod
    def get_cleaned_rows(rows):
        _data = [row for row in csv.DictReader(rows)]
        
        product_ids = [graphene.Node.from_global_id(media['product_id'])[1] for media in _data if media.get('state')]
        
        product_qs = Product.objects.filter(id__in=product_ids).values('id', 'is_published', 'brand_id', 'brand__status')
        products = dict()
        for product in product_qs:
            products[product['id']] = {
                'product_status': 1 if product.get('is_published') else 0,
                'brand_status': 1 if product.get('brand__status') != BrandStatusEnum.INACTIVE else 0,
                'brand_id': graphene.Node.to_global_id('Brand', product.get('brand_id'))
            }

        data = []
        for media in _data:
            row = dict()
            pid = NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(media['product_id'])[1])
            row.update(**products.get(pid, {}))
            row['product_id'] = media['product_id']
            row['media_url'] = media['media_url'].split(f'{settings.GS_LOCATION}/')[-1]
            row['state'] = media['state']
            if row['state']:
                data.append(row)
                
        return data

    @staticmethod
    @app.task
    def upload_csv(rows):
        data = ExploreProductUploadCSV.get_cleaned_rows(rows)
        
        _url = settings.CONTENT_SERVICE_URL + '/streaming/api/explore/product/upload/'
        service_token = settings.CONTENT_SERVICE_TOKEN

        batch_size = 1000
        size = len(data)
        for idx in range(0, size, batch_size):
            start = TimeUtilities.get_current_date_time()
            api_client = ApiClient(url=_url)
            api_client.add_header('SERVICE-TOKEN', service_token)
            api_client.body = {'data': data[idx: idx + batch_size]}
            api_client.post()
            end = TimeUtilities.get_current_date_time()

            code = api_client.fetch_response_code()
            res = api_client.fetch_response()
            logger.info(f'explore upload_csv: code: {code} started at: {start} took: {end - start}\nres: {res}')
            
class OrderLineCashgramCSV:


    query_set = []

    def __init__(self,start_date,end_date):
        query_set = OrderLineCashgram.objects.select_related('orderline','orderline__brand','refund_by_user').filter(created_at__gte=start_date, created_at__lte=end_date)
        self.query_set = query_set

    def get_headers_of_orderline_cashgram(self):
        return [
            "Order Id",
            "Refund By User",
            "Refund Status",
            "Brand Id",
            "Brand Name",
            "Refund Amount",
            "Created At",
            "Updated At"
            ]
    
    def get_queryset(self):
        return self.query_set
    
    def get_order_id(self,orderline_cashgram_instance):

        order_id = orderline_cashgram_instance.orderline.order_id
        order_id = graphene.Node.to_global_id("Order",order_id )
        return order_id
    
    def get_refund_by_user(self,orderline_cashgram_instance):
        user = orderline_cashgram_instance.refund_by_user
        email  = user.email
        if email:
            return email
        else:
            return None 

    def get_refund_amount(self,orderline_cashgram_instance):

        return orderline_cashgram_instance.refund_amount
    
    def get_refund_status(self,orderline_cashgram_instance):

        return orderline_cashgram_instance.refund_status

    def get_brand_id(self,orderline_cashgram_instance):

        orderline  = orderline_cashgram_instance.orderline
        brand_id = orderline.brand_id
        brand_id = graphene.Node.to_global_id("Brand",brand_id)
        return brand_id
    
    def get_brand_name(self,orderline_cashgram_instance):

        orderline = orderline_cashgram_instance.orderline
        brand_name = orderline.brand.brand_name

        return brand_name

    def get_created_at(self,orderline_cashgram_instance):

        return orderline_cashgram_instance.created_at

    def get_updated_at(self,orderline_cashgram_instance):

        return orderline_cashgram_instance.updated_at

class PublishedProductsCSV():
    query_set = []

    def __init__(self):
        query_set = Product.objects.select_related('brand','default_variant').filter(is_published=True)
        self.query_set = query_set

    def get_headers_of_published_products_csv(self):
        return [
            "Id",
            "Product Name",
            "Brand Name",
            "MRP",
            "Customer MSP",
            "Step Price",
            "True MSP",
            "PDP Views weekly",
            "Brand Order Count Weekly",
            "Category",
            "Shopify",
            "COD Price",
            "is COD applicable",
            "Step Price Active",
            "Shipping Same State",
            "Shipping Other State",
            "Min Value Amount for Free shipping",
        ]
    
    def get_queryset(self):
        return self.query_set

class TopProductViewsCSV:

    def __init__(self):
        self.yesterday_views = self.get_yesterday_views()
        self.product_ids = list(self.yesterday_views.keys())
        self.last_week_views = self.get_last_week_views()
        
        self.product_qs = Product.objects.filter(id__in=self.product_ids).values('id', 'brand__brand_name', 'name', 'default_variant__price_amount', 
        'default_variant__cost_price_amount', 'slug', 'category__name', 'brand__commission__commission_percentage', 'brand__commission__zaamo_commission', 
        'step_price', 'brand__brand_shipping__shipping_cost_other_state_amount', 'brand__cod_base_price', 'brand__cod')

        self.variant_qs = ProductVariant.objects.filter(product_id__in=self.product_ids)\
            .annotate(quantity=Case(When(track_inventory=False, then=Value('50')), default=Sum('stocks__quantity'), output_field=IntegerField()))\
                .filter(quantity=0).values('product_id', 'name')
        
        last_week = TimeUtilities().subtract_time_from_timestamp(TimeUtilities().get_today_start(), days=7)
        self.checkout_qs = CheckoutLine.objects.filter(checkout__last_change__gt=last_week).filter(variant__product_id__in=self.product_ids)\
                            .annotate(pid=F('variant__product_id')).values('pid').annotate(count=Count('id')).order_by('pid').values('pid', 'count')
        self.order_qs = OrderLine.objects.filter(created_at__gt=last_week).filter(metadata__fake__isnull=True).filter(variant__product_id__in=self.product_ids)\
                            .annotate(pid=F('variant__product_id')).values('pid').annotate(count=Count('id')).order_by('pid').values('pid', 'count')

    def get_headers(self):
        headers = ["brand name", "product name", "MSP", "MRP", "product link", "pdp views yesterday", "pdp views last 7 days", 
                    "a2c last 7 days", "orders last 7 days", "category", "brand total commission", "zaamo commission", "step price", 
                    "out of stock variants", "shipping fees", "COD fees"]
        return headers

    def get_rows(self):
        rows = []
        checkout_count = {checkout['pid']: checkout['count'] for checkout in self.checkout_qs}
        order_count = {order['pid']: order['count'] for order in self.order_qs}
        out_of_stock = self.get_out_of_stock_variants()
        for product in self.product_qs:
            row = [
                product.get('brand__brand_name'),
                product.get('name'),
                product.get('default_variant__price_amount'),
                product.get('default_variant__cost_price_amount'),
                f"https://zaamo.co/zaamo/products/{product.get('slug')}",
                self.yesterday_views.get(str(product['id']), 0),
                self.last_week_views.get(str(product['id']), 0),
                checkout_count.get(product['id'], 0),
                order_count.get(product['id'], 0),
                product.get('category__name'),
                product.get('brand__commission__commission_percentage'),
                product.get('brand__commission__zaamo_commission'),
                product.get('step_price'),
                ','.join(out_of_stock.get(product['id'], [])),
                product.get('brand__brand_shipping__shipping_cost_other_state_amount'),
                product.get('brand__cod_base_price') if product.get('brand__cod') else 'NA',
            ]
            rows.append(row)
        rows.sort(key=lambda row: row[5], reverse=True)
        return rows

    def get_yesterday_views(self):
        today = TimeUtilities().get_today_start()
        yesterday = TimeUtilities().get_yesterdays_date()
        date_range = set_time_date_ga(yesterday, today)
        yesterday_views = get_top_products_by_views(date_range)

        return yesterday_views

    def get_last_week_views(self):
        today = TimeUtilities().get_today_start()
        last_week = TimeUtilities().subtract_time_from_timestamp(today, days=7)
        date_range = set_time_date_ga(last_week, today)
        week_views = get_top_products_by_views(date_range, product_ids=self.product_ids, limit=None)

        return week_views

    def get_out_of_stock_variants(self):
        out_of_stock = dict()
        for variant in self.variant_qs:
            if not variant['product_id'] in out_of_stock:
                out_of_stock[variant['product_id']] = []
            out_of_stock[variant['product_id']].append(variant['name'])
        return out_of_stock

class ShopifyCSV:

    def __init__(self, brand_ids, size_chart=None) -> None:

        self.brand_ids = brand_ids
        self.size_chart_only = size_chart
        self.product_ids = Product.objects.filter(brand_id__in=brand_ids).values_list('id', flat=True)
        self.queryset = ProductVariant.objects.filter(product_id__in=self.product_ids).annotate(quantity=Case(When(track_inventory=False, then=Value('50')), default=Sum('stocks__quantity'), output_field=IntegerField()))\
                        .values('id', 'product__name', 'product__description_json__description_text', 'cost_price_amount', 'price_amount', 'product__slug', 'product__brand__brand_name', 'product__category__name', 
                            'product__category_id', 'quantity', 'price_amount', 'product__publication_date', 'product_id', 'name', 'product__brand__status', 'product__is_published', 'product__product_type__name'
                        )
        
    def get_rows(self):
        
        if self.size_chart_only:
            return self.get_size_chart_rows()
        
        products = dict()
        tags = self.get_product_tags()
        product_images = self.get_product_images()
        
        for variant in self.queryset:
            pid = variant.get('product_id')
            if not pid in products:
                products[pid] = []
            products[pid].append(variant)
        
        rows = []
        IMAGE_URL_PREFIX = f"https://storage.googleapis.com/{settings.GS_MEDIA_BUCKET_NAME}/{settings.GS_LOCATION}"
        for pid, variants in products.items():
            images = product_images.get(pid)
            tag = ','.join(tags.get(pid))
            if not images:
                continue
            img_count = len(images)
            for idx, (variant, image_key) in enumerate(zip_longest(variants, images), start=1):
                pos = min(idx, img_count)
                if variant:
                    if not variant.get("product__description_json__description_text"):
                        variant['product__description_json__description_text'] = '<p> Zaamo Exclusive Catalogue <p>'
                    row = {
                        "Handle": variant.get("product__slug"),
                        "Title": variant.get("product__name"),
                        "Body (HTML)": '<html><body>' + variant.get("product__description_json__description_text") +'</body></html>',
                        "Vendor": variant.get("product__brand__brand_name"),
                        "Product Category": "Apparel & Accessories > Clothing",
                        "Type": variant.get("product__category__name"),
                        "Option1 Name": "Size",
                        "Option1 Value": variant.get('name'),
                        "Tags": tag,
                        "Published": variant.get('product__is_published'),
                        "Variant SKU": variant.get('id'),
                        "Variant Inventory Qty": variant.get('quantity'),
                        "Variant Price": variant.get('price_amount'),
                        "Image Src": f"{IMAGE_URL_PREFIX}/{image_key}" if image_key else '',
                        "Status": variant.get("product__brand__status"),
                        "Variant Inventory Policy": "deny",
                        "Variant Fulfillment Service": "manual",
                        "Image Position": pos, 
                        "Variant Inventory Tracker": "Shopify",
                        "Variant Compare At Price": variant.get('cost_price_amount')
                    }
                else:
                    row = {
                        "Handle": variants[0].get("product__slug"),
                        "Image Src": f"{IMAGE_URL_PREFIX}/{image_key}" if image_key else '',
                        "Image Position": pos
                    }
                rows.append(row)
        
        return rows
    
    def get_size_chart_rows(self):
        products = Product.objects.filter(brand_id__in=self.brand_ids).values_list('id', 'slug', 'brand_id')
        size_charts = self.get_size_charts()
        rows = []
        for product_id, slug, brand_id in products:
            pid = graphene.Node.to_global_id('Product', product_id)
            bid = graphene.Node.to_global_id('Brand', brand_id)
            row = {
                'Handle': slug,
                'Image Src': size_charts.get(pid) or size_charts.get(bid)
            }
            rows.append(row)
        return rows

    def get_size_charts(self):
        size_charts = dict()
        url = settings.CONTENT_SERVICE_URL + '/streaming/api/size_chart/'
        api_client = ApiClient(url=url)
        api_client.add_header('SERVICE-TOKEN', settings.CONTENT_SERVICE_TOKEN)
        
        max_count = 100000
        limit = 10000
        brand_ids = [graphene.Node.to_global_id('Brand', brand_id) for brand_id in self.brand_ids]
        for offset in range(0, max_count, limit):
            api_client.body = {'brand_ids': brand_ids, 'offset': offset, 'limit': limit}
            api_client.post()
            data = api_client.fetch_response().get('data', {})
            size_charts.update(data)
            
            if len(data.keys()) < limit:
                break
        
        return size_charts
    
    @staticmethod
    def get_headers():
        headers = ["Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "Published", "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name", "Option3 Value", 
                   "Variant SKU", "Variant Grams", "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service", "Variant Price", "Variant Compare At Price", 
                   "Variant Requires Shipping", "Variant Taxable", "Variant Barcode", "Image Src", "Image Position", "Image Alt Text", "Gift Card", "SEO Title", "SEO Description", "Google Shopping / Google Product Category", 
                   "Google Shopping / Gender", "Google Shopping / Age Group", "Google Shopping / MPN", "Google Shopping / AdWords Grouping", "Google Shopping / AdWords Labels", "Google Shopping / Condition", 
                   "Google Shopping / Custom Product", "Google Shopping / Custom Label 0", "Google Shopping / Custom Label 1", "Google Shopping / Custom Label 2", "Google Shopping / Custom Label 3", 
                   "Google Shopping / Custom Label 4", "Variant Image", "Variant Weight Unit", "Variant Tax Code", "Cost per item", "Price / International", "Compare At Price / International", "Status"]
        return headers
        
    def get_product_tags(self):
        queryset = Product.objects.filter(id__in=self.product_ids).values_list('id', 'through_product_tag_product__product_tag__name')
        tags = dict()
        for id, tag in queryset:
            if not id in tags:
                tags[id] = set()
            if tag:
                tags[id].add(tag)
        return tags

    def get_product_images(self):
        image_qs = ProductImage.objects.filter(product_id__in=self.product_ids).order_by('id').values_list('product_id', 'image')
        
        images = dict()
        for pid, image in image_qs:
            if not pid in images:
                images[pid] = []
            images[pid].append(image)
        return images


class ShopifyProductDetailsCSV:

    def __init__(self, start_date=None,end_date=None) -> None:

        self.qs= ZaamoShopifyProductMapping.objects.all().select_related('product_zaamo','product_zaamo__brand','product_zaamo__default_variant')
        self.start_date = start_date
        self.end_date = end_date

        out_of_stock_qs = Stock.objects.select_related("product_variant")\
                .values("product_variant__product_id","product_variant__name")\
                .annotate(
                    total_quantity_allocated=Coalesce(Sum("allocations__quantity_allocated"), 0)\
                )\
                .annotate(total_quantity=Coalesce(Sum("quantity",distinct=True), 0))\
                .annotate(total_available=Case(When(product_variant__track_inventory=False, then=1),\
                default=(F("total_quantity") - F("total_quantity_allocated"))))\
                .filter(product_variant__product_id__in=self.qs.values('product_zaamo_id'), total_available__lte=0)

        self.out_of_stock_variants = defaultdict(list)

        for out_of_stock_v in out_of_stock_qs:
            self.out_of_stock_variants[out_of_stock_v['product_variant__product_id']].append(out_of_stock_v['product_variant__name'])

        self.effective_revenue = defaultdict(lambda: (0, 0))

        brand_commisions = Commission.objects.filter(brand_id__in=self.qs.values('product_zaamo__brand_id'))
        
        brand_commisions_dict  = {com.brand_id:(com.commission_percentage,com.zaamo_commission) for com in brand_commisions}

        brand_shipping_dict = self.get_shipping_data()
        
        for zaamo_product in self.qs.only('product_zaamo','product_id_brand','extra_charges').distinct():

            if self.effective_revenue.get(zaamo_product.product_id_brand):
                continue
            
            brand_comm_tuple=brand_commisions_dict.get(zaamo_product.product_zaamo.brand_id,(0,2))

            ship_charge = NumberUtilities.convert_string_to_decimal(brand_shipping_dict[zaamo_product.product_zaamo.brand_id][0]) if NumberUtilities.convert_string_to_decimal(brand_shipping_dict[zaamo_product.product_zaamo.brand_id][2]) > zaamo_product.product_zaamo.default_variant.price_amount else 0

            cod_charge = NumberUtilities.convert_string_to_decimal(brand_shipping_dict[zaamo_product.product_zaamo.brand_id][1])
            
            try:
                self.effective_revenue[zaamo_product.product_id_brand] = (self.get_zaamo_commission_using_step_pricing(brand_comm_tuple[0],zaamo_product.product_zaamo.default_variant,brand_comm_tuple[1],ship_charge)+(zaamo_product.extra_charges-ship_charge),self.get_zaamo_commission_using_step_pricing(brand_comm_tuple[0],zaamo_product.product_zaamo.default_variant,brand_comm_tuple[1],cod_charge)+(zaamo_product.extra_charges+100-cod_charge))
                
            except Exception as e:
                
                continue

        self.qs = self.qs.values('product_zaamo__name','product_zaamo__step_price','extra_charges','product_zaamo__brand__brand_name','product_zaamo__brand__private_metadata__source_name','product_zaamo_id','product_zaamo__default_variant__price_amount','product_zaamo__default_variant__cost_price_amount','product_zaamo__brand_id','product_id_brand','variant_zaamo_id','product_zaamo__metadata__brand_order_count_monthly','product_zaamo__slug')
        
    
    def brand_order_count_on_brand_level(self):

        brand_order_month_count = BrandOrderCount.objects.all().values('brand_name').order_by('brand_name').annotate(order_counts=Sum('brand_order_count_last_month'))

        brand_order_month_count_dict = {order_c['brand_name']:order_c['order_counts'] for order_c in brand_order_month_count}

        return brand_order_month_count_dict

    def get_order_line_data(self):

        orders_zaamo_monthly = defaultdict(int)
        orders_cod_zaamo_monthly = defaultdict(int)
        time_filter = TimeUtilities.get_n_days_before_date(30)
        order_lines_qs = OrderLine.objects.filter(created_at__gte=time_filter,metadata__shopify=True).select_related('variant')
        
        order_lines_qs = order_lines_qs.annotate(pid=F('variant__product_id')).values('pid').annotate(count=Count('id'),
                count_cod=Count(Case(When(cod=True,then=1)))
                ).order_by('pid').values('pid', 'count','count_cod')
        
        for i in order_lines_qs:
            
            orders_zaamo_monthly[i['pid']] = i['count']
            orders_cod_zaamo_monthly[i['pid']] = i['count_cod']

        return orders_zaamo_monthly,orders_cod_zaamo_monthly

    def get_shipping_data(self):
        
        brand_shipping_subquery = BrandShippingData.objects.filter(brand=OuterRef('id')).order_by('id').values('shipping_cost_same_state_amount')[:1]
        brand_minimum_cos_subquery = BrandShippingData.objects.filter(brand=OuterRef('id')).order_by('id').values('min_order_value_free_cost_amount')[:1]
        
        brand_obj_list = Brand.objects.filter(id__in = self.qs.values('product_zaamo__brand_id')).annotate(shipping_price=Subquery(brand_shipping_subquery),minimum_cost=Subquery(brand_minimum_cos_subquery)).values('id','cod_base_price','shipping_price','status','minimum_cost')

        brand_shipping_dict = defaultdict(lambda: (0, 0, 0))
        
        for shipping_data in brand_obj_list:

            cod_price = shipping_data.get('cod_base_price') or 0
            ship_price = shipping_data.get('shipping_price') or 0
            min_price = shipping_data.get('minimum_cost') or 0

            brand_shipping_dict[shipping_data.get('id')] = (ship_price,cod_price,min_price)

        return brand_shipping_dict
        
    
    def brand_commission_fetch(self):
        
        brand_commissions = Commission.objects.all().annotate(total_commission=F('zaamo_commission')+F('commission_percentage')).values('brand_id','total_commission','commission_percentage')
        brand_commission_dict = {comm['brand_id']:comm['total_commission'] for comm in brand_commissions}
        influencer_commission_dict = {comm['brand_id']:comm['commission_percentage'] for comm in brand_commissions}

        return brand_commission_dict,influencer_commission_dict

    def get_delayed_and_placed_order_count(self):

        delayed_orders_qs = Brand.objects.all().values('id').annotate(delayed_orders_count=Count('order_lines__id', filter=Q(order_lines__metadata__status__in=[FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS], order_lines__metadata__brand_order_status='delayed')),placed_orders_count=Count('order_lines__id', filter=Q(order_lines__metadata__status__in=[FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS]))).values('id', 'delayed_orders_count','placed_orders_count')
        
        delayed_orders = {ins['id']: ins['delayed_orders_count'] for ins in delayed_orders_qs}

        placed_orders = {ins['id']: ins['placed_orders_count'] for ins in delayed_orders_qs}

        return delayed_orders, placed_orders
    
    def get_rows(self):

        orders_zaamo_monthly,orders_cod_zaamo_monthly = self.get_order_line_data()
        orders_placed_zaamo_monthly,orders_delayed_zaamo_monthly = self.get_delayed_and_placed_order_count()
        brand_order_count_brand_level = self.brand_order_count_on_brand_level()

        brand_commission_dict,influencer_commission_dict = self.brand_commission_fetch()

        rows = []
        done = []
        
        for i in self.qs :

            if i.get('product_zaamo_id') in done:
                continue

            infl_comm = i.get('product_zaamo__default_variant__price_amount')*NumberUtilities.convert_string_to_decimal(influencer_commission_dict.get(i.get('product_zaamo__brand_id'),0))/100
            
            price_amount = math.ceil(i.get('product_zaamo__default_variant__price_amount')+i.get('extra_charges'))
            cost_price_amount = math.ceil(i.get('product_zaamo__default_variant__cost_price_amount')+i.get('extra_charges'))

            source_brand_name = i.get('product_zaamo__brand__private_metadata__source_name')
            
            row = [
                    i.get('product_id_brand'),
                    brand_order_count_brand_level.get(source_brand_name),
                    i.get('product_zaamo__metadata__brand_order_count_monthly',0),
                    orders_zaamo_monthly.get(i.get('product_zaamo_id'),0),
                    orders_cod_zaamo_monthly.get(i.get('product_zaamo_id'),0),
                    brand_commission_dict.get(i.get('product_zaamo__brand_id'),0),
                    i.get('product_zaamo__step_price'),
                    orders_delayed_zaamo_monthly.get(i.get('product_zaamo__brand_id'),0),
                    orders_placed_zaamo_monthly.get(i.get('product_zaamo__brand_id'),0),
                    i.get('product_zaamo__name'),
                    i.get('product_zaamo__brand__brand_name'),
                    price_amount,
                    cost_price_amount,
                    f"https://zaamo.co/zaamo/products/{i.get('product_zaamo__slug')}",
                    ', '.join(self.out_of_stock_variants[i.get('product_zaamo_id')]),
                    self.effective_revenue[i.get('product_id_brand')][0],
                    self.effective_revenue[i.get('product_id_brand')][1],
                    self.effective_revenue[i.get('product_id_brand')][0]+infl_comm,
                    self.effective_revenue[i.get('product_id_brand')][1]+infl_comm
                    
                 ]

            done.append(i.get('product_zaamo_id'))
            rows.append(row)
            
        return rows
    
    @staticmethod
    def get_headers():
        # headers = ['Product Name','Brand Name','Product ID','Zaamo Shopify Order All Time','MSP','MRP','Shopify Product Link','Image Url','Zaamo Store PDP link','Brand Status','Is Published on Zaamo','Shopify Product Status','Shopify Product Id']
        headers = [
                    'Shopify Product Id',
                    'brand 30 days brand order count',
                    'product 30 days brand order count',
                    'product 30 days zaamo order count',
                    'product 30 days zaamo cod order count',
                    'brand total commission',
                    'Step Price',
                    'Delayed order count for brand',
                    'inprocess/placed order count for brand' ,
                    'Product Name',
                    'Brand Name',
                    'MSP',
                    'MRP',
                    'Zaamo Store PDP link',
                    'out of stock variants',
                    'effective_commission_paid',
                    'effective_commission_cod',
                    'effective_with_influencer_commission_paid',
                    'effective_with_influencer_commission_cod'
                    ]
        return headers
        
    def get_product_images(self):
        image_qs = ProductImage.objects.filter(product_id__in=self.qs.values('product_zaamo_id')).order_by('id').values_list('product_id', 'image')
        
        images = dict()
        for pid, image in image_qs:
            if not pid in images:
                images[pid] = []
            images[pid].append(image)
        return images


    def get_zaamo_commission_using_step_pricing(self,commission_percentage,variant,zaamo_commission_percentage_brand,extra_charge=Decimal('0.00')):
        zaamo_commission_percentage_brand = NumberUtilities.convert_string_to_decimal(zaamo_commission_percentage_brand/100)
        
        try:
            
            true_msp = NumberUtilities.convert_string_to_decimal(variant.metadata.get('true_msp'))
            cur_MSP = NumberUtilities.convert_string_to_decimal(variant.price_amount)

            influencer_commission = NumberUtilities.convert_string_to_decimal(commission_percentage/100) if commission_percentage else NumberUtilities.convert_string_to_decimal("0.0")
            percent_without_influencer_commission = 1 - influencer_commission
            
            if not true_msp:
                true_msp = cur_MSP

            zaamo_commission_percentage = percent_without_influencer_commission - (percent_without_influencer_commission-zaamo_commission_percentage_brand)*((true_msp+extra_charge)/(cur_MSP+extra_charge))
            
            return round((cur_MSP+extra_charge)*zaamo_commission_percentage,2)
        
        except Exception as e:
            return cur_MSP*zaamo_commission_percentage_brand
        

class OrderCalculations(OrderCsvContext):

    def __init__(self) -> None:
        pass
    
    def get_shopify_url(self,orderline_instance):
        mapping = orderline_instance.order_line_zaamo.first()

        if mapping:
            return mapping.metadata.get('shopify_url','')
        
        return ''

    def get_order_related_calculations(self,order_id):
        lines = OrderLine.objects.filter(order_id=order_id).select_related('brand','variant','variant__product').prefetch_related('brand__commission')
        
        if not lines:
            return {'order_id':order_id, 'message':"No order with this order id."}
        
        lines_resp = []

        for line in lines:
            zaamo_order_line_price = get_zaamo_order_line_price(line)
            commission = line.brand.commission.first()
            fulfillment = line.fulfillment_line.first().fulfillment
            zaamo_shopify_price = '{:.2f}'.format(get_orderline_shopify_price(line))
            shipping_cod_on_brand_side = NumberUtilities.convert_string_to_float(get_shipping_or_cod_charge(line)) + NumberUtilities.convert_string_to_float(self.get_shopify_charge(line))

            extra_shopify_charge = self.get_shopify_charge(line)
            platform_fees_without_extra_charge = NumberUtilities.convert_string_to_decimal(line.metadata.get('platform_fees')) - extra_shopify_charge

            if shipping_cod_on_brand_side:
                cod_str = 'shipping' if not line.cod else 'COD'
                desc_price = f"(including {cod_str} charge: {shipping_cod_on_brand_side})"

            if not line.cod:
                msp_plus_shipping = self.get_msp(line) + self.get_shipping_price(line)
                brand_due_amount_desc = f" msp+shipping ({msp_plus_shipping}) - platform_fees_without_extra_charge ({platform_fees_without_extra_charge}) - influencer_commission ({line.metadata.get('influencer_commission')})"
            else:
                brand_due_amount_desc = f" - platform_fees ({line.metadata.get('platform_fees')}) - influencer_commission ({line.metadata.get('influencer_commission')})"


            step_price = self.get_msp(line) - self.get_true_msp(line)
            lines_resp.append({
                'order_line_id' : line.id,
                'brand_name' : line.brand.brand_name,
                'product_name' : line.product_name,
                'COD' : line.cod,
                'influencer_commission(Brand)' : commission.commission_percentage,
                'zaamo_commission(Brand)' : commission.zaamo_commission,
                'zaamo_shopify_price' : f"{zaamo_shopify_price} {desc_price}",
                'zaamo_price(if order placed on zaamo directly)' : zaamo_order_line_price,
                'step_price' : step_price,
                'mrp' : self.get_mrp(line),
                'msp' : f"{self.get_msp(line)} :: true_msp({self.get_true_msp(line)}) + step_price({step_price})",
                'true_msp' : self.get_true_msp(line),
                'order_price_placed_on_brand_side' : "{:.2f}".format(get_brand_order_price_cod_paid(line)) + f" {desc_price}",
                'shipping/cod_charge_on_brand_side' : shipping_cod_on_brand_side,
                'shipping_charge_on_zaamo_order_line' : self.get_shipping_price(line) if not line.cod else 0,
                'cod_charge_on_zaamo_order_line' : line.metadata.get('cod_price') if line.cod else 0,
                'discount_amount' : line.metadata.get('discount_amount'),
                'influencer_commission_on_order_line' : line.metadata.get('influencer_commission'),
                'extra_shopify_charged_on_zaamo' : f"{extra_shopify_charge}",
                'platform_fees_percentage' : line.metadata.get('platform_percentage'),
                'platform_fees' : f"{line.metadata.get('platform_fees')} := ((msp ({self.get_msp(line)}) + {cod_str} ({self.get_shipping_price(line) if not line.cod else line.metadata.get('cod_price')}) * {line.metadata.get('platform_percentage')} %) : {platform_fees_without_extra_charge} + (Extra shopify charge) : {extra_shopify_charge})",
                'brand_due_amount' : f"{line.metadata.get('brand_due_amount')} := {brand_due_amount_desc}",
                'revenue' : line.metadata.get('revenue'),
                'revenue_with_shopify_markup' : line.metadata.get('revenue_with_shopify_markup'),
                'platform' : 'SHOP' if line.metadata.get('shopify') else 'IS',
                'order_status' : fulfillment.status,
                'order_created_at' : TimeUtilities.convert_datetime_to_string(line.created_at),
                'order_status_updated' : TimeUtilities.convert_datetime_to_string(fulfillment.updated_at),
                'shopify_url' : self.get_shopify_url(line)
            })

        return {'order_id':order_id,'lines':lines_resp}
