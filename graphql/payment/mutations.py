from urllib.parse import urlparse
import graphene
from django.conf import settings
from django.core.exceptions import ValidationError

from saleor.utilities.request_utilities import RequestUtilities

from ...checkout.calculations import calculate_checkout_total_with_gift_cards
from ...checkout.checkout_cleaner import clean_billing_address, clean_checkout_shipping,validate_checkout_lines
from ...checkout.utils import cancel_active_payments, get_voucher_for_checkout, voucher_error_msg
from ...core.permissions import OrderPermissions
from ...core.utils import get_client_ip
from ...core.utils.url import validate_storefront_url
from ...payment import PaymentError, gateway, models
from ...payment.error_codes import PaymentErrorCode
from ...payment.utils import create_payment, is_currency_supported
from ..account.i18n import I18nMixin
from ..account.types import AddressInput
from ..checkout.types import Checkout
from ..core.mutations import BaseMutation
from ..core.scalars import PositiveDecimal
from ..core.types import common as common_types
from ..core.utils import from_global_id_strict_type
from .types import Payment, PaymentInitialized
from saleor.discount.models import Voucher
from django.utils import timezone
import logging
logger = logging.getLogger(__name__)


class PaymentInput(graphene.InputObjectType):
    gateway = graphene.Field(
        graphene.String,
        description="A gateway to use with that payment.",
        required=True,
    )
    token = graphene.String(
        required=False,
        description=(
            "Client-side generated payment token, representing customer's "
            "billing data in a secure manner."
        ),
    )
    amount = PositiveDecimal(
        required=False,
        description=(
            "Total amount of the transaction, including "
            "all taxes and discounts. If no amount is provided, "
            "the checkout total will be used."
        ),
    )
    billing_address = AddressInput(
        required=False,
        description=(
            "[Deprecated] Billing address. If empty, the billing address associated "
            "with the checkout instance will be used. Use `checkoutCreate` or "
            "`checkoutBillingAddressUpdate` mutations to set it. This field will be "
            "removed after 2020-07-31."
        ),
    )
    return_url = graphene.String(
        required=False,
        description=(
            "URL of a storefront view where user should be redirected after "
            "requiring additional actions. Payment with additional actions will not be "
            "finished if this field is not provided."
        ),
    )
    is_new = graphene.Boolean(desctiption="boolean to run new cashfree api", required=False)


class CheckoutPaymentCreate(BaseMutation, I18nMixin):
    checkout = graphene.Field(Checkout, description="Related checkout object.")
    payment = graphene.Field(Payment, description="A newly created payment.")

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.", required=True)
        input = PaymentInput(
            description="Data required to create a new payment.", required=True
        )

    class Meta:
        description = "Create a new payment for given checkout."
        error_type_class = common_types.PaymentError
        error_type_field = "payment_errors"

    @classmethod
    def clean_shipping_method(cls, checkout):
        if not checkout.shipping_method:
            raise ValidationError(
                {
                    "shipping_method": ValidationError(
                        "Shipping method not set for this checkout.",
                        code=PaymentErrorCode.SHIPPING_METHOD_NOT_SET,
                    )
                }
            )

    # @classmethod
    # def clean_payment_amount(cls, info, checkout_total, amount):
    #     if amount != checkout_total.gross.amount:
    #         raise ValidationError(
    #             {
    #                 "amount": ValidationError(
    #                     "Partial payments are not allowed, amount should be "
    #                     "equal checkout's total.",
    #                     code=PaymentErrorCode.PARTIAL_PAYMENT_NOT_ALLOWED,
    #                 )
    #             }
    #         )

    @classmethod
    def validate_gateway(cls, gateway_id, currency):
        if not is_currency_supported(currency, gateway_id):
            raise ValidationError(
                {
                    "gateway": ValidationError(
                        f"The gateway {gateway_id} does not support checkout currency.",
                        code=PaymentErrorCode.NOT_SUPPORTED_GATEWAY.value,
                    )
                }
            )

    @classmethod
    def validate_token(cls, manager, gateway: str, input_data: dict):
        token = input_data.get("token")
        is_required = manager.token_is_required_as_payment_input(gateway)
        if not token and is_required:
            raise ValidationError(
                {
                    "token": ValidationError(
                        f"Token is required for {gateway}.",
                        code=PaymentErrorCode.REQUIRED.value,
                    ),
                }
            )

    @classmethod
    def validate_return_url(cls, input_data):
        return_url = input_data.get("return_url")
        if not return_url:
            return
        try:
            return
            # FIXME validate return_url based on which domains are existing
            #validate_storefront_url(return_url)
        except ValidationError as error:
            raise ValidationError(
                {"redirect_url": error}, code=PaymentErrorCode.INVALID
            )

    @classmethod
    def validate_voucher_code(cls, voucher_code):
        if not voucher_code:
            return
        
        try:
            voucher = Voucher.objects.active(date=timezone.now()).get(code=voucher_code)
        except Voucher.DoesNotExist:
            voucher = Voucher.objects.filter(code=voucher_code).first()
        
            message = voucher_error_msg(voucher)

            raise ValidationError(
                {
                    "voucher_code": ValidationError(
                        message,
                        code=PaymentErrorCode.INVALID,
                    ),
                }
            )

    @classmethod
    def update_app_code_in_checkout(cls,checkout,app_code):
        
        if not checkout.app_code:
            checkout.app_code=app_code
            checkout.save()

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, **data):
        checkout_id = from_global_id_strict_type(
            checkout_id, only_type=Checkout, field="checkout_id"
        )

        checkout = models.Checkout.objects.prefetch_related(
            "lines__variant__product__collections"
        ).get(pk=checkout_id)
        logger.info(f"payment creation started for :: {checkout.token}, with data :: {data}")

        data = data["input"]
        # gateway = data["gateway"]

        #boolean to check if cashfree new api needs to be called
        is_new_cashfree_api = data.get('is_new',False)
        
        url = urlparse(info.context.META.get('HTTP_ORIGIN', ''))
        host = url.hostname
        razorpay = settings.RAZORPAY.get('active_status', False)

        app_code =  RequestUtilities.get_app_code_from_headers(info.context)
        platform_code =  RequestUtilities.get_platfrom_type_from_headers(info.context)
        cls.update_app_code_in_checkout(checkout,app_code)

        gateway = 'zaamo.payments.cashfree' 
        
        logger.info(gateway)
        
        cls.validate_gateway(gateway, checkout.currency)
        cls.validate_token(info.context.plugins, gateway, data)
        cls.validate_return_url(data)
        cls.validate_voucher_code(checkout.voucher_code)

        checkout_total = calculate_checkout_total_with_gift_cards(
            checkout, info.context.discounts
        )
        amount = data.get("amount", checkout_total.gross.amount)
        
        validate_checkout_lines(checkout,list(checkout),PaymentErrorCode)

        logger.info("cleaning checkout shipping")
        clean_checkout_shipping(
            checkout, list(checkout), info.context.discounts, PaymentErrorCode
        )

        logger.info("cleaning billing address")
        clean_billing_address(checkout, PaymentErrorCode)
        # cls.clean_payment_amount(info, checkout_total, amount)
        extra_data = {
            "customer_user_agent": info.context.META.get("HTTP_USER_AGENT"),
            "is_new_cashfree_api":is_new_cashfree_api
        }

        logger.info("cancelling active payments")
        cancel_active_payments(checkout)

        
        #boolean for running new cashfree api
        payment = create_payment(
            gateway=gateway,
            payment_token=data.get("token", ""),
            total=amount,
            currency=settings.DEFAULT_CURRENCY,
            email=checkout.email,
            extra_data=extra_data,
            # FIXME this is not a customer IP address. It is a client storefront ip
            customer_ip_address=get_client_ip(info.context),
            checkout=checkout,
            return_url=data.get("return_url"),
        )
        logger.info(f"payment creation successful for checkout_id :: {checkout.token}, amount :: {amount}, payment :: {payment}")
        return CheckoutPaymentCreate(payment=payment, checkout=checkout)


class PaymentCapture(BaseMutation):
    payment = graphene.Field(Payment, description="Updated payment.")

    class Arguments:
        payment_id = graphene.ID(required=True, description="Payment ID.")
        amount = PositiveDecimal(description="Transaction amount.")

    class Meta:
        description = "Captures the authorized payment amount."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = common_types.PaymentError
        error_type_field = "payment_errors"

    @classmethod
    def perform_mutation(cls, _root, info, payment_id, amount=None):
        payment = cls.get_node_or_error(
            info, payment_id, field="payment_id", only_type=Payment
        )
        try:
            gateway.capture(payment, amount)
            payment.refresh_from_db()
        except PaymentError as e:
            raise ValidationError(str(e), code=PaymentErrorCode.PAYMENT_ERROR)
        return PaymentCapture(payment=payment)


class PaymentRefund(PaymentCapture):
    class Meta:
        description = "Refunds the captured payment amount."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = common_types.PaymentError
        error_type_field = "payment_errors"

    @classmethod
    def perform_mutation(cls, _root, info, payment_id, amount=None):
        payment = cls.get_node_or_error(
            info, payment_id, field="payment_id", only_type=Payment
        )
        try:
            gateway.refund(payment, amount=amount)
            payment.refresh_from_db()
        except PaymentError as e:
            raise ValidationError(str(e), code=PaymentErrorCode.PAYMENT_ERROR)
        return PaymentRefund(payment=payment)


class PaymentVoid(BaseMutation):
    payment = graphene.Field(Payment, description="Updated payment.")

    class Arguments:
        payment_id = graphene.ID(required=True, description="Payment ID.")

    class Meta:
        description = "Voids the authorized payment."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = common_types.PaymentError
        error_type_field = "payment_errors"

    @classmethod
    def perform_mutation(cls, _root, info, payment_id):
        payment = cls.get_node_or_error(
            info, payment_id, field="payment_id", only_type=Payment
        )
        try:
            gateway.void(payment)
            payment.refresh_from_db()
        except PaymentError as e:
            raise ValidationError(str(e), code=PaymentErrorCode.PAYMENT_ERROR)
        return PaymentVoid(payment=payment)


class PaymentInitialize(BaseMutation):
    initialized_payment = graphene.Field(PaymentInitialized, required=False)

    class Arguments:
        gateway = graphene.String(
            description="A gateway name used to initialize the payment.", required=True,
        )
        payment_data = graphene.JSONString(
            required=False,
            description=(
                "Client-side generated data required to initialize the payment."
            ),
        )

    class Meta:
        description = "Initializes payment process when it is required by gateway."
        error_type_class = common_types.PaymentError
        error_type_field = "payment_errors"

    @classmethod
    def perform_mutation(cls, _root, info, gateway, payment_data):
        try:
            response = info.context.plugins.initialize_payment(gateway, payment_data)
        except PaymentError as e:
            raise ValidationError(
                {
                    "payment_data": ValidationError(
                        str(e), code=PaymentErrorCode.INVALID.value
                    )
                }
            )
        return PaymentInitialize(initialized_payment=response)
