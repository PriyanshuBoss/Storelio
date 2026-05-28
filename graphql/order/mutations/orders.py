import graphene
from django.core.exceptions import ValidationError
from django.db import transaction
import logging
from saleor.external_services.freshdesk.freshdesk_impl import create_fresh_desk_order_ticket
from saleor.external_services.whatsapp.tasks import send_whatsapp_order_refund
from saleor.graphql.meta.mutations import MetadataInput, UpdateMetadata
from saleor.graphql.meta.permissions import PUBLIC_META_PERMISSION_MAP
from saleor.graphql.support.types import FreshDeskTickets
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.external_services.cashgram import create_cashgram_and_send_link,post_data_cashgram_creation
from ....account.models import User
from ....core.permissions import OrderPermissions
from ....core.taxes import zero_taxed_money
from ....order import OrderStatus, events, models
from ....order.actions import (
    cancel_order,
    clean_mark_order_as_paid,
    mark_order_as_paid,
    order_captured,
    order_refunded,
    order_shipping_updated,
    order_voided,
)
from ....order.error_codes import OrderErrorCode
from ....order.utils import  get_valid_shipping_methods_for_order, update_order_prices
from ....payment import CustomPaymentChoices, PaymentError, TransactionKind, gateway
from ...account.types import AddressInput
from ...core.mutations import BaseMutation
from ...core.scalars import UUID, PositiveDecimal
from ...core.types.common import MetadataError, OrderError
from ...core.utils import validate_required_string_field
from ...meta.deprecated.mutations import ClearMetaBaseMutation, UpdateMetaBaseMutation
from ...meta.deprecated.types import MetaInput, MetaPath
from ...order.mutations.draft_orders import DraftOrderCreate
from ...order.types import Order, OrderEvent,OrderLine,FulfillmentStatus
from ...shipping.types import ShippingMethod
from saleor.order.emails import send_cashgram_creation_email
from decimal import Decimal

logger = logging.getLogger(__name__)

def clean_order_update_shipping(order, method):
    if not order.shipping_address:
        raise ValidationError(
            {
                "order": ValidationError(
                    "Cannot choose a shipping method for an order without "
                    "the shipping address.",
                    code=OrderErrorCode.ORDER_NO_SHIPPING_ADDRESS,
                )
            }
        )

    valid_methods = get_valid_shipping_methods_for_order(order)
    if valid_methods is None or method.pk not in valid_methods.values_list(
        "id", flat=True
    ):
        raise ValidationError(
            {
                "shipping_method": ValidationError(
                    "Shipping method cannot be used with this order.",
                    code=OrderErrorCode.SHIPPING_METHOD_NOT_APPLICABLE,
                )
            }
        )


def clean_order_cancel(order):
    if order and not order.can_cancel():
        raise ValidationError(
            {
                "order": ValidationError(
                    "This order can't be canceled.",
                    code=OrderErrorCode.CANNOT_CANCEL_ORDER,
                )
            }
        )


def clean_payment(payment):
    if not payment:
        raise ValidationError(
            {
                "payment": ValidationError(
                    "There's no payment associated with the order.",
                    code=OrderErrorCode.PAYMENT_MISSING,
                )
            }
        )


def clean_order_capture(payment):
    clean_payment(payment)
    if not payment.is_active:
        raise ValidationError(
            {
                "payment": ValidationError(
                    "Only pre-authorized payments can be captured",
                    code=OrderErrorCode.CAPTURE_INACTIVE_PAYMENT,
                )
            }
        )


def clean_void_payment(payment):
    """Check for payment errors."""
    clean_payment(payment)
    if not payment.is_active:
        raise ValidationError(
            {
                "payment": ValidationError(
                    "Only pre-authorized payments can be voided",
                    code=OrderErrorCode.VOID_INACTIVE_PAYMENT,
                )
            }
        )


def clean_refund_payment(payment):
    clean_payment(payment)
    if payment.gateway == CustomPaymentChoices.MANUAL:
        raise ValidationError(
            {
                "payment": ValidationError(
                    "Manual payments can not be refunded.",
                    code=OrderErrorCode.CANNOT_REFUND,
                )
            }
        )


def try_payment_action(order, user, payment, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except (PaymentError, ValueError) as e:
        message = str(e)
        events.payment_failed_event(
            order=order, user=user, message=message, payment=payment
        )
        raise ValidationError(
            {"payment": ValidationError(message, code=OrderErrorCode.PAYMENT_ERROR)}
        )


class OrderUpdateInput(graphene.InputObjectType):
    billing_address = AddressInput(description="Billing address of the customer.")
    user_email = graphene.String(description="Email address of the customer.")
    shipping_address = AddressInput(description="Shipping address of the customer.")


class OrderUpdate(DraftOrderCreate):
    class Arguments:
        id = graphene.ID(required=True, description="ID of an order to update.")
        input = OrderUpdateInput(
            required=True, description="Fields required to update an order."
        )

    class Meta:
        description = "Updates an order."
        model = models.Order
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def clean_input(cls, info, instance, data):
        draft_order_cleaned_input = super().clean_input(info, instance, data)

        # We must to filter out field added by DraftOrderUpdate
        editable_fields = ["billing_address", "shipping_address", "user_email"]
        cleaned_input = {}
        for key in draft_order_cleaned_input:
            if key in editable_fields:
                cleaned_input[key] = draft_order_cleaned_input[key]
        return cleaned_input

    @classmethod
    def get_instance(cls, info, **data):
        instance = super().get_instance(info, **data)
        if instance.status == OrderStatus.DRAFT:
            raise ValidationError(
                {
                    "id": ValidationError(
                        "Provided order id belongs to draft order. "
                        "Use `draftOrderUpdate` mutation instead.",
                        code=OrderErrorCode.INVALID,
                    )
                }
            )
        return instance

    @classmethod
    @transaction.atomic
    def save(cls, info, instance, cleaned_input):
        cls._save_addresses(info, instance, cleaned_input)
        if instance.user_email:
            user = User.objects.filter(email=instance.user_email).first()
            instance.user = user
        instance.save()
        info.context.plugins.order_updated(instance)


class OrderUpdateShippingInput(graphene.InputObjectType):
    shipping_method = graphene.ID(
        description="ID of the selected shipping method.", name="shippingMethod"
    )


class OrderUpdateShipping(BaseMutation):
    order = graphene.Field(Order, description="Order with updated shipping method.")

    class Arguments:
        id = graphene.ID(
            required=True,
            name="order",
            description="ID of the order to update a shipping method.",
        )
        input = OrderUpdateShippingInput(
            description="Fields required to change shipping method of the order."
        )

    class Meta:
        description = "Updates a shipping method of the order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)
        data = data.get("input")

        if not data["shipping_method"]:
            if not order.is_draft() and order.is_shipping_required():
                raise ValidationError(
                    {
                        "shipping_method": ValidationError(
                            "Shipping method is required for this order.",
                            code=OrderErrorCode.SHIPPING_METHOD_REQUIRED,
                        )
                    }
                )

            order.shipping_method = None
            order.shipping_price = zero_taxed_money()
            order.shipping_method_name = None
            order.save(
                update_fields=[
                    "currency",
                    "shipping_method",
                    "shipping_price_net_amount",
                    "shipping_price_gross_amount",
                    "shipping_method_name",
                ]
            )
            return OrderUpdateShipping(order=order)

        method = cls.get_node_or_error(
            info,
            data["shipping_method"],
            field="shipping_method",
            only_type=ShippingMethod,
        )

        clean_order_update_shipping(order, method)

        order.shipping_method = method
        order.shipping_price = info.context.plugins.calculate_order_shipping(order)
        order.shipping_method_name = method.name
        order.save(
            update_fields=[
                "currency",
                "shipping_method",
                "shipping_method_name",
                "shipping_price_net_amount",
                "shipping_price_gross_amount",
            ]
        )
        update_order_prices(order, info.context.discounts)
        # Post-process the results
        order_shipping_updated(order)
        return OrderUpdateShipping(order=order)


class OrderAddNoteInput(graphene.InputObjectType):
    message = graphene.String(
        description="Note message.", name="message", required=True
    )


class OrderAddNote(BaseMutation):
    order = graphene.Field(Order, description="Order with the note added.")
    event = graphene.Field(OrderEvent, description="Order note created.")

    class Arguments:
        id = graphene.ID(
            required=True,
            description="ID of the order to add a note for.",
            name="order",
        )
        input = OrderAddNoteInput(
            required=True, description="Fields required to create a note for the order."
        )

    class Meta:
        description = "Adds note to the order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def clean_input(cls, _info, _instance, data):
        try:
            cleaned_input = validate_required_string_field(data["input"], "message")
        except ValidationError:
            raise ValidationError(
                {
                    "message": ValidationError(
                        "Message can't be empty.", code=OrderErrorCode.REQUIRED,
                    )
                }
            )
        return cleaned_input

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)
        cleaned_input = cls.clean_input(info, order, data)
        event = events.order_note_added_event(
            order=order, user=info.context.user, message=cleaned_input["message"],
        )
        return OrderAddNote(order=order, event=event)


class OrderCancel(BaseMutation):
    order = graphene.Field(Order, description="Canceled order.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of the order to cancel.")

    class Meta:
        description = "Cancel an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)
        clean_order_cancel(order)
        cancel_order(order=order, user=info.context.user)
        return OrderCancel(order=order)


class OrderMarkAsPaid(BaseMutation):
    order = graphene.Field(Order, description="Order marked as paid.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of the order to mark paid.")

    class Meta:
        description = "Mark order as manually paid."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def clean_billing_address(cls, instance):
        if not instance.billing_address:
            raise ValidationError(
                "Order billing address is required to mark order as paid.",
                code=OrderErrorCode.BILLING_ADDRESS_NOT_SET,
            )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)

        cls.clean_billing_address(order)
        try_payment_action(
            order, info.context.user, None, clean_mark_order_as_paid, order
        )

        mark_order_as_paid(order, info.context.user)
        return OrderMarkAsPaid(order=order)


class OrderCapture(BaseMutation):
    order = graphene.Field(Order, description="Captured order.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of the order to capture.")
        amount = PositiveDecimal(
            required=True, description="Amount of money to capture."
        )

    class Meta:
        description = "Capture an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, amount, **data):
        if amount <= 0:
            raise ValidationError(
                {
                    "amount": ValidationError(
                        "Amount should be a positive number.",
                        code=OrderErrorCode.ZERO_QUANTITY,
                    )
                }
            )

        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)
        payment = order.get_last_payment()
        clean_order_capture(payment)

        transaction = try_payment_action(
            order, info.context.user, payment, gateway.capture, payment, amount
        )
        # Confirm that we changed the status to capture. Some payment can receive
        # asynchronous webhook with update status
        if transaction.kind == TransactionKind.CAPTURE:
            order_captured(order, info.context.user, amount, payment)
        return OrderCapture(order=order)


class OrderVoid(BaseMutation):
    order = graphene.Field(Order, description="A voided order.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of the order to void.")

    class Meta:
        description = "Void an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)
        payment = order.get_last_payment()
        clean_void_payment(payment)

        transaction = try_payment_action(
            order, info.context.user, payment, gateway.void, payment
        )
        # Confirm that we changed the status to void. Some payment can receive
        # asynchronous webhook with update status
        if transaction.kind == TransactionKind.VOID:
            order_voided(order, info.context.user, payment)
        return OrderVoid(order=order)


class OrderRefund(BaseMutation):
    order = graphene.Field(Order, description="A refunded order.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of the order to refund.")
        amount = PositiveDecimal(
            required=True, description="Amount of money to refund."
        )

    class Meta:
        description = "Refund an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, amount, **data):
        if amount <= 0:
            raise ValidationError(
                {
                    "amount": ValidationError(
                        "Amount should be a positive number.",
                        code=OrderErrorCode.ZERO_QUANTITY,
                    )
                }
            )

        order = cls.get_node_or_error(info, data.get("id"), only_type=Order)
        payment = order.get_last_payment()
        clean_refund_payment(payment)

        transaction = try_payment_action(
            order, info.context.user, payment, gateway.refund, payment, amount
        )

        # Confirm that we changed the status to refund. Some payment can receive
        # asynchronous webhook with update status
        if transaction.kind == TransactionKind.REFUND:
            order_refunded(order, info.context.user, amount, payment)
        return OrderRefund(order=order)


class OrderUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates meta for order."
        model = models.Order
        public = True

    class Arguments:
        token = UUID(description="Token of an object to update.", required=True)
        input = MetaInput(
            description="Fields required to update new or stored metadata item.",
            required=True,
        )

    @classmethod
    def get_instance(cls, info, **data):
        token = data["token"]
        return models.Order.objects.get(token=token)


class OrderUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates private meta for order."
        model = models.Order
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = False


class OrderClearMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears stored metadata value."
        model = models.Order
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = True

    class Arguments:
        token = UUID(description="Token of an object to clear.", required=True)
        input = MetaPath(
            description="Fields required to update new or stored metadata item.",
            required=True,
        )

    @classmethod
    def get_instance(cls, info, **data):
        token = data["token"]
        return models.Order.objects.get(token=token)


class OrderClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears stored private metadata value."
        model = models.Order
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = False


class OrderLineMetaUpdate(UpdateMetadata):
    
    class Meta:
        description = "Updates metadata of an orderline."
        permission_map = PUBLIC_META_PERMISSION_MAP
        model = models.OrderLine

        error_type_class = MetadataError
        public = True
        error_type_field = "metadata_errors"
        return_field_name = "OrderLine"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        instance = cls.get_instance(info, **data)
        if instance:
            metadata_list = data.get("input")
            if 'penalty' in [data["key"].strip() for data in metadata_list]:
                
                penalty_percentage = NumberUtilities.convert_string_to_decimal('0')
                for item in metadata_list:
                    if item.get('key') == 'penalty':
                        penalty_percentage = NumberUtilities.convert_string_to_decimal(item.get('value'))
                        break

                # if penalty is not already deducted
                if instance.metadata.get('penalty') is None:
                    brand_due_amount = NumberUtilities.convert_string_to_decimal(instance.metadata.get('brand_due_amount', '0'))
                    if brand_due_amount < 0:
                        updated_brand_due_amount = brand_due_amount + penalty_percentage * Decimal(brand_due_amount)/100
                    else:
                        updated_brand_due_amount = brand_due_amount - penalty_percentage * Decimal(brand_due_amount)/100
                    
                    updated_brand_due_amount = "{0:.3f}".format(updated_brand_due_amount)
                    instance.metadata.update({"brand_due_amount": updated_brand_due_amount})
                    instance.save()
        return super().perform_mutation(root, info, **data)

class RefundOrderLine(BaseMutation):

    success = graphene.Boolean(description = "CashGram Creation")

    class Arguments:
        id = graphene.ID(required = True ,description = "ID of the orderline for refund")

    class Meta:
        description = "Refund of Orderline"
        model = models.OrderLine
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def send_mail_zaamo_user(cls,user,orderline,cashgram_instance):
        
        user_email = user.email
        order_id = orderline.order_id
        amount  = cashgram_instance.refund_amount
        reference_id = cashgram_instance.reference_id
        cashgram_id = cashgram_instance.cashgram_id

        data = {
            "order_id":order_id,
            "amount":amount,
            "reference_id":reference_id,
            "cashgram_id":cashgram_id
        }
        data = StringUtilities.convert_object_to_string(data)
        send_cashgram_creation_email.delay(user_email,data)

    @staticmethod
    def send_order_refund_on_whatsapp(cashgram_instance: models.OrderLineCashgram):
        order_id, brand_name, user_id, user_mobile = models.OrderLineCashgram.objects.filter(id=cashgram_instance.id).values_list('orderline__order_id', 'orderline__brand__brand_name', 'orderline__order__user_id', 'orderline__order__user__mobile_no').first()
        data = {
            'order_id': graphene.Node.to_global_id('Order', order_id),
            'brand_name': brand_name,
            'cashgram_link': cashgram_instance.cashgram_link,
            'user_id': user_id,
            'user_mobile': user_mobile
        }
        send_whatsapp_order_refund.delay(data)

    
    @classmethod
    def perform_mutation(cls, root, info, **data):

        user = info.context.user
        orderline = cls.get_node_or_error(info, data.get("id"), only_type=OrderLine)
        fulfillment_line = orderline.fulfillment_line.first()
        fulfillment = fulfillment_line.fulfillment
        created = False

        if fulfillment.status in [FulfillmentStatus.CANCELLATION_INITIATED,FulfillmentStatus.RETURN_INITIATED] and (not models.OrderLineCashgram.objects.filter(orderline_id = orderline.id).exists()):
            
            orderline_id = orderline.id
            post_data = post_data_cashgram_creation(orderline)
            logger.info(f'{orderline_id} Cashgram creation Post data : {post_data}')
            response_data = create_cashgram_and_send_link(orderline,post_data)
            logger.info(f'{orderline_id} Cashgram creation API response : {response_data}')
            if response_data.get('data'):
                orderline_cashgram = models.OrderLineCashgram()
                orderline_cashgram.cashgram_id = StringUtilities.convert_object_to_string(orderline.id)
                orderline_cashgram.cashgram_link = StringUtilities.convert_object_to_string(response_data.get('data').get('cashgramLink'))
                orderline_cashgram.reference_id = StringUtilities.convert_object_to_string(response_data.get('data').get('referenceId'))
                orderline_cashgram.orderline = orderline
                orderline_cashgram.refund_by_user = user
                orderline_cashgram.refund_amount = post_data.get('amount')
                orderline_cashgram.metadata = post_data
                orderline_cashgram.save()
                created = True
                cls.send_mail_zaamo_user(user,orderline,orderline_cashgram)
                cls.send_order_refund_on_whatsapp(orderline_cashgram)

        else:

            err_msg = "This Orderline can't be refunded or already refunded once"
            raise ValidationError(
                {
                    "fulfillment": ValidationError(
                        err_msg, code=OrderErrorCode.CANNOT_REFUND
                    )
                }
            )
        
        return cls(success=created)


class CreateOrderFreshdeskTicket(BaseMutation):
    order = graphene.Field(Order, description="Order ticket created")
    ticket = graphene.Field(FreshDeskTickets, description="Order ticket created")

    class Arguments:
        id = graphene.ID(required=True, description="ID of the order to create ticket upon.")
        note = graphene.String(description="Note for customer.")

    class Meta:
        description = "Create freshdesk ticket for order"
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        fulfillmentline_id = graphene.Node.from_global_id(data.get("id"))[1]
        order,ticket = create_fresh_desk_order_ticket(fulfillmentline_id,data.get('note'))
        return CreateOrderFreshdeskTicket(order=order,ticket=ticket)
