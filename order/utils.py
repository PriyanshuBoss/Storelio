from collections import defaultdict
from decimal import Decimal
from functools import wraps
from typing import Iterable, List
import logging
import graphene
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, F, ExpressionWrapper
from django.db import models
from django.utils import timezone
from prices import Money, TaxedMoney
from saleor.discount import VoucherOwner
from saleor.graphql.analytics.enums import BrandOrderStatus
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from ..account.models import User
from ..core.taxes import zero_money
from ..core.weight import zero_weight
from ..discount.models import NotApplicable, Voucher, VoucherType
from ..discount.utils import (
    get_discounted_lines,
    get_products_voucher_discount,
    validate_voucher_in_order,
    get_discounted_lines_for_specific_brand_products,

)
from ..order import OrderStatus
from ..order.models import Order, OrderLine
from saleor.shipping.utils import get_pincode
from ..plugins.manager import get_plugins_manager
from ..product.utils.digital_products import get_default_digital_content_settings
from ..shipping.models import ShippingMethod
from ..warehouse.management import deallocate_stock, increase_stock
from ..warehouse.models import Warehouse
from . import FulfillmentStatus, events
from saleor.utilities.number_utilities import NumberUtilities
from saleor.notifications.utils import send_notifications
logger = logging.getLogger(__name__)


def get_order_country(order: Order) -> str:
    """Return country to which order will be shipped."""
    address = order.billing_address
    if order.is_shipping_required():
        address = order.shipping_address
    if address is None:
        return settings.DEFAULT_COUNTRY
    return address.country.code


def order_line_needs_automatic_fulfillment(line: OrderLine) -> bool:
    """Check if given line is digital and should be automatically fulfilled."""
    digital_content_settings = get_default_digital_content_settings()
    default_automatic_fulfillment = digital_content_settings["automatic_fulfillment"]
    content = line.variant.digital_content if line.variant else None
    if not content:
        return False
    if default_automatic_fulfillment and content.use_default_settings:
        return True
    if content.automatic_fulfillment:
        return True
    return False


def order_needs_automatic_fulfillment(order: Order) -> bool:
    """Check if order has digital products which should be automatically fulfilled."""
    for line in order.lines.digital():
        if order_line_needs_automatic_fulfillment(line):
            return True
    return False


def update_voucher_discount(func):
    """Recalculate order discount amount based on order voucher."""

    @wraps(func)
    def decorator(*args, **kwargs):
        if kwargs.pop("update_voucher_discount", True):
            order = args[0]
            try:
                discount = get_voucher_discount_for_order(order)
            except NotApplicable:
                discount = zero_money(order.currency)
            order.discount = discount
        return func(*args, **kwargs)

    return decorator


@update_voucher_discount
def recalculate_order(order: Order, **kwargs):
    """Recalculate and assign total price of order.

    Total price is a sum of items in order and order shipping price minus
    discount amount.

    Voucher discount amount is recalculated by default. To avoid this, pass
    update_voucher_discount argument set to False.
    """
    # avoid using prefetched order lines
    lines = [OrderLine.objects.get(pk=line.pk) for line in order]
    prices = [line.get_total() for line in lines]
    total = sum(prices, order.shipping_price)
    # discount amount can't be greater than order total
    order.discount_amount = min(order.discount_amount, total.gross.amount)
    if order.discount:
        total -= order.discount
    order.total = total
    order.save(
        update_fields=[
            "discount_amount",
            "total_net_amount",
            "total_gross_amount",
            "currency",
        ]
    )
    recalculate_order_weight(order)


def recalculate_order_weight(order):
    """Recalculate order weights."""
    weight = zero_weight()
    for line in order:
        if line.variant:
            weight += line.variant.get_weight() * line.quantity
    order.weight = weight
    order.save(update_fields=["weight"])


def update_order_prices(order, discounts):
    """Update prices in order with given discounts and proper taxes."""
    manager = get_plugins_manager()
    for line in order:  # type: OrderLine
        if line.variant:
            unit_price = line.variant.get_price(discounts)
            unit_price = TaxedMoney(unit_price, unit_price)
            line.unit_price = unit_price
            line.save(
                update_fields=[
                    "currency",
                    "unit_price_net_amount",
                    "unit_price_gross_amount",
                ]
            )

            price = manager.calculate_order_line_unit(line)
            if price != line.unit_price:
                line.unit_price = price
                if price.tax and price.net:
                    line.tax_rate = price.tax / price.net
                line.save()

    if order.shipping_method:
        order.shipping_price = manager.calculate_order_shipping(order)
        order.save(
            update_fields=[
                "shipping_price_net_amount",
                "shipping_price_gross_amount",
                "currency",
            ]
        )

    recalculate_order(order)


def update_order_status(order):
    """Update order status depending on fulfillments."""
    quantity_fulfilled = order.quantity_fulfilled
    total_quantity = order.get_total_quantity()

    if quantity_fulfilled <= 0:
        status = OrderStatus.UNFULFILLED
    elif quantity_fulfilled < total_quantity:
        status = OrderStatus.PARTIALLY_FULFILLED
    else:
        status = OrderStatus.FULFILLED

    if status != order.status:
        order.status = status
        order.save(update_fields=["status"])


@transaction.atomic
def add_variant_to_draft_order(order, variant, quantity, discounts=None):
    """Add total_quantity of variant to order.

    Returns an order line the variant was added to.
    """

    try:
        line = order.lines.get(variant=variant)
        line.quantity += quantity
        line.save(update_fields=["quantity"])
    except OrderLine.DoesNotExist:
        unit_price = variant.get_price(discounts)
        unit_price = TaxedMoney(net=unit_price, gross=unit_price)
        product = variant.product
        product_name = StringUtilities.convert_object_to_string(product)
        variant_name = StringUtilities.convert_object_to_string(variant)
        translated_product_name = StringUtilities.convert_object_to_string(product.translated)
        translated_variant_name = StringUtilities.convert_object_to_string(variant.translated)
        if translated_product_name == product_name:
            translated_product_name = ""
        if translated_variant_name == variant_name:
            translated_variant_name = ""
        line = order.lines.create(
            product_name=product_name,
            variant_name=variant_name,
            translated_product_name=translated_product_name,
            translated_variant_name=translated_variant_name,
            product_sku=variant.sku,
            is_shipping_required=variant.is_shipping_required(),
            quantity=quantity,
            unit_price=unit_price,
            variant=variant,
        )
        manager = get_plugins_manager()
        unit_price = manager.calculate_order_line_unit(line)
        line.unit_price = unit_price
        line.tax_rate = (
            unit_price.tax / unit_price.net if unit_price.net.amount != 0 else 0
        )
        line.save(
            update_fields=[
                "currency",
                "unit_price_net_amount",
                "unit_price_gross_amount",
                "tax_rate",
            ]
        )

    return line


def add_gift_card_to_order(order, gift_card, total_price_left):
    """Add gift card to order.

    Return a total price left after applying the gift cards.
    """
    if total_price_left > zero_money(total_price_left.currency):
        order.gift_cards.add(gift_card)
        if total_price_left < gift_card.current_balance:
            gift_card.current_balance = gift_card.current_balance - total_price_left
            total_price_left = zero_money(total_price_left.currency)
        else:
            total_price_left = total_price_left - gift_card.current_balance
            gift_card.current_balance_amount = 0
        gift_card.last_used_on = timezone.now()
        gift_card.save(update_fields=["current_balance_amount", "last_used_on"])
    return total_price_left


def change_order_line_quantity(user, line, old_quantity, new_quantity):
    """Change the quantity of ordered items in a order line."""
    if new_quantity:
        line.quantity = new_quantity
        line.save(update_fields=["quantity"])
    else:
        delete_order_line(line)

    quantity_diff = old_quantity - new_quantity

    # Create the removal event
    if quantity_diff > 0:
        events.draft_order_removed_products_event(
            order=line.order, user=user, order_lines=[(quantity_diff, line)]
        )
    elif quantity_diff < 0:
        events.draft_order_added_products_event(
            order=line.order, user=user, order_lines=[(quantity_diff * -1, line)]
        )


def delete_order_line(line):
    """Delete an order line from an order."""
    line.delete()


def restock_order_lines(order):
    """Return ordered products to corresponding stocks."""
    country = get_order_country(order)
    default_warehouse = Warehouse.objects.filter(
        shipping_zones__countries__contains=country
    ).first()

    for line in order:
        if line.variant and line.variant.track_inventory:
            if line.quantity_unfulfilled > 0:
                deallocate_stock(line, line.quantity_unfulfilled)
            if line.quantity_fulfilled > 0:
                allocation = line.allocations.first()
                warehouse = (
                    allocation.stock.warehouse if allocation else default_warehouse
                )
                increase_stock(line, warehouse, line.quantity_fulfilled)

        if line.quantity_fulfilled > 0:
            line.quantity_fulfilled = 0
            line.save(update_fields=["quantity_fulfilled"])


def restock_fulfillment_lines(fulfillment, warehouse):
    """Return fulfilled products to corresponding stocks.

    Return products to stocks and update order lines quantity fulfilled values.
    """
    order_lines = []
    for line in fulfillment:
        if line.order_line.variant and line.order_line.variant.track_inventory:
            increase_stock(line.order_line, warehouse, line.quantity, allocate=True)
        order_line = line.order_line
        order_line.quantity_fulfilled -= line.quantity
        order_lines.append(order_line)
    OrderLine.objects.bulk_update(order_lines, ["quantity_fulfilled"])


def sum_order_totals(qs):
    zero = Money(0, currency=settings.DEFAULT_CURRENCY)
    taxed_zero = TaxedMoney(zero, zero)
    return sum([order.total for order in qs], taxed_zero)


def get_valid_shipping_methods_for_order(order: Order):
    return ShippingMethod.objects.applicable_shipping_methods_for_instance(
        order, price=order.get_subtotal().gross
    )


def get_prices_of_discounted_specific_product(
    lines: Iterable[OrderLine], voucher: Voucher,
) -> List[Money]:
    """Get prices of variants belonging to the discounted specific products.

    Specific products are products, collections and categories.
    Product must be assigned directly to the discounted category, assigning
    product to child category won't work.
    """
    line_prices = []
    discounted_lines = get_discounted_lines(lines, voucher)

    if voucher.metadata.get('only_free_cod') == True:
        brands_list = []
        for line in discounted_lines:
            brand_id = line.brand_id
            if brand_id not in brands_list:
                cod_price_amount = line.metadata.get('cod_price')
                cod_price_amount = NumberUtilities.convert_string_to_decimal(cod_price_amount)
                cod_price = Money(cod_price_amount,'INR')
                line_prices.extend([cod_price])
                brands_list.append(brand_id)
            
    elif voucher.metadata.get('only_free_shipping')==True:
        for line in discounted_lines:
            shipping_gross = Money(line.shipping_cost_amount,'INR')
            line_prices.extend([shipping_gross])

    elif voucher.is_shipping and lines[0].order.platform_code==PlatformTypeEnum.INFLUENCER_HOME:
        
        for line in discounted_lines:
            shipping_gross = Money(line.shipping_cost_amount,line.order.currency)/line.quantity
            line_prices.extend([line.unit_price_gross + shipping_gross] * line.quantity)

    else:
        for line in discounted_lines:
            line_prices.extend([line.unit_price_gross] * line.quantity)
    
    return line_prices

def get_prices_of_discounted_specific_brand_product(
    lines: Iterable[OrderLine], voucher: Voucher,
) -> List[Money]:
    """Get prices of variants belonging to the discounted specific products.

    Specific brand prodicts are products and categories of a Brand .
    Product must be assigned directly to the discounted category, assigning
    product to child category won't work.
    """
    line_prices = []
    discounted_lines = get_discounted_lines_for_specific_brand_products(lines, voucher)

    if voucher.metadata.get('only_free_cod') == True:
        brands_list = []
        for line in discounted_lines:
            brand_id = line.brand_id
            if brand_id not in brands_list:
                cod_price_amount = line.metadata.get('cod_price')
                cod_price_amount = NumberUtilities.convert_string_to_decimal(cod_price_amount)
                cod_price = Money(cod_price_amount,'INR')
                line_prices.extend([cod_price])
                brands_list.append(brand_id)

    elif voucher.metadata.get('only_free_shipping')==True:
        for line in discounted_lines:
            shipping_gross = Money(line.shipping_cost_amount,'INR')
            line_prices.extend([shipping_gross])
    
    elif voucher.is_shipping and lines[0].order.platform_code==PlatformTypeEnum.INFLUENCER_HOME:
        
        for line in discounted_lines:
            shipping_gross = Money(line.shipping_cost_amount,line.order.currency)/line.quantity
            line_prices.extend([line.unit_price_gross + shipping_gross] * line.quantity)

    else:
        for line in discounted_lines:
            line_prices.extend([line.unit_price_gross] * line.quantity)

    return line_prices


def get_products_voucher_discount_for_order(order: Order) -> Money:
    """Calculate products discount value for a voucher, depending on its type."""
    prices = None
    voucher = order.voucher
    if voucher and voucher.type == VoucherType.SPECIFIC_PRODUCT:
        prices = get_prices_of_discounted_specific_product(order.lines.all(), voucher)
    elif voucher and voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:
        prices = get_prices_of_discounted_specific_brand_product(order.lines.all(), voucher)
    if not prices:
        msg = "This offer is only valid for selected items."
        raise NotApplicable(msg)
    return get_products_voucher_discount(voucher, prices)  # type: ignore


def get_voucher_discount_for_order(order: Order) -> Money:
    """Calculate discount value depending on voucher and discount types.

    Raise NotApplicable if voucher of given type cannot be applied.
    """
    if not order.voucher:
        return zero_money(order.currency)
    validate_voucher_in_order(order)
    subtotal = order.get_subtotal()
    if order.voucher.type == VoucherType.ENTIRE_ORDER:
        return order.voucher.get_discount_amount_for(subtotal.gross)
    if order.voucher.type == VoucherType.SHIPPING:
        return order.voucher.get_discount_amount_for(order.shipping_price)
    if order.voucher.type == VoucherType.SPECIFIC_PRODUCT or order.voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:
        return get_products_voucher_discount_for_order(order)
    raise NotImplementedError("Unknown discount type")

def get_voucher_discount_for_orderline(orderline: OrderLine) -> Money:
    voucher = orderline.order.voucher
    platform_code = orderline.order.platform_code

    if not voucher:
        return zero_money(orderline.order.currency)

    if voucher.type == VoucherType.ENTIRE_ORDER:
        
        all_orderlines_sum = orderline.order.lines.all().annotate(line_total=ExpressionWrapper(
            F('unit_price_net_amount') * F('quantity'), 
            output_field=models.DecimalField())).aggregate(Sum("line_total")).get('line_total__sum')

        discount_value = ((orderline.unit_price_net_amount * orderline.quantity)/all_orderlines_sum) * orderline.order.discount_amount

        if voucher.metadata.get('only_free_shipping')==True:
            if orderline.order.shipping_price_gross_amount>0:
                discount_value = (orderline.shipping_cost_amount/orderline.order.shipping_price_gross_amount)*orderline.order.discount_amount
            else:
                discount_value = 0

        if voucher.metadata.get('only_free_cod')==True:
            
            if not orderline.cod:
                return zero_money(orderline.order.currency)

            cod_lines = orderline.order.lines.distinct('brand_id').order_by('brand_id')
            cod_price_sum = 0
            for line in cod_lines:
                cod_price_amount = line.metadata.get('cod_price')
                cod_price_amount = NumberUtilities.convert_string_to_decimal(cod_price_amount)
                cod_price_sum+=cod_price_amount

            cod_price_amount = orderline.metadata.get('cod_price')
            cod_price_amount = NumberUtilities.convert_string_to_decimal(cod_price_amount)
            order_inst =orderline.order
            cod_lines_same_brand = order_inst.lines.all().filter(cod=True,brand_id=orderline.brand_id).count()
            if cod_price_sum>0:
                discount_value = ((cod_price_amount/cod_lines_same_brand)*orderline.order.discount_amount)/cod_price_sum
            else:
                discount_value = 0

        return Money(discount_value, orderline.order.currency)
    
    if voucher.type == VoucherType.SPECIFIC_PRODUCT:

        discounted_lines = get_discounted_lines(orderline.order.lines.all(), voucher)

        prices = get_prices_of_discounted_specific_product(orderline.order.lines.all(), voucher)
        if not prices or orderline not in discounted_lines:
            return zero_money(orderline.order.currency)
        else:
            price_sum = sum([price.amount for price in prices])

            if voucher.metadata.get('only_free_cod')==True:
                cod_price_amount = orderline.metadata.get('cod_price')
                cod_price_amount = NumberUtilities.convert_string_to_decimal(cod_price_amount)
                order_inst =orderline.order
                cod_lines_same_brand = order_inst.lines.all().filter(cod=True,brand_id=orderline.brand_id).count()
                if price_sum>0:
                    discount_value = ((cod_price_amount/cod_lines_same_brand)*orderline.order.discount_amount)/price_sum
                else:
                    discount_value = 0

                return Money(discount_value, orderline.order.currency)

            if voucher.max_discount and price_sum > voucher.max_discount.amount:
                
                discount_value = ((orderline.unit_price_net_amount * orderline.quantity)/price_sum) * orderline.order.discount_amount

                if voucher.metadata.get('only_free_shipping')==True:
                    if price_sum>0:
                        discount_value = (orderline.shipping_cost_amount/price_sum)*orderline.order.discount_amount
                    else:
                        discount_value = 0
                
                if voucher.is_shipping and platform_code==PlatformTypeEnum.INFLUENCER_HOME:  
                    discount_value = (((orderline.unit_price_net_amount * orderline.quantity)+orderline.shipping_cost_amount)/price_sum) * orderline.order.discount_amount      
                
                return Money(discount_value, orderline.order.currency)

            if voucher.metadata.get('only_free_shipping')==True:
                shipping_gross = Money(orderline.shipping_cost_amount,orderline.order.currency)
                return get_products_voucher_discount(voucher,[shipping_gross])

            if voucher.is_shipping and platform_code==PlatformTypeEnum.INFLUENCER_HOME:
                shipping_gross = Money(orderline.shipping_cost_amount,orderline.order.currency)/orderline.quantity
                return get_products_voucher_discount(voucher, [orderline.unit_price_gross+shipping_gross] * orderline.quantity)
            
            return get_products_voucher_discount(voucher, [orderline.unit_price_gross] * orderline.quantity) 
    
    if voucher.type == VoucherType.SPECIFIC_BRAND_PRODUCTS:

        discounted_lines = get_discounted_lines_for_specific_brand_products(orderline.order.lines.all(), voucher)

        prices = get_prices_of_discounted_specific_brand_product(orderline.order.lines.all(), voucher)
        
        if not prices or orderline not in discounted_lines:
            return zero_money(orderline.order.currency)
        else:
            price_sum = sum([price.amount for price in prices])

            if voucher.metadata.get('only_free_cod')==True:
                cod_price_amount = orderline.metadata.get('cod_price')
                cod_price_amount = NumberUtilities.convert_string_to_decimal(cod_price_amount)
                order_inst =orderline.order
                cod_lines_same_brand = order_inst.lines.all().filter(cod=True,brand_id=orderline.brand_id).count()
                if price_sum>0:
                    discount_value = ((cod_price_amount/cod_lines_same_brand)*orderline.order.discount_amount)/price_sum
                else:
                    discount_value = 0
                
                return Money(discount_value, orderline.order.currency)

            if (voucher.max_discount and price_sum > voucher.max_discount.amount) or (voucher.discount_rule.get('deal_type')):

                discount_value = ((orderline.unit_price_net_amount * orderline.quantity)/price_sum) * orderline.order.discount_amount

                if voucher.metadata.get('only_free_shipping')==True:
                    if price_sum>0:
                        discount_value = (orderline.shipping_cost_amount/price_sum)*orderline.order.discount_amount
                    else:
                        discount_value = 0
                
                if voucher.is_shipping and platform_code==PlatformTypeEnum.INFLUENCER_HOME:  
                    discount_value = (((orderline.unit_price_net_amount * orderline.quantity)+orderline.shipping_cost_amount)/price_sum) * orderline.order.discount_amount      
                
                return Money(discount_value, orderline.order.currency)

            if voucher.metadata.get('only_free_shipping')==True:
                shipping_gross = Money(orderline.shipping_cost_amount,orderline.order.currency)
                return get_products_voucher_discount(voucher,[shipping_gross])
            
            if voucher.is_shipping and platform_code==PlatformTypeEnum.INFLUENCER_HOME:
                shipping_gross = Money(orderline.shipping_cost_amount,orderline.order.currency)/orderline.quantity
                return get_products_voucher_discount(voucher, [orderline.unit_price_gross+shipping_gross] * orderline.quantity)
            
            return get_products_voucher_discount(voucher, [orderline.unit_price_gross] * orderline.quantity) 
    

def match_orders_with_new_user(user: User) -> None:
    Order.objects.confirmed().filter(user_email=user.email, user=None).update(user=user)


def order_placing_notification(order):

    user = order.user
    user_id = user.id
    global_order_id = graphene.Node.to_global_id("Order",order.id)

    context_variables = dict()
    context_variables[user_id] = {'order_id':global_order_id}

    return send_notifications([user],context_variables,event_code="EV_order_placing")

def orderline_update_notification(fulfillment,fulfillment_status):

    if fulfillment.metadata.get('brand_cancelled'):
        return True
    
    fulfillment_line = fulfillment.lines.first()
    orderline  = fulfillment_line.order_line
    product_name = orderline.product_name
    user = orderline.order.user
    user_id = user.id
    context_variables = dict()
    context_variables[user_id] = {'product_name':product_name,'order_status':fulfillment_status}

    return send_notifications([user],context_variables,event_code="EV_order_status_update")

def notification_fulfillment_note(fulfillment_line):

    user = fulfillment_line.order_line.order.user
    order_note = fulfillment_line.note
    user_id = user.id
    try:
        product = fulfillment_line.order_line.variant.product
        product_name = product.name
        media_url = product.get_product_url()
    except:
        product_name = "Note"
        media_url=""
    context_variables = dict()
    context_variables[user_id] = {
        'product_name':product_name,
        'media': media_url,
        'order_note': order_note
    }
    return send_notifications([user],context_variables,event_code="EV_order_note_update")

 
def update_brand_order_status(order_lines):
    
    to_update = []
    order_lines = order_lines.prefetch_related('fulfillment_line__fulfillment').select_related('order','brand')
    
    for root in order_lines:
        
        order_created = root.order.created
        todays_date = TimeUtilities.get_current_date_time()
        
        if root.fulfillment_line:
            fulfillment_line_instance = root.fulfillment_line.first()
            fulfillment = fulfillment_line_instance.fulfillment
        else:
            continue

        
        fullfillment_status_condition_set = {
            FulfillmentStatus.RETURN_REQUESTED,
            FulfillmentStatus.RETURN_INITIATED,
            FulfillmentStatus.RETURN_COMPLETED,
            FulfillmentStatus.CANCELLATION_INITIATED,
            FulfillmentStatus.CANCELLATION_PROCESSED,
            FulfillmentStatus.DELIVERED,
            FulfillmentStatus.SHIPPED
        }

        fullfillment_status_condition_set_before_shipping = {
            FulfillmentStatus.PLACED,
            FulfillmentStatus.INPROCESS,
            #FulfillmentStatus.SHIPPED
        }

        brand_order_status = BrandOrderStatus.ON_TIME
        
        brand_instance = root.brand
        order_processing_days = brand_instance.order_processing_days
        order_shipping_days = brand_instance.order_shipping_days

        fulfillment_status = fulfillment.status

        if fulfillment_status in fullfillment_status_condition_set_before_shipping:
            diff = todays_date - order_created
            diff_in_days = diff.days
            
            if diff_in_days >= order_shipping_days + 1:
                brand_order_status = BrandOrderStatus.DELAYED
                
                #setting orderline metadata to delayed
                delayed_dict = {}
                delayed_dict['brand_order_status'] = 'delayed'
                delayed_dict['brand_order_status_updated_at'] = todays_date
                root.metadata.update(delayed_dict)
        
        if root.metadata.get('brand_order_status') == 'delayed' and fulfillment_status in fullfillment_status_condition_set:
            diff = fulfillment.updated_at - order_created
            diff_in_days = diff.days
            
            if diff_in_days <= order_processing_days+order_shipping_days:
                delayed_dict = {}
                delayed_dict['brand_order_status'] = 'on_time'
                delayed_dict['brand_order_status_updated_at'] = todays_date
                root.metadata.update(delayed_dict)

        if not root.metadata.get('status'):
            root.metadata['status']=fulfillment_status
            
        to_update.append(root)
        
    OrderLine.objects.bulk_update(to_update,['metadata'])
            

def get_cod_amount(orderline_instance):

    if orderline_instance.cod:
        cod_lines_same_brand = orderline_instance.order.lines.filter(brand_id=orderline_instance.brand_id).count()
        cod_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('cod_price'))/cod_lines_same_brand
        
    else:
        cod_amount = 0

    return cod_amount

def get_shipping_or_cod_charge(orderline_instance):
    if StringUtilities.convert_object_to_string(orderline_instance.metadata.get('zaamo_shipping')).lower() == 'true':
        shipping = 0
    else:
        shipping = orderline_instance.shipping_cost_amount

    is_cod = orderline_instance.cod
    shipping_or_cod_charge = shipping if not is_cod else get_cod_amount(orderline_instance)

    return shipping_or_cod_charge

def get_true_msp(orderline_instance):

    if orderline_instance.metadata.get('true_msp'):
        unit_msp = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('true_msp'))
        return unit_msp * orderline_instance.quantity

    else:
        return orderline_instance.unit_price_net_amount * orderline_instance.quantity

def get_msp(orderline_instance):
    
    voucher = orderline_instance.order.voucher

    if voucher and voucher.owner ==VoucherOwner.BRAND:
        return get_true_msp(orderline_instance)

    return orderline_instance.unit_price_net_amount * orderline_instance.quantity
    
def get_order_processed_value(orderline_instance):
    order_value = Decimal(0)
    order_value = get_orderline_shopify_price(orderline_instance)
    order_value = order_value or NumberUtilities.convert_string_to_decimal(get_final_price_paid(orderline_instance))

    return order_value

def get_orderline_shopify_price(orderline_instance):
    shopify_price = get_msp(orderline_instance) + Decimal(get_shipping_or_cod_charge(orderline_instance)) + Decimal(orderline_instance.metadata.get('extra_shopify_charge', '0')) - Decimal(orderline_instance.metadata.get('discount_amount', '0'))
    return shopify_price

def get_zaamo_order_line_price(orderline_instance):
    shopify_price = get_msp(orderline_instance) + Decimal(get_shipping_or_cod_charge(orderline_instance)) - Decimal(orderline_instance.metadata.get('discount_amount', '0'))
    return shopify_price

def get_order_shopify_price(orderline_instance):
    shopify_price = NumberUtilities.convert_string_to_decimal(orderline_instance.order.metadata.get('zaamo_shopify_order_price', '0.00'))
    return shopify_price

def get_final_price_paid(orderline_instance):

    line_price_undiscounted = orderline_instance.unit_price_net_amount * orderline_instance.quantity
    line_price_undiscounted+=orderline_instance.shipping_cost_amount
    if not orderline_instance.metadata.get('discount_amount'):
        line_discount_amount = get_voucher_discount_for_orderline(orderline_instance).amount
    else:
        line_discount_amount = NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('discount_amount'))

    return line_price_undiscounted - line_discount_amount

def update_revenue_in_orderline_meta(orderline_instance):

    order_status = orderline_instance.metadata.get('status','placed')
    return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER, FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)

    order_value = NumberUtilities.convert_string_to_float(get_order_processed_value(orderline_instance))
    final_price_paid = NumberUtilities.convert_string_to_float(get_final_price_paid(orderline_instance))
    brand_due_amount = NumberUtilities.convert_string_to_float(orderline_instance.metadata.get('brand_due_amount'))
    inf_commission = NumberUtilities.convert_string_to_float(orderline_instance.metadata.get('influencer_commission'))

    try:
        store_name = orderline_instance.order.order_store.first().store.store_name
    except:
        store_name = 'zaamo'
    if store_name == 'zaamo':
        inf_commission = 0

    if orderline_instance.cod or order_status in return_or_cancel:
        final_price_paid = 0
        order_value = 0

    revenue = final_price_paid - brand_due_amount - inf_commission
    revenue_with_shopify_markup = order_value - brand_due_amount - inf_commission

    orderline_instance.metadata['revenue']=round(revenue,3)
    orderline_instance.metadata['revenue_with_shopify_markup']=round(revenue_with_shopify_markup,3)

    return orderline_instance

def get_brand_order_price_cod_paid(orderline_instance):
        calculated_shopify_price = NumberUtilities.convert_string_to_decimal(orderline_instance.unit_price_net_amount*orderline_instance.quantity) + NumberUtilities.convert_string_to_decimal(get_shipping_or_cod_charge(orderline_instance)) + NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('extra_shopify_charge', '0')) - NumberUtilities.convert_string_to_decimal(orderline_instance.metadata.get('discount_amount', '0'))
        
        unit_price = get_true_msp(orderline_instance)
        with_out_calculated_shopify_price = NumberUtilities.convert_string_to_decimal(unit_price*orderline_instance.quantity) + NumberUtilities.convert_string_to_decimal(get_shipping_or_cod_charge(orderline_instance))
        
        if orderline_instance.cod:
            return NumberUtilities.convert_string_to_decimal(calculated_shopify_price)
        else:
            return NumberUtilities.convert_string_to_decimal(with_out_calculated_shopify_price)
        

def get_taxable_amount(fulfillment_status,orderline_instance,to_update=False):


    shipped_or_exchange = (FulfillmentStatus.SHIPPED, FulfillmentStatus.DELIVERED, FulfillmentStatus.EXCHANGE_COMPLETED, FulfillmentStatus.EXCHANGE_INITIATED, FulfillmentStatus.EXCHANGE_REQUESTED)

    return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER,  
                FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)

    tax_amt = NumberUtilities.convert_string_to_decimal(get_true_msp(orderline_instance) + get_shipping_or_cod_charge(orderline_instance))
    if fulfillment_status in shipped_or_exchange:
    
        return tax_amt,True

    if fulfillment_status in return_or_cancel:
        if to_update:

            if (orderline_instance.metadata.get('tax',False)==True):
                taxable_amt = tax_amt
                return -1*taxable_amt, False
        
    return 0, False
    
