"""Contain functions which are base for calculating checkout properties.

It's recommended to use functions from calculations.py module to take in account plugin
manager.
"""

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, List, Optional
from saleor.utilities.number_utilities import NumberUtilities
from prices import TaxedMoney , Money
from ..core.prices import quantize_price
from ..core.taxes import zero_taxed_money
from ..discount import DiscountInfo
from saleor.shipping.utils import get_locations
from saleor.brand.models import BrandShippingData

if TYPE_CHECKING:
    # flake8: noqa
    from .models import Checkout, CheckoutLine

def shipping_price_by_location(checkout: "Checkout",lines:Iterable["CheckoutLine"]) -> Money:

    total_shipping_cost,_,_ = calculate_shipping_from_dict(checkout,lines)

    return Money(total_shipping_cost,checkout.shipping_method.currency)

def calculate_brand_shopped_cost(lines:Iterable["CheckoutLine"]):

    brand_cost_dict= {}
    brand_shipping_data_dict = {}
    brand_quantity = {}
    brand_ids = []
    for checkoutline in lines:
        brand = checkoutline.variant.product.brand

        if brand and not checkoutline.cod:
            brand_id = brand.id
            brand_ids.append(brand_id)
            if brand_cost_dict.get(brand_id):
                brand_cost_dict[brand_id] += (checkoutline.quantity * checkoutline.variant.price_amount)
                brand_quantity[brand_id] += checkoutline.quantity
            else:
                brand_cost_dict[brand_id] = (checkoutline.quantity * checkoutline.variant.price_amount)
                brand_quantity[brand_id] = checkoutline.quantity

    brand_shipping = BrandShippingData.objects.filter(brand_id__in=brand_ids)
    for data in brand_shipping:
        if not data.brand_id in brand_shipping_data_dict:
            brand_shipping_data_dict[data.brand_id] = data

    return brand_cost_dict,brand_shipping_data_dict,brand_quantity


def calculate_shipping_from_dict(checkout:"Checkout" , lines:Iterable["CheckoutLine"]):

    brand_cost_dict,brand_shipping_data_dict,brand_quantity = calculate_brand_shopped_cost(lines)

    total_shipping_price = 0
    brand_shipping_cost =  {}
    pincodes = set()
    if checkout.shipping_address:
        pincodes = set([checkout.shipping_address.postal_code])
    for data in brand_shipping_data_dict.values():
        pincodes.add(data.home_state_pincode)
    
    locations = get_locations(pincodes)

    for brand_id in brand_cost_dict:

        brand_shipping_cost[brand_id] = Money(0,checkout.currency)
        if brand_shipping_data_dict.get(brand_id):
            brand_shipping_data = brand_shipping_data_dict[brand_id]
            user_shipping_data = checkout.shipping_address

            if brand_cost_dict[brand_id] < brand_shipping_data.min_order_value_free_cost_amount and user_shipping_data:

                brand_pincode = brand_shipping_data.home_state_pincode
                brand_country = brand_shipping_data.country
                user_pincode = user_shipping_data.postal_code
                user_country = user_shipping_data.country

                brand_location = locations.get((brand_pincode, brand_country))
                user_location= locations.get((user_pincode, user_country))
                
                if brand_location and user_location:
                    
                    if brand_location.state == user_location.state:
                        brand_shipping_cost[brand_id] = brand_shipping_data.shipping_cost_same_state
                        total_shipping_price+=brand_shipping_data.shipping_cost_same_state_amount
                    else:
                        brand_shipping_cost[brand_id] = brand_shipping_data.shipping_cost_other_state
                        total_shipping_price+=brand_shipping_data.shipping_cost_other_state_amount
        
       

    return total_shipping_price,brand_shipping_cost,brand_quantity


def base_checkout_shipping_price(
    checkout: "Checkout", lines: Iterable["CheckoutLine"]
) -> TaxedMoney:
    """Return checkout shipping price."""
    if not checkout.shipping_method or not checkout.is_shipping_required():
        return zero_taxed_money(checkout.currency)

    transport_shipping_price = shipping_price_by_location(checkout,lines)
    shipping_price = checkout.shipping_method.get_total() + transport_shipping_price
    return quantize_price(
        TaxedMoney(net=shipping_price, gross=shipping_price), shipping_price.currency
    )

def get_brand_cod_price_splitting(checkout_lines):
    
    brand_cost = defaultdict(Decimal)
    brand_cod_charge = defaultdict(Decimal)
    brand_added = dict()

    for line in checkout_lines:

        if not line.cod:
            continue

        brand = line.variant.product.brand
        brand_id = brand.id

        min_value_price = brand.metadata.get('min_value_for_free_cod')
        
        brand_cost[brand_id] += (line.quantity * line.variant.price_amount)

        if min_value_price:
            min_value_price = NumberUtilities.convert_string_to_decimal(min_value_price)
            
            if brand_cost[brand_id]>min_value_price:
                brand_cod_charge[brand_id] = Decimal(0)
                brand_added[brand_id] = True
                continue

        
        if brand_added.get(brand_id):
            continue
        
        cod_base_price = brand.cod_base_price
        brand_cod_charge[brand_id] = NumberUtilities.convert_string_to_decimal(cod_base_price)
        brand_added[brand_id] = True
        
    return brand_cod_charge

def base_checkout_cod_charge(
    checkout: "Checkout", lines: Iterable["CheckoutLine"]
) -> TaxedMoney:
    """Return checkout cod price."""
    
    brand_cod_charge=get_brand_cod_price_splitting(lines)

    cod_price = Money(sum(brand_cod_charge.values()),checkout.currency)

    return quantize_price(
        TaxedMoney(net=cod_price, gross=cod_price), cod_price.currency
    )


def base_checkout_subtotal(line_totals: List[TaxedMoney], currency: str) -> TaxedMoney:
    """Return the total cost of all checkout lines."""
    return sum(line_totals, zero_taxed_money(currency))


def base_checkout_total(
    subtotal: TaxedMoney,
    shipping_price: TaxedMoney,
    cod_charge:TaxedMoney,
    discount: TaxedMoney,
    currency: str,
) -> TaxedMoney:
    """Return the total cost of the checkout."""
    total = subtotal + shipping_price - discount + cod_charge
    return max(total, zero_taxed_money(currency))


def base_checkout_line_total(
    line: "CheckoutLine", discounts: Optional[Iterable[DiscountInfo]] = None
) -> TaxedMoney:
    """Return the total price of this line."""
    amount = line.quantity * line.variant.get_price(discounts or [])
    price = quantize_price(amount, amount.currency)
    return TaxedMoney(net=price, gross=price)
