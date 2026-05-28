"""Checkout-related utility functions."""
from decimal import Decimal
import math
from typing import Iterable, List, Optional, Tuple
from django.db.models import Q
import logging
from django.core.exceptions import ValidationError
from django.db.models import Max, Min, Sum, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from prices import Money, MoneyRange, TaxedMoneyRange
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.number_utilities import NumberUtilities
from django.conf import settings
from ..account.models import User
from ..checkout import calculations
from ..checkout.error_codes import CheckoutErrorCode
from ..core.exceptions import ProductNotPublished
from saleor.external_services.mail.mail_impl import MailImpl
from ..core.prices import quantize_price
from ..core.taxes import zero_taxed_money ,zero_money
from ..core.utils.promo_code import (
    InvalidPromoCode,
    promo_code_is_gift_card,
    promo_code_is_voucher,
    promo_code_is_voucher_of_store,
)
from ..discount import DiscountInfo, VoucherOwner, VoucherType,DealType
from ..discount.models import NotApplicable, Voucher, VoucherLogs
from ..discount.utils import (
    get_discounted_lines,
    get_discounted_lines_for_specific_brand_products,
    get_products_voucher_discount,
    validate_voucher_for_checkout,
)
from ..giftcard.utils import (
    add_gift_card_code_to_checkout,
    remove_gift_card_code_from_checkout,
)
from ..plugins.manager import get_plugins_manager
from ..shipping.models import ShippingMethod
from ..warehouse.availability import check_stock_quantity
from . import AddressType
from .models import Checkout, CheckoutLine
from saleor.order.models import Order
from .base_calculations import base_checkout_cod_charge, calculate_brand_shopped_cost, calculate_shipping_from_dict,get_brand_cod_price_splitting
from saleor.notifications.utils import send_notification_to_device
from saleor.settings import IS_BETA

logger = logging.getLogger(__name__)

def get_user_checkout(
    user: User,store = None, checkout_queryset=Checkout.objects.all(), auto_create=False
) -> Tuple[Optional[Checkout], bool]:
    """Return an active checkout for given user or None if no auto create.

    If auto create is enabled, it will retrieve an active checkout or create it
    (safer for concurrency).
    """
    if auto_create:
        return checkout_queryset.get_or_create(
            user=user,
            defaults={
                "shipping_address": user.default_shipping_address,
                "billing_address": user.default_billing_address,
            },
        )
    
    if store:
        return checkout_queryset.filter(user=user,checkoutstore__store = store).first(), False
    else:
        return checkout_queryset.filter(user=user).first(), False


def update_checkout_quantity(checkout):
    """Update the total quantity in checkout."""
    total_lines = checkout.lines.aggregate(total_quantity=Sum("quantity"))[
        "total_quantity"
    ]
    if not total_lines:
        total_lines = 0
    checkout.quantity = total_lines
    checkout.save(update_fields=["quantity"])

def get_prepaid_amount(checkout):
    taxed_total = calculations.checkout_total(
                    checkout=checkout, lines=checkout.lines.all(), discounts=[]
                    )
    cod_lines = checkout.lines.all().filter(cod=True)

    discount_on_cod_lines = sum([line.data.get('discount_amount', 0) for line in cod_lines])

    cod_prices = sum([line.quantity * line.variant.price_amount for line in cod_lines])
    
    cod_shipping_price,_,_ = calculate_shipping_from_dict(checkout,cod_lines)
    cod_charges = base_checkout_cod_charge(checkout,cod_lines)

    prepaid_amount = taxed_total.gross.amount-(Decimal(cod_prices)+Decimal(cod_shipping_price)+cod_charges.net.amount-Decimal(discount_on_cod_lines))    
    
    if prepaid_amount<0:
        prepaid_amount=Decimal('0.0')
    prepaid_amount = math.ceil(NumberUtilities.convert_string_to_float(prepaid_amount))
    return prepaid_amount

def check_variant_in_stock(
    checkout, variant, quantity=1, replace=False, check_quantity=True
) -> Tuple[int, Optional[CheckoutLine]]:
    """Check if a given variant is in stock and return the new quantity + line."""
    line = checkout.lines.filter(variant=variant).first()
    line_quantity = 0 if line is None else line.quantity

    new_quantity = quantity if replace else (quantity + line_quantity)

    if new_quantity < 0:
        raise ValueError(
            "%r is not a valid quantity (results in %r)" % (quantity, new_quantity)
        )

    if new_quantity > 0 and check_quantity:
        check_stock_quantity(variant, checkout.get_country(), new_quantity)

    return new_quantity, line


def add_variant_to_checkout(
    checkout, variant, cod=False, quantity=1, replace=False, check_quantity=True
):
    """Add a product variant to checkout.

    If `replace` is truthy then any previous quantity is discarded instead
    of added to.
    """
    if not variant.product.is_published:
        raise ProductNotPublished()

    new_quantity, line = check_variant_in_stock(
        checkout,
        variant,
        quantity=quantity,
        replace=replace,
        check_quantity=check_quantity,
    )

    

    if line is None:
        line = checkout.lines.filter(variant=variant).first()
   
    if new_quantity == 0:
        if line is not None:
            line.delete()
    elif line is None:
        checkout.lines.create(checkout=checkout, variant=variant, quantity=new_quantity, cod=cod)
    elif new_quantity > 0 and line:
        line.quantity = new_quantity
        line.cod=cod
        line.save(update_fields=["quantity", "cod"])

    update_checkout_quantity(checkout)


def _check_new_checkout_address(checkout, address, address_type):
    """Check if and address in checkout has changed and if to remove old one."""
    if address_type == AddressType.BILLING:
        old_address = checkout.billing_address
    else:
        old_address = checkout.shipping_address

    has_address_changed = any(
        [
            not address and old_address,
            address and not old_address,
            address and old_address and address != old_address,
        ]
    )

    remove_old_address = (
        has_address_changed
        and old_address is not None
        and (not checkout.user or old_address not in checkout.user.addresses.all())
    )

    return has_address_changed, remove_old_address


def change_billing_address_in_checkout(checkout, address):
    """Save billing address in checkout if changed.

    Remove previously saved address if not connected to any user.
    """
    changed, remove = _check_new_checkout_address(
        checkout, address, AddressType.BILLING
    )
    if changed:
        # if remove:
        #     checkout.billing_address.delete()
        checkout.billing_address = address
        checkout.save(update_fields=["billing_address", "last_change"])


def change_shipping_address_in_checkout(checkout, address):
    """Save shipping address in checkout if changed.

    Remove previously saved address if not connected to any user.
    """
    changed, remove = _check_new_checkout_address(
        checkout, address, AddressType.SHIPPING
    )
    if changed:
        # if remove:
        #     checkout.shipping_address.delete()
        checkout.shipping_address = address
        checkout.save(update_fields=["shipping_address", "last_change"])


def _get_shipping_voucher_discount_for_checkout(
    voucher, checkout, lines, discounts: Optional[Iterable[DiscountInfo]] = None
):
    """Calculate discount value for a voucher of shipping type."""
    if not checkout.is_shipping_required():
        msg = "Your order does not require shipping."
        raise NotApplicable(msg)
    shipping_method = checkout.shipping_method
    if not shipping_method:
        msg = "Please select a shipping method first."
        raise NotApplicable(msg)

    # check if voucher is limited to specified countries
    shipping_country = checkout.shipping_address.country
    if voucher.countries and shipping_country.code not in voucher.countries:
        msg = "This offer is not valid in your country."
        raise NotApplicable(msg)

    shipping_price = calculations.checkout_shipping_price(
        checkout=checkout, lines=lines, discounts=discounts
    ).gross
    return voucher.get_discount_amount_for(shipping_price)


def _get_products_voucher_discount(
    lines, voucher, discounts: Optional[Iterable[DiscountInfo]] = None,brand_shipping_dict = None,brand_quantity = None,checkout=None
):
    """Calculate products discount value for a voucher, depending on its type."""
    prices = None
    if voucher.type == VoucherType.SPECIFIC_PRODUCT or voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:
        prices = get_prices_of_discounted_specific_product(lines,voucher, discounts,brand_shipping_dict,brand_quantity,checkout)
    if not prices:
        msg = "This offer is only valid for selected items."
        raise NotApplicable(msg)
  
    return get_products_voucher_discount(voucher, prices)

def get_checkoutline_prices_of_discounted_specific_brand_product(
    lines: Iterable[CheckoutLine], voucher: Voucher,
) -> List[Money]:
    """Get prices of variants belonging to the discounted specific products.

    Specific brand prodicts are products and categories of a Brand .
    Product must be assigned directly to the discounted category, assigning
    product to child category won't work.
    """
    line_prices = []
    discounted_lines = get_discounted_lines_for_specific_brand_products(lines, voucher)

    for line in discounted_lines:
        
        line_prices.extend([line.variant.price] * line.quantity)

    return line_prices


def get_voucher_discount_for_checkoutline(checkoutline: CheckoutLine, voucher) -> Money:
    checkout = checkoutline.checkout
    variant = checkoutline.variant
    manager = get_plugins_manager()
    total_line_price = manager.calculate_checkout_line_total(checkoutline, [])

    
    if not voucher:
        return zero_money()

    if voucher.type == VoucherType.ENTIRE_ORDER:
        all_checkoutline_sum = checkoutline.checkout.lines.all().annotate(line_total=ExpressionWrapper(
            F('variant__price_amount') * F('quantity'), 
            output_field= DecimalField())).aggregate(Sum("line_total")).get('line_total__sum')

        discount_value = ((variant.price_amount * checkoutline.quantity)/all_checkoutline_sum) * checkout.discount_amount

        return Money(discount_value, checkout.currency)
    
    if voucher.type == VoucherType.SPECIFIC_PRODUCT:

        discounted_lines = get_discounted_lines(checkout.lines.all(), voucher)
        
        prices = get_prices_of_discounted_specific_product(checkout.lines.all(), 
        voucher)

        if not prices or checkoutline not in discounted_lines:
            return zero_money(checkout.currency)
        else:
            
            price_sum = sum([price.amount for price in prices])
            if voucher.max_discount and price_sum > voucher.max_discount.amount:
                
                discount_value = ((variant.price_amount * checkoutline.quantity)/price_sum) * checkout.discount_amount
                
                return Money(discount_value, checkout.currency)

            return get_products_voucher_discount(voucher, [variant.price] * checkoutline.quantity) 
    
    if voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:

        discounted_lines = get_discounted_lines_for_specific_brand_products(checkout.lines.all(), voucher)

        prices = get_checkoutline_prices_of_discounted_specific_brand_product(checkout.lines.all(), voucher)

        if not prices or checkoutline not in discounted_lines:
            return zero_money(checkout.currency)
        else:
            price_sum = sum([price.amount for price in prices])
            
            if voucher.max_discount and price_sum > voucher.max_discount.amount:
                discount_value = ((variant.price_amount *  checkoutline.quantity)/price_sum) * checkout.discount_amount
                return Money(discount_value, checkout.currency)

            return get_products_voucher_discount(voucher, [variant.price] * checkoutline.quantity) 
    


def get_prices_of_discounted_specific_product(
    lines: List[CheckoutLine],
    voucher: Voucher,
    discounts: Optional[Iterable[DiscountInfo]] = None,
    brand_shipping_dict = None,
    brand_quantity = None,
    checkout:Checkout=None,
) -> List[Money]:
    """Get prices of variants belonging to the discounted specific products.

    Specific products are products, collections and categories.
    Product must be assigned directly to the discounted category, assigning
    product to child category won't work.
    """
    line_prices = []
    if  voucher.type == VoucherType.SPECIFIC_PRODUCT:
        discounted_lines = get_discounted_lines(lines,voucher)
        if len(discounted_lines)==0:
            msg = "This offer is only valid for selected items."
            raise NotApplicable(msg)
        
        if voucher.metadata.get('max_products_allowed'):
            limit = NumberUtilities.convert_string_to_number(voucher.metadata.get('max_products_allowed'))
            total_quantity = sum(discounted_line.quantity for discounted_line in discounted_lines) 
            if total_quantity > limit:
                msg = "This offer is valid only for {} products quantity".format(limit)
                raise NotApplicable(msg)

    elif voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:
        discounted_lines = get_discounted_lines_for_specific_brand_products(lines,voucher)
        if len(discounted_lines)==0:
            msg = "This coupon is not applicable on this brand"
            raise NotApplicable(msg)
        
        if voucher.discount_rule.get('deal_type') and voucher.min_checkout_items_quantity:
            total_quantity = sum(discounted_line.quantity for discounted_line in discounted_lines)
            min_quantity = voucher.min_checkout_items_quantity
            if total_quantity<min_quantity:
                msg = "This offer is valid only when {} specific products are added".format(min_quantity)
                raise NotApplicable(msg)

    
    if checkout and voucher:
        validate_voucher_for_checkout(voucher, checkout, discounted_lines, discounts)
    
    if voucher.metadata.get('only_free_cod'):
        brand_cod_charge = get_brand_cod_price_splitting(discounted_lines)
        brand_cod_charge_list = brand_cod_charge.values()
        for brand_cod_charge in brand_cod_charge_list:
            brand_cod_price = Money(brand_cod_charge,'INR')
            line_prices.extend([brand_cod_price])
        
        return line_prices

    for line in discounted_lines:
        variant = line.variant
        product = variant.product
        brand_id = product.brand_id
        shipping_cost = 0

        if brand_shipping_dict and brand_quantity:
            if  brand_shipping_dict.get(brand_id) and brand_quantity.get(brand_id):
                brand_shipping_amount = brand_shipping_dict[brand_id].amount
                shipping_cost = (brand_shipping_amount/brand_quantity[brand_id])
        
        line_unit_price = zero_money('INR')

        if not (voucher.metadata.get('only_free_shipping')):

            line_total = calculations.checkout_line_total(
                line=line, discounts=discounts or []
            ).gross
            line_unit_price = quantize_price(
                (line_total / line.quantity), line_total.currency
            )

        shipping_price = Money(shipping_cost,'INR')
        line_unit_price += shipping_price
        line_prices.extend([line_unit_price] * line.quantity)

    return line_prices

def remove_thrift_products_for_discount(lines: Iterable[CheckoutLine])->Money:

    total_thrift_purchase = Money(0,'INR')
    for line in lines:
        try:
            brand = line.variant.product.brand  
        except Exception as e:
            continue

        if brand.brand_name == "thrift_brand":
            total_thrift_purchase+=(line.variant.get_price()*line.quantity)
    
    return total_thrift_purchase
        
def get_voucher_discount_for_checkout(
    voucher: Voucher,
    checkout: Checkout,
    lines: Iterable[CheckoutLine],
    discounts: Optional[Iterable[DiscountInfo]] = None,
    platform_code = None
) -> Money:
    """Calculate discount value depending on voucher and discount types.

    Raise NotApplicable if voucher of given type cannot be applied.
    """
    validate_voucher_for_checkout(voucher, checkout, lines, discounts)
    if voucher.type == VoucherType.ENTIRE_ORDER:

        shipping_cost = calculations.checkout_shipping_price(checkout=checkout,lines=lines,discounts = discounts).gross
        cod_charge = calculations.checkout_cod_charge(checkout=checkout,lines=lines,discounts = discounts).gross

        if voucher.metadata.get('only_free_shipping') == True:
            return voucher.get_discount_amount_for(shipping_cost)
        
        if voucher.metadata.get('only_free_cod') == True:
            return voucher.get_discount_amount_for(cod_charge)

        subtotal = calculations.checkout_subtotal(
            checkout=checkout, lines=lines, discounts=discounts
        ).gross
        
        total_thrift_purchase = remove_thrift_products_for_discount(lines=lines)
        subtotal = subtotal - total_thrift_purchase

        if voucher.is_shipping and platform_code==PlatformTypeEnum.INFLUENCER_HOME:
            subtotal+=shipping_cost
        
        subtotal+=cod_charge
        
        return voucher.get_discount_amount_for(subtotal)

    if voucher.type == VoucherType.SHIPPING:
        return _get_shipping_voucher_discount_for_checkout(
            voucher, checkout, lines, discounts
        )
    if voucher.type == VoucherType.SPECIFIC_PRODUCT or voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:

        shipping_cost = Money(0,'INR')
        brand_shipping_dict = {}
        brand_quantity = {}
        if (voucher.is_shipping and platform_code==PlatformTypeEnum.INFLUENCER_HOME) or voucher.metadata.get('only_free_shipping') == True:
            _,brand_shipping_dict,brand_quantity = calculate_shipping_from_dict(checkout,lines)

        discount = _get_products_voucher_discount(lines, voucher, discounts,brand_shipping_dict,brand_quantity,checkout)

        # this is compared with max_discount to make max_discount_on_order <= voucher.max_discount in case of VoucherType.SPECIFIC_PRODUCT also.
        if voucher.max_discount and discount > voucher.max_discount:
            return voucher.max_discount
        return discount
    
    raise NotImplementedError("Unknown discount type")


def get_voucher_for_checkout(
    checkout: Checkout, vouchers=None, with_lock: bool = False , expiration_buffer:bool = False
) -> Optional[Voucher]:
    """Return voucher with voucher code saved in checkout if active or None."""
    if checkout.voucher_code is not None:
        voucher = Voucher.objects.none()
        
        if vouchers is None:
            final_time = timezone.now()
            voucher = Voucher.objects.filter(code=checkout.voucher_code)

            if expiration_buffer and voucher:
                final_time = TimeUtilities.subtract_time_from_timestamp(timezone.now(),minutes=20)
                voucher_instance = voucher[0]

                if voucher_instance.start_date > final_time:
                    final_time= timezone.now()

           
        
        try:
            logger.info(final_time)
            vouchers = voucher.active(date=final_time)
            logger.info(vouchers)
            
            qs = vouchers
            voucher = qs.get(code=checkout.voucher_code)
            current_time = StringUtilities.convert_number_to_string(TimeUtilities.get_current_date_time())
            
            if with_lock:
                info_log = f'voucher instance before lock at {current_time} for voucher code {voucher.code}'
                logger.info(info_log)
            
            if voucher and with_lock and voucher.usage_limit is not None:
                voucher = vouchers.select_for_update().get(code=checkout.voucher_code)
            
            current_time = StringUtilities.convert_number_to_string(TimeUtilities.get_current_date_time())
            
            if with_lock:
                info_log = f'voucher instance returned after lock at {current_time} for voucher code {voucher.code}'
                logger.info(info_log)
            
            return voucher
        
        except Voucher.DoesNotExist as e:
            logger.info(e)
            return None
    
    logger.info(f"checkout voucher code is none for checkout :: {checkout.token}")
    
    return None


def recalculate_checkout_discount(
    checkout: Checkout, lines: Iterable[CheckoutLine], discounts: Iterable[DiscountInfo]
):
    """Recalculate `checkout.discount` based on the voucher.

    Will clear both voucher and discount if the discount is no longer
    applicable.
    """
    voucher = get_voucher_for_checkout(checkout)
    if voucher is not None:
        try:
            discount = get_voucher_discount_for_checkout(
                voucher, checkout, lines, discounts
            )
        except NotApplicable:
            remove_voucher_from_checkout(checkout)
        else:
            subtotal = calculations.checkout_subtotal(
                checkout=checkout, lines=lines, discounts=discounts
            ).gross
            checkout.discount = (
                min(discount, subtotal)
                if voucher.type != VoucherType.SHIPPING
                else discount
            )
            checkout.discount_name = str(voucher)
            checkout.translated_discount_name = (
                voucher.translated.name
                if voucher.translated.name != voucher.name
                else ""
            )
            checkout.save(
                update_fields=[
                    "translated_discount_name",
                    "discount_amount",
                    "discount_name",
                    "currency",
                ]
            )
            
    else:
        remove_voucher_from_checkout(checkout)

    
def botd_min_bag_value(checkout: Checkout,lines: Iterable[CheckoutLine],voucher: Voucher):
    if not voucher:
        raise InvalidPromoCode()
    if "BOTD" in voucher.code:
        brand_amount = {}
        for line in lines:
            variant = line.variant
            product = variant.product
            brand_id = product.brand_id
            if brand_id in brand_amount:
                brand_amount[brand_id] += (variant.price_amount*line.quantity)
            else:
                brand_amount[brand_id] = (variant.price_amount*line.quantity)

        botd_brand = voucher.brands.first()
        botd_brand_id = botd_brand.id
        if brand_amount.get(botd_brand_id):
            if brand_amount[botd_brand_id] <  NumberUtilities.convert_string_to_float(settings.BOTD_MIN_SPENT):
                raise InvalidPromoCode(message="Promo code is invalid. The minimum checkout value should be greater than 2000")
        else:
            raise NotApplicable(msg = "Only for Selected Brands")

def add_promo_code_to_checkout(
    checkout: Checkout,
    lines: Iterable[CheckoutLine],
    promo_code: str,
    discounts: Optional[Iterable[DiscountInfo]] = None,
    store_id=None,
    platform_code=None,
    app_code = None
):
    """Add gift card or voucher data to checkout.

    Raise InvalidPromoCode if promo code does not match to any voucher or gift card.
    """
    valid_promo_code = promo_code_is_voucher_of_store(promo_code, store_id)

    is_zaamo_shopify = checkout.metadata.get('shopify')

    if valid_promo_code:
        
        voucher = Voucher.objects.filter(code = valid_promo_code).first()

        if not is_zaamo_shopify and voucher and any([line.cod for line in lines]) and (not voucher.metadata.get('only_free_cod')) and voucher.owner in [VoucherOwner.ZAAMO, VoucherOwner.BRAND, VoucherOwner.ZAAMO_BRAND]:
            message = "This promocode is not applicable with COD"
            raise InvalidPromoCode(message=message)

        add_voucher_code_to_checkout(checkout, lines, valid_promo_code, discounts, platform_code, store_id,app_code)

    elif promo_code_is_gift_card(promo_code):
        add_gift_card_code_to_checkout(checkout, valid_promo_code)

    else:
        
        # VoucherLogs.objects.create( user=checkout.user, 
        #                             voucher_code=promo_code, 
        #                             store_id=store_id, 
        #                             log_msg="Voucher is not applicable on this store"
        #                             )
    
        raise InvalidPromoCode(message="Voucher is not applicable on this store")

def voucher_error_msg(voucher):

    if voucher:
        if voucher.usage_limit and voucher.used >= voucher.usage_limit:
            message = "Promo code is invalid, as it has exceded the usage limit"
        elif voucher.end_date and timezone.now()> voucher.end_date:
            message = "Promo code is invalid, as it has been expired on {}".format(voucher.end_date)
        elif voucher.start_date and voucher.start_date > timezone.now():
            message = "Promo code is invalid, as it will be active on {}".format(voucher.start_date)
    else:
        message = "Promo code is invalid, as it doesn't exists"
    return message

def check_app_and_platform_of_voucher(voucher,app_code,platform_code):
    if voucher and  voucher.metadata.get('app_code') == PlatformTypeEnum.ZAAMO_STORE and app_code != PlatformTypeEnum.ZAAMO_STORE:
            raise InvalidPromoCode(message="Applicable on only Zaamo app")
    if voucher and voucher.metadata.get('app_code') == "IS_WEB" and not (platform_code == PlatformTypeEnum.INFLUENCER_STORE and app_code == ""):
            raise InvalidPromoCode(message="Applicable only on web")

def add_voucher_code_to_checkout(
    checkout: Checkout,
    lines: Iterable[CheckoutLine],
    voucher_code: str,
    discounts: Optional[Iterable[DiscountInfo]] = None,
    platform_code=None,
    store_id=None,
    app_code=None,
):
    """Add voucher data to checkout by code.

    Raise InvalidPromoCode() if voucher of given type cannot be applied.
    """
    try:
        voucher = Voucher.objects.active(date=timezone.now()).get(code=voucher_code)
    except Voucher.DoesNotExist:
        voucher = Voucher.objects.filter(code=voucher_code).first()
        
        message = voucher_error_msg(voucher)

        # VoucherLogs.objects.create( user=checkout.user, 
        #                             voucher_code=voucher_code, 
        #                             store_id=store_id, 
        #                             log_msg=message
        #                             )
        raise InvalidPromoCode(message=message)

    try:
        if ("COTD" in voucher_code) or ("BOTD" in voucher_code) or ("DISGRPB30" in voucher_code) or ("DISGRPB_30" in voucher_code):
            validate_voucher_code_for_user_for_n_days_use(checkout, voucher, store_id, platform_code, 1000)
        
        if voucher_code.startswith('SZ') and platform_code == PlatformTypeEnum.INFLUENCER_STORE:
            raise InvalidPromoCode(message="Only Applicable on Influencer home")

        check_app_and_platform_of_voucher(voucher,app_code,platform_code)
        botd_min_bag_value(checkout,lines,voucher)
        add_voucher_to_checkout(checkout, lines, voucher, discounts,platform_code)
    except Exception as e:
        # VoucherLogs.objects.create( user=checkout.user, 
        #                             voucher_code=voucher_code, 
        #                             store_id=store_id, 
        #                             log_msg=e
        #                             )
        raise ValidationError(
            {
                "promo_code": ValidationError(
                    e,
                    code=CheckoutErrorCode.VOUCHER_NOT_APPLICABLE.value,
                )
            }
        )


def validate_voucher_code_for_user_for_n_days_use(checkout, voucher, store_id, platform_code, n):
    
    order_with_this_voucher_in_last_n_days = checkout.user.orders.filter(
                    Q(voucher__code__icontains='COTD')|Q(voucher__code__icontains='BOTD')|Q(voucher__code__icontains='DISGRPB30'),
                    platform_code=PlatformTypeEnum.INFLUENCER_STORE,
                    created__gt=TimeUtilities.subtract_time_from_timestamp(
                                    TimeUtilities.get_current_date_time(), days=n)
                    )

    if platform_code == PlatformTypeEnum.INFLUENCER_STORE and order_with_this_voucher_in_last_n_days.exists():
        last_order_date_with_voucher = order_with_this_voucher_in_last_n_days.first().created

        voucher_applicable_after = TimeUtilities.parse_date(
                                        TimeUtilities.add_time_in_timestamp(last_order_date_with_voucher, days=n)
                                        , "%d-%m-%Y")

        # VoucherLogs.objects.create( user=checkout.user, 
        #                             voucher_code=voucher.code, 
        #                             store_id=store_id, 
        #                             log_msg="You have recently used a COTD or BOTD coupon at a Zaamo influencer store. Checkout Deals section for exclusive discounts curated by the influencer."
        #                             )
        raise ValidationError(
                    "You have recently used a COTD or BOTD coupon at a Zaamo influencer store. Checkout Deals section for exclusive discounts curated by the influencer.",
                    code=CheckoutErrorCode.VOUCHER_NOT_APPLICABLE.value,
                )


def validate_checkout(checkout):
    lines = list(checkout)

    if not lines or not (checkout.shipping_address and checkout.billing_address) :
        
        MailImpl.send_mail_without_template("order_failure", 'order creation failed for checkout_token :: {} because checkoutlines were empty or no shipping_address or billing_address'.format(checkout.token),'Order creation FAILED', ['vaibhav+test@zaamo.co'])
            
        raise ValidationError(
                {"checkout_complete": "No Lines available in checkout while creating order or no shipping_address or billing_address "}, code=CheckoutErrorCode.CHECKOUT_LINES_EMPTY.value
            )

            
    return True

def add_voucher_to_checkout(
    checkout: Checkout,
    lines: Iterable[CheckoutLine],
    voucher: Voucher,
    discounts: Optional[Iterable[DiscountInfo]] = None,
    platform_code = None
    
):
    """Add voucher data to checkout.

    Raise NotApplicable if voucher of given type cannot be applied.
    """
    discount = get_voucher_discount_for_checkout(voucher, checkout, lines, discounts,platform_code)
    checkout.voucher_code = voucher.code
    checkout.discount_name = voucher.name
    checkout.translated_discount_name = (
        voucher.translated.name if voucher.translated.name != voucher.name else ""
    )
    checkout.discount = discount
    checkout.save(
        update_fields=[
            "voucher_code",
            "discount_name",
            "translated_discount_name",
            "discount_amount",
        ]
    )


def remove_promo_code_from_checkout(checkout: Checkout, promo_code: str, store_id=None):
    """Remove gift card or voucher data from checkout."""

    promo_code = promo_code_is_voucher_of_store(promo_code, store_id)
   
    if promo_code:
        remove_voucher_code_from_checkout(checkout, promo_code)
    elif promo_code_is_gift_card(promo_code):
        remove_gift_card_code_from_checkout(checkout, promo_code)


def remove_voucher_code_from_checkout(checkout: Checkout, voucher_code: str):
    """Remove voucher data from checkout by code."""
    existing_voucher = get_voucher_for_checkout(checkout)
    if existing_voucher and existing_voucher.code == voucher_code:
        remove_voucher_from_checkout(checkout)
    elif checkout.voucher_code == voucher_code:
        remove_voucher_from_checkout(checkout)


def remove_voucher_from_checkout(checkout: Checkout):
    """Remove voucher data from checkout."""
    checkout.voucher_code = None
    checkout.discount_name = None
    checkout.translated_discount_name = None
    checkout.discount_amount = 0
    checkout.save(
        update_fields=[
            "voucher_code",
            "discount_name",
            "translated_discount_name",
            "discount_amount",
            "currency",
        ]
    )


def get_valid_shipping_methods_for_checkout(
    checkout: Checkout,
    lines: Iterable[CheckoutLine],
    discounts: Iterable[DiscountInfo],
    country_code: Optional[str] = None,
):
    manager = get_plugins_manager()
    return ShippingMethod.objects.applicable_shipping_methods_for_instance(
        checkout,
        price=manager.calculate_checkout_subtotal(checkout, lines, discounts).gross,
        country_code=country_code,
    )


def is_valid_shipping_method(
    checkout: Checkout, lines: Iterable[CheckoutLine], discounts: Iterable[DiscountInfo]
):
    """Check if shipping method is valid and remove (if not)."""
    if not checkout.shipping_method:
        return False

    valid_methods = get_valid_shipping_methods_for_checkout(checkout, lines, discounts)
    if valid_methods is None or checkout.shipping_method not in valid_methods:
        clear_shipping_method(checkout)
        return False
    return True


def get_shipping_price_estimate(
    checkout: Checkout,
    lines: Iterable[CheckoutLine],
    discounts: Iterable[DiscountInfo],
    country_code: str,
) -> Optional[TaxedMoneyRange]:
    """Return the estimated price range for shipping for given order."""

    shipping_methods = get_valid_shipping_methods_for_checkout(
        checkout, lines, discounts, country_code=country_code
    )

    if shipping_methods is None:
        return None

    # TODO: extension manager should be able to have impact on shipping price estimates
    min_price_amount, max_price_amount = shipping_methods.aggregate(
        price_amount_min=Min("price_amount"), price_amount_max=Max("price_amount")
    ).values()

    if min_price_amount is None:
        return None

    manager = get_plugins_manager()
    prices = MoneyRange(
        start=Money(min_price_amount, checkout.currency),
        stop=Money(max_price_amount, checkout.currency),
    )
    return manager.apply_taxes_to_shipping_price_range(prices, country_code)


def clear_shipping_method(checkout: Checkout):
    checkout.shipping_method = None
    checkout.save(update_fields=["shipping_method", "last_change"])


def is_fully_paid(
    checkout: Checkout, lines: Iterable[CheckoutLine], discounts: Iterable[DiscountInfo]
):
    """Check if provided payment methods cover the checkout's total amount.

    Note that these payments may not be captured or charged at all.
    """
    payments = [payment for payment in checkout.payments.all() if payment.is_active]
    total_paid = sum([p.total for p in payments])
    # checkout_total = (
    #     calculations.checkout_total(checkout=checkout, lines=lines, discounts=discounts)
    #     - checkout.get_total_gift_cards_balance()
    # )
    # checkout_total = max(
    #     checkout_total, zero_taxed_money(checkout_total.currency)
    # ).gross
    prepaid_amount = get_prepaid_amount(checkout)
    return total_paid >= prepaid_amount


def clean_checkout(
    checkout: Checkout, lines: Iterable[CheckoutLine], discounts: Iterable[DiscountInfo]
):
    """Check if checkout can be completed."""
    if checkout.is_shipping_required():
        if not checkout.shipping_method:
            raise ValidationError(
                "Shipping method is not set",
                code=CheckoutErrorCode.SHIPPING_METHOD_NOT_SET.value,
            )
        if not checkout.shipping_address:
            raise ValidationError(
                "Shipping address is not set",
                code=CheckoutErrorCode.SHIPPING_ADDRESS_NOT_SET.value,
            )
        if not is_valid_shipping_method(checkout, lines, discounts):
            raise ValidationError(
                "Shipping method is not valid for your shipping address",
                code=CheckoutErrorCode.INVALID_SHIPPING_METHOD.value,
            )

    if not checkout.billing_address:
        raise ValidationError(
            "Billing address is not set",
            code=CheckoutErrorCode.BILLING_ADDRESS_NOT_SET.value,
        )

    if not is_fully_paid(checkout, lines, discounts):
        raise ValidationError(
            "Provided payment methods can not cover the checkout's total amount",
            code=CheckoutErrorCode.CHECKOUT_NOT_FULLY_PAID.value,
        )


def cancel_active_payments(checkout: Checkout):
    checkout.payments.filter(is_active=True).update(is_active=False)

def notification_abandoned_cart_logged_in():

    if IS_BETA:
        return

    last_24_hr = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),1)
    checkouts = Checkout.objects.filter(last_change__gte = last_24_hr,mobile_device_id__isnull=False,quantity__gte=1)\
        .order_by('mobile_device_id','-last_change')\
        .distinct('mobile_device_id')\
        .select_related('user').prefetch_related('lines__variant__product')
    devices = checkouts.values_list('mobile_device_id',flat=True)  
    
    for checkout in checkouts:
        
        if not checkout.mobile_device_id:
            continue
        
        user = checkout.user
        
        if not user:
            continue
        
        user_id = user.id
        
        try:
            media_url = checkout.lines.first().variant.product.get_product_url()
            product_name = checkout.lines.first().variant.product.name
            # include check for product unpublished, brand inactive
        except:
            media_url=""
            product_name = "this fit"
        
        context_variables = dict()
        context_variables[user_id] = {
            "media":media_url,
            "product_name":product_name
        }
        
        send_notification_to_device([user],devices,context_variables=context_variables,event_code="EV_abandoned_cart")

    
def notification_abandoned_cart_guest_user():

    # for abandoned cart, checkout has user null
    #  for notification function user_id is required, if for all checkout 203, 1881 can be mapped to a checkout, then notification will work
    # this function is only for checkouts where user is null and only those devices where 203 or 1881 user is mapped
    # this covers most cases, one case remaining that they created checkout from web and then logged in to app and did not open bag page
    from saleor.notifications.models import Device
    
    if IS_BETA:
        return

    last_24_hr = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),1)
    checkouts = Checkout.objects.filter(last_change__gte = last_24_hr,mobile_device_id__isnull=False,user__isnull=True,quantity__gte=1)\
        .order_by('mobile_device_id','-last_change')\
        .distinct('mobile_device_id')\
        .select_related('user').prefetch_related('lines__variant__product')
    devices_eligible = checkouts.values_list('mobile_device_id',flat=True)
    devices_guest_user = Device.objects.filter(device_id__in=devices_eligible,user__in=[1881,203])

    for checkout in checkouts:
    
        if not checkout.mobile_device_id:
            continue
        
        device = devices_guest_user.filter(device_id=checkout.mobile_device_id).order_by('-app_version').first()
        
        if device:
            user = device.user
        else:
            continue
        
        user_id = user.id
        
        try:
            media_url = checkout.lines.first().variant.product.get_product_url()
            product_name = checkout.lines.first().variant.product.name
            # include check for product unpublished, brand inactive
        except:
            media_url=""
            product_name = "this fit"
        
        context_variables = dict()
        context_variables[user_id] = {
            "media":media_url,
            "product_name":product_name
        }

        send_notification_to_device([user],[device.device_id],context_variables=context_variables,event_code="EV_abandoned_cart")
