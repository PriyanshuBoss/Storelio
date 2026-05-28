from typing import List

import graphene
import django_filters
from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.utils import timezone
from graphene_django.filter.filterset import GlobalIDMultipleChoiceFilter, GlobalIDFilter

from saleor.graphql.utils import get_nodes

from ...discount import DiscountValueType
from ...discount.models import Sale, Voucher, VoucherQueryset, VoucherStoreDealMapping
from saleor.brand import models as brand_models
from saleor.product import models as product_models
from saleor.store import models as store_models
from ..core.filters import EnumFilter, ListObjectTypeFilter, ObjectTypeFilter
from ..core.types.common import DateTimeRangeInput, IntRangeInput
from ..utils.filters import filter_by_query_param, filter_range_field
from .enums import DiscountStatusEnum, DiscountValueTypeEnum, VoucherDiscountType, VoucherTypeEnum


def filter_status(
    qs: VoucherQueryset, _, value: List[DiscountStatusEnum]
) -> VoucherQueryset:
    if not value:
        return qs
    query_objects = qs.none()
    now = timezone.now()
    if DiscountStatusEnum.ACTIVE in value:
        query_objects |= qs.active(now)
    if DiscountStatusEnum.EXPIRED in value:
        query_objects |= qs.expired(now)
    if DiscountStatusEnum.SCHEDULED in value:
        query_objects |= qs.filter(start_date__gt=now)
    return qs & query_objects


def filter_times_used(qs, _, value):
    return filter_range_field(qs, "used", value)


def filter_discount_type(
    qs: VoucherQueryset, _, value: List[VoucherDiscountType]
) -> VoucherQueryset:
    if value:
        query = Q()
        if VoucherDiscountType.FIXED in value:
            query |= Q(
                discount_value_type=VoucherDiscountType.FIXED.value  # type: ignore
            )
        if VoucherDiscountType.PERCENTAGE in value:
            query |= Q(
                discount_value_type=VoucherDiscountType.PERCENTAGE.value  # type: ignore
            )
        if VoucherDiscountType.SHIPPING in value:
            query |= Q(type=VoucherDiscountType.SHIPPING)
        qs = qs.filter(query).distinct()
    return qs


def filter_started(qs, _, value):
    return filter_range_field(qs, "start_date", value)


def filter_sale_type(qs, _, value):
    if value in [DiscountValueType.FIXED, DiscountValueType.PERCENTAGE]:
        qs = qs.filter(type=value)
    return qs


def filter_sale_search(qs, _, value):
    search_fields = ("name", "value", "type")
    if value:
        qs = filter_by_query_param(qs, value, search_fields)
    return qs


def filter_voucher_search(qs, _, value):
    search_fields = ("name", "code")
    if value:
        qs = filter_by_query_param(qs, value, search_fields)
    return qs

def filter_vouchers_by_brands(qs, brands):
    return qs.filter(brands__in=brands)

def filter_brands(qs, _, value):
    if value:
        brands = get_nodes(value, "Brand", brand_models.Brand)
        qs = filter_vouchers_by_brands(qs, brands)
    return qs

def filter_vouchers_by_collections(qs, collections):
    return qs.filter(collections__in=collections)

def filter_collections(qs, _, value):
    if value:
        collections = get_nodes(value, "Collection", product_models.Collection)
        qs = filter_vouchers_by_collections(qs, collections)
    return qs

def filter_vouchers_by_stores(qs, stores):
    return qs.filter(store__in=stores)

def filter_stores(qs, _, value):
    if value:
        stores = get_nodes(value, "Store", store_models.StoreInfo)
        qs = filter_vouchers_by_stores(qs, stores)
    return qs

def filter_sourcing_search(qs, _, value):
    if value:
        endswith = Q()
        contains = Q()
        for sourcing_id in value:
            endswith |= Q(code__endswith=Concat(Value('_'), Value(sourcing_id)))
            contains |= Q(code__contains=Concat(Value('_'), Value(sourcing_id), Value('_')))
        
        return qs.filter(code__startswith='SZ').filter(endswith | contains)

    return qs

def filter_voucher_type(qs, _, value):
    return qs.filter(type=value)
    
class VoucherFilter(django_filters.FilterSet):
    status = ListObjectTypeFilter(input_class=DiscountStatusEnum, method=filter_status)
    times_used = ObjectTypeFilter(input_class=IntRangeInput, method=filter_times_used)

    discount_type = ListObjectTypeFilter(
        input_class=VoucherDiscountType, method=filter_discount_type
    )
    started = ObjectTypeFilter(input_class=DateTimeRangeInput, method=filter_started)
    search = django_filters.CharFilter(method=filter_voucher_search)
    brands = GlobalIDMultipleChoiceFilter(method=filter_brands)
    collections = GlobalIDMultipleChoiceFilter(method=filter_collections)
    stores = GlobalIDMultipleChoiceFilter(method=filter_stores)
    sourcing_search = ListObjectTypeFilter(input_class=graphene.Int, method=filter_sourcing_search)
    voucher_type = EnumFilter(input_class=VoucherTypeEnum, method=filter_voucher_type)
    class Meta:
        model = Voucher
        fields = ["status", "times_used", "discount_type", "started", "search", "voucher_type"]


class SaleFilter(django_filters.FilterSet):
    status = ListObjectTypeFilter(input_class=DiscountStatusEnum, method=filter_status)
    sale_type = ObjectTypeFilter(
        input_class=DiscountValueTypeEnum, method=filter_sale_type
    )
    started = ObjectTypeFilter(input_class=DateTimeRangeInput, method=filter_started)
    search = django_filters.CharFilter(method=filter_sale_search)

    class Meta:
        model = Sale
        fields = ["status", "sale_type", "started", "search"]

class VoucherStoreDealFilter(django_filters.FilterSet):
    id = GlobalIDFilter(field_name="id")

    class Meta:
        model = VoucherStoreDealMapping
        fields = []

