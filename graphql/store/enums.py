from saleor.graphql.core.enums import to_enum
from saleor.store.states import (StoreAppEnum, StoreTileEnum, StoreTypeEnum, StoreStatus, StoreNextActions, StoreBrandSourcingRequestEnum, BrandCollabEnum)
from saleor.utilities.request_utilities import PlatformTypeEnum

StoreTypeEnums = to_enum(StoreTypeEnum, type_name="StoreTypeEnum")
StoreTileEnums = to_enum(StoreTileEnum, type_name="StoreTileEnum")
StoreAppEnums = to_enum(StoreAppEnum, type_name="StoreAppEnum")
PlatformTypeEnums = to_enum(PlatformTypeEnum,type_name="PlatformTypeEnum")
StoreStatusEnums = to_enum(StoreStatus,type_name="StoreStatusEnum")
StoreNextActionsEnums = to_enum(StoreNextActions,type_name="StoreNextActionsEnum")
BrandSourceRequestEnums = to_enum(StoreBrandSourcingRequestEnum, type_name="BrandSourceRequestEnum")
BrandCollabEnums = to_enum(BrandCollabEnum, type_name="BrandCollabEnum")
