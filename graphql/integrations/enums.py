from saleor.graphql.core.enums import to_enum
from saleor.product import BarterType


BarterTypeEnum = to_enum(BarterType, type_name='BarterTypeEnum')
