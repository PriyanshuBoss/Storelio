import django_filters
from saleor.graphql.core.filters import EnumFilter
from saleor.graphql.core.types.filter_input import FilterInputObjectType
from saleor.notifications.enums import ApplicationTypeEnums, DeviceTypeEnums

from saleor.notifications.models import NotifyAppUpdate

def filter_device_type(qs, _, value):
    return qs.filter(device_type=value)

def filter_application_type(qs, _, value):
    return qs.filter(app_type=value)

class NotifyAppUpdateFilter(django_filters.FilterSet):
    device_type = EnumFilter(input_class=DeviceTypeEnums, method=filter_device_type)
    application_type = EnumFilter(input_class=ApplicationTypeEnums, method=filter_application_type)


    class Meta:
        model = NotifyAppUpdate
        fields = ["device_type", "application_type"]


class NotifyAppUpdateInput(FilterInputObjectType):
    class Meta:
        filterset_class = NotifyAppUpdateFilter
