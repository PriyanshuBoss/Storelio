import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Set
from decimal import Decimal
from django.db.models import F
from django.utils import timezone
from prices import Money

from ..checkout import calculations
from ..core.taxes import zero_money
from . import DiscountInfo,DealType
from .models import NotApplicable, Sale, VoucherCustomer
if TYPE_CHECKING:
    # flake8: noqa
    from .models import Voucher
    from ..product.models import Collection, Product
    from ..checkout.models import Checkout, CheckoutLine
    from ..order.models import Order


def increase_voucher_usage(voucher: "Voucher") -> None:
    """Increase voucher uses by 1."""
    voucher.used = F("used") + 1
    voucher.save(update_fields=["used"])


def decrease_voucher_usage(voucher: "Voucher") -> None:
    """Decrease voucher uses by 1."""
    voucher.used = F("used") - 1
    voucher.save(update_fields=["used"])


def add_voucher_usage_by_customer(voucher: "Voucher", customer_email: str) -> None:
    voucher_customer = VoucherCustomer.objects.filter(
        voucher=voucher, customer_email=customer_email
    )
    if voucher_customer:
        raise NotApplicable("This offer is only valid once per customer.")
    VoucherCustomer.objects.create(voucher=voucher, customer_email=customer_email)


def remove_voucher_usage_by_customer(voucher: "Voucher", customer_email: str) -> None:
    voucher_customer = VoucherCustomer.objects.filter(
        voucher=voucher, customer_email=customer_email
    )
    if voucher_customer:
        voucher_customer.delete()


def get_product_discount_on_sale(
    product: "Product", product_collections: Set[int], discount: DiscountInfo
):
    """Return discount value if product is on sale or raise NotApplicable."""
    is_product_on_sale = (
        product.id in discount.product_ids
        or product.category_id in discount.category_ids
        or product_collections.intersection(discount.collection_ids)
    )
    if is_product_on_sale:
        return discount.sale.get_discount()
    raise NotApplicable("Discount not applicable for this product")


def get_product_discounts(
    *,
    product: "Product",
    collections: Iterable["Collection"],
    discounts: Iterable[DiscountInfo]
) -> Money:
    """Return discount values for all discounts applicable to a product."""
    product_collections = set(pc.id for pc in collections)
    for discount in discounts or []:
        try:
            yield get_product_discount_on_sale(product, product_collections, discount)
        except NotApplicable:
            pass


def calculate_discounted_price(
    *,
    product: "Product",
    price: Money,
    collections: Iterable["Collection"],
    discounts: Optional[Iterable[DiscountInfo]]
) -> Money:
    """Return minimum product's price of all prices with discounts applied."""
    if discounts:
        discount_prices = list(
            get_product_discounts(
                product=product, collections=collections, discounts=discounts
            )
        )
        if discount_prices:
            price = min(discount(price) for discount in discount_prices)
    return price


def get_discounted_lines(lines, voucher):
    discounted_products = voucher.products.all()
    discounted_categories = set(voucher.categories.all())
    discounted_collections = set(voucher.collections.all())
    discounted_brands = set(voucher.brands.all())
    discounted_lines = []

    if discounted_products or discounted_collections or discounted_categories or discounted_brands:
        for line in lines:
            variant_instance = line.variant
            product_instance = variant_instance.product
            
            line_product = product_instance
            line_category = product_instance.category
            line_brand = product_instance.brand
            line_collections = set(product_instance.collections.all())
            
            if line.variant and (
                line_product in discounted_products
                or line_category in discounted_categories
                or line_brand in discounted_brands
                or line_collections.intersection(discounted_collections)
            ):
                discounted_lines.append(line)
    else:
        # If there's no discounted products, collections or categories,
        # it means that all products are discounted
        discounted_lines.extend(list(lines))

    return discounted_lines

def get_discounted_lines_for_specific_brand_products(lines, voucher):
    discounted_products = voucher.products.all()
    discounted_categories = set(voucher.categories.all())
    discounted_collections = set(voucher.collections.all())
    discounted_brands = set(voucher.brands.all())
    discounted_lines = []

    if discounted_products or discounted_collections or discounted_categories or discounted_brands:

        for line in lines:
            variant_instance = line.variant
            product_instance = variant_instance.product            
            line_product = product_instance
            line_category = product_instance.category
            line_brand = product_instance.brand
            line_collections = set(product_instance.collections.all())


            if discounted_brands and discounted_products :  

                if line.variant and (line_brand in discounted_brands) and (line_product in discounted_products): 
                    discounted_lines.append(line)

            elif discounted_brands and discounted_collections and discounted_categories:

                if line.variant and (line_brand in discounted_brands) and (line_collections.intersection(discounted_collections)) and (line_category in discounted_categories):
                    discounted_lines.append(line)
            
            elif discounted_brands and discounted_collections:

                if line.variant and (line_brand in discounted_brands) and (line_collections.intersection(discounted_collections)):
                    discounted_lines.append(line)

            elif discounted_brands and discounted_categories :

                if line.variant and (line_brand in discounted_brands) and (line_category in discounted_categories):
                    discounted_lines.append(line)
            
            elif discounted_brands:
                
                if line.variant and (line_brand in discounted_brands):
                    discounted_lines.append(line)
            
    else:
        # If there's no discounted products, collections or categories,
        # it means that all products are discounted
        discounted_lines.extend(list(lines))

    return discounted_lines


def validate_voucher_for_checkout(
    voucher: "Voucher",
    checkout: "Checkout",
    lines: Iterable["CheckoutLine"],
    discounts: Optional[Iterable[DiscountInfo]],
):
    subtotal = calculations.checkout_subtotal(
        checkout=checkout, lines=lines, discounts=discounts
    )

    customer_email = checkout.get_customer_email()
    validate_voucher(voucher, subtotal.gross, checkout.quantity, customer_email)


def validate_voucher_in_order(order: "Order"):
    subtotal = order.get_subtotal()
    quantity = order.get_total_quantity()
    customer_email = order.get_customer_email()
    if not order.voucher:
        return
    validate_voucher(order.voucher, subtotal.gross, quantity, customer_email)


def validate_voucher(
    voucher: "Voucher", total_price: Money, quantity: int, customer_email: str
) -> None:
    voucher.validate_min_spent(total_price)
    voucher.validate_min_checkout_items_quantity(quantity)
    if voucher.apply_once_per_customer:
        voucher.validate_once_per_customer(customer_email)

def buy_m_get_n_products_free_discount(voucher:"Voucher",prices: Iterable[Money]) -> Money:
    """Calculate discount value for a voucher of buy m products get n free """
    
    prices.sort()
    n_products = voucher.discount_rule.get('rule').get('n_products')
    free_product_count = (len(prices) - voucher.min_checkout_items_quantity) + 1   
    if free_product_count>=n_products: 
        total_amount = sum(prices[:n_products], zero_money(voucher.currency))
    else:
        total_amount = sum(prices[:free_product_count], zero_money(voucher.currency))
    
    return total_amount

def buy_m_get_x_perc_off_on_n_products_discount(voucher:"Voucher",prices: Iterable[Money]) -> Money:
    """Calculate discount value for a voucher of buy m products get x percent off on n products """

    prices.sort()
    discount_product_count = (len(prices) - voucher.min_checkout_items_quantity) + 1 
    n_products = voucher.discount_rule.get('rule').get('n_products')
    discount_percentage = voucher.discount_value
    if discount_product_count>=n_products:
        total_amount = sum(prices[:n_products], zero_money(voucher.currency))
    else:
        total_amount = sum(prices[:discount_product_count], zero_money(voucher.currency))

    return total_amount*(discount_percentage/100)

def buy_m_get_x_perc_off_buy_n_get_y_perc_off_discount(voucher:"Voucher",prices: Iterable[Money]) -> Money:
    """Calculate discount value for a voucher of buy m products get x percent off and y percent off on n products """

    prices.sort()
    total_line = len(prices)
    total_amount = sum(prices, zero_money(voucher.currency))
    m_products = voucher.min_checkout_items_quantity
    n_products = voucher.discount_rule.get('rule').get('n_products')
    first_x_discount = voucher.discount_value
    y_discount = voucher.discount_rule.get('rule').get('y_percent_discount')
    y_discount = Decimal(y_discount)

    if total_line>=m_products and total_line<n_products:
        return total_amount*(first_x_discount/100)

    elif total_line>=n_products:
        return total_amount*(y_discount/100)

def buy_all_products_at_same_price_discount(voucher:"Voucher",prices: Iterable[Money]) -> Money:
    """Calculate discount value for a voucher of buy all products at x price """

    discount_value = voucher.discount_value
    total_sum=Money(0,'INR')
    for price in prices:
        total_sum += (price - Money(discount_value,'INR'))

    return total_sum

def get_products_voucher_discount(voucher: "Voucher", prices: Iterable[Money]) -> Money:
    """Calculate discount value for a voucher of product or category type."""
    if voucher.apply_once_per_order:
        return voucher.get_discount_amount_for(min(prices))
    
    if voucher.discount_rule.get('deal_type') == DealType.BUY_M_GET_N_FREE:
        return buy_m_get_n_products_free_discount(voucher,prices)

    elif voucher.discount_rule.get('deal_type') == DealType.BUY_M_GET_X_PERC_OFF_N_PROD:
        return buy_m_get_x_perc_off_on_n_products_discount(voucher,prices)

    elif voucher.discount_rule.get('deal_type') == DealType.BUY_M_GET_X_PERC_OFF_BUY_N_GET_Y_PERC_OFF:
        return buy_m_get_x_perc_off_buy_n_get_y_perc_off_discount(voucher,prices)

    elif voucher.discount_rule.get('deal_type') == DealType.BUY_PRODUCTS_AT_SAME_PRICE:
        return buy_all_products_at_same_price_discount(voucher,prices)

    else:    
        discounts = (voucher.get_discount_amount_for(price) for price in prices)
        total_amount = sum(discounts, zero_money(voucher.currency))
        return total_amount


def _fetch_categories(sale_pks: Iterable[str]) -> Dict[int, Set[int]]:
    from ..product.models import Category

    categories = Sale.categories.through.objects.filter(
        sale_id__in=sale_pks
    ).values_list("sale_id", "category_id")
    category_map: Dict[int, Set[int]] = defaultdict(set)
    for sale_pk, category_pk in categories:
        category_map[sale_pk].add(category_pk)
    subcategory_map: Dict[int, Set[int]] = defaultdict(set)
    for sale_pk, category_pks in category_map.items():
        subcategory_map[sale_pk] = set(
            Category.tree.filter(pk__in=category_pks)
            .get_descendants(include_self=True)
            .values_list("pk", flat=True)
        )
    return subcategory_map


def _fetch_collections(sale_pks: Iterable[str]) -> Dict[int, Set[int]]:
    collections = Sale.collections.through.objects.filter(
        sale_id__in=sale_pks
    ).values_list("sale_id", "collection_id")
    collection_map: Dict[int, Set[int]] = defaultdict(set)
    for sale_pk, collection_pk in collections:
        collection_map[sale_pk].add(collection_pk)
    return collection_map


def _fetch_products(sale_pks: Iterable[str]) -> Dict[int, Set[int]]:
    products = Sale.products.through.objects.filter(sale_id__in=sale_pks).values_list(
        "sale_id", "product_id"
    )
    product_map: Dict[int, Set[int]] = defaultdict(set)
    for sale_pk, product_pk in products:
        product_map[sale_pk].add(product_pk)
    return product_map


def fetch_discounts(date: datetime.date) -> List[DiscountInfo]:
    # sales = list(Sale.objects.active(date))
    # pks = {s.pk for s in sales}
    # collections = _fetch_collections(pks)
    # products = _fetch_products(pks)
    # categories = _fetch_categories(pks)

    # return [
    #     DiscountInfo(
    #         sale=sale,
    #         category_ids=categories[sale.pk],
    #         collection_ids=collections[sale.pk],
    #         product_ids=products[sale.pk],
    #     )
    #     for sale in sales
    # ]
    return []

def fetch_active_discounts() -> List[DiscountInfo]:
    return fetch_discounts(timezone.now())

