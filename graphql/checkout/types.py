import datetime
from decimal import Decimal
import graphene
from prices import Money
from promise import Promise
from saleor.discount.models import Voucher
from saleor.discount.utils import fetch_discounts, validate_voucher_for_checkout

from saleor.graphql.checkout.enums import CheckoutVoucherStatusEnum
from saleor.graphql.checkout.resolvers import resolve_cod_price
from saleor.utilities.time_utilities import TimeUtilities

from ...checkout import calculations, models
from ...checkout.utils import get_prepaid_amount, get_valid_shipping_methods_for_checkout
from ...core.exceptions import PermissionDenied
from ...core.permissions import AccountPermissions, CheckoutPermissions
from ...core.taxes import display_gross_prices, zero_taxed_money
from ...plugins.manager import get_plugins_manager
from ..account.utils import requestor_has_access
from ..core.connection import CountableDjangoObjectType
from ..core.scalars import UUID
from ..core.types.money import TaxedMoney
from ..decorators import permission_required
from ..discount.dataloaders import DiscountsByDateTimeLoader
from ..giftcard.types import GiftCard
from ..meta.deprecated.resolvers import resolve_meta, resolve_private_meta
from ..meta.types import ObjectWithMetadata
from ..shipping.types import ShippingMethod
from ..utils import get_user_or_app_from_context
from .dataloaders import CheckoutLinesByCheckoutTokenLoader
from saleor.graphql.brand.types import Brand

class GatewayConfigLine(graphene.ObjectType):
    field = graphene.String(required=True, description="Gateway config key.")
    value = graphene.String(description="Gateway config value for key.")

    class Meta:
        description = "Payment gateway client configuration key and value pair."


class PaymentGateway(graphene.ObjectType):
    name = graphene.String(required=True, description="Payment gateway name.")
    id = graphene.ID(required=True, description="Payment gateway ID.")
    config = graphene.List(
        graphene.NonNull(GatewayConfigLine),
        required=True,
        description="Payment gateway client configuration.",
    )
    currencies = graphene.List(
        graphene.String,
        required=True,
        description="Payment gateway supported currencies.",
    )

    class Meta:
        description = (
            "Available payment gateway backend with configuration "
            "necessary to setup client."
        )

class BrandShippingPrice(graphene.ObjectType):
    brand = graphene.Field(Brand,description="Brand instance")
    shipping_cost = graphene.Field(
        TaxedMoney,
        description="The cost of the Shipping price for brand.",
    )


class CheckoutLine(CountableDjangoObjectType):
    total_price = graphene.Field(
        TaxedMoney,
        description="The sum of the checkout line price, taxes and discounts.",
    )
    requires_shipping = graphene.Boolean(
        description="Indicates whether the item need to be delivered."
    )
    cod_base_price = graphene.Float(description="COD base price of brand" )
    class Meta:
        only_fields = ["id", "quantity", "variant", 'cod']
        description = "Represents an item in the checkout."
        interfaces = [graphene.relay.Node]
        model = models.CheckoutLine
        filter_fields = ["id"]

    @staticmethod
    def resolve_total_price(self, info):
        def calculate_total_price(discounts):
            line_total = info.context.plugins.calculate_checkout_line_total(
                checkout_line=self, discounts=discounts
            )

            if self.cod:
                line_discount = self.data.get('discount_amount', 0)
                line_total -= Money(Decimal(line_discount), "INR")
            return line_total

        return (
            DiscountsByDateTimeLoader(info.context)
            .load(info.context.request_time)
            .then(calculate_total_price)
        )
    
    @staticmethod
    def resolve_cod_base_price(self, info):
        return self.variant.product.brand.cod_base_price

    @staticmethod
    def resolve_requires_shipping(root: models.CheckoutLine, *_args):
        return root.is_shipping_required()

class CheckoutVoucherStatus(graphene.ObjectType):
    status = graphene.String(description="status of voucher to checkout")
    message = graphene.String(description="message for voucher to checkout")

class Checkout(CountableDjangoObjectType):
    available_shipping_methods = graphene.List(
        ShippingMethod,
        required=True,
        description="Shipping methods that can be used with this order.",
    )
    available_payment_gateways = graphene.List(
        graphene.NonNull(PaymentGateway),
        description="List of available payment gateways.",
        required=True,
    )
    email = graphene.String(description="Email of a customer.", required=True)
    gift_cards = graphene.List(
        GiftCard, description="List of gift cards associated with this checkout."
    )
    is_shipping_required = graphene.Boolean(
        description="Returns True, if checkout requires shipping.", required=True
    )
    lines = graphene.List(
        CheckoutLine,
        description=(
            "A list of checkout lines, each containing information about "
            "an item in the checkout."
        ),
    )
    shipping_price = graphene.Field(
        TaxedMoney,
        description="The price of the shipping, with all the taxes included.",
    )
    subtotal_price = graphene.Field(
        TaxedMoney,
        description="The price of the checkout before shipping, with taxes included.",
    )
    token = graphene.Field(UUID, description=("The checkout's token."), required=True)
    total_price = graphene.Field(
        TaxedMoney,
        description=(
            "The sum of the the checkout line prices, with all the taxes,"
            "shipping costs, and discounts included."
        ),
    )
    total_mrp = graphene.String(description="Sum of all checkoutline's variant cost_price_amount.")
    payable_price = graphene.String(description="Payable price after discount and COD calculations")
    cod_base_price = graphene.String(description="Sum of all checkoutline's brand base COD price.")
    voucher_status = graphene.Field(CheckoutVoucherStatus, description="Returns boolean value if attached voucher is valid or not.")
    store = graphene.Field('saleor.graphql.store.types.Store', description="Store on which this Checkout is created")
    class Meta:
        only_fields = [
            "billing_address",
            "created",
            "discount_name",
            "gift_cards",
            "is_shipping_required",
            "last_change",
            "note",
            "quantity",
            "shipping_address",
            "shipping_method",
            "translated_discount_name",
            "user",
            "voucher_code",
            "discount",
        ]
        description = "Checkout object."
        model = models.Checkout
        interfaces = [graphene.relay.Node, ObjectWithMetadata]
        filter_fields = ["token"]

    def resolve_store(root: models.Checkout, info):
        checkout_store = root.checkoutstore_set.first()
        if checkout_store:
            return checkout_store.store
        return None


    @staticmethod
    def resolve_user(root: models.Checkout, info):
        requestor = get_user_or_app_from_context(info.context)
        if requestor_has_access(requestor, root.user, AccountPermissions.MANAGE_USERS):
            return root.user
        raise PermissionDenied()

    @staticmethod
    def resolve_email(root: models.Checkout, info):
        return root.get_customer_email()

    @staticmethod
    def resolve_total_price(root: models.Checkout, info):
        def calculate_total_price(data):
            lines, discounts = data
            taxed_total = (
                calculations.checkout_total(
                    checkout=root, lines=lines, discounts=discounts
                )
                - root.get_total_gift_cards_balance()
            )
            # cod_lines_base_price = sum(
            #     [line.variant.product.brand.cod_base_price for line in lines if line.cod]
            #     )
            # taxed_total += Money(Decimal(cod_lines_base_price), root.currency)
            return max(taxed_total, zero_taxed_money())

        lines = CheckoutLinesByCheckoutTokenLoader(info.context).load(root.token)
        discounts = DiscountsByDateTimeLoader(info.context).load(
            info.context.request_time
        )
        

        return Promise.all([lines, discounts]).then(calculate_total_price)

    def resolve_total_mrp(root: models.Checkout, info):
        lines = root.lines.all().values('variant__cost_price_amount', 'quantity')
        total_mrp = Decimal(0.0)
        for line in lines:
            total_mrp += (line.get('variant__cost_price_amount')*line.get('quantity'))

        return "{0:.3f}".format(total_mrp)

    def resolve_cod_base_price(root: models.Checkout, info):
        return resolve_cod_price(root,info)

    @staticmethod
    def resolve_payable_price(root: models.Checkout, info):
        prepaid_amount = get_prepaid_amount(root) 
        return "{0:.2f}".format(prepaid_amount)    

    @staticmethod
    def resolve_subtotal_price(root: models.Checkout, info):
        def calculate_subtotal_price(data):
            lines, discounts = data
            return calculations.checkout_subtotal(
                checkout=root, lines=lines, discounts=discounts
            )

        lines = CheckoutLinesByCheckoutTokenLoader(info.context).load(root.token)
        discounts = DiscountsByDateTimeLoader(info.context).load(
            info.context.request_time
        )

        return Promise.all([lines, discounts]).then(calculate_subtotal_price)

    @staticmethod
    def resolve_shipping_price(root: models.Checkout, info):
        def calculate_shipping_price(data):
            lines, discounts = data
            return calculations.checkout_shipping_price(
                checkout=root, lines=lines, discounts=discounts
            )

        lines = CheckoutLinesByCheckoutTokenLoader(info.context).load(root.token)
        discounts = DiscountsByDateTimeLoader(info.context).load(
            info.context.request_time
        )

        return Promise.all([lines, discounts]).then(calculate_shipping_price)

    @staticmethod
    def resolve_lines(root: models.Checkout, *_args):
        return root.lines.all()

    @staticmethod
    def resolve_available_shipping_methods(root: models.Checkout, info):
        def calculate_available_shipping_methods(data):
            lines, discounts = data
            available = get_valid_shipping_methods_for_checkout(root, lines, discounts)
            if available is None:
                return []

            manager = get_plugins_manager()
            display_gross = display_gross_prices()
            for shipping_method in available:
                # ignore mypy checking because it is checked in
                # get_valid_shipping_methods_for_checkout
                taxed_price = manager.apply_taxes_to_shipping(
                    shipping_method.price, root.shipping_address  # type: ignore
                )
                if display_gross:
                    shipping_method.price = taxed_price.gross
                else:
                    shipping_method.price = taxed_price.net
            return available

        lines = CheckoutLinesByCheckoutTokenLoader(info.context).load(root.token)
        discounts = DiscountsByDateTimeLoader(info.context).load(
            info.context.request_time
        )

        return Promise.all([lines, discounts]).then(
            calculate_available_shipping_methods
        )

    @staticmethod
    def resolve_available_payment_gateways(root: models.Checkout, _info):
        return get_plugins_manager().checkout_available_payment_gateways(checkout=root)

    @staticmethod
    def resolve_gift_cards(root: models.Checkout, _info):
        return root.gift_cards.all()

    @staticmethod
    def resolve_is_shipping_required(root: models.Checkout, _info):
        return root.is_shipping_required()

    @staticmethod
    @permission_required(CheckoutPermissions.MANAGE_CHECKOUTS)
    def resolve_private_meta(root: models.Checkout, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.Checkout, _info):
        return resolve_meta(root, _info)

    def resolve_voucher_status(root: models.Checkout, _info):
        
        if root.voucher_code and root.discount_name:
            
            try:
                voucher = Voucher.objects.active(TimeUtilities.get_current_date_time()).get(code=root.voucher_code)
                discounts = fetch_discounts(datetime.date.today())
                validate_voucher_for_checkout(voucher, root, root.lines.all(), discounts)
                status =  CheckoutVoucherStatusEnum.Valid
                message = "Voucher is valid for checkout"
            except:
                status =  CheckoutVoucherStatusEnum.Invalid
                message = "Voucher is in-valid for checkout. Please remove the voucher"

        else:
            status = CheckoutVoucherStatusEnum.NOTAPPLIED
            message = "No Voucher is applied to the checkout"

        return CheckoutVoucherStatus(
                status = status,
                message = message
                )
