import django_filters
from graphene.types import field
from graphene_django.filter import GlobalIDMultipleChoiceFilter
from saleor.graphql.utils import get_nodes
from ..core.types import FilterInputObjectType
from saleor.graphql.product.filters import filter_fields_containing_value
from saleor.support.models import SupportQueries
from saleor.store.models import StoreInfo

class SupportQueryFilter(django_filters.FilterSet):
    ids = GlobalIDMultipleChoiceFilter(field_name="id")
    email =  django_filters.CharFilter(field_name='email', lookup_expr='iexact')
    store = GlobalIDMultipleChoiceFilter(method="filter_stores", field_name="store")
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("email")
    )

    class Meta:
        model = SupportQueries
        fields = ["email", "search", "store"]

    def filter_stores(self, qs, _, value): 
        if value:
            store = get_nodes(value, "Store", StoreInfo)
            qs = qs.filter(store__in=store)
            
        return qs


class SupportQueryFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = SupportQueryFilter
