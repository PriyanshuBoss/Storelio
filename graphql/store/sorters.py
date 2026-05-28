import graphene
from saleor.graphql.core.types.sort_input import SortInputObjectType
from saleor.utilities.time_utilities import TimeUtilities
from django.db.models import Q, QuerySet, Sum, F, DecimalField
from django.db.models.functions import Coalesce
from saleor.utilities.request_utilities import PlatformTypeEnum

class StorePayoutSortField(graphene.Enum):
    DATE = ["date"]

    @property
    def description(self):
        if self in [
            StorePayoutSortField.BRAND_NAME,
            StorePayoutSortField.UPDATED_AT,
            StorePayoutSortField.CREATED_AT
        ]:
            sort_name = self.name.lower().replace("_", " ")

            return f"Sort brands by {sort_name}."
        
        raise ValueError("Unsupported enum value: %s" % self.value)

class StorePayoutSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = StorePayoutSortField
        type_name = "store payout"

class StoreManagerCommentSortField(graphene.Enum):
    UPDATED_AT  = ["updated_at"]
    CREATED_AT = ["created_at"]

    @property
    def description(self):
        if self in [
            StoreManagerCommentSortField.UPDATED_AT,
            StoreManagerCommentSortField.CREATED_AT
        ]:
            sort_name = self.name.lower().replace("_", " ")

            return f"Sort comments by {sort_name}."
        
        raise ValueError("Unsupported enum value: %s" % self.value)

class StoreManagerCommentInput(SortInputObjectType):
    class Meta:
        sort_enum = StoreManagerCommentSortField
        type_name = "StoreManagerComment"


class BrandSourceRequestSortField(graphene.Enum):
    CREATED_AT = ["created_at"]

    @property
    def description(self):
        if self in [
            BrandSourceRequestSortField.CREATED_AT
        ]:
            sort_name = self.name.lower().replace("_", " ")

            return f"Sort comments by {sort_name}."
        
        raise ValueError("Unsupported enum value: %s" % self.value)

class BrandSourceRequestInput(SortInputObjectType):
    class Meta:
        sort_enum = BrandSourceRequestSortField
        type_name = "BrandSourceRequest"

class StoreSortField(graphene.Enum):
    GMV_LAST_HOUR = ["gmv_last_hour", "id"]
    GMV_LAST_24_HOUR = ["gmv_last_24_hour", "id"]
    GMV_LAST_7_DAYS = ["gmv_last_7_days", "id"]
    GMV_LAST_30_DAYS = ["gmv_last_30_days", "id"]
    RANDOM = ["randomize","id"]
    COUPON_CREATED = ["recommended"]

    @staticmethod
    def qs_with_gmv_last_hour(queryset: QuerySet) -> QuerySet:
        time_utilities = TimeUtilities()
        end_date =  TimeUtilities.get_current_date_time()
        start_date = time_utilities.get_last_hour_date_time()

        queryset = queryset.prefetch_related('order_store').annotate(
            gmv_last_hour = Coalesce(
                Sum(
                    F('order_store__order__total_net_amount')+F('order_store__order__discount_amount'),
                    filter=Q(order_store__created_at__gte=start_date) & Q(order_store__created_at__lte=end_date) & Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),
                    output_field=DecimalField()
                ), 0
            )
        )

        return queryset
    
    @staticmethod
    def qs_with_gmv_last_24_hour(queryset: QuerySet) -> QuerySet:
        time_utilities = TimeUtilities()
        end_date =  TimeUtilities.get_current_date_time()
        start_date = time_utilities.subtract_time_from_timestamp(end_date, hours=24)

        queryset = queryset.prefetch_related('order_store').annotate(
            gmv_last_24_hour = Coalesce(
                Sum(
                    F('order_store__order__total_net_amount')+F('order_store__order__discount_amount'),
                    filter=Q(order_store__created_at__gte=start_date) & Q(order_store__created_at__lte=end_date) & Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),
                    output_field=DecimalField()
                ), 0
            )
        )

        return queryset

    @staticmethod
    def qs_with_gmv_last_7_days(queryset: QuerySet) -> QuerySet:
        time_utilities = TimeUtilities()
        end_date = TimeUtilities.get_current_date_time()
        start_date = time_utilities.subtract_time_from_timestamp(end_date, days=7)
        
        queryset = queryset.prefetch_related('order_store').annotate(
            gmv_last_7_days = Coalesce(
                Sum(
                    F('order_store__order__total_net_amount')+F('order_store__order__discount_amount'),
                    filter=Q(order_store__created_at__gte=start_date) & Q(order_store__created_at__lte=end_date) & Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),
                    output_field=DecimalField()
                ), 0
            )
        )
        
        return queryset

    @staticmethod
    def qs_with_gmv_last_30_days(queryset: QuerySet) -> QuerySet:
        time_utilities = TimeUtilities()
        end_date = TimeUtilities.get_current_date_time()
        start_date = time_utilities.subtract_time_from_timestamp(end_date, days=30)
        
        queryset = queryset.prefetch_related('order_store').annotate(
            gmv_last_30_days = Coalesce(
                Sum(
                    F('order_store__order__total_net_amount')+F('order_store__order__discount_amount'),
                    filter=Q(order_store__created_at__gte=start_date) & Q(order_store__created_at__lte=end_date) & Q(order_store__order__platform_code=PlatformTypeEnum.INFLUENCER_STORE),
                    output_field=DecimalField()
                ), 0
            )
        )
        
        return queryset
    @staticmethod
    def qs_with_randomize(queryset: QuerySet) -> QuerySet:     
        return queryset    

    @staticmethod
    def qs_with_coupon_created(queryset: QuerySet) -> QuerySet:
        return queryset

class StoreSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = StoreSortField
        type_name = "Store"
