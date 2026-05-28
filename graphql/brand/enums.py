
import graphene
from saleor.brand.states import BrandMobileTypes, BrandSourceEnum, PreferedPaymentModeEnum, BrandStatusEnum, BrandEmailStateEnum, BrandImportanceEnum
from saleor.graphql.core.enums import to_enum


PreferedPaymentModeEnums = to_enum(PreferedPaymentModeEnum, type_name="PreferedPaymentModeEnum")
BrandSourceEnums = to_enum(BrandSourceEnum, type_name='BrandSourceEnum')
BrandStatusEnums = to_enum(BrandStatusEnum, type_name='BrandStatusEnum')
BrandEmailStateEnums = to_enum(BrandEmailStateEnum, type_name='BrandEmailStateEnum')
BrandMobileTypeEnums = to_enum(BrandMobileTypes, type_name='BrandMobileTypeEnum')
BrandImportanceEnums = to_enum(BrandImportanceEnum, type_name='BrandImportanceEnum')

class BrandActive(graphene.Enum):
    ACTIVE = 'true'
    INACTIVE = 'false'

