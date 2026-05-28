import graphene

from ...discount import DiscountValueType, VoucherType, VoucherOwner,DealType


class DiscountValueTypeEnum(graphene.Enum):
    FIXED = DiscountValueType.FIXED
    PERCENTAGE = DiscountValueType.PERCENTAGE


class VoucherTypeEnum(graphene.Enum):
    SHIPPING = VoucherType.SHIPPING
    ENTIRE_ORDER = VoucherType.ENTIRE_ORDER
    SPECIFIC_BRAND_PRODUCTS = VoucherType.SPECIFIC_BRAND_PRODUCTS
    SPECIFIC_PRODUCT = VoucherType.SPECIFIC_PRODUCT


class DiscountStatusEnum(graphene.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SCHEDULED = "scheduled"


class VoucherDiscountType(graphene.Enum):
    FIXED = "fixed"
    PERCENTAGE = "percentage"
    SHIPPING = "shipping"

class VoucherOwnerEnum(graphene.Enum):
    ZAAMO = VoucherOwner.ZAAMO
    BRAND = VoucherOwner.BRAND
    ZAAMO_BRAND = VoucherOwner.ZAAMO_BRAND

class DealTypeEnum(graphene.Enum):
    BUY_M_GET_N_FREE = DealType.BUY_M_GET_N_FREE
    BUY_M_GET_X_PERC_OFF_N_PROD = DealType.BUY_M_GET_X_PERC_OFF_N_PROD
    BUY_M_GET_X_PERC_OFF_BUY_N_GET_Y_PERC_OFF = DealType.BUY_M_GET_X_PERC_OFF_BUY_N_GET_Y_PERC_OFF
    BUY_PRODUCTS_AT_SAME_PRICE = DealType.BUY_PRODUCTS_AT_SAME_PRICE
    BUY_M_GET_Y_OFF = DealType.BUY_M_GET_Y_OFF
    NORMAL = DealType.NORMAL