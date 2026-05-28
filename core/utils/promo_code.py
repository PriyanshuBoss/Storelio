import uuid
from saleor.store.models import StoreInfo
from django.core.exceptions import ValidationError
from saleor.discount import VoucherType
from ...discount.models import Voucher
from ...giftcard.error_codes import GiftCardErrorCode
from ...giftcard.models import GiftCard


class InvalidPromoCode(ValidationError):
    def __init__(self, message=None, **kwargs):
        if message is None:
            message = {
                "promo_code": ValidationError(
                    "Promo code is invalid", code=GiftCardErrorCode.INVALID
                )
            }
        super().__init__(message, **kwargs)


class PromoCodeAlreadyExists(ValidationError):
    def __init__(self, message=None, **kwargs):
        code = kwargs.get("code", GiftCardErrorCode.ALREADY_EXISTS)
        if message is None:
            message = {
                "promo_code": ValidationError("Promo code already exists.", code=code)
            }
        super().__init__(message, **kwargs)


def generate_promo_code():
    """Generate a promo unique code that can be used as a voucher or gift card code."""

    code = str(uuid.uuid4()).replace("-", "").upper()[:12]
    while not is_available_promo_code(code):
        code = str(uuid.uuid4()).replace("-", "").upper()[:12]
    return code


def is_available_promo_code(code):
    return not (promo_code_is_gift_card(code) or promo_code_is_voucher(code))


def promo_code_is_voucher(code):
    return Voucher.objects.filter(code=code).exists()


def promo_code_is_gift_card(code):
    return GiftCard.objects.filter(code=code).exists()


def promo_code_is_voucher_of_store(code, store_id):

    if not store_id or not code:
        return False

    code = code.upper()

    voucher = Voucher.objects.filter(code = code).first()

    if voucher and voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:
        default_store = StoreInfo.objects.filter(store_name = 'Zaamo_Default').first()
        store_id = default_store.id

    voucher_filter = Voucher.objects.filter(code=code, store_id=store_id)

    if not voucher_filter:
        voucher_filter = Voucher.objects.filter(name=code, store_id=store_id)

    if voucher_filter:
        return voucher_filter[0].code
