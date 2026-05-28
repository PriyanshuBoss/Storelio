import django_filters
from django.db.models import Count, Sum,Subquery
import graphene

from graphene_django.filter import GlobalIDFilter
from saleor.graphql.core.types.filter_input import FilterInputObjectType

from ...account.models import User,Influencer, UserMedia,UserLikeStatus
from ..core.filters import EnumFilter, ObjectTypeFilter
from ..core.types.common import DateRangeInput, IntRangeInput, PriceRangeInput
from ..utils.filters import filter_by_query_param, filter_range_field
from .enums import StaffMemberStatus,InfluencerStateEnum, InfluencerStatusEnums


def filter_date_joined(qs, _, value):
    return filter_range_field(qs, "date_joined__date", value)


def filter_money_spent(qs, _, value):
    qs = qs.annotate(money_spent=Sum("orders__total_gross_amount"))
    return filter_range_field(qs, "money_spent", value)


def filter_number_of_orders(qs, _, value):
    qs = qs.annotate(total_orders=Count("orders"))
    return filter_range_field(qs, "total_orders", value)


def filter_placed_orders(qs, _, value):
    return filter_range_field(qs, "orders__created__date", value)


def filter_status(qs, _, value):
    if value == StaffMemberStatus.ACTIVE:
        qs = qs.filter(is_staff=True, is_active=True)
    elif value == StaffMemberStatus.DEACTIVATED:
        qs = qs.filter(is_staff=True, is_active=False)
    return qs


def filter_staff_search(qs, _, value):
    search_fields = (
        "email",
        "first_name",
        "last_name",
        "default_shipping_address__first_name",
        "default_shipping_address__last_name",
        "default_shipping_address__city",
        "default_shipping_address__country",
        "default_shipping_address__phone",
    )
    if value:
        qs = filter_by_query_param(qs, value, search_fields)
    return qs


def filter_search(qs, _, value):
    search_fields = ("name",)
    if value:
        qs = filter_by_query_param(qs, value, search_fields)
    return qs

def filter_search_influencer(qs,_,value):
    search_fields = ("instagram_username","instagram_link", "user__mobile_no")
    if value:
        qs = filter_by_query_param(qs, value, search_fields)
    return qs

def filter_influencer_by_state(qs,_,value):
    return qs.filter(state = value)

def filter_influencer_by_status(qs,_,value):
    return qs.filter(status = value)

class CustomerFilter(django_filters.FilterSet):
    date_joined = ObjectTypeFilter(
        input_class=DateRangeInput, method=filter_date_joined
    )
    money_spent = ObjectTypeFilter(
        input_class=PriceRangeInput, method=filter_money_spent
    )
    number_of_orders = ObjectTypeFilter(
        input_class=IntRangeInput, method=filter_number_of_orders
    )
    placed_orders = ObjectTypeFilter(
        input_class=DateRangeInput, method=filter_placed_orders
    )
    search = django_filters.CharFilter(method=filter_staff_search)

    class Meta:
        model = User
        fields = [
            "date_joined",
            "money_spent",
            "number_of_orders",
            "placed_orders",
            "search",
        ]


class PermissionGroupFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method=filter_search)


class StaffUserFilter(django_filters.FilterSet):
    status = EnumFilter(input_class=StaffMemberStatus, method=filter_status)
    search = django_filters.CharFilter(method=filter_staff_search)

    # TODO - Figure out after permision types
    # department = ObjectTypeFilter

    class Meta:
        model = User
        fields = ["status", "search"]

class InfluencerFilter(django_filters.FilterSet):

    state = EnumFilter(input_class=InfluencerStateEnum, method=filter_influencer_by_state)
    search = django_filters.CharFilter(method=filter_search_influencer)
    status = EnumFilter(input_class=InfluencerStatusEnums, method=filter_influencer_by_status)

    class Meta:
        model = Influencer
        fields = ["state","search","id", "status"]


def filter_by_like_status(qs,_,value):

    if value==False:
        return qs.filter(id__in=Subquery(UserLikeStatus.objects.filter(like_status=False).values('content_id')))

    if value == True:
        return qs.filter(id__in=Subquery(UserLikeStatus.objects.filter(like_status=True).values('content_id')))

    return qs


def filter_by_user_id(qs,_,value):

    if value:
        user_id = graphene.Node.from_global_id(value)[1]
        return qs.filter(user_id=user_id)
    
    return qs

class UserMediaFilter(django_filters.FilterSet):

    like_status = django_filters.BooleanFilter(method = filter_by_like_status)
    user_id = GlobalIDFilter(method=filter_by_user_id)

    class Meta:
        model = UserMedia
        fields = []

class UserMediaFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = UserMediaFilter
