from saleor.graphql.core.enums import to_enum
from saleor.notifications.states import ApplicationType, DeviceType

DeviceTypeEnums = to_enum(DeviceType, type_name="DeviceType")
ApplicationTypeEnums = to_enum(ApplicationType, type_name="ApplicationTypeEnums")
