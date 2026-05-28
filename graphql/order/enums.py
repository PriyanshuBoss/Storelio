import graphene

from ...graphql.core.enums import to_enum
from ...order import OrderEvents, OrderEventsEmails
from saleor.order import FulfillmentStatus, SourcingRequestOrderStatusFilter
from saleor.graphql.analytics.enums import BrandOrderStatus
from saleor.graphql.core.enums import to_enum
from saleor.utilities.time_utilities import TimeUtilities
from datetime import datetime

OrderEventsEnum = to_enum(OrderEvents)
OrderEventsEmailsEnum = to_enum(OrderEventsEmails)
BrandOrderStatusEnum = to_enum(BrandOrderStatus)
OrderFullfillmentStatusEnum = to_enum(FulfillmentStatus)
SourcingRequestOrderStatusFilterEnum = to_enum(SourcingRequestOrderStatusFilter)


class OrderStatusFilter(graphene.Enum):
    READY_TO_FULFILL = "ready_to_fulfill"
    READY_TO_CAPTURE = "ready_to_capture"
    UNFULFILLED = "unfulfilled"
    PARTIALLY_FULFILLED = "partially fulfilled"
    FULFILLED = "fulfilled"
    CANCELED = "canceled"


class TimePeriod(graphene.Enum):
    LASTHOUR = "Last hour"
    TODAY = "Today"
    YESTERDAY = "Yesterday"
    TILLTODAYTHISWEEK = "Till today in this calander week"
    LASTWEEK = "Last calander week"
    TILLTODAYTHISMONTH = "Till today this month"
    LASTMONTH = "Last month"
    OVERALL = "Overall till date"


    @staticmethod
    def time_period_to_datetime(value):
        timeutility = TimeUtilities()
        release_date = datetime(2022, 1, 4)
        date_range = {"gte": release_date, "lte": TimeUtilities.get_current_date_time()}
        
        if value==TimePeriod.LASTHOUR:
           date_range["gte"] = timeutility.get_last_hour_date_time()
        
        elif value==TimePeriod.TODAY: 
            today_start = timeutility.get_today_start()
            date_range["gte"] = today_start

        elif value==TimePeriod.YESTERDAY: 
            yesterday_start = timeutility.get_yesterdays_date()
            today_start = timeutility.get_today_start()
            date_range["gte"] = yesterday_start
            date_range["lte"] = today_start

        elif value==TimePeriod.TILLTODAYTHISWEEK: 
            this_week_start = timeutility.get_current_week_start()
            date_range["gte"] = this_week_start

        elif value==TimePeriod.LASTWEEK: 
            last_week_start, last_week_end = timeutility.get_prev_week_boundaries()
            date_range["gte"] = last_week_start 
            date_range["lte"] = last_week_end

        elif value==TimePeriod.TILLTODAYTHISMONTH: 
            curr_month_start_date = timeutility.get_current_month_start()
            date_range["gte"] = curr_month_start_date

        elif value==TimePeriod.LASTMONTH: 
            prev_month_start_date, prev_month_end_date = timeutility.get_prev_month_boundaries()
            date_range["gte"] = prev_month_start_date
            date_range["lte"] = prev_month_end_date

        if date_range["gte"] < release_date:
            date_range["gte"] = release_date

        return date_range

