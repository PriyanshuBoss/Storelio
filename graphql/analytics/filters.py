import django_filters
from graphene_django.filter.filterset import GlobalIDMultipleChoiceFilter

from saleor.graphql.core.filters import ListObjectTypeFilter
from saleor.graphql.store.enums import StoreNextActionsEnums, StoreStatusEnums
from ..core.types import FilterInputObjectType
from saleor.product import models as product_models
from saleor.store import models as store_models
from saleor.store.store_utilities import get_all_collections, get_all_products
from saleor.graphql.product.filters import filter_collections
from ..utils import get_nodes



def filter_by_store(qs, _, stores):
    
    stores = get_nodes(stores, "Store", store_models.StoreInfo)

    return get_all_products(stores, qs=qs)


def filter_collections_by_stores(qs, _, stores):
    stores = get_nodes(stores, "Store", store_models.StoreInfo)
    
    return get_all_collections(stores, qs)

def filter_by_store_status(qs, _, status):

    if status:
        qs = qs.filter(actions__status__in=status)
    return qs

def filter_by_store_next_action(qs, _, next_actions):
    if next_actions:
        qs = qs.filter(actions__next_actions__in=next_actions)
    return qs

class ProductAnalyticsFilter(django_filters.FilterSet):
    
    stores = GlobalIDMultipleChoiceFilter(method=filter_by_store)
    collections = GlobalIDMultipleChoiceFilter(method=filter_collections)

    class Meta:
        model = product_models.Product
        fields = [
            "is_published",
        ]


class ProductAnalyticsFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = ProductAnalyticsFilter


class CollectionAnalyticsFilter(django_filters.FilterSet):
    
    stores = GlobalIDMultipleChoiceFilter(method=filter_collections_by_stores)

    class Meta:
        model = product_models.Collection
        fields = [
            "is_published",
        ]


class CollectionAnalyticsFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = CollectionAnalyticsFilter


class StoreAnalyticsFilter(django_filters.FilterSet):
    
    stores = GlobalIDMultipleChoiceFilter(field_name="id")

    store_status = ListObjectTypeFilter(
        input_class=StoreStatusEnums, method=filter_by_store_status
    )
    store_next_actions = ListObjectTypeFilter(
        input_class=StoreNextActionsEnums, method=filter_by_store_next_action
    )

    class Meta:
        model = store_models.StoreInfo
        fields = [
            "state",
        ]


class StoreAnalyticsFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = StoreAnalyticsFilter

