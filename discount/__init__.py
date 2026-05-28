from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Set, Union

from django.conf import settings

if TYPE_CHECKING:
    # flake8: noqa
    from .models import Sale, Voucher


class DiscountValueType:
    FIXED = "fixed"
    PERCENTAGE = "percentage"

    CHOICES = [
        (FIXED, settings.DEFAULT_CURRENCY),
        (PERCENTAGE, "%"),
    ]

class DealType:

    BUY_M_GET_N_FREE = "Buy m products get n free"
    BUY_M_GET_X_PERC_OFF_N_PROD = "Buy m products get x percent off on n products"
    BUY_M_GET_X_PERC_OFF_BUY_N_GET_Y_PERC_OFF = "Buy m products get x percent off and n products get y percent off"
    BUY_PRODUCTS_AT_SAME_PRICE = "Buy products at same price"
    BUY_M_GET_Y_OFF = "Buy m products get y off"
    NORMAL = "Normal"
class VoucherType:
    SHIPPING = "shipping"
    ENTIRE_ORDER = "entire_order"
    SPECIFIC_PRODUCT = "specific_product"
    SPECIFIC_BRAND_PRODUCTS = "specific_brand_products"

    CHOICES = [
        (ENTIRE_ORDER, "Entire order"),
        (SHIPPING, "Shipping"),
        (SPECIFIC_PRODUCT, "Specific products, collections and categories"),
        (SPECIFIC_BRAND_PRODUCTS,"Specific brand products"),
    ]


@dataclass
class DiscountInfo:
    sale: Union["Sale", "Voucher"]
    product_ids: Union[List[int], Set[int]]
    category_ids: Union[List[int], Set[int]]
    collection_ids: Union[List[int], Set[int]]

class VoucherOwner:
    ZAAMO = "zaamo"
    BRAND = "brand"
    ZAAMO_BRAND="zaamo_brand"

    CHOICES = [
        (ZAAMO, "zaamo"),
        (BRAND, "brand"),
        (ZAAMO_BRAND,"zaamo_brand"),
        ]
