from collections import defaultdict
from dataclasses import field
import datetime
from decimal import Decimal
import graphene
from django.db.models.aggregates import Count, Avg, Sum
from django.db.models import Case, When, IntegerField, F, Q, Subquery, DecimalField
from django.db.models.functions import Coalesce, Cast
from django.db.models import OuterRef
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from graphene_django.registry import Registry
from saleor.discount.models import Voucher
from saleor.graphql.analytics.sorters import OrderLineSortingInput, StoreAnalyticsSortField
from saleor.graphql.utils import resolve_global_ids_to_primary_keys
from graphql.language.ast import (BooleanValue, StringValue, IntValue, ListValue,
 ObjectValue, FloatValue, Variable, EnumValue)
from saleor.brand.models import Brand
from saleor.graphql.product.sorters import  ProductOrderField
from saleor.graphql.product.types.products import Category, ProductType, ProductVariant
from saleor.graphql.core.connection import CountableDjangoObjectType
from saleor.graphql.core.fields import FilterInputConnectionField, PrefetchingConnectionField
from saleor.graphql.product.dataloaders.products import ImagesByProductIdLoader
from saleor.graphql.store.types import Store, StoreManagerActions
from saleor.graphql.order.types import Fulfillment, OrderLine
from saleor.notifications.models import Device
from saleor.order.utils import get_voucher_discount_for_orderline
from saleor.product.templatetags.product_images import get_product_image_thumbnail
from saleor.store.store_utilities import get_all_collections, get_all_products
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.wishlist.models import Wishlist
from ...order import models
from saleor.product import SourcingRequestStatus, models as product_models
from saleor.order import models as order_models
from saleor.order import FulfillmentStatus
from saleor.graphql.order.filters import time_period as time_period_filter
from saleor.store import models as store_models
from ..meta.types import ObjectWithMetadata
from graphene import relay
from ..core.types import Image
from saleor.graphql.store.enums import StoreAppEnum
from .enums import SortDirectionEnum
from saleor.graphql.order.enums import OrderFullfillmentStatusEnum
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.external_services.google_analytics.ga_helper import get_product_views
from saleor.checkout.models import CheckoutLine

from saleor.graphql.order.enums import TimePeriod
from saleor.graphql.analytics.resolvers import (brand_commission_queryset, checkout_store_queryset, order_store_queryset, orderline_store_product_brand_queryset,
        product_wishlist_queryset, product_google_analytics_queryset, collection_google_analytics_queryset,
        resolve_fulfillments, resolve_likes_count,
        resolve_my_order_lines,resolve_order_line, resolve_order_line_from_store_excluding_influencer, 
        resolve_orders_count, resolve_product_type_of_brand, store_google_analytics_queryset, variant_product_order_queryset, voucher_store_queryset,
        resolve_total_earning,aggregate_product_analytics,resolve_store_visits,resolve_store_count_product, resolve_wishlist_count_product,paginated_resolve_product_of_brand,
        resolve_publication_date_product,resolve_is_published_product,resolve_due_amount )

class BaseAnalyticsMixin(object):

    @classmethod
    def get_selection_field_argument_value(cls, info, selection_name, argument_name):
        selections = info.operation.selection_set.selections

        for selection in selections:
            if selection.name.value == selection_name:
                for argument in selection.arguments:
                    if argument.name.value == argument_name:
                        
                        if isinstance(argument.value, (Variable)):
                            return info.variable_values.get(argument.value.name.value, '')

                        elif isinstance(argument.value, (BooleanValue, StringValue, IntValue, FloatValue, EnumValue)):
                            if hasattr(argument.value, "value"):
                                return argument.value.value
                        elif  isinstance(argument.value, (ObjectValue)):
                            _dict = {}
                            # for single level of nesting
                            for field in argument.value.fields:
                                key = field.name.value
                                if isinstance(field.value, (BooleanValue, StringValue, IntValue, FloatValue, EnumValue)):
                                    value = field.value.value
                                elif isinstance(field.value, (ListValue)):
                                    value = [value.value for value in field.value.values]
                                elif isinstance(field.value, (Variable)):
                                    value = info.variable_values.get(field.value.name.value, '')
                                else:
                                    value = ''
                                _dict.update({key:value})         
                            return _dict
                        else:
                            return info.variable_values.get(argument.value.name.value, '')

        return ''


    @classmethod
    def get_queryset(cls, queryset, info):
        user = info.context.user
        authorised_brands = user.get_authorised_brands()
        authorised_stores = user.get_authorised_stores()
        setattr(info.context, 'authorised_brands', authorised_brands)
        setattr(info.context, 'authorised_stores', authorised_stores)
        return super().get_queryset(queryset, info)

class Dashboard(graphene.ObjectType):
    date = graphene.String(description="date of metric")
    active_influencer_count = graphene.Int(description="count of influencer stores")
    wishlist_count = graphene.Int(description="count of wishlist")
    signups_count = graphene.Int(description="count of signups")
    purchase_count = graphene.Decimal(description="purchase count of all stores")
    products_added_in_collections = graphene.Int(description="count of products added in collections")
    abandoned_cart_count = graphene.Int(description="count of abandoned cart")
    total_site_visits = graphene.Int(description="count of total site visits")
    total_store_visits = graphene.Int(description="count of total store visits")
    total_product_visits = graphene.Int(description="count of total pdp visits")
    total_collection_visits = graphene.Int(description="count of total collection visits")
    total_landing_page_visits = graphene.Int(description="count of Zaamo.co visits")  
    total_selling_price = graphene.Decimal(description="total selling price of Zaamo.co")
    total_brand_discount = graphene.Decimal(description="total brand discount amount of Zaamo.co")
    total_coupon_adjustments = graphene.Decimal(description="total coupon adjustments of Zaamo.co")
    total_net_gmv = graphene.Decimal(description="total selling price + total shipping price of IS in Zaamo.co")
    per_day_checkout_count = graphene.Int(description="count of checkouts per day")
    per_day_order_count = graphene.Int(description="count of orders per day")  

    class Meta:
        description = "Represents user address data."


class MasterDashboard(BaseAnalyticsMixin, CountableDjangoObjectType):
    created = graphene.String() 
    id = graphene.ID(description = "Decode as Order : id",required = True)
    store = graphene.Field(Store, description="Store to which this order is related")
    lines = graphene.List(
        lambda: OrderLine, required=True, description="List of order lines.",
        )
    fulfillments = graphene.List(
        Fulfillment, required=True, description="List of shipments for the order.",
    )
    source = graphene.String(description="Info of store app")

    streak_order = graphene.Boolean(description="boolean value if order was a streak order or not")


    class Meta:
        description = "Master Dashboard"

        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Order
        only_fields = [
            "billing_address",
            "created",
            "customer_note",
            "discount",
            "discount_name",
            "display_gross_prices",
            "gift_cards",
            "language_code",
            "shipping_address",
            "shipping_method",
            "shipping_method_name",
            "shipping_price",
            "status",
            "token",
            "tracking_client_id",
            "translated_discount_name",
            "user",
            "voucher",
            "weight",
            "app_code"
        ]

    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)

        cls.filter_data = cls.get_selection_field_argument_value(info, "masterDashboard", 
        "filter")
        
        user = info.context.user
        authorised_brands = info.context.authorised_brands
        
        qs = qs.filter(id__in=qs.filter(lines__brand__in=authorised_brands).values_list('id', flat=True))
        qs = qs.select_related("shipping_address", "billing_address", "user", "voucher")

        if user.is_user_brand_part():
            return qs

        authorised_stores = info.context.authorised_stores

        return qs.store_orders(authorised_stores)

    def resolve_id(root:models.Order , _info):
        return graphene.Node.to_global_id("Order",root.id)

    def resolve_source(root: models.Order, _info):
        
        if root.metadata.get('shopify'):
            source = "SHOP"
            return source
        
        if root.app_code == PlatformTypeEnum.INFLUENCER_HOME:
            source = "IH APP"
        elif root.app_code == PlatformTypeEnum.ZAAMO_STORE:
            source = "ZS APP"
        elif root.platform_code == PlatformTypeEnum.INFLUENCER_HOME:
            source = "IH"
        else:
            source = "IS"
            
        return source

    def resolve_store(root: models.Order, _info):
        order_store = root.order_store.select_related("store").first()
        if order_store:
            return order_store.store
        return None
    
    def resolve_streak_order(root: models.Order, _info):
        order_store = root.order_store.first()
        if order_store:
            return order_store.streak_order
        return None

    def resolve_created(root: models.Order, _info):
    
        if root.created:
            return TimeUtilities.parse_date(root.created, date_format="%d %b %Y")
        return root.created

    def resolve_fulfillments(root: models.Order, _info):
        brands = MasterDashboard.filter_data.get("brands", "")
        
        if brands:
            type, brands = resolve_global_ids_to_primary_keys(brands)
        else:
            brands = []
        
        brands = [NumberUtilities.convert_string_to_number(id) for id in brands]

        if brands:
            setattr(_info.context, 'brand_id', brands)
        else:
            setattr(_info.context, 'brand_id', None)

        return resolve_fulfillments(root, _info, brands)

    @staticmethod
    def resolve_lines(root: models.Order, _info):
        brands = MasterDashboard.filter_data.get("brands", "")
        fulfillments_status = MasterDashboard.filter_data.get("fulfillmentStatus", "")
        search_by_product = MasterDashboard.filter_data.get("searchByProduct","")
        fulfillments_status_list = []
        if isinstance(fulfillments_status, list):
            for status in fulfillments_status:
                if getattr(OrderFullfillmentStatusEnum, status, None):
                    status_value = getattr(OrderFullfillmentStatusEnum, status).value
                else:
                    status_value = status
                fulfillments_status_list.append(status_value)
        else:
            if getattr(OrderFullfillmentStatusEnum, fulfillments_status, None):
                status_value = getattr(OrderFullfillmentStatusEnum, fulfillments_status).value
                fulfillments_status_list.append(status_value)
            
        if brands:
            type, brands = resolve_global_ids_to_primary_keys(brands)
        else:
            brands = []
        brands = [NumberUtilities.convert_string_to_number(id) for id in brands]

        qs = resolve_order_line(root, _info, brands,fulfillments_status_list,search_by_product)

        return qs.select_related('order', 'variant', 'variant__product','brand')


class ProductAnalytics(BaseAnalyticsMixin, CountableDjangoObjectType):
    msp = graphene.String(description="maximum selling price among all variants of product")

    latest_purchase_date = graphene.String(description="Last purchase date of product")

    purchase_count = graphene.String(description="Order Count for the product")

    wishlist_count = graphene.String(description="Wishlist Count for the product,\
    returns no of user having this product in their wishlist.")

    visits = graphene.String(description="No. of views on a product based on a store or a collection.")

    thumbnail = graphene.Field(
        Image,
        description="The main thumbnail for a product.",
        size=graphene.Argument(graphene.Int, description="Size of thumbnail."),
    )

    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)
        authorised_stores = info.context.user.get_authorised_stores()

        cls.filter_data = cls.get_selection_field_argument_value(info, "productsAnalytics", "filter")
        
        sort_by_filter = cls.get_selection_field_argument_value(info, "productsAnalytics", "sortBy")
        
        if isinstance(sort_by_filter, dict):
            sort_by_field = sort_by_filter.get("field", '')
        
            if isinstance(sort_by_field, str) and getattr(ProductOrderField, sort_by_field, None):
                cls.sort_by = getattr(ProductOrderField, sort_by_field).value
            else:
                cls.sort_by = sort_by_field
        else:
            cls.sort_by = None
        
        if cls.filter_data:
            stores = cls.filter_data.get("stores", [])
            type, store_ids = resolve_global_ids_to_primary_keys(stores)

        if not store_ids:
            store_ids = [store.id for store in authorised_stores]

        cls.store_ids = store_ids
        
        cls.stores_orders_ids = order_store_queryset().filter(store__id__in=store_ids).values_list("order__id", flat=True
        )
        cls.variant_product_order_queryset = variant_product_order_queryset()
        cls.product_wishlist_queryset = product_wishlist_queryset()
        cls.product_google_analytics_queryset = product_google_analytics_queryset()

        qs = super().get_queryset(queryset, info)

        if cls.sort_by and isinstance(cls.sort_by, list):
            if cls.sort_by[0] == 'sales_this_month':
                qs = cls.annotate_sales_this_month(qs)
            # now using metadata field weekly_visits 
            # elif cls.sort_by[0] == 'weekly_visits':
            #     qs = cls.annotate_weekly_visits(qs)

        return get_all_products(authorised_stores, qs=qs)

    @classmethod
    def annotate_sales_this_month(cls, queryset):
        date_range = TimePeriod.time_period_to_datetime(TimePeriod.TILLTODAYTHISMONTH)
        
        orders = cls.variant_product_order_queryset.filter(order__in=cls.stores_orders_ids)\
            .filter(order__created__gte=date_range["gte"], order__created__lte=date_range["lte"])\
                .values_list("order", flat=True)
        
        sales = product_models.Product.objects.filter(variants__order_lines__order__in=orders).values('id').annotate(
            sum=Coalesce(Sum(
            F("variants__price_amount") * F("variants__order_lines__quantity_fulfilled"),
            output_field=DecimalField()
            ), 0.0)
        )
        
        queryset = queryset.annotate(sales_this_month=Case(
                        *[When(id=sale["id"], then=sale["sum"]) for sale in sales], 
                        default=0.0, 
                        output_field=DecimalField()
                        )
                    )
        return queryset

    @classmethod
    def annotate_weekly_visits(cls, queryset):
        product_analytics = product_google_analytics_queryset(TimePeriod.LASTWEEK).get("products", {})
        product_visits = {  
                            product_id: aggregate_product_analytics(analytics, cls.store_ids) 
                            for product_id, analytics in product_analytics.items()
                        }
        queryset = queryset.annotate(weekly_visits=Case(
                        *[When(id=id, then=count) for id, count in product_visits.items()], 
                        default=0, 
                        output_field=IntegerField()
                        )
                    )
        return queryset

    class Meta:
        description = "Represents analytics of individual item for sale in the storefront."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = product_models.Product
        registry = Registry()
        only_fields = [
            "available_for_purchase",
            "brand",
            "id",
            "name",
            "slug",
            "publication_date",
            "updated_at",
        ]

    def resolve_msp(root: product_models.Product, _info):
        return root.msp
    
    def resolve_latest_purchase_date(root: product_models.Product, _info):
        
        latest_product_order_lines = ProductAnalytics.variant_product_order_queryset.filter(
            variant__product=root.id).filter(order__in=ProductAnalytics.stores_orders_ids).last()

        if latest_product_order_lines:
            order_created = latest_product_order_lines.get("order__created")
            return TimeUtilities.parse_date(order_created, date_format="%d %b %Y")

        return "No Order placed"

    def resolve_purchase_count(root: product_models.Product, _info):

        return ProductAnalytics.variant_product_order_queryset.filter(
            variant__product=root.id).filter(order__in=ProductAnalytics.stores_orders_ids).values(
            'order').aggregate(Count("order")).get('order__count')
    
    def resolve_wishlist_count(root: product_models.Product, _info):
        wishlist_count = 0
        product_wishlists = ProductAnalytics.product_wishlist_queryset.filter(product_id=root.id).filter(
            wishlist__store__id__in=ProductAnalytics.store_ids
        )

        if product_wishlists:
            wishlist_count = product_wishlists.values("wishlist_id").aggregate(Count("wishlist_id")).get("wishlist_id__count")

        return wishlist_count

    def resolve_visits(root: product_models.Product, _info):
        pid_analytics = ProductAnalytics.product_google_analytics_queryset["products"].get(str(root.id))
        store_ids = ProductAnalytics.store_ids
        if not pid_analytics:
            return 0
        else:
            return aggregate_product_analytics(pid_analytics,store_ids)
        

    @staticmethod
    def resolve_thumbnail(root: product_models.Product, info, *, size=1080):
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


class CollectionAnalytics(BaseAnalyticsMixin, CountableDjangoObjectType):
    no_of_products = graphene.String(description="No. of products in a collection")
    total_collection_views = graphene.String(description="No. of views in a collection")
    total_view_of_product_pages = graphene.String(description="Total no. of views of product pages of a collection")
    total_product_purchase_count = graphene.String(description="Total no. product orders of a collection")
    date_of_last_visit = graphene.String(description="Date of last visit of a collection")
    date_of_last_purchase = graphene.String(description="Date of last order form a collection")
    collection_id = graphene.String(description = "Decode as Collection : id")

    @classmethod
    def get_queryset(cls, queryset, info):
        qs = super().get_queryset(queryset, info)

        authorised_stores = info.context.user.get_authorised_stores()
        cls.collection_google_analytics_queryset = collection_google_analytics_queryset()
        
        return get_all_collections(authorised_stores, qs=qs)

    class Meta:
        description = "Represents analytics of individual collection in the storefront."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = product_models.Collection
        registry = Registry()
        only_fields = [
            "name",
            "created_at",
            "updated_at",
            "products",
            "background_image",
            "image_url",
            "publication_date",
            "is_published",
        ]

    def resolve_no_of_products(root: product_models.Collection, _info):
        return root.total_products_count

    def resolve_total_collection_views(root: product_models.Collection, _info):
        visits = CollectionAnalytics.collection_google_analytics_queryset["collections"].get(str(root.id))
        if not visits:
            return 0
        else:
            total_visits =  visits.get("collection_visits")
            if not total_visits:
                return 0
            else:
                return total_visits

    def resolve_total_view_of_product_pages(root: product_models.Collection, _info):
    
        return 0
    
    def resolve_total_product_purchase_count(root: product_models.Collection, _info):
    
        return 0
    
    def resolve_date_of_last_visit(root: product_models.Collection, _info):
    
        return ''

    def resolve_date_of_last_purchase(root: product_models.Collection, _info):
    
        return ''

    def resolve_collection_id(root: product_models.Collection, _info):
        return graphene.Node.to_global_id("Collection",root.id)
    

class StoreAnalytics(BaseAnalyticsMixin, CountableDjangoObjectType):

    store_id = graphene.String(description="Store id")

    total_visitors = graphene.String(description="Total visitor on a store.")

    total_product_page_views = graphene.String(description="Total product page views in a store.")

    total_collection_views = graphene.String(description="Total collection views of store.")

    wishlist_of_products = graphene.String(description="Products added to wishlist by store.")

    product_last_added = graphene.String(description="Datetime when a product was last added to a collection.")

    total_orders = graphene.String(description="No of order by any store.")

    last_30_days_total_orders = graphene.String(description="No of order by any store in store in last 30 days")

    last_7_days_total_orders = graphene.String(description="No of order by any store in last 7 days")

    average_order_value = graphene.String(description="Average order value of a store.")

    average_number_of_items_in_order = graphene.String(description="Average no of order items of a store.")

    average_abandoned_cart = graphene.String(description="Average abandoned cart of s store.")

    no_of_coupons_used = graphene.String(description="No. of coupons used on a store")

    total_store_sales = graphene.String(description="Sum of all order value of store")

    last_30_days_total_store_sales = graphene.String(description="Sum of all order value of store in last 30 days")

    last_7_days_total_store_sales = graphene.String(description="Sum of all order value of store in last 7 days")

    total_msp_sales = graphene.String(description="Sum of all order value of store")
    
    phone_number = graphene.String(description="phone number of influencer")
    

    total_earnings = graphene.String(description="Sum of all commissions earned by influencer")

    last_payout = graphene.String(description="Last payout recieved")

    net_payout_due = graphene.String(description="Net payout due")

    number_of_products_sold = graphene.String(description="Number of products sold")

    last_30_days_number_of_products_sold = graphene.String(description="Number of products sold in last 30 days")

    last_7_days_number_of_products_sold = graphene.String(description="Number of products sold in last 7 days")
    
    no_of_sourcing_requests_initiated = graphene.String(description="Number of sourcing request initiated.")
   
    no_of_sourcing_requests_brand_fullfilled = graphene.String(description="Number of sourcing request brand fullfilled.")

    actions = graphene.Field(StoreManagerActions, description="store actions by store manager")

    total_brand_clicks = graphene.Int(description="Total brand clicks")

    total_category_clicks = graphene.Int(description="Total category clicks")
    
    my_orders = graphene.Int(description="Number of clicks on My Orders")
    
    checkout_success = graphene.Int(description="Checkout success.")
    
    checkout_fail = graphene.Int(description="Checkout fail.")

    last_login_time = graphene.String(description="Datetime of last login")

    cities = graphene.String(description="Cities of last 3 orders")
    
    return_policy = graphene.Int(description="Number of clicks on Return Policy")
    
    app_last_launched_at = graphene.String(description="Datetime of last login")

    last_30_days_pdp_views = graphene.Int(description="Product page views.")

    last_7_days_pdp_views = graphene.Int(description="Product page views.")

    last_7_days_total_visitors = graphene.Int(description="Unique visitors on a store.")
    
    last_7_days_a2c = graphene.Int(description="Added to cart.")

    @classmethod
    def get_saved_analytics(cls):
        
        datetime_range = TimePeriod.time_period_to_datetime(cls.time_period)
        
        day_past_30 = datetime.datetime.now() - datetime.timedelta(30)
        day_past_7 = datetime.datetime.now() - datetime.timedelta(7)

        cls.last_analytics_update_datetime = store_models.StoreAnalytics.objects.last().created_at

        qs = store_models.StoreAnalytics.objects.select_related("store").values("store_id").annotate(
                saved_total_orders = Coalesce(Sum("total_orders",
                                        filter = Q(
                                            analytics_date__gte=datetime_range["gte"], 
                                            analytics_date__lte=datetime_range["lte"]
                                            )
                                    ), 0),
                saved_total_orderlines = Coalesce(Sum("orderlines_count",
                                        filter = Q(
                                            analytics_date__gte=datetime_range["gte"], 
                                            analytics_date__lte=datetime_range["lte"]
                                            )
                                    ), 0),
                saved_no_of_coupons_used = Coalesce(Sum('no_of_coupons_used', 
                                            filter = Q(
                                            analytics_date__gte=datetime_range["gte"], 
                                            analytics_date__lte=datetime_range["lte"]
                                            )
                                            ),0),
                saved_abandoned_cart_count = Coalesce(Sum('abandoned_cart_count', 
                                            filter = Q(
                                            analytics_date__gte=datetime_range["gte"], 
                                            analytics_date__lte=datetime_range["lte"]
                                            )
                                            ),0),
                saved_total_store_sales_after_discount = Coalesce(Sum("total_store_sales_after_discount",
                                        filter = Q(
                                            analytics_date__gte=datetime_range["gte"], 
                                            analytics_date__lte=datetime_range["lte"]
                                            )
                                    ),0),
                saved_wishlist_of_products = Coalesce(Sum("wishlist_of_products",
                                        filter = Q(
                                            analytics_date__gte=datetime_range["gte"], 
                                            analytics_date__lte=datetime_range["lte"]
                                            )
                                        ), 0),
                saved_no_of_sourcing_requests_initiated = Coalesce(Sum("no_of_sourcing_requests_initiated",
                                                            filter = Q(
                                                            analytics_date__gte=datetime_range["gte"], 
                                                            analytics_date__lte=datetime_range["lte"]
                                                        )
                                                    ),0),
                saved_no_of_sourcing_requests_brand_fullfilled = Coalesce(Sum("no_of_sourcing_requests_brand_fullfilled",
                                                                    filter = Q(
                                                                    analytics_date__gte=datetime_range["gte"], 
                                                                    analytics_date__lte=datetime_range["lte"]
                                                                )
                                                            ),0),
                saved_number_of_products_sold = Coalesce(Sum("number_of_products_sold", 
                                                    filter = Q(
                                                        analytics_date__gte=datetime_range["gte"], 
                                                        analytics_date__lte=datetime_range["lte"]
                                                    )
                                            ),0),
                saved_total_store_sales = Coalesce(Sum("total_store_sales", 
                                            filter = Q(
                                                analytics_date__gte=datetime_range["gte"], 
                                                analytics_date__lte=datetime_range["lte"]
                                                )
                                        ),0),
                saved_total_msp_sales = Coalesce(Sum("total_msp_sales", 
                                            filter = Q(
                                                analytics_date__gte=datetime_range["gte"], 
                                                analytics_date__lte=datetime_range["lte"]
                                            )
                                    ),0),

                last_30_days_total_orders= Coalesce(Sum('total_orders',
                                                filter= Q(analytics_date__gte=day_past_30)
                                            ),0),
                last_7_days_total_orders= Coalesce(Sum('total_orders',
                                                filter= Q(analytics_date__gte=day_past_7)
                                            ),0),

                last_30_days_total_store_sales = Coalesce(Sum("total_store_sales",
                                                    filter= Q(analytics_date__gte=day_past_30)
                                                ),0),
                
                last_7_days_total_store_sales = Coalesce(Sum("total_store_sales",
                                                    filter= Q(analytics_date__gte=day_past_7)
                                                ),0),
                last_30_days_number_of_products_sold = Coalesce(Sum("number_of_products_sold", 
                                                    filter= Q(analytics_date__gte=day_past_30)
                                                ),0),

                last_7_days_number_of_products_sold = Coalesce(Sum("number_of_products_sold", 
                                                    filter= Q(analytics_date__gte=day_past_7)
                                                ),0),
        ).order_by('store_id')

        qs_last_values_d = dict()
        qs_last_values = store_models.StoreAnalytics.objects.select_related("store").values('store_id','last_payout', 
                            'mobile_no', 'last_product_added', 'net_payout_due', 'total_earnings','last_3_order_cities').order_by('-updated_at')
        
        for val in qs_last_values:
            if qs_last_values_d.get(val['store_id']):
                continue
            qs_last_values_d[val['store_id']] = val
            

        # saved_analytics = qs.values(
        #     'store_id', 'saved_total_orders', 'saved_total_store_sales_after_discount', 'saved_wishlist_of_products',
        #     'saved_no_of_sourcing_requests_initiated', 'saved_no_of_sourcing_requests_brand_fullfilled',
        #     'saved_number_of_products_sold', 'saved_total_store_sales', 'saved_total_msp_sales', 
        #     'last_30_days_total_orders', 'last_7_days_total_orders', 'last_30_days_total_store_sales', 
        #     'last_7_days_total_store_sales', 'last_30_days_number_of_products_sold', 'last_7_days_number_of_products_sold',
        #     'last_payout', 'mobile_no', 'last_product_added', 'net_payout_due', 'total_earnings',
        #     'saved_no_of_coupons_used', 'saved_abandoned_cart_count', 'saved_total_orderlines'
        # )
        cls.saved_analytics = {value['store_id']:value for value in qs if value.get('store_id')}

        for store_id,value in qs_last_values_d.items():
            if cls.saved_analytics.get(value['store_id']):
                cls.saved_analytics[value['store_id']].update(value)
            
        return qs

    @classmethod
    def get_queryset(cls, queryset, info):
        
        qs = super().get_queryset(queryset, info)
        app_last_launched_at_subquery = Device.objects.filter(user=OuterRef('user_id')).order_by('-app_last_launched_at').values('app_last_launched_at')[:1]
        store_member_user_objs = store_models.StoreMemberState.objects.filter(store_id__in=qs.values('id')).select_related('user').annotate(app_last_launched_at=Subquery(app_last_launched_at_subquery))

        cls.store_member_user_objs_dict = {stm.user_id:(stm.user,stm.app_last_launched_at) for stm in store_member_user_objs}

        cls.prepare_last_n_days_pdp_views()
        cls.prepare_last_n_days_a2c()
        cls.store_authorised_users_dict = {}
        
        storeid_userid_list = qs.prefetch_related("store_member__user","store_member__user__devices").values_list("id", "store_members__user")
        
        for storeid_userid in storeid_userid_list:  
            if cls.store_member_user_objs_dict.get(storeid_userid[1]):
                cls.store_authorised_users_dict.setdefault(storeid_userid[0],[]).append(cls.store_member_user_objs_dict.get(storeid_userid[1])[0])

        if getattr(TimePeriod, cls.get_selection_field_argument_value(
            info, "storeAnalytics", "timePeriod"), None):
            cls.time_period = getattr(TimePeriod, cls.get_selection_field_argument_value(
                info, "storeAnalytics", "timePeriod"), None)
        else:
            cls.time_period = cls.get_selection_field_argument_value(
                info, "storeAnalytics", "timePeriod")
        
        sort_by_filter = cls.get_selection_field_argument_value(info, "storeAnalytics", "sortBy")
        
        if isinstance(sort_by_filter, dict):
            sort_by_field = sort_by_filter.get("field", '')
        
            if isinstance(sort_by_field, str) and getattr(StoreAnalyticsSortField, sort_by_field, None):
                cls.sort_by = getattr(StoreAnalyticsSortField, sort_by_field).value
            else:
                cls.sort_by = sort_by_field
        else:
            cls.sort_by = None
            
        cls.order_store_queryset = order_store_queryset()
        
        cls.brand_commission_queryset = brand_commission_queryset()
        
        cls.orderline_store_product_brand_queryset = orderline_store_product_brand_queryset()
        cls.checkout_store_queryset = checkout_store_queryset()
        cls.voucher_store_queryset = voucher_store_queryset()
        cls.store_google_analytics_queryset = store_google_analytics_queryset(cls.time_period)
        cls.get_saved_analytics()
        qs = cls.annotate_store_analytics_attributes(qs)
        # store_list = [data.id for data in info.context.authorised_stores]
        qs = qs.filter(id__in= info.context.authorised_stores.values_list('id',flat=True)).prefetch_related('actions')
        return qs
    
    @classmethod
    def prepare_last_n_days_a2c(cls):
        last_week = TimeUtilities().subtract_time_from_timestamp(TimeUtilities().get_today_start(), days=7)
        qs = CheckoutLine.objects.filter(checkout__last_change__gt=last_week).annotate(store_id=F("checkout__checkoutstore__store_id"))\
                            .values('store_id').annotate(count=Count('id', distinct=True)).order_by('store_id').values('store_id', 'count')
        cls.last_7_days_a2c_data = {a2c['store_id']: a2c['count'] for a2c in qs}


    @classmethod
    def prepare_last_n_days_pdp_views(cls):
        past_week = cls.get_last_n_days_pdp_views(days=7)
        past_month = cls.get_last_n_days_pdp_views(days=30)
        cls.past_week_pdp_views_data = past_week
        cls.past_month_pdp_views_data = past_month
    

    @classmethod
    def get_last_n_days_pdp_views(cls, days=30, group_by='store'):
        date_range = {
            'start_date': TimeUtilities.get_n_days_before_date(days=days).strftime('%Y-%m-%d'),
            'end_date': TimeUtilities.get_n_days_before_date(days=0).strftime('%Y-%m-%d')
        }
        product_views = dict()
        docs = get_product_views(date_range=date_range, group_by=group_by)
        for doc in docs:
            product_views[NumberUtilities.convert_string_to_number(doc['_id'])] = doc['views']
        
        return product_views

    @classmethod
    def annotate_store_analytics_attributes(cls, qs):
        cls.datetime_range = TimePeriod.time_period_to_datetime(cls.time_period)
        cls.latest_store_analytics_dict = {}
        # for case when saved analytics update time is more then 1 hr, then to get last hour analytics.
        if cls.datetime_range["gte"] > cls.last_analytics_update_datetime:
            cls.last_analytics_update_datetime = cls.datetime_range["gte"]
        elif cls.datetime_range["lte"] < cls.last_analytics_update_datetime:
            cls.last_analytics_update_datetime = datetime.datetime.now()

        cls.store_values = {NumberUtilities.convert_string_to_number(store_id):store for store_id,store in cls.store_google_analytics_queryset.items()}

        # order_store_qs = order_store_queryset().filter(order__platform_code=PlatformTypeEnum.INFLUENCER_STORE)

        # cls.order_store_annotated_values = list(order_store_qs.filter(
        #     Q(order__created__gte= cls.last_analytics_update_datetime)).values("store"
        # ).annotate(
        #     total_store_sales=Sum(F("order__total_net_amount") + F("order__discount_amount")),

        #     total_msp_sales=Sum(F("order__discount_amount")),
        #     total_store_sales_after_discount = Sum(F("order__total_net_amount")),
        #     total_orders=Count('order__id', distinct=True),
        # ).values(
        #     "store", 
        #     "total_store_sales", 
        #     "total_store_sales_after_discount",
        #     "total_msp_sales",
        #     "total_orders",
        #     )
        # )

        # cls.order_store_lines_annotated_values = list(order_store_qs.filter(Q(
        #                                 order__created__gte= cls.last_analytics_update_datetime)
        #                                 ).values("store"
        #                                 ).annotate(
        #                                         number_of_products_sold=Sum("order__lines__quantity")

        # ).values(
        #     "store",
        #     "number_of_products_sold",
        # ))

        # cls.product_sourcing_queryset = list(qs.filter(product_sourcing__created_at__gt=cls.last_analytics_update_datetime
        # ).annotate(no_of_sourcing_requests_initiated=Count('product_sourcing__id', distinct=True,
        #             filter=Q(
        #                     Q(product_sourcing__created_at__gte=cls.last_analytics_update_datetime
        #                     )
        #             )),
        # no_of_sourcing_requests_brand_fullfilled = Count('product_sourcing__id', distinct=True,
        #                             filter=Q(
        #                                     Q(product_sourcing__created_at__gte=cls.last_analytics_update_datetime),
        #                                     Q(product_sourcing__status__in=[
        #                                         SourcingRequestStatus.BRAND_COUPON_CREATED,
        #                                         SourcingRequestStatus.BRAND_COLLAB_APPROVED,
        #                                         SourcingRequestStatus.BRAND_CONTACT_INFLUENCER
        #                                     ])
        #                                     )
        #             )
        
                    
        # ).values("id", "no_of_sourcing_requests_initiated", "no_of_sourcing_requests_brand_fullfilled"))


        # cls.wishlist_of_products = list(qs.filter(wishlist__created_at__gt=cls.last_analytics_update_datetime
        # ).annotate(wishlist_of_products=Count('wishlist__id', distinct=True)).values("id", "wishlist_of_products"))

        # cls.latest_store_analytics_dict = {}

        # for store in cls.order_store_annotated_values:

        #     for key in store:
        #         if not store[key]:
        #             store[key]=0

        #     if store['store'] in cls.latest_store_analytics_dict:
        #         cls.latest_store_analytics_dict[store['store']].update(store)
        #     else:
        #         cls.latest_store_analytics_dict[store['store']] = store

        # for store in cls.order_store_lines_annotated_values:
            
        #     for key in store:
        #         if not store[key]:
        #             store[key]=0

        #     if store['store'] in cls.latest_store_analytics_dict:
        #         cls.latest_store_analytics_dict[store['store']].update(store)
        #     else:
        #         cls.latest_store_analytics_dict[store['store']] = store
        
        # for store in cls.product_sourcing_queryset:
            
        #     for key in store:
        #         if not store[key]:
        #             store[key]=0

        #     if store['id'] in cls.product_sourcing_queryset:
        #         cls.latest_store_analytics_dict[store['id']].update(store)
        #     else:
        #         cls.latest_store_analytics_dict[store['id']] = store

        # for store in cls.wishlist_of_products:
            
        #     for key in store:
        #         if not store[key]:
        #             store[key]=0

        #     if store['id'] in cls.wishlist_of_products:
        #         cls.latest_store_analytics_dict[store['id']].update(store)
        #     else:
        #         cls.latest_store_analytics_dict[store['id']] = store
        
        if cls.sort_by and isinstance(cls.sort_by, list):
            if cls.sort_by[0] not in ['created_at']:
                qs = getattr(cls, "annotate_{}".format(cls.sort_by[0]))(qs)
            
        return qs


    @classmethod
    def annotate_total_orders(cls, qs):
        return qs.annotate(
            total_orders=Count('order_store__order__id', distinct=True,
                filter=Q(
                    Q(order_store__created_at__gte=cls.datetime_range["gte"], order_store__created_at__lte=cls.datetime_range["lte"]),
                    Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),)
                    ))
    
    @classmethod
    def annotate_last_7_days_total_orders(cls, qs):
        day_past_7 = datetime.datetime.now() - datetime.timedelta(7)
        return qs.annotate(last_7_days_total_orders=Count('order_store__order__id', distinct=True,
                filter=Q(
                    Q(order_store__created_at__gte=day_past_7),
                    Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),)
                    ))
    
    @classmethod
    def annotate_last_30_days_total_orders(cls, qs):
        day_past_30 = datetime.datetime.now() - datetime.timedelta(30)
        return qs.annotate(last_30_days_total_orders=Count('order_store__order__id', distinct=True,
                filter=Q(
                    Q(order_store__created_at__gte=day_past_30),
                    Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),)
                    ))

    @classmethod
    def annotate_avg_order_value(cls, qs):
        return qs.annotate(avg_order_value=Coalesce(
                Avg('order_store__order__total_net_amount',
                    filter=Q(
                        Q(order_store__created_at__gte=cls.datetime_range["gte"], order_store__created_at__lte=cls.datetime_range["lte"]) 
                        & Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE))), 0))

    @classmethod
    def annotate_wishlist_of_products(cls, qs):
        return qs.annotate(wishlist_of_products=Count('wishlist__id', distinct=True,
                    filter=Q(wishlist__created_at__gte=cls.datetime_range["gte"], wishlist__created_at__lte=cls.datetime_range["lte"])
                ))
    
    @classmethod
    def annotate_number_of_products_sold(cls, qs):
        return qs.annotate(number_of_products_sold=Sum("order_store__order__lines__quantity",
                filter=Q(order_store__created_at__gte=cls.datetime_range["gte"], order_store__created_at__lte=cls.datetime_range["lte"])
        ))

    @classmethod
    def annotate_last_30_days_number_of_products_sold(cls, qs):
        day_past_30 = datetime.datetime.now() - datetime.timedelta(30)
        return qs.annotate(last_30_days_number_of_products_sold=Sum("order_store__order__lines__quantity",
                filter=Q(order_store__order__created__gte=day_past_30)
        ))

    @classmethod
    def annotate_last_7_days_number_of_products_sold(cls, qs):
        day_past_7 = datetime.datetime.now() - datetime.timedelta(7)
        return qs.annotate(last_7_days_number_of_products_sold=Sum("order_store__order__lines__quantity",
                filter=Q(order_store__order__created__gte=day_past_7)
        ))

    @classmethod
    def annotate_total_store_sales(cls, qs):
        return qs.annotate(total_store_sales = Sum(F("order_store__order__total_net_amount") + F("order_store__order__discount_amount"),
        filter=Q(order_store__created_at__gte=cls.datetime_range["gte"], order_store__created_at__lte=cls.datetime_range["lte"])
        ))

    @classmethod
    def annotate_last_30_days_total_store_sales(cls, qs):
        day_past_30 = datetime.datetime.now() - datetime.timedelta(30)
        return qs.annotate(last_30_days_total_store_sales=Sum(F("order_store__order__total_net_amount") + F("order_store__order__discount_amount"),
        filter=Q(order_store__created_at__gte=day_past_30)
        ))

    @classmethod
    def annotate_last_7_days_total_store_sales(cls, qs):
        day_past_7 = datetime.datetime.now() - datetime.timedelta(7)
        return qs.annotate(last_7_days_total_store_sales=Sum(F("order_store__order__total_net_amount") + F("order_store__order__discount_amount"),
        filter=Q(order_store__created_at__gte=day_past_7)
        ))

    @classmethod
    def annotate_total_msp_sales(cls, qs):
        
        return qs.annotate(total_msp_sales=Sum("order_store__order__discount_amount",
        filter= Q(order_store__created_at__gte=cls.datetime_range["gte"], order_store__created_at__lte=cls.datetime_range["lte"])
        ))
    

    @classmethod
    def annotate_no_of_sourcing_requests_initiated(cls, qs):
        return qs.annotate(no_of_sourcing_requests_initiated=Count('product_sourcing__id', distinct=True,
                                    filter=Q(
                                            Q(product_sourcing__created_at__gte=cls.datetime_range["gte"], product_sourcing__created_at__lte=cls.datetime_range["lte"]),
                                            )
                    ))

    @classmethod
    def annotate_no_of_sourcing_requests_brand_fullfilled(cls, qs):
        return qs.annotate(no_of_sourcing_requests_brand_fullfilled = Count('product_sourcing__id', distinct=True,
                                    filter=Q(
                                            Q(product_sourcing__created_at__gte=cls.datetime_range["gte"], product_sourcing__created_at__lte=cls.datetime_range["lte"]),
                                            Q(product_sourcing__status__in=[
                                                SourcingRequestStatus.BRAND_COUPON_CREATED,
                                                SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_BRAND,
                                                SourcingRequestStatus.BRAND_COUPON_CLUBBED
                                            ])
                                            )
                    ))


    @classmethod
    def annotate_total_visitors(cls, qs):
        return qs.annotate(total_visitors=Coalesce(Cast(KeyTextTransform('total_visitors', 'metadata'), IntegerField()), 0))

    @classmethod
    def annotate_total_brand_clicks(cls, qs):
        return qs.annotate(total_brand_clicks=Case(*[When(id=id, then=store.get("brand_click_total", 0)) for id,store in cls.store_values.items()], default=0, output_field=IntegerField()))

    @classmethod
    def annotate_total_category_clicks(cls, qs):
        return qs.annotate(total_category_clicks=Case(*[When(id=id, then=store.get("cat_click_total", 0)) for id,store in cls.store_values.items()], default=0, output_field=IntegerField()))
    
    @classmethod
    def annotate_return_policy(cls, qs):
        return qs.annotate(return_policy=Case(*[When(id=id, then=store.get("return_policy", 0)) for id,store in cls.store_values.items()], default=0, output_field=IntegerField()))

    @classmethod
    def annotate_my_orders(cls, qs):
        return qs.annotate(my_orders=Case(*[When(id=id, then=store.get("my_orders", 0)) for  id,store in cls.store_values.items()], default=0, output_field=IntegerField()))

    @classmethod
    def annotate_checkout_success(cls, qs):
        return qs.annotate(checkout_success=Case(*[When(id=id, then=store.get("checkout_success", 0)) for id,store in cls.store_values.items()], default=0, output_field=IntegerField()))

    @classmethod
    def annotate_checkout_fail(cls, qs):
        return qs.annotate(checkout_fail=Case(*[When(id=id, then=store.get("checkout_fail", 0)) for id,store in cls.store_values.items()], default=0, output_field=IntegerField()))
    

    class Meta:
        description = "Represents analytics of individual Store."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = store_models.StoreInfo
        registry = Registry()
        only_fields = [
            "store_name",
            "actions",
            "created_at",
            "updated_at",
            "store_url",
            "state",
           
        ]
    
    def resolve_store_id(root: store_models.StoreInfo , _info):
        return graphene.Node.to_global_id("Store", root.id)

    def resolve_product_last_added(root: store_models.StoreInfo, _info):

        # created_at = product_models.CollectionProduct.objects.filter(collection__collection_store__store_id=root.id)\
        #     .order_by('-created_at').values_list('created_at', flat=True).first()
        # if created_at:
        #     created_at = created_at.strftime('%d-%m-%y %H:%M')
            
        # return created_at
        saved_last_product_added = ''
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
            saved_last_product_added = store.get("last_product_added", 0)
        
        return saved_last_product_added

    
    def resolve_actions(root: store_models.StoreInfo, _info):
        
        if hasattr(root, 'actions'):
            return root.actions

        return {}

    def resolve_number_of_products_sold(root: store_models.StoreInfo, _info):
        if hasattr(root, "number_of_products_sold"):
            return root.number_of_products_sold
        else:
            saved_number_of_products_sold = 0
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_number_of_products_sold = store.get("saved_number_of_products_sold", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("number_of_products_sold", 0)
            
            return saved_number_of_products_sold + latest_analytics

    def resolve_last_30_days_number_of_products_sold(root: store_models.StoreInfo, _info):
        if hasattr(root, "last_30_days_number_of_products_sold"):
            return root.last_30_days_number_of_products_sold
        else:
            saved_last_30_days_number_of_products_sold = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_last_30_days_number_of_products_sold = store.get("last_30_days_number_of_products_sold", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("number_of_products_sold", 0)
            
            return saved_last_30_days_number_of_products_sold + latest_analytics

    def resolve_last_7_days_number_of_products_sold(root: store_models.StoreInfo, _info):
        if hasattr(root, "last_7_days_number_of_products_sold"):
            return root.last_7_days_number_of_products_sold
        else:
            saved_last_7_days_number_of_products_sold = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_last_7_days_number_of_products_sold = store.get("last_7_days_number_of_products_sold", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("number_of_products_sold", 0)
            
            return saved_last_7_days_number_of_products_sold + latest_analytics

    def resolve_no_of_sourcing_requests_initiated(root: store_models.StoreInfo, _info):
        if hasattr(root, "no_of_sourcing_requests_initiated"):
            return root.no_of_sourcing_requests_initiated
        else:
            saved_no_of_sourcing_requests_initiated = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_no_of_sourcing_requests_initiated = store.get("saved_no_of_sourcing_requests_initiated", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("no_of_sourcing_requests_initiated", 0)
            
            return saved_no_of_sourcing_requests_initiated + latest_analytics

    def resolve_no_of_sourcing_requests_brand_fullfilled(root: store_models.StoreInfo, _info):
        if hasattr(root, "no_of_sourcing_requests_brand_fullfilled"):
            return root.no_of_sourcing_requests_brand_fullfilled
        else:
            saved_no_of_sourcing_requests_brand_fullfilled = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_no_of_sourcing_requests_brand_fullfilled = store.get("saved_no_of_sourcing_requests_brand_fullfilled", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("no_of_sourcing_requests_brand_fullfilled", 0)
            
            return saved_no_of_sourcing_requests_brand_fullfilled + latest_analytics

    def resolve_total_visitors(root: store_models.StoreInfo, _info):
        total_visitors = root.metadata.get('total_visitors', 0)
        return total_visitors

    def resolve_total_product_page_views(root: store_models.StoreInfo, _info):

        visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
        total_visits =  visits.get("pdp_visit_total", 0)
        
        return total_visits

    def resolve_total_collection_views(root: store_models.StoreInfo, _info):

        visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
        total_visits =  visits.get("col_visits_total", 0)
        
        return total_visits


    def resolve_wishlist_of_products(root: store_models.StoreInfo, _info):
        
        if hasattr(root, "wishlist_of_products"):
            return root.wishlist_of_products
        else:
            saved_wishlist_of_products = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_wishlist_of_products = store.get("saved_wishlist_of_products", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("wishlist_of_products", 0)
            
            return saved_wishlist_of_products + latest_analytics
        
    def resolve_last_payout(root: store_models.StoreInfo, _info):
        # last_payout = root.store_payout.order_by('-date').first()
        # if last_payout:
        #     return last_payout.amount
        saved_last_payout=0
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
            saved_last_payout = store.get("last_payout", 0)
            
        return saved_last_payout

    def resolve_net_payout_due(root: store_models.StoreInfo, _info):
        # earnings = 0
                
        # store_order_lines = time_period_filter(StoreAnalytics.orderline_store_product_brand_queryset.filter(
        #     order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).filter(
        #     order__order_store__store=root.id).exclude(fulfillment_line__fulfillment__status__in = [
        #         FulfillmentStatus.RETURN_COMPLETED, FulfillmentStatus.RETURN_INITIATED ,
        #         FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLATION_INITIATED]), 
        #         "total_earnings", StoreAnalytics.time_period, field="order__created__date")

        # for line in store_order_lines:
        
        #     earnings += Decimal(line["metadata"].get("influencer_commission", 0))

        # paid_amount_dict = store_models.StorePayout.objects.filter(store = root).aggregate(Sum('amount'))
        # paid_amount = 0
        # if paid_amount_dict.get('amount__sum'):
        #     paid_amount = paid_amount_dict['amount__sum']

        # due_amount = earnings - paid_amount
        saved_net_payout_due=0
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
            saved_net_payout_due = store.get("net_payout_due", 0)
            
        return saved_net_payout_due

    def resolve_total_orders(root: store_models.StoreInfo, _info):
        if hasattr(root, "total_orders"):
            return root.total_orders
        else:
            saved_total_orders = 0
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_total_orders = store.get("saved_total_orders", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_orders", 0)
            
            return saved_total_orders + latest_analytics

    def resolve_last_7_days_total_orders(root: store_models.StoreInfo, _info):

        if hasattr(root, "last_7_days_total_orders"):
            return root.last_7_days_total_orders
        else:
            saved_last_7_days_total_orders = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_last_7_days_total_orders = store.get("last_7_days_total_orders", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_orders", 0)
            
            return saved_last_7_days_total_orders + latest_analytics
    
    def resolve_last_30_days_total_orders(root: store_models.StoreInfo, _info):
        if hasattr(root, "last_30_days_total_orders"):
            return root.last_30_days_total_orders
        else:
            saved_last_30_days_total_orders = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_last_30_days_total_orders = store.get("last_30_days_total_orders", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_orders", 0)
            
            return saved_last_30_days_total_orders + latest_analytics

    def resolve_average_order_value(root: store_models.StoreInfo, _info):
        if hasattr(root, "avg_order_value"):
            return "{0:.3f}".format(root.avg_order_value)
        else:
            saved_total_store_sales_after_discount = 0
            saved_total_orders = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_total_store_sales_after_discount = store.get("saved_total_store_sales_after_discount", 0)
                saved_total_orders = store.get("saved_total_orders", 0)
                    
            latest_total_store_sales_after_discount = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_store_sales_after_discount", 0)
            latest_total_orders = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_orders", 0)


            if (saved_total_orders + latest_total_orders):
                average_order_value = (saved_total_store_sales_after_discount + latest_total_store_sales_after_discount) / (saved_total_orders + latest_total_orders) 
            else:
                average_order_value = 0
            
            return "{0:.3f}".format(average_order_value)

    def resolve_average_number_of_items_in_order(root: store_models.StoreInfo, _info):
        # store_members = StoreAnalytics.store_authorised_users_dict.get(root.id, [])
        
        # qs = time_period_filter(StoreAnalytics.order_store_queryset.exclude(order__user__in=store_members).filter(store=root.id),
        # "average_number_of_items_in_order", StoreAnalytics.time_period, field="created_at").values("order")
        # avg_lines = 0
        # order_count = qs.count()
        # if order_count:
        #     avg_lines = order_models.Order.objects.filter(id__in=Subquery(qs)).annotate(lines_quantity=Sum('lines__quantity')).aggregate(Sum("lines_quantity")).get("lines_quantity__sum", 0)/order_count
        
        # if avg_lines:
        #     return "{0:.3f}".format(avg_lines)
        # return 0
        average_number_of_items_in_order = 0
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
            
            saved_total_orders = store.get("saved_total_orders", 0)
            saved_total_orderlines = store.get("saved_total_orderlines", 0)
            if saved_total_orders:
                average_number_of_items_in_order = saved_total_orderlines/saved_total_orders
            else:
                average_number_of_items_in_order = 0
            
        
        return "{0:.3f}".format(average_number_of_items_in_order)


    def resolve_average_abandoned_cart(root: store_models.StoreInfo, _info):
        # store_members = StoreAnalytics.store_authorised_users_dict.get(root.id, [])
        
        # qs = time_period_filter(StoreAnalytics.checkout_store_queryset.exclude(token__user__in=store_members).filter(store=root.id),
        # "average_abandoned_cart", StoreAnalytics.time_period, field="created_at")

        # return qs.count()
        
        saved_abandoned_cart_count = 0
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
                    
            saved_abandoned_cart_count = store.get("saved_abandoned_cart_count", 0)
            
        
        return saved_abandoned_cart_count

    
    def resolve_no_of_coupons_used(root: store_models.StoreInfo, __info):
        # qs = time_period_filter(order_models.Order.objects.all(), 
        # "no_of_coupons_used", StoreAnalytics.time_period, field="created")

        # vouchers = StoreAnalytics.voucher_store_queryset.filter(store=root.id).values_list('id', flat=True)
        # store_members = StoreAnalytics.store_authorised_users_dict.get(root.id, [])  
        
        # qs = qs.filter(voucher__in=vouchers).exclude(user__in=store_members)
        # return qs.count()

        saved_no_of_coupons_used = ""
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
                    
            saved_no_of_coupons_used = store.get("saved_no_of_coupons_used", 0)
            
        return saved_no_of_coupons_used
        
        

    def resolve_total_store_sales(root: store_models.StoreInfo, _info):
        if hasattr(root, "total_store_sales"):
            return "{0:.3f}".format(root.total_store_sales)
        else:
            saved_total_store_sales = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)

            if store:
                saved_total_store_sales = store.get("saved_total_store_sales", 0)

            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_store_sales", 0)
            
            return "{0:.3f}".format(saved_total_store_sales + latest_analytics)

    def resolve_last_30_days_total_store_sales(root: store_models.StoreInfo, _info):
        if hasattr(root, "last_30_days_total_store_sales"):
            return "{0:.3f}".format(root.last_30_days_total_store_sales)
        else:
            saved_last_30_days_total_store_sales = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_last_30_days_total_store_sales = store.get("last_30_days_total_store_sales", 0)

            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_store_sales", 0)
            
            return "{0:.3f}".format(saved_last_30_days_total_store_sales + latest_analytics)

    def resolve_last_7_days_total_store_sales(root: store_models.StoreInfo, _info):
        if hasattr(root, "last_7_days_total_store_sales"):
            return "{0:.3f}".format(root.last_7_days_total_store_sales)
        else:
            saved_last_7_days_total_store_sales = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_last_7_days_total_store_sales = store.get("last_7_days_total_store_sales", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_store_sales", 0)
            
            return "{0:.3f}".format(saved_last_7_days_total_store_sales + latest_analytics)

    def resolve_total_msp_sales(root: store_models.StoreInfo, _info):
        if hasattr(root, "total_msp_sales"):
            return "{0:.3f}".format(root.total_msp_sales)
        else:
            saved_total_msp_sales = 0
            
            store = StoreAnalytics.saved_analytics.get(root.id)
            if store:
                saved_total_msp_sales = store.get("saved_total_msp_sales", 0)
            latest_analytics = StoreAnalytics.latest_store_analytics_dict.get(root.id, {}).get("total_msp_sales", 0)
            
            return "{0:.3f}".format(saved_total_msp_sales + latest_analytics)

    def resolve_phone_number(root: store_models.StoreInfo, _info):
        # store_members = root.get_store_authorized_users()
        # if store_members:
        #     return store_members[0].mobile_no
        # else:
        #     return ""
        saved_mobile_no = ""
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
                    
            saved_mobile_no = store.get("mobile_no", 0)
                    
        
        return saved_mobile_no

    
    def resolve_total_brand_clicks(root: store_models.StoreInfo, _info):
        if hasattr(root, "total_brand_clicks"):
            return root.total_brand_clicks
        else:
            visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
            total_brand_clicks =  visits.get("total_brand_clicks", 0)
            return total_brand_clicks
    
    def resolve_total_category_clicks(root: store_models.StoreInfo, _info):
        if hasattr(root, "total_category_clicks"):
            return root.total_category_clicks
        else:
            visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
            total_category_clicks =  visits.get("total_category_clicks", 0)
            return total_category_clicks
    
    def resolve_my_orders(root: store_models.StoreInfo, _info):
        return 0
        #return 0 for my_orders for now since the use case of this keys isn't clear at the moment.
        '''
        if hasattr(root, "my_orders"):
            return root.my_orders
        else:
            visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
            my_orders =  visits.get("my_orders", 0)
            return my_orders
        '''

    def resolve_checkout_success(root: store_models.StoreInfo, _info):
        if hasattr(root, "checkout_success"):
            return root.checkout_success
        else:
            visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
            checkout_success =  visits.get("checkout_success", 0)
            return checkout_success

    def resolve_checkout_fail(root: store_models.StoreInfo, _info):
        if hasattr(root, "checkout_fail"):
            return root.checkout_fail
        else:
            visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
            checkout_fail =  visits.get("checkout_fail", 0)
            return checkout_fail

    def resolve_return_policy(root: store_models.StoreInfo, _info):
        if hasattr(root, "return_policy"):
            return root.return_policy
        else:
            visits = StoreAnalytics.store_google_analytics_queryset.get(str(root.id), {})
            return_policy =  visits.get("return_policy", 0)
            return return_policy
    
    def resolve_total_earnings(root: store_models.StoreInfo, _info):
        # earnings = 0
        # store_order_lines = time_period_filter(StoreAnalytics.orderline_store_product_brand_queryset.filter(
        #     order__platform_code=PlatformTypeEnum.INFLUENCER_STORE).filter(
        #     order__order_store__store=root.id).exclude(fulfillment_line__fulfillment__status__in = [
        #         FulfillmentStatus.RETURN_COMPLETED, FulfillmentStatus.RETURN_INITIATED ,
        #         FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLATION_INITIATED]), 
        #         "total_earnings", StoreAnalytics.time_period, field="order__created__date")

        # for line in store_order_lines:
    
        #     earnings += Decimal(line["metadata"].get("influencer_commission", 0))
        saved_total_earnings=0
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
                    
            saved_total_earnings = store.get("total_earnings", 0)

        return "{0:.3f}".format(saved_total_earnings)

    
    def resolve_last_login_time(root: store_models.StoreInfo, _info):
        store_members = StoreAnalytics.store_authorised_users_dict.get(root.id, [])
        if store_members:
            return store_members[0].last_login
        else:
            return ""
        

    def resolve_cities(root: store_models.StoreInfo, _info):
        
        store = StoreAnalytics.saved_analytics.get(root.id)
        if store:
                    
            return store.get("last_3_order_cities", '')

        return ''
    
    
    def resolve_app_last_launched_at(root: store_models.StoreInfo, _info):
        store_members = StoreAnalytics.store_authorised_users_dict.get(root.id, [])

        if store_members:
            if StoreAnalytics.store_member_user_objs_dict.get(store_members[0].id):
                return StoreAnalytics.store_member_user_objs_dict.get(store_members[0].id)[1]
            
        return ""

    def resolve_last_7_days_total_visitors(root: store_models.StoreInfo, _info):
        return root.metadata.get('weekly_visitors', 0)
    
    def resolve_last_30_days_pdp_views(root: store_models.StoreInfo, _info):
        return StoreAnalytics.past_month_pdp_views_data.get(root.id, 0)
    
    def resolve_last_7_days_pdp_views(root: store_models.StoreInfo, _info):
        return StoreAnalytics.past_week_pdp_views_data.get(root.id, 0)
    
    def resolve_last_7_days_a2c(root: store_models.StoreInfo, _info):
        return StoreAnalytics.last_7_days_a2c_data.get(root.id, 0)

class EarningAnalytics(CountableDjangoObjectType):
    earnings = graphene.Decimal(description='Total earning of store')
    visits_count = graphene.Int(description='visits on the store')
    orders_count = graphene.Int(description='count of order lines related to store')
    likes_count = graphene.Int(description='count of like on the store\
        return the number of wishlistItem related to the store')
    signups = graphene.Int(description='number of sign ups')
    due_amount = graphene.Decimal(description='amount due on the store')
    lines = FilterInputConnectionField(
        lambda: OrderLine, required=True, description="List of order lines.",
        myline = graphene.Argument(graphene.Boolean, description="Boolean to show order line of current user in specified stores"),
        sort_by=OrderLineSortingInput(description="Sort orderlines."),
        )
    total_amount_paid = graphene.Decimal(description = "Total amount paid in Payout")
    available_coupons_count = graphene.Int(description='count of available coupon')

    class Meta:
        description = "Earning Dashboard analytics"
        model = store_models.StoreInfo
        exclude = ("store_type", "store_category_page_level")
        registry = Registry()

    def resolve_earnings(root, _info):
        
        return resolve_total_earning(root, _info)
    
    def resolve_lines(root, _info, myline=False, **args):

        if myline:
            return resolve_my_order_lines(root, _info)
        else:
            return resolve_order_line_from_store_excluding_influencer(root, _info)

    def resolve_visits_count(root, _info):
        return resolve_store_visits(root)
        
        
    def resolve_orders_count(root, _info):

        return resolve_orders_count(root, _info)
    
    def resolve_likes_count(root, _info):

        return resolve_likes_count(root)

    def resolve_signups(root, _info):
        
        return 0
    
    def resolve_due_amount(root, _info):

        return resolve_due_amount(root,_info)
    
    def resolve_total_amount_paid(root,info,**kwargs):

        total_amount = root.store_payout.all().aggregate(Sum('amount'))
        if total_amount.get('amount__sum'):
            return total_amount.get('amount__sum')
        else:
            return Decimal(0)
    
    def resolve_available_coupons_count(root,info,**kwargs):
        todays_date = TimeUtilities.get_current_date_time()
        return Voucher.objects.filter(store_id =root.id).active(todays_date).exclude(Q(metadata__has_key='hide_listing')&Q(metadata__hide_listing = True)).count()

class brandvariant(graphene.ObjectType):
    name = graphene.String(description="name of the product")
    track_inventory = graphene.Boolean(description="Track inventory bool")
    brand_stock = graphene.Int(
        description="Inventory from brand side"
    )

    
    @staticmethod
    def resolve_name(root, _info):
        fields = root['fields']
        return fields.get('name','')
    
    @staticmethod
    def resolve_track_inventory(root, _info):
        fields = root['fields']
        return fields.get('track_inventory','')
    
    @staticmethod
    def resolve_brand_stock(root, _info):
        fields = root['stock']
        return fields.get('quantity','')

class pdpsorttype(graphene.InputObjectType):
    publication_date = graphene.String(description="sort from publication date")
    pdp_views = graphene.String(description="sort from pdp views")
    order_counts = graphene.String(description = "sort from order counts")
    brand_order_counts = graphene.String(description = "sort from brand order counts")

class pdpproducttype(graphene.ObjectType):
    product_zaamo_id = graphene.String(description="Product zaamo id")
    slug = graphene.String(description="Product slug")
    total_store_views = graphene.Int(description = 'Total views of product from store ')
    data_source = graphene.String(description = "source of data")
    brand_id = graphene.String(description="brand id")
    product_id_brand = graphene.String(description="name of the product")
    variant_id_brands = graphene.List(graphene.String, description="list of variant id in brand")
    name = graphene.String(description="name of the product")
    images = graphene.List(graphene.String, description="images of the product")
    variants = graphene.List(brandvariant, description='List of variants in product')
    category = graphene.Field(
        Category, description="List of variants for the product."
    )
    zaamo_variants = graphene.List(
        ProductVariant, description="List of variants for the product."
    )
    description = graphene.String(description = 'description of product')
    publication_date = graphene.String(description="date of the publication")
    brand_product_creation_date = graphene.String(description="date of product creation from brand's end")
    brand_product_mrp = graphene.String(description="mrp of product")
    brand_product_msp = graphene.String(description="msp of product")
    weekly_visits = graphene.Int(
        description="weekly visits on particular product"
    )
    wishlist_count = graphene.Int(
        description="count of wishlist which have this product"
    )
    order_count = graphene.Int(
        description="order lines placed with the product"
    )
    pdp_views = graphene.Int(
        description="pdp views with the product"
    )
    store_count = graphene.Int(
        description="number of stores which have this product"
    )
    brand_order_count_last_week = graphene.Int(
        description="weekly brand order count"
    )
    brand_order_count = graphene.Int(
        description="brand order count"
    )
    is_published = graphene.Boolean(description="Whether the product is published.")
    value_deal = graphene.Boolean(description="is value deal bool")
    commission = graphene.String(description="Commssions for products", required=False)
    brand_barter = graphene.String(description="Brand Barter for Products")

    @staticmethod
    def resolve_name(root, _info):
        return root['product.product']['fields']['name']
    
    @staticmethod
    def resolve_images(root, _info):
        return root.get('product.productimage')

    @staticmethod
    def resolve_variants(root, _info):
        variant_list = root.get('product.productvariant',[])
            
        return variant_list
    
    @staticmethod
    def resolve_category(root, _info):

        if root.get('product_zaamo'):
            return root.get('product_zaamo').category
        
        return None

    @staticmethod
    def resolve_total_store_views(root, _info):

        return root.get('storeview_count',0)

    @staticmethod
    def resolve_zaamo_variants(root, _info):
        
        if root.get('product_zaamo_id'):
            return root.get('product_zaamo').variants.all()
        
        return product_models.ProductVariant.objects.none()

    @staticmethod
    def resolve_product_zaamo_id(root, _info):
        if root.get('product_zaamo_id'):
            return root.get('product_zaamo_id')

        return ''
    
    @staticmethod
    def resolve_data_source(root, _info):
        if root.get('product_zaamo_id'):
            return 'postgres'

        return 'mongo'

    @staticmethod
    def resolve_slug(root, _info):
        if root.get('slug'):
            return root.get('slug')

        return ''
    
    @staticmethod
    def resolve_brand_id(root, _info):
        if root.get('brand_id'):
            return root.get('brand_id')

        return ''

    @staticmethod
    def resolve_product_id_brand(root, _info):
        brand_mapping = root['product.brand_variant_zaamomapping']

        return brand_mapping.get('product_id_brand','')

    @staticmethod
    def resolve_variant_id_brands(root, _info):
        brand_mapping = root['product.brand_variant_zaamomapping']

        return brand_mapping.get('variant_id_brands',[])
    
    @staticmethod
    def resolve_description(root, _info):
        product_data = root['product.product']['fields']
        description_json = product_data['description_json']
        description = description_json.get('description_text')

        return description

    @staticmethod
    def resolve_publication_date(root, _info):
        return resolve_publication_date_product(root)
        
    @staticmethod
    def resolve_is_published(root, _info):
        return resolve_is_published_product(root)
    
    @staticmethod
    def resolve_wishlist_count(root, _info):
        return root.get('wishlist_count',0)

    @staticmethod
    def resolve_weekly_visits(root, _info):
        return 0

    @staticmethod
    def resolve_pdp_views(root, _info):
        return root.get('pdp_views',0)

    @staticmethod
    def resolve_order_count(root, _info):
        return root.get('order_count',0)

    @staticmethod
    def resolve_store_count(root, _info):
        return root.get('store_count',0)
    
    
    @staticmethod
    def resolve_brand_order_count_last_week(root, _info):
        return root.get('brand_order_count_last_week',0)
    
    
    @staticmethod
    def resolve_brand_order_count(root, _info):
        return root.get('brand_order_count',0)
    
    @staticmethod
    def resolve_commission(root, _info):
        
        if root.get('product_zaamo'):

            if root.get('product_zaamo').has_custom_commission:
                return root.get('product_zaamo').commission_percentage

        return root.get('commission',0.0)

    @staticmethod
    def resolve_brand_barter(root,_info):

        if root.get('product_zaamo'):
            return root.get('product_zaamo').brand_barter
        
        return False

    @staticmethod
    def resolve_brand_product_creation_date(root, _info):
        return root.get('product.created_at')
        
    
    @staticmethod
    def resolve_brand_product_creation_date(root, _info):
        return root.get('product.created_at','')
    
    @staticmethod
    def resolve_brand_product_mrp(root, _info):
        variant_data = root.get('product.productvariant')
        if variant_data:
            fields = variant_data[0].get('fields')
            if fields:
                return fields.get('cost_price_amount',0.0)
        
        return 0.0
    
    @staticmethod
    def resolve_brand_product_msp(root, _info):
        variant_data = root.get('product.productvariant')
        if variant_data:
            fields = variant_data[0].get('fields')
            if fields:
                return fields.get('price_amount',0.0)
        
        return 0.0

    @staticmethod
    def resolve_value_deal(root,_info):
        
        if root.get('product_zaamo'):
            return root.get('product_zaamo').metadata.get('value_deal',False)
        
        return False

class PdpAnalytics(BaseAnalyticsMixin,CountableDjangoObjectType):
    collections = graphene.List(graphene.String, description='List of collections in brand')
    categories = graphene.List(graphene.String, description='List of categories in brand')
    sub_categories = graphene.List(graphene.String, description='List of sub_categories in brand')
    product_type = graphene.List(ProductType, description='List of product_type in brand')
    products = graphene.List(
        pdpproducttype,
        description="List of products in the brand.",
        page=graphene.Argument(graphene.Int, description='page number'),
        brand_collection=graphene.Argument(graphene.List(graphene.String), description="list of collection names"),
        brand_category=graphene.Argument(graphene.List(graphene.String), description="list of category names"),
        brand_sub_category=graphene.Argument(graphene.List(graphene.String), description="list of sub category names"),
        product_type=graphene.Argument(graphene.List(graphene.ID), description="list of product type names"),
        is_published=graphene.Argument(graphene.Boolean, description="is product published"),
        data_source=graphene.Argument(graphene.String, description="Source of Data"),
        sort = graphene.Argument(pdpsorttype, description="sorting arguments for pdp")
    )

    class Meta:
        description = "PDP Analytics"
        model = Brand
        interfaces = [relay.Node, ObjectWithMetadata]
        registry = Registry()
        only_fields = [
            'brand_name',
            'id'
        ]


    @staticmethod
    def resolve_collections(root, _info):
        
        return _info.context.collection_category_data['collection']
    
    @staticmethod
    def resolve_categories(root, _info):
        
        return _info.context.collection_category_data['category']
    
    @staticmethod
    def resolve_sub_categories(root, _info):
        
        return _info.context.collection_category_data['subcategory']
    
    @staticmethod
    def resolve_product_type(root, _info):
        return resolve_product_type_of_brand(root, _info)
    
    @staticmethod
    def resolve_products(root, _info, page=1, **args):
        return paginated_resolve_product_of_brand(root, _info, args, page)

class MasterDashboardKPI(graphene.ObjectType):
    gmv = graphene.Decimal(description="total cost of all orders")
    products_sold = graphene.Int(description="total number of products sold")
    received_order_count = graphene.Int(description="count of received order")
    shipped_order_count = graphene.Int(description="count of shipped order")
    delivered_order_count = graphene.Int(description="count of delivered order")
    delayed_order_count = graphene.Int(description="total number of orders delayed")
    influencer_earning = graphene.Int(description="total earnings of influencers")
    completed_sourcing_requests = graphene.String(description="count of completed sourcing requests")
    number_of_botdTrueBrands = graphene.Int(description="total number of botdTrueBrands")
    store_gmv = graphene.Int(description="store gmv")

    class Meta:
        description = "Represents master dashboard kpis"


class SourceWithZaamoKPI(graphene.ObjectType):

    count_of_coupons_created_by_brand = graphene.Int(description="number of coupons created by brand in current month")

    class Meta:
        description = "Represents source with zaamo kpis"

