from itertools import chain
from typing import Optional

import graphene
from django.contrib.auth import models as auth_models
from i18naddress import get_validation_rules
from django.db.models import Subquery,Q,Sum,Case, When, Value, IntegerField
from ...account import models
from ...core.exceptions import PermissionDenied
from django.db.models.functions import Coalesce,Round
from saleor.utilities.django_utilities import Random
from ...core.permissions import AccountPermissions
from ...payment import gateway
from ...payment.utils import fetch_customer_id
from ..utils import format_permissions_for_display, get_user_or_app_from_context
from ..utils.filters import filter_by_query_param
from .types import AddressValidationData, ChoiceValue, User
from .utils import (
    get_allowed_fields_camel_case,
    get_required_fields_camel_case,
    get_user_permissions,
)

USER_SEARCH_FIELDS = (
    "email",
    "first_name",
    "last_name",
    "default_shipping_address__first_name",
    "default_shipping_address__last_name",
    "default_shipping_address__city",
    "default_shipping_address__country",
)


def resolve_customers(info, query, **_kwargs):
    qs = models.User.objects.customers()
    qs = filter_by_query_param(
        queryset=qs, query=query, search_fields=USER_SEARCH_FIELDS
    )
    return qs.distinct()


def resolve_permission_groups(info, **_kwargs):
    return auth_models.Group.objects.all()


def resolve_staff_users(info, query, **_kwargs):
    qs = models.User.objects.staff()
    qs = filter_by_query_param(
        queryset=qs, query=query, search_fields=USER_SEARCH_FIELDS
    )
    return qs.distinct()


def resolve_user(info, id):
    requester = get_user_or_app_from_context(info.context)
    if requester:
        _model, user_pk = graphene.Node.from_global_id(id)
        if requester.has_perms(
            [AccountPermissions.MANAGE_STAFF, AccountPermissions.MANAGE_USERS]
        ):
            return models.User.objects.filter(pk=user_pk).first()
        if requester.has_perm(AccountPermissions.MANAGE_STAFF):
            return models.User.objects.staff().filter(pk=user_pk).first()
        if requester.has_perm(AccountPermissions.MANAGE_USERS):
            return models.User.objects.customers().filter(pk=user_pk).first()
    return PermissionDenied()


def resolve_address_validation_rules(
    info,
    country_code: str,
    country_area: Optional[str],
    city: Optional[str],
    city_area: Optional[str],
):

    params = {
        "country_code": country_code,
        "country_area": country_area,
        "city": city,
        "city_area": city_area,
    }
    rules = get_validation_rules(params)
    return AddressValidationData(
        country_code=rules.country_code,
        country_name=rules.country_name,
        address_format=rules.address_format,
        address_latin_format=rules.address_latin_format,
        allowed_fields=get_allowed_fields_camel_case(rules.allowed_fields),
        required_fields=get_required_fields_camel_case(rules.required_fields),
        upper_fields=rules.upper_fields,
        country_area_type=rules.country_area_type,
        country_area_choices=[
            ChoiceValue(area[0], area[1]) for area in rules.country_area_choices
        ],
        city_type=rules.city_type,
        city_choices=[ChoiceValue(area[0], area[1]) for area in rules.city_choices],
        city_area_type=rules.city_type,
        city_area_choices=[
            ChoiceValue(area[0], area[1]) for area in rules.city_area_choices
        ],
        postal_code_type=rules.postal_code_type,
        postal_code_matchers=[
            compiled.pattern for compiled in rules.postal_code_matchers
        ],
        postal_code_examples=rules.postal_code_examples,
        postal_code_prefix=rules.postal_code_prefix,
    )


def resolve_payment_sources(user: models.User):
    stored_customer_accounts = (
        (gtw.id, fetch_customer_id(user, gtw.id)) for gtw in gateway.list_gateways()
    )
    return list(
        chain(
            *[
                prepare_graphql_payment_sources_type(
                    gateway.list_payment_sources(gtw, customer_id)
                )
                for gtw, customer_id in stored_customer_accounts
                if customer_id is not None
            ]
        )
    )


def prepare_graphql_payment_sources_type(payment_sources):
    sources = []
    for src in payment_sources:
        sources.append(
            {
                "gateway": src.gateway,
                "credit_card_info": {
                    "last_digits": src.credit_card_info.last_4,
                    "exp_year": src.credit_card_info.exp_year,
                    "exp_month": src.credit_card_info.exp_month,
                    "brand": "",
                    "first_digits": "",
                },
            }
        )
    return sources


def resolve_address(info, id):
    user = info.context.user
    app = info.context.app
    _model, address_pk = graphene.Node.from_global_id(id)
    if app and app.has_perm(AccountPermissions.MANAGE_USERS):
        return models.Address.objects.filter(pk=address_pk).first()
    if user and not user.is_anonymous:
        return user.addresses.filter(id=address_pk).first()
    return PermissionDenied()


def resolve_permissions(root: models.User):
    permissions = get_user_permissions(root)
    permissions = permissions.order_by("codename")
    return format_permissions_for_display(permissions)

def resolve_user_by_mobile(info, mobile_no):
    
    user_filter = models.User.objects.filter(mobile_no=mobile_no)

    if user_filter:
        return user_filter.first()

def resolve_user_liked_content(info,user_id=None):
    
    if user_id:
        user_id = graphene.Node.from_global_id(user_id)[1]
    else:
        user = info.context.user
        user_id = user.id if user else None
        
    if not user_id:
        return None
    
    else:
        return models.UserMedia.objects.filter(id__in=Subquery(models.UserLikeStatus.objects.filter(user_id=user_id).values('content_id')))

def resolve_user_media(info):

    return models.UserMedia.objects.all().select_related('user')

def resolve_content_feed(info,user_id=None):
    
    if user_id:
        user_id = graphene.Node.from_global_id(user_id)[1]
    else:
        user = info.context.user
        user_id = user.id if user else None
        
    if not user_id:
        return None
    
    
    queryset = models.UserMedia.objects.all().exclude(Q(id__in=Subquery(
                    models.UserLikeStatus.objects.filter(Q(user_id=user_id)).values('content_id')))|Q(user_id=user_id))
    
    message_count_qs = models.UserFollowedStatus.objects.filter(user_id=user_id,message_count__gt=1).values('user','message_count')
    message_count_user_dict = {obj.get('user_id'):obj.get('message_count') for obj in message_count_qs}
    qs_like_count = queryset.values('user_id').annotate(
                                total_likes=Sum('likes_count'),
                                total_dislikes=Sum('dislikes_count')
                            )
    user_sorting_variable_map = dict()

    for like_count in qs_like_count:
        user_sorting_variable_map[like_count['user_id']] = (like_count['total_likes']-like_count['total_dislikes'])*(message_count_user_dict.get(like_count['user_id'],0)+1)
        
    queryset = queryset.annotate(
                    sort_value=Case(
                        *[When(user_id=user_id, then=Value(values)) for user_id, values in user_sorting_variable_map.items()],
                        default=Value(0),
                        output_field=IntegerField()
                    )
                )
    
    return queryset.annotate(random = Round(Random(seed=0)*100000+1,output_field=IntegerField())).select_related('user')

def resolve_all_likes(info,content_id):
    content_id = graphene.Node.from_global_id(content_id)[1]

    if content_id:
        return models.User.objects.filter(id__in=Subquery(models.UserLikeStatus.objects.filter(content_id=content_id).values('user_id')))
    
    else:
        return None

def resolve_user_followers(info, user_id):
    if user_id:
        user_id = graphene.Node.from_global_id(user_id)[1]
    return models.UserFollowedStatus.objects.filter(followee_id=user_id, follow_status=True)

def resolve_user_following(info, user_id):
    if user_id:
        user_id = graphene.Node.from_global_id(user_id)[1]
    return models.UserFollowedStatus.objects.filter(user_id=user_id, follow_status=True)
