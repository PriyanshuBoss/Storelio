import graphene
from ..core.types import SortInputObjectType
from django.db.models import QuerySet


class OrderLineSortField(graphene.Enum):
    CREATION_DATE = ["order__created", "pk"]

    @property
    def description(self):
        if self.name in OrderLineSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort orders lines by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)


class OrderLineSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = OrderLineSortField
        type_name = "lines"


class StoreAnalyticsSortField(graphene.Enum):
    TOTAL_VISITORS  = ["total_visitors", "created_at"]
    TOTAL_ORDERS    = ["total_orders", "created_at"]
    WISHLIST        = ["wishlist_of_products", "created_at"]
    AVG_ORDER_VALUE = ["avg_order_value", "created_at"]
    TOTAL_BRAND_CLICKS = ["total_brand_clicks", "created_at"]
    TOTAL_CATEGORY_CLICKS = ["total_category_clicks", "created_at"]
    MY_ORDERS = ["my_orders", "created_at"]
    CHECKOUT_SUCCESS = ["checkout_success", "created_at"]
    CHECKOUT_FAIL = ["checkout_fail", "created_at"]
    RETURN_POLICY = ["return_policy", "created_at"]
    LAST_30_DAYS_TOTAL_ORDERS    = ["last_30_days_total_orders", "created_at"]
    LAST_30_DAYS_TOTAL_STORE_SALES = ["last_30_days_total_store_sales", "created_at"]
    LAST_30_DAYS_NUMBER_OF_PRODUCT_SOLD = ["last_30_days_number_of_products_sold", "created_at"]
    LAST_7_DAYS_NUMBER_OF_PRODUCT_SOLD = ["last_7_days_total_orders", "created_at"]
    LAST_7_DAYS_TOTAL_STORE_SALES = ["last_7_days_total_store_sales", "created_at"]
    LAST_7_DAYS_TOTAL_ORDERS    = ["last_7_days_total_orders", "created_at"] 
    CREATED_AT = ["created_at"]


    @property
    def description(self):
        if self.name in StoreAnalyticsSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort Store by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    ### field annotation done earlier in get_queryset StoreAnalytics
    @staticmethod
    def qs_with_total_visitors(queryset: QuerySet) -> QuerySet:
        return queryset
    
    @staticmethod
    def qs_with_total_orders(queryset: QuerySet) -> QuerySet:
        return queryset

    @staticmethod
    def qs_with_wishlist_of_products(queryset: QuerySet) -> QuerySet:
        return queryset

    @staticmethod
    def qs_with_avg_order_value(queryset: QuerySet) -> QuerySet:
        return queryset


class StoreAnalyticsSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = StoreAnalyticsSortField
        type_name = "store_analytics"

