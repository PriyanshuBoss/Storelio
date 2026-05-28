from django.core.exceptions import ValidationError
from saleor.checkout.complete_checkout import get_cod_amount
from saleor.discount import VoucherOwner
from saleor.order import FulfillmentStatus
from saleor.order.utils import get_voucher_discount_for_orderline

from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities

from ...core.exceptions import InsufficientStock
from ...order.error_codes import OrderErrorCode
from ...warehouse.availability import check_stock_quantity


def validate_total_quantity(order):
    if order.get_total_quantity() == 0:
        raise ValidationError(
            {
                "lines": ValidationError(
                    "Could not create order without any products.",
                    code=OrderErrorCode.REQUIRED,
                )
            }
        )


def validate_shipping_method(order):
    method = order.shipping_method
    shipping_address = order.shipping_address
    shipping_not_valid = (
        method
        and shipping_address
        and shipping_address.country.code not in method.shipping_zone.countries
    )  # noqa
    if shipping_not_valid:
        raise ValidationError(
            {
                "shipping": ValidationError(
                    "Shipping method is not valid for chosen shipping address",
                    code=OrderErrorCode.SHIPPING_METHOD_NOT_APPLICABLE,
                )
            }
        )


def validate_order_lines(order, country):
    for line in order:
        if line.variant is None:
            raise ValidationError(
                {
                    "lines": ValidationError(
                        "Could not create orders with non-existing products.",
                        code=OrderErrorCode.NOT_FOUND,
                    )
                }
            )
        if line.variant.track_inventory:
            try:
                check_stock_quantity(line.variant, country, line.quantity)
            except InsufficientStock as exc:
                raise ValidationError(
                    {
                        "lines": ValidationError(
                            f"Insufficient product stock: {exc.item}",
                            code=OrderErrorCode.INSUFFICIENT_STOCK,
                        )
                    }
                )


def validate_product_is_published(order):
    for line in order:
        if not line.variant.product.is_published:
            raise ValidationError(
                {
                    "lines": ValidationError(
                        "Can't finalize draft with unpublished product.",
                        code=OrderErrorCode.PRODUCT_NOT_PUBLISHED,
                    )
                }
            )


def validate_product_is_available_for_purchase(order):
    for line in order:
        if not line.variant.product.is_available_for_purchase():
            raise ValidationError(
                {
                    "lines": ValidationError(
                        "Can't finalize draft with product unavailable for purchase.",
                        code=OrderErrorCode.PRODUCT_UNAVAILABLE_FOR_PURCHASE,
                    )
                }
            )


def validate_draft_order(order, country):
    """Check if the given order contains the proper data.

    - Has proper customer data,
    - Shipping address and method are set up,
    - Product variants for order lines still exists in database.
    - Product variants are availale in requested quantity.
    - Product variants are published.

    Returns a list of errors if any were found.
    """
    if order.is_shipping_required():
        validate_shipping_method(order)
    validate_total_quantity(order)
    validate_order_lines(order, country)
    validate_product_is_published(order)
    validate_product_is_available_for_purchase(order)


def get_true_msp(orderline_instance):

    if orderline_instance.metadata.get('true_msp'):

        unit_msp = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('true_msp'))
        return unit_msp * orderline_instance.quantity

    else:
        return orderline_instance.unit_price_net_amount * orderline_instance.quantity

def get_final_price_paid(orderline_instance):

    line_price_undiscounted = orderline_instance.unit_price_net_amount * orderline_instance.quantity
    line_price_undiscounted+=orderline_instance.shipping_cost_amount
    
    if not orderline_instance.metadata.get('discount_amount'):
        line_discount_amount = get_voucher_discount_for_orderline(orderline_instance).amount
    else:
        line_discount_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('discount_amount'))

    return "{0:.3f}".format(line_price_undiscounted - line_discount_amount)

def set_brand_due_amount_to_orderline_meta_for_cancellation(line, voucher):
    
    # msp = line.unit_price_net_amount * line.quantity 
    true_msp = line.variant.metadata.get('true_msp') or line.variant.price_amount
    true_msp = NumberUtilities.convert_string_to_decimal(true_msp)
    zaamo_commission_percentage = NumberUtilities.convert_string_to_decimal("2.0")/100
    msp = true_msp
    
    if StringUtilities.convert_object_to_string(line.metadata.get('zaamo_shipping')).lower() == 'true':
        msp_plus_shipping = msp
    else:
        msp_plus_shipping = msp + line.shipping_cost_amount

    if voucher and voucher.owner ==VoucherOwner.BRAND:
        platform_fees = (true_msp + line.shipping_cost_amount) * NumberUtilities.convert_string_to_decimal("2.0")/100

    elif voucher and voucher.owner == VoucherOwner.ZAAMO_BRAND:
        discount_amount = get_voucher_discount_for_orderline(line).amount
        zaamo_discount =  NumberUtilities.convert_string_to_decimal(voucher.metadata.get('Zaamo_discount',"0"))
        brand_discount = NumberUtilities.convert_string_to_decimal(voucher.metadata.get('Brand_discount',"0"))
        total_discount = zaamo_discount+brand_discount

        msp_for_mixed_coupon = msp - discount_amount*(brand_discount/total_discount)

        if StringUtilities.convert_object_to_string(line.metadata.get('zaamo_shipping')).lower() == 'true':
            msp_for_mixed_coupon_shipping = msp_for_mixed_coupon
        else:
            msp_for_mixed_coupon_shipping = msp_for_mixed_coupon + line.shipping_cost_amount

        platform_fees = msp_for_mixed_coupon_shipping * zaamo_commission_percentage

    else:
        platform_fees = msp_plus_shipping * zaamo_commission_percentage

        if line.cod:
            msp_plus_shipping = 0
            cod_price = NumberUtilities.convert_string_to_decimal(get_cod_amount(line))
            platform_fees =  cod_price * NumberUtilities.convert_string_to_decimal(zaamo_commission_percentage)
    
    platform_percentage = NumberUtilities.convert_string_to_decimal("2.0")
    brand_due_amount = -platform_fees
    brand_due = {
        "brand_due_amount": "{0:.3f}".format(brand_due_amount),
        "platform_fees": "{0:.3f}".format(platform_fees),
        "platform_percentage" : "{0:.2f}".format(platform_percentage) 
    }
    
    line.metadata.update(brand_due)
    return line