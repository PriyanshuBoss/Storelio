import graphene
from saleor.graphql.core.filters import EnumFilter, ListObjectTypeFilter
from saleor.graphql.core.types.filter_input import FilterInputObjectType
from saleor.graphql.store.enums import StoreTileEnums, StoreTileEnum, StoreTypeEnums, StoreStatusEnums, BrandSourceRequestEnums, BrandCollabEnums, StoreNextActionsEnums
from saleor.graphql.store.types import Store
from saleor.graphql.utils import get_nodes
from saleor.store.models import StoreCategoryPage, StoreManagerComment, StoreTile, StoreInfo, BrandSourcingRequest
import django_filters
from saleor.graphql.utils.filters import filter_by_query_param
from graphene_django.filter import  GlobalIDMultipleChoiceFilter, GlobalIDFilter
from saleor.graphql.brand.types import Brand
from saleor.graphql.product.types import Category
from django.db.models import Q
from saleor.account.models import User
from saleor.brand import models as brand_models

def filter_tile_type(qs, _ , value):

    if value:
        qs = qs.filter(Q(tile_type=value)|Q(tile_type=StoreTileEnum.INFLUENCER_HOME_STORE)).active()

    return qs

def filter_brands(qs, _, value):
    
    if value:
        brands = get_nodes(value, Brand)
        qs = qs.filter(brand__in=brands)
    
    return qs

def filter_stores(qs, _, value):
    
    if value:
        stores = get_nodes(value, Store)
        qs = qs.filter(store__in=stores)
    
    return qs

def filter_categories(qs, _, value):
    
    if value:
        categories = get_nodes(value, Category)
        qs = qs.filter(category__in=categories)
    
    return qs

def filter_by_store_type(qs, _, value):
    if value:
        qs = qs.filter(store_type=value)
    
    return qs

def filter_by_store_barter(qs, _, value):

    if value:
        qs = qs.filter(Q(metadata__store_barter = True))
    else:
        qs = qs.filter(Q(metadata__store_barter = False) | Q(metadata__store_barter__isnull = True))

    return qs

    
def filter_brand_source_request_by_stores(qs, _, value):

    if value:
        stores = get_nodes(value, "Store", StoreInfo)
        qs = qs.filter(store__in = stores)
    
    return qs

def filter_brand_source_request_by_brands(qs, _, value):

    if value:
        brands = get_nodes(value, "Brand", brand_models.Brand)
        qs = qs.filter(brand__in = brands)
    
    return qs

def filter_brand_source_request_by_state(qs, _, value):
    
    if value:
        qs = qs.filter(state = value)
    
    return qs

def filter_brand_source_request_by_store_bucket(qs, _, value):

    if value:
        qs = qs.filter(store_bucket = value)
    
    return qs

def filter_brand_source_request_by_user(qs, _, value):
    
    if value:
        users = get_nodes(value,"User",User)
        qs = qs.filter(created_by__in = users)
    
    return qs 

def filter_brand_source_request_by_brand_collab(qs, _, value):
    
    if value:
        qs = qs.filter(brand_collab = value)

    return qs

def filter_brand_source_request_by_containing_mail(qs,_,value):
    
    if value:
        qs = qs.filter(Q(store_managers__contains = value) | Q(brand_managers__contains = value))
    
    return qs

def filter_store_by_search(qs, _, value):
    if value:
        qs = filter_by_query_param(qs, value, ("store_name","slug"))
    return qs

def filter_store_status(qs, _, value):
    if value:
        qs = qs.filter(actions__status__in = value)
    return qs

def filter_store_manager(qs, _, value):
    if value:
        qs = qs.filter(staff_store_mappings__user__email__in = value)
    return qs

def filter_by_store_next_actions(qs, _, value):
    if value:
        qs = qs.filter(actions__next_actions__in = value)
    return qs


class StoreTileFilter(django_filters.FilterSet):

    tile_type = EnumFilter(
        input_class=StoreTileEnums, method=filter_tile_type
    )
   
    class Meta:
        model = StoreTile
        fields = [
           "tile_type"
        ]

class StoreTileFilterInput(FilterInputObjectType):
    
    class Meta:
        filterset_class = StoreTileFilter


class StoreManagerCommentFilter(django_filters.FilterSet):
    
    stores = GlobalIDMultipleChoiceFilter(method=filter_stores, field_name="store")
   
    class Meta:
        model = StoreManagerComment
        fields = [
           "stores"
        ]
class StoreManagerCommentFilterInput(FilterInputObjectType):
    
    class Meta:
        filterset_class = StoreManagerCommentFilter


class StoreCategoryPageFilter(django_filters.FilterSet):

    brands = GlobalIDMultipleChoiceFilter(method=filter_brands, field_name="brand")
    categories = GlobalIDMultipleChoiceFilter(method=filter_categories, field_name="category")
    
    class Meta:
        model = StoreCategoryPage
        fields = [
            "brands",
            "categories"
        ]

class StoreCategoryPageFilterInput(FilterInputObjectType):
    
    class Meta:
        filterset_class = StoreCategoryPageFilter


class StoreFilter(django_filters.FilterSet):
    store_type = EnumFilter(input_class=StoreTypeEnums, method=filter_by_store_type)
    store_barter = django_filters.BooleanFilter(method=filter_by_store_barter)
    search = django_filters.CharFilter(method=filter_store_by_search)
    status = ListObjectTypeFilter(input_class=StoreStatusEnums, method = filter_store_status)
    manager_email = ListObjectTypeFilter(input_class =graphene.String, method=filter_store_manager)
    next_actions = ListObjectTypeFilter(input_class=StoreNextActionsEnums, method = filter_by_store_next_actions)
    class Meta:
        model = StoreInfo
        fields = [
            "store_type"
        ]

class StoreFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = StoreFilter

class BrandSourceRequestFilter(django_filters.FilterSet):
    stores = GlobalIDMultipleChoiceFilter(method=filter_brand_source_request_by_stores)
    brands = GlobalIDMultipleChoiceFilter(method=filter_brand_source_request_by_brands)
    state = EnumFilter(input_class=BrandSourceRequestEnums, method = filter_brand_source_request_by_state)
    store_bucket = EnumFilter(input_class=StoreStatusEnums, method = filter_brand_source_request_by_store_bucket)
    created_by = GlobalIDMultipleChoiceFilter(method=filter_brand_source_request_by_user)
    brand_collab = EnumFilter(input_class=BrandCollabEnums, method=filter_brand_source_request_by_brand_collab)
    search = django_filters.CharFilter(method=filter_brand_source_request_by_containing_mail)
    id = GlobalIDFilter(field_name="id")

    class Meta:
        model = BrandSourcingRequest
        fields = [
            "stores",
            "brands",
            "state",
            "store_bucket",
            "created_by",
            "brand_collab",
            "search"
        ]

class BrandSourceRequestFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandSourceRequestFilter

