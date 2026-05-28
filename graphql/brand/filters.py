import django_filters
import graphene
from django.db.models import Q
from graphene_django.filter import GlobalIDFilter, GlobalIDMultipleChoiceFilter
from saleor.graphql.brand.enums import BrandActive, BrandStatusEnums, BrandImportanceEnums
from saleor.graphql.utils import resolve_global_ids_to_primary_keys
from saleor.graphql.core.filters import EnumFilter, ListObjectTypeFilter
from ..core.types import FilterInputObjectType
from saleor.graphql.product.filters import filter_fields_containing_value
from saleor.brand.models import Brand,BrandGrouping, BrandCollection
from saleor.store.models import StoreInfo
from django.db.models import Count

def filter_brand_active(qs, _, value):

    if value == BrandActive.ACTIVE:
        qs = qs.filter(status=BrandStatusEnums.ACTIVE.value)
    
    elif value == BrandActive.INACTIVE:
        qs = qs.filter(status=BrandStatusEnums.INACTIVE.value)
    
    return qs

def filter_brand_status(qs, _, value):


    if value:
        qs = qs.filter(status__in=value)
    
    return qs

def filter_brand_by_commission(qs, _, value):
    
    if value:
        qs=qs.filter(commission__commission_percentage=value)

    return qs

def filter_brand_by_brand_barter(qs,_,value):

    return qs.filter(brand_barter = value)
  
def filter_brand_by_too_many_orders(qs,_,value):

    return qs.filter(too_many_orders = value)

def filter_brand_by_duplicate_brand(qs,_,value):

    if value:
        qs = qs.filter(Q(metadata__duplicate_brand = True))
    else:
        qs = qs.filter(Q(metadata__duplicate_brand = False) | Q(metadata__duplicate_brand__isnull = True))

    return qs

def filter_brand_collection_by_product_count(qs,_, value):
    
    if value:
        qs = qs.annotate(product_count=Count("product")).filter(product_count__gte=value)

    return qs

def filter_by_category_ids(qs,_,value):

    if value:
        _,category_ids = resolve_global_ids_to_primary_keys(value)
        qs = qs.filter(products__category__in = category_ids).distinct()
        
    return qs

def filter_brand_importance(qs, _, value):

    if value:
        qs = qs.filter(importance__in=value)
    
    return qs   

def filter_brand_tag_by_name(qs,_, value):
    
    if value:
        qs = qs.filter(name=value)

    return qs

def filter_brand_collection(qs, _, value):
    
    if value:
        brand = graphene.Node.from_global_id(value)[1]
        qs = qs.filter(brand=brand)

    return qs


def filter_brands_collection(qs, _, value):
    if value:
        brands = resolve_global_ids_to_primary_keys(value, graphene_type="Brand")[1]
        qs = qs.filter(brand_id__in=brands)
    return qs

def filter_brand_collection_products(qs, _, value):
    
    
    if value:
        brand_collection_id = graphene.Node.from_global_id(value)[1]
        return qs.filter(id=brand_collection_id)
    return qs

def filter_brand_collection_active(qs, _, value):
    
    return qs.filter(active=value)

def filter_brand_groups_by_customize(qs,_,value):

    return qs.filter(customize = value)

class BrandFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("brand_name", "company_name", "private_metadata__source_name","brand_contact_name")
    )
    ids = GlobalIDMultipleChoiceFilter(field_name="id")
    is_active = EnumFilter(
        input_class=BrandActive, method=filter_brand_active
    )

    status =  ListObjectTypeFilter(
        input_class=BrandStatusEnums, method=filter_brand_status
    )
    brand_barter = django_filters.BooleanFilter(method = filter_brand_by_brand_barter)
    too_many_orders = django_filters.BooleanFilter(method = filter_brand_by_too_many_orders)
    commission = django_filters.CharFilter(
        method=filter_brand_by_commission
    )
    duplicate_brand = django_filters.BooleanFilter(method = filter_brand_by_duplicate_brand)
    slug = django_filters.CharFilter(field_name='slug', lookup_expr='iexact')
    category_ids = GlobalIDMultipleChoiceFilter(method=filter_by_category_ids)
    importance = ListObjectTypeFilter(input_class=BrandImportanceEnums, method=filter_brand_importance)
    
    class Meta:
        model = Brand
        fields = ["search", "is_active","brand_barter","too_many_orders", "status"]


class BrandFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandFilter

class BrandGroupingFilter(django_filters.FilterSet):
    id = GlobalIDFilter(field_name="id")
    customize = django_filters.BooleanFilter(method =filter_brand_groups_by_customize)
    class Meta:
        model = BrandGrouping
        fields = []

class BrandCollectionFilter(django_filters.FilterSet):
    brand = GlobalIDFilter(method=filter_brand_collection)
    brands = GlobalIDMultipleChoiceFilter(method=filter_brands_collection, field_name="brand")
    min_product_count = django_filters.CharFilter(
        method=filter_brand_collection_by_product_count
    )
    is_active = django_filters.BooleanFilter(method = filter_brand_collection_active)
    brand_collection_products = GlobalIDFilter(method=filter_brand_collection_products)
   
    class Meta:
        model = BrandCollection
        fields = []

class BrandTagFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        method=filter_brand_tag_by_name
    )
    
    class Meta:
        model = BrandCollection
        fields = []

class BrandGroupingFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandGroupingFilter

class BrandCollectionFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandCollectionFilter


class BrandTagFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandTagFilter

class BrandBarterStoreFilter(django_filters.FilterSet):
    ids = GlobalIDMultipleChoiceFilter(field_name="id")

    class Meta:
        model = StoreInfo
        fields = []

class BrandBarterStoreFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandBarterStoreFilter
