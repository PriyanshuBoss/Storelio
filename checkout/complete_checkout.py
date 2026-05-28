from datetime import date
from decimal import Decimal
from typing import Iterable, List, Optional, Tuple
import logging
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.encoding import smart_text
from django.utils.translation import get_language
from prices import TaxedMoney
from saleor.order.utils import get_voucher_discount_for_orderline,update_revenue_in_orderline_meta
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from ..account.error_codes import AccountErrorCode
from ..account.models import User
from ..account.utils import store_user_address
from ..checkout import calculations
from ..checkout.error_codes import CheckoutErrorCode
from ..core.exceptions import InsufficientStock
from ..core.prices import quantize_price
from ..core.taxes import TaxError, zero_taxed_money
from ..core.utils.url import validate_storefront_url
from ..discount import DiscountInfo, VoucherOwner , DiscountValueType , VoucherType
from ..discount.models import NotApplicable
from ..discount.utils import (
    add_voucher_usage_by_customer,
    decrease_voucher_usage,
    increase_voucher_usage,
    remove_voucher_usage_by_customer,
)
from ..order.actions import order_created
from ..order.emails import send_brand_order_confirmation, send_customer_order_confirmation, send_zaamo_order_confirmation, send_order_confirmation_to_staff,send_order_confirmation_to_influencer_for_thirft
from ..order.messaging import send_sms_for_order_confirmation
from ..order.models import Order, OrderLine
from ..order.utils import order_placing_notification
from ..payment import PaymentError, gateway
from ..payment.models import Payment, Transaction
from ..payment.utils import store_customer_id
from ..plugins.manager import get_plugins_manager
from ..warehouse.availability import check_stock_quantity
from ..warehouse.management import allocate_stock
from . import AddressType, models
from .checkout_cleaner import clean_checkout_payment, clean_checkout_shipping
from .models import Checkout, CheckoutLine
from .utils import get_prepaid_amount, get_voucher_for_checkout, validate_checkout
from .base_calculations import calculate_shipping_from_dict, get_brand_cod_price_splitting
from saleor.external_services.whatsapp.tasks import order_placing_whatsapp_notification

logger = logging.getLogger(__name__)


def _get_voucher_data_for_order(checkout: Checkout) -> dict:
    """Fetch, process and return voucher/discount data from checkout.

    Careful! It should be called inside a transaction.

    :raises NotApplicable: When the voucher is not applicable in the current checkout.
    """
    voucher = get_voucher_for_checkout(checkout, with_lock=True,expiration_buffer=True)

    if checkout.voucher_code and not voucher:
        msg = "Voucher expired in meantime. Order placement aborted."
        logger.info(msg)
        raise NotApplicable(msg)

    if not voucher:
        return {}
    
    increase_voucher_usage(voucher)
    if voucher.apply_once_per_customer:
        add_voucher_usage_by_customer(voucher, checkout.get_customer_email())
    return {
        "voucher": voucher,
        "discount": checkout.discount,
        "discount_name": checkout.discount_name,
        "translated_discount_name": checkout.translated_discount_name,
    }


def _process_shipping_data_for_order(
    checkout: Checkout, shipping_price: TaxedMoney
) -> dict:
    """Fetch, process and return shipping data from checkout."""
    if not checkout.is_shipping_required():
        return {}

    shipping_address = checkout.shipping_address

    # if checkout.user:
    #     store_user_address(checkout.user, shipping_address, AddressType.SHIPPING)
        # if (
        #     shipping_address
        #     and checkout.user.addresses.filter(pk=shipping_address.pk).exists() 
        # ):
        #     shipping_address = shipping_address.get_copy()

    '''Above if statemnet was removed due to multiple address creation'''
    return {
        "shipping_address": shipping_address,
        "shipping_method": checkout.shipping_method,
        "shipping_method_name": smart_text(checkout.shipping_method),
        "shipping_price": shipping_price,
        "weight": checkout.get_total_weight(),
    }


def _process_user_data_for_order(checkout: Checkout):
    """Fetch, process and return shipping data from checkout."""
    billing_address = checkout.billing_address

    # if checkout.user:
    #     store_user_address(checkout.user, billing_address, AddressType.BILLING)
        # if (
        #     billing_address
        #     and checkout.user.addresses.filter(pk=billing_address.pk).exists()
        # ):
        #     billing_address = billing_address.get_copy()
        
    '''Above if statemnet was removed due to multiple address creation'''
    return {
        "user": checkout.user,
        "user_email": checkout.get_customer_email(),
        "billing_address": billing_address,
        "customer_note": checkout.note,
    }


def _validate_gift_cards(checkout: Checkout):
    """Check if all gift cards assigned to checkout are available."""
    if (
        not checkout.gift_cards.count()
        == checkout.gift_cards.active(date=date.today()).count()
    ):
        msg = "Gift card has expired. Order placement cancelled."
        raise NotApplicable(msg)


def _create_line_for_order(checkout_line: "CheckoutLine", discounts) -> OrderLine:
    """Create a line for the given order.

    :raises InsufficientStock: when there is not enough items in stock for this variant.
    """

    quantity = checkout_line.quantity
    variant = checkout_line.variant
    product = variant.product
    country = checkout_line.checkout.get_country()
    check_stock_quantity(variant, country, quantity)

    product_name = str(product)
    variant_name = str(variant)

    translated_product_name = str(product.translated)
    translated_variant_name = str(variant.translated)

    if translated_product_name == product_name:
        translated_product_name = ""

    if translated_variant_name == variant_name:
        translated_variant_name = ""

    manager = get_plugins_manager()
    total_line_price = manager.calculate_checkout_line_total(checkout_line, discounts)
    unit_price = quantize_price(
        total_line_price / checkout_line.quantity, total_line_price.currency
    )
    tax_rate = NumberUtilities.convert_string_to_decimal("0.0")
    # The condition will return False when unit_price.gross is 0.0
    if not isinstance(unit_price, Decimal) and unit_price.gross:
        tax_rate = unit_price.tax / unit_price.net

    line = OrderLine(
        product_name=product_name,
        variant_name=variant_name,
        translated_product_name=translated_product_name,
        translated_variant_name=translated_variant_name,
        product_sku=variant.sku,
        is_shipping_required=variant.is_shipping_required(),
        quantity=quantity,
        variant=variant,
        unit_price=unit_price,  # type: ignore
        tax_rate=tax_rate,
        brand_id=product.brand_id,
        cod = checkout_line.cod
    )
    
    line.metadata.update(
            {
                "cod_price": 0,
                "discount_amount": checkout_line.data.get('discount_amount', 0)
            }
        )
    return line


def _prepare_order_data(
    *, checkout: Checkout, lines: Iterable[CheckoutLine], discounts
) -> dict:
    """Run checks and return all the data from a given checkout to create an order.

    :raises NotApplicable InsufficientStock:
    """
    order_data = {}

    manager = get_plugins_manager()
    taxed_total = calculations.checkout_total(
        checkout=checkout, lines=lines, discounts=discounts
    )
    cards_total = checkout.get_total_gift_cards_balance()
    taxed_total.gross -= cards_total
    taxed_total.net -= cards_total

    taxed_total = max(taxed_total, zero_taxed_money(checkout.currency))

    shipping_total = manager.calculate_checkout_shipping(checkout, lines, discounts)
    order_data.update(_process_shipping_data_for_order(checkout, shipping_total))
    order_data.update(_process_user_data_for_order(checkout))
    order_data.update(
        {
            "language_code": get_language(),
            "tracking_client_id": checkout.tracking_code or "",
            "total": taxed_total,
            "platform_code": checkout.platform_code,
            "app_code":checkout.app_code,
        }
    )

    order_data["lines"] = [
        _create_line_for_order(checkout_line=line, discounts=discounts)
        for line in lines
    ]

    brand_cod_charge=get_brand_cod_price_splitting(lines)

    for line in order_data["lines"]:
        line.metadata['cod_price'] = brand_cod_charge[line.brand_id]

    # validate checkout gift cards
    _validate_gift_cards(checkout)

    # Get voucher data (last) as they require a transaction
    order_data.update(_get_voucher_data_for_order(checkout))

    # assign gift cards to the order

    order_data["total_price_left"] = (
        manager.calculate_checkout_subtotal(checkout, lines, discounts)
        + shipping_total
        - checkout.discount
    ).gross

    manager.preprocess_order_creation(checkout, discounts)
    return order_data

def get_orderline_commission_percentage(product, brand, streak_order=False):
    commission_percentage = 0

    if product.has_custom_commission:
        commission_percentage = product.commission_percentage
    else:
        commission = brand.commission.first()
        if commission:
            commission_percentage = commission.commission_percentage
    
    return commission_percentage

def set_influencer_commission_to_orderline_meta(line, voucher,brand, streak_order=None, platform_type=PlatformTypeEnum.INFLUENCER_STORE):

    value = line.unit_price.gross.amount * line.quantity
    
    thrift = brand and brand.brand_name == "thrift_brand"
    if voucher and voucher.owner == VoucherOwner.BRAND:
        commission=NumberUtilities.convert_string_to_decimal(0)
    elif voucher and voucher.owner == VoucherOwner.ZAAMO_BRAND:
        discount_amount = get_voucher_discount_for_orderline(line).amount
        zaamo_discount =  NumberUtilities.convert_string_to_decimal(voucher.metadata.get('Zaamo_discount',"0"))
        brand_discount = NumberUtilities.convert_string_to_decimal(voucher.metadata.get('Brand_discount',"0"))
        total_discount = zaamo_discount+brand_discount
        
        value = value - discount_amount*(brand_discount/total_discount)

        commission = value * NumberUtilities.convert_string_to_decimal(line.commission_percentage) /100
        
        if streak_order:
            commission = commission * NumberUtilities.convert_string_to_decimal(settings.STORE_STREAK_COMMISSION)
    
    elif voucher and voucher.name=="COTD":
        commission = value * NumberUtilities.convert_string_to_decimal(line.commission_percentage) * NumberUtilities.convert_string_to_decimal(settings.STORE_STREAK_COMMISSION) /100
    elif streak_order and not thrift:
        commission = value * NumberUtilities.convert_string_to_decimal(line.commission_percentage) * NumberUtilities.convert_string_to_decimal(settings.STORE_STREAK_COMMISSION) /100
    elif not streak_order and not thrift:
        commission = value * NumberUtilities.convert_string_to_decimal(line.commission_percentage) /100
    else :
        # this is case when thift is True 
        commission = (value * NumberUtilities.convert_string_to_decimal(line.commission_percentage) /100) + line.shipping_cost_amount
     
    if platform_type==PlatformTypeEnum.INFLUENCER_STORE:
        influencer_commission = {"influencer_commission": commission}
        zaamo_commission = {}
    else:
        # when platform_type is INFLUENCER_HOME

        influencer_commission = {"influencer_commission": NumberUtilities.convert_string_to_decimal(0)}
        zaamo_commission = {"zaamo_commission": commission}

    line.metadata.update(zaamo_commission)
    line.metadata.update(influencer_commission)


    return line

def get_cod_amount(orderline_instance,is_zaamo_shopify=None):
        order_inst = orderline_instance.order

        if orderline_instance.cod:

            if is_zaamo_shopify:
                cod_lines_same_brand = order_inst.lines.all().filter(cod=True,brand_id=orderline_instance.brand_id).count()
                cod_amount = orderline_instance.quantity * orderline_instance.variant.price_amount- NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('discount_amount')) + NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('cod_price'))/cod_lines_same_brand
                cod_amount = "{0:.3f}".format(cod_amount)

            else:    
                cod_lines_same_brand = order_inst.lines.all().filter(cod=True,brand_id=orderline_instance.brand_id).count()
                cod_amount = orderline_instance.quantity * orderline_instance.variant.price_amount + NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('cod_price'))/cod_lines_same_brand
                cod_amount = "{0:.3f}".format(cod_amount)
        else:
            cod_amount = '0'

        return cod_amount

def get_zaamo_commission_using_step_pricing(brand_commision,line,zaamo_commission_percentage_brand,extra_charge=Decimal('0.00')):
    zaamo_commission_percentage_brand = NumberUtilities.convert_string_to_decimal(zaamo_commission_percentage_brand/100)

    try:
        
        influencer_commission = NumberUtilities.convert_string_to_decimal(brand_commision.commission_percentage/100) if brand_commision.commission_percentage else NumberUtilities.convert_string_to_decimal("0.0")
        percent_without_influencer_commission = 1 - influencer_commission
        
        true_msp = NumberUtilities.convert_string_to_decimal(line.variant.metadata.get('true_msp')) * line.quantity 
        cur_MSP = NumberUtilities.convert_string_to_decimal(line.variant.price_amount) * line.quantity 
        
        if not true_msp:
            true_msp = cur_MSP

        zaamo_commission_percentage = percent_without_influencer_commission - (percent_without_influencer_commission-zaamo_commission_percentage_brand)*((true_msp+extra_charge)/(cur_MSP+extra_charge))
        return zaamo_commission_percentage
    
    except Exception as e:
        
        return zaamo_commission_percentage_brand

def set_brand_due_amount_to_orderline_meta(line, voucher,brand,is_zaamo_shopify=None):
    
    msp = line.unit_price_net_amount * line.quantity 
    true_msp = line.variant.metadata.get('true_msp') or line.variant.price_amount
    true_msp = NumberUtilities.convert_string_to_decimal(true_msp)

    brand_commision = line.brand.commission.first()
    if voucher and voucher.owner == VoucherOwner.BRAND:
        zaamo_commission_percentage_brand = NumberUtilities.convert_string_to_decimal("2.0")
    elif brand_commision:
        zaamo_commission_percentage_brand = NumberUtilities.convert_string_to_decimal(brand_commision.zaamo_commission)
    else:
        zaamo_commission_percentage_brand = NumberUtilities.convert_string_to_decimal("2.0")
    
    
    if StringUtilities.convert_object_to_string(line.metadata.get('zaamo_shipping')).lower() == 'true':
        msp_plus_shipping = msp
        zaamo_commission_percentage = get_zaamo_commission_using_step_pricing(brand_commision,line,zaamo_commission_percentage_brand)


    else:
        msp_plus_shipping = msp + line.shipping_cost_amount
        zaamo_commission_percentage = get_zaamo_commission_using_step_pricing(brand_commision,line,zaamo_commission_percentage_brand,extra_charge=line.shipping_cost_amount)

    if voucher and voucher.owner ==VoucherOwner.BRAND:
        platform_fees = (true_msp + line.shipping_cost_amount) * NumberUtilities.convert_string_to_decimal("2.0")/100
        brand_due_amount = -platform_fees

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

        extra_charge = msp_for_mixed_coupon_shipping - msp

        zaamo_commission_percentage = get_zaamo_commission_using_step_pricing(brand_commision,line,zaamo_commission_percentage_brand,extra_charge)

        platform_fees = msp_for_mixed_coupon_shipping * zaamo_commission_percentage
        
        if is_zaamo_shopify and line.cod:
            msp_for_mixed_coupon_shipping = 0
            cod_price = NumberUtilities.convert_string_to_decimal(get_cod_amount(line,is_zaamo_shopify))
            extra_charge = cod_price - msp
            zaamo_commission_percentage = get_zaamo_commission_using_step_pricing(brand_commision,line,zaamo_commission_percentage_brand,extra_charge)

            platform_fees =  cod_price * NumberUtilities.convert_string_to_decimal(zaamo_commission_percentage)


        brand_due_amount = msp_for_mixed_coupon_shipping - (msp_for_mixed_coupon * NumberUtilities.convert_string_to_decimal(line.commission_percentage)/100) - platform_fees
    else:
        platform_fees = msp_plus_shipping * zaamo_commission_percentage

        if line.cod:
            msp_plus_shipping = 0
            cod_price = NumberUtilities.convert_string_to_decimal(get_cod_amount(line,is_zaamo_shopify))
            extra_charge = cod_price - msp
            zaamo_commission_percentage = get_zaamo_commission_using_step_pricing(brand_commision,line,zaamo_commission_percentage_brand,extra_charge)

            platform_fees =  cod_price * NumberUtilities.convert_string_to_decimal(zaamo_commission_percentage)

        brand_due_amount = msp_plus_shipping - (msp * NumberUtilities.convert_string_to_decimal(line.commission_percentage)/100) - platform_fees
    
    platform_percentage = NumberUtilities.convert_string_to_decimal("2.0") if voucher and voucher.owner ==VoucherOwner.BRAND else zaamo_commission_percentage*100
    brand_due = {
        "brand_due_amount": "{0:.3f}".format(brand_due_amount),
        "platform_fees": "{0:.3f}".format(platform_fees),
        "platform_percentage" : "{0:.2f}".format(platform_percentage),
        "commission_given_by_brand" : "{0:.2f}".format(zaamo_commission_percentage_brand)
    }
    
    if line.cod:
        brand_due['payment_due_for_customer'] = get_cod_amount(line,is_zaamo_shopify)
    
    brand_due['true_msp']= true_msp

    if is_zaamo_shopify:
        brand_due['shopify']=True

    line.metadata.update(brand_due)
    return line

def set_orderline_discount_amount_to_orderline_meta(line):
    discount_amount = get_voucher_discount_for_orderline(line)
    discount_dict = {"discount_amount": "{0:.3f}".format(discount_amount.amount), "voucher_code": ""}

    voucher = line.order.voucher

    if voucher:
        discount_dict["voucher_code"] = voucher.code
    
    if voucher and voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:

        zaamo_discount = NumberUtilities.convert_string_to_decimal(voucher.metadata.get('Zaamo_discount',"0"))
        brand_discount = NumberUtilities.convert_string_to_decimal(voucher.metadata.get('Brand_discount',"0")) 
            
        total_discount = zaamo_discount + brand_discount
        zaamo_discount_money = discount_amount*(zaamo_discount/total_discount)
        brand_discount_money = discount_amount*(brand_discount/total_discount)
        discount_dict["zaamo_discount_amount"] = "{0:.3f}".format(zaamo_discount_money.amount)
        discount_dict["brand_discount_amount"] = "{0:.3f}".format(brand_discount_money.amount)

    line.metadata.update(discount_dict)
    return line

def set_shipped_by_to_orderline_meta(line,brand):

    zaamo_shipping = brand.metadata.get('zaamo_shipping')
    if zaamo_shipping:
        zaamo_shipping = StringUtilities.convert_object_to_string(zaamo_shipping).lower()
        shipped_dict = {"zaamo_shipping":zaamo_shipping}
        line.metadata.update(shipped_dict)
    
    return line

@transaction.atomic
def _create_order(*, checkout: Checkout, order_data: dict, user: User) -> Order:
    """Create an order from the checkout.

    Each order will get a private copy of both the billing and the shipping
    address (if shipping).

    If any of the addresses is new and the user is logged in the address
    will also get saved to that user's address book.

    Current user's language is saved in the order so we can later determine
    which language to use when sending email.
    """
    from ..order.utils import add_gift_card_to_order

    order = Order.objects.filter(checkout_token=checkout.token).first()

    checkout_lines = checkout.lines.all()
    is_zaamo_shopify = checkout.metadata.get('shopify')
    logger.info("Order fetch with token_id :: %s", checkout.token)
    logger.info("Checkout lines info with variant_ids ::%s", [data.variant_id for data in checkout_lines ])

    if order is not None:
        logger.info("Order created previously with order id :: %s", order.id)
        return order
        

    total_price_left = order_data.pop("total_price_left")
    order_lines = order_data.pop("lines")
    streak_order = order_data.pop("streak_order")
    prepaid_amount = get_prepaid_amount(checkout)
    order_data['metadata'] = {"prepaid_amount": prepaid_amount}
    order = Order.objects.create(**order_data, checkout_token=checkout.token)
    
    _,brand_shipping_dict,brand_quantity = calculate_shipping_from_dict(checkout, checkout_lines)
    logger.info("Order Created from create_order with order id :: %s and order_date ::%s",order.id, order_data)
    logger.info("Order lines popped ::%s", order_lines)
    
    for line in order_lines:
        line.order_id = order.pk
        
        if line.variant:
            product = line.variant.product
            line.brand = product.brand
            brand_id = line.brand_id
            if brand_shipping_dict.get(brand_id) and brand_quantity.get(brand_id):
                brand_shipping_amount = brand_shipping_dict[brand_id].amount
                shipping_cost = (brand_shipping_amount/brand_quantity[brand_id])*line.quantity
                line.shipping_cost_amount = shipping_cost

            line.commission_percentage = get_orderline_commission_percentage(product, line.brand, streak_order=streak_order)
            too_many_orders = product.brand.too_many_orders
            line.metadata["too_many_orders"] = too_many_orders
            
    order_lines = OrderLine.objects.bulk_create(order_lines)

    for line in order_lines:
        brand = line.brand
        line = set_shipped_by_to_orderline_meta(line,brand)
        line = set_influencer_commission_to_orderline_meta(line, order.voucher,brand,streak_order=streak_order, platform_type=order.platform_code)
        line = set_brand_due_amount_to_orderline_meta(line, order.voucher,brand,is_zaamo_shopify)
        line = set_orderline_discount_amount_to_orderline_meta(line)
        line = update_revenue_in_orderline_meta(line)
        line.save()
    
    logger.info("Order lines bulk created ::%s", order_lines)
    # allocate stocks from the lines
    thrift_product_ordered = False
    for line in order_lines:  # type: OrderLine
        variant = line.variant
        if line.brand.brand_name == "thrift_brand":
            thrift_product_ordered = True
        
        if variant and variant.track_inventory:
            logger.info("Order lines stock allocation for  ::%s", line.id)
            allocate_stock(line, checkout.get_country(), line.quantity)

    # Add gift cards to the order
    for gift_card in checkout.gift_cards.select_for_update():
        total_price_left = add_gift_card_to_order(order, gift_card, total_price_left)

    # assign checkout payments to the order
    x = checkout.payments.update(order=order)
    logger.info("assign checkout payments to the order::%s with update status ::%s", order.id, x)

    # copy metadata from the checkout into the new order
    order.metadata.update(checkout.metadata)
    order.private_metadata = checkout.private_metadata
    order.save()

    transaction.on_commit(lambda: order_created(order=order, user=user))
    
    for brand in brand_shipping_dict:
        brand_shipping_dict[brand] = NumberUtilities.convert_string_to_number(brand_shipping_dict[brand].amount)
    # Send the order confirmation email
    brand_cod_charges = get_brand_cod_price_splitting(checkout_lines)

    cod_amount_sum = sum(brand_cod_charges.values())

    
    transaction.on_commit(
        lambda: send_zaamo_order_confirmation.delay(order.pk,brand_shipping_dict,cod_amount_sum,prepaid_amount)
    )

    transaction.on_commit(
        lambda: send_brand_order_confirmation.delay(order.pk,brand_shipping_dict,brand_cod_charges)
    )
    
    transaction.on_commit(
        lambda:order_placing_whatsapp_notification.delay(order.pk)
    )

    if is_zaamo_shopify:
        
        logger.info("Order returned successfully for order id::%s", order.id)
        return order

    
    transaction.on_commit(
        lambda: send_customer_order_confirmation.delay(order.pk,brand_shipping_dict,cod_amount_sum,prepaid_amount)
    )

    # transaction.on_commit(
    #     lambda: send_order_confirmation_to_staff.delay(order.pk,brand_shipping_dict)
    # )

    # transaction.on_commit(
    #     lambda: send_sms_for_order_confirmation.delay(order.pk)
    # )

    if thrift_product_ordered:
        transaction.on_commit(
            lambda: send_order_confirmation_to_influencer_for_thirft.delay(order.pk,brand_shipping_dict)
        )

    transaction.on_commit(
        lambda:order_placing_notification(order)
    )
    
    logger.info("Order returned successfully for order id::%s", order.id)
    return order


def _prepare_checkout(
    checkout: models.Checkout, discounts, tracking_code, redirect_url, payment
):
    """Prepare checkout object to complete the checkout process."""

    validate_checkout(checkout)

    lines = list(checkout)

    clean_checkout_shipping(checkout, lines, discounts, CheckoutErrorCode)
    clean_checkout_payment(
        checkout, lines, discounts, CheckoutErrorCode, last_payment=payment
    )

    if redirect_url:
        try:
            validate_storefront_url(redirect_url)
        except ValidationError as error:
            raise ValidationError(
                {"redirect_url": error}, code=AccountErrorCode.INVALID.value
            )

    to_update = []
    if redirect_url and redirect_url != checkout.redirect_url:
        checkout.redirect_url = redirect_url
        to_update.append("redirect_url")

    if tracking_code and tracking_code != checkout.tracking_code:
        checkout.tracking_code = tracking_code
        to_update.append("tracking_code")

    if to_update:
        to_update.append("last_change")
        checkout.save(update_fields=to_update)


def release_voucher_usage(order_data: dict):
    voucher = order_data.get("voucher")
    if voucher:
        decrease_voucher_usage(voucher)
        if "user_email" in order_data:
            remove_voucher_usage_by_customer(voucher, order_data["user_email"])


def _get_order_data(checkout: models.Checkout, discounts: List[DiscountInfo]) -> dict:
    """Prepare data that will be converted to order and its lines."""
    try:
        order_data = _prepare_order_data(
            checkout=checkout, lines=list(checkout), discounts=discounts,
        )
    except InsufficientStock as e:
        raise ValidationError(f"Insufficient product stock: {e.item}", code=e.code)
    except NotApplicable:
        log_string = "Voucher not applicable at " + StringUtilities.convert_number_to_string(TimeUtilities.get_current_date_time())
        
        raise ValidationError(
            log_string,
            code=CheckoutErrorCode.VOUCHER_NOT_APPLICABLE.value,
        )
    except TaxError as tax_error:
        raise ValidationError(
            "Unable to calculate taxes - %s" % str(tax_error),
            code=CheckoutErrorCode.TAX_ERROR.value,
        )
    return order_data


def _process_payment(
    payment: Payment,
    store_source: bool,
    payment_data: Optional[dict],
    order_data: dict,
) -> Transaction:
    """Process the payment assigned to checkout."""
    try:
        if payment.to_confirm:
            txn = gateway.confirm(payment, additional_data=payment_data)
        else:
            txn = gateway.process_payment(
                payment=payment,
                token=payment.token,
                store_source=store_source,
                additional_data=payment_data,
            )
        payment.refresh_from_db()
        if not txn.is_success:
            raise PaymentError(txn.error)
    except PaymentError as e:
        release_voucher_usage(order_data)
        raise ValidationError(str(e), code=CheckoutErrorCode.PAYMENT_ERROR.value)
    return txn


def complete_checkout(
    checkout: models.Checkout,
    payment_data,
    store_source,
    discounts,
    user,
    tracking_code=None,
    redirect_url=None,
    streak_order=False,
) -> Tuple[Optional[Order], bool, dict]:
    """Logic required to finalize the checkout and convert it to order.

    Should be used with transaction_with_commit_on_errors, as there is a possibility
    for thread race.
    :raises ValidationError
    """
    payment = checkout.get_last_active_payment()
    logger.info("payment fetched to complete checkout ::%s, for checkout :: %s", payment, checkout.token)
    _prepare_checkout(
        checkout=checkout,
        discounts=discounts,
        tracking_code=tracking_code,
        redirect_url=redirect_url,
        payment=payment,
    )

    try:
        order_data = _get_order_data(checkout, discounts)
        logger.info("Order data fetched in complete checkout ::%s", order_data)
    
    except ValidationError as error:
        gateway.payment_refund_or_void(payment)
        logger.exception("Exception raised in complete checkout")
        logger.exception(error)
        raise error
    
    is_zaamo_shopify = checkout.metadata.get('shopify')
    
    if not is_zaamo_shopify:
        
        txn = _process_payment(
            payment=payment,  # type: ignore
            store_source=store_source,
            payment_data=payment_data,
            order_data=order_data,
        )
        logger.info("Transaction processed with txn :: %s", txn)

        if txn.customer_id and user.is_authenticated:
            store_customer_id(user, payment.gateway, txn.customer_id)  # type: ignore

        action_required = txn.action_required
        action_data = txn.action_required_data if action_required else {}
        
    action_required = None
    action_data = {}
    order = None
    order_data["streak_order"] = streak_order
    if not action_required:
        try:
            order = _create_order(
                checkout=checkout, order_data=order_data, user=user,  # type: ignore
            )
            # remove checkout after order is successfully created
            logger.info("Order creation successfull with order_id: %s", order.id)
            checkout.delete()
        except InsufficientStock as e:
            release_voucher_usage(order_data)
            gateway.payment_refund_or_void(payment)
            logger.exception(
            "order not created because of Insufficient product stock for checkout token as:: %s  and order_data as :: %s and for user_id :: %s", 
            checkout.token, order_data, user.id)

            raise ValidationError(f"Insufficient product stock: {e.item}", code=e.code)
    
    user_id = "None"
    if user:
        user_id= user.id

    if order:
        logger.info(
            "order created for user-id: %s with order id: %s and order data as:: %s", user_id, order.id, order_data)
    
    return order, action_required, action_data
