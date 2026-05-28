from collections import defaultdict
from decimal import Decimal
import logging
import graphene
from django.core.exceptions import ValidationError
from django.template.defaultfilters import pluralize
from saleor.external_services.freshdesk.tasks import create_freshdesk_ticket_for_cancelled_orders_task
from saleor.graphql.order.utils import set_brand_due_amount_to_orderline_meta_for_cancellation
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.utilities.time_utilities import TimeUtilities
from ....core.exceptions import InsufficientStock
from ....core.permissions import OrderPermissions
from ....order import models
from ....warehouse import models as warehouse_models
from ....order.actions import (
    cancel_fulfillment,
    create_fulfillments,
    fulfillment_tracking_updated,
)
from ....order.emails import send_fulfillment_update
from ....order.utils import orderline_update_notification, update_revenue_in_orderline_meta
from ....order.error_codes import OrderErrorCode
from ...core.mutations import BaseMutation
from ...core.types.common import OrderError
from ...core.utils import from_global_id_strict_type, get_duplicated_values
from ...meta.deprecated.mutations import ClearMetaBaseMutation, UpdateMetaBaseMutation
from ...order.types import Fulfillment, Order, FulfillmentLine
from ...warehouse.types import Warehouse
from ..types import OrderLine
from saleor.order import FulfillmentStatus
from saleor.graphql.order.enums import OrderFullfillmentStatusEnum
from saleor.notifications.tasks import send_notification_fulfillment_note
from saleor.external_services.whatsapp.tasks import send_whatsapp_fulfillment_note



logger = logging.getLogger(__name__)

class OrderFulfillStockInput(graphene.InputObjectType):
    quantity = graphene.Int(
        description="The number of line items to be fulfilled from given warehouse.",
        required=True,
    )
    warehouse = graphene.ID(
        description="ID of the warehouse from which the item will be fulfilled.",
        required=True,
    )


class OrderFulfillLineInput(graphene.InputObjectType):
    order_line_id = graphene.ID(
        description="The ID of the order line.", name="orderLineId"
    )
    
    stocks = graphene.List(
        graphene.NonNull(OrderFulfillStockInput),
        required=True,
        description="List of stock items to create.",
    )


class OrderFulfillInput(graphene.InputObjectType):
    fulfillment_status = OrderFullfillmentStatusEnum(
                                description=(
                                    "Status for Fulfillment"
                                ),
                            )
    lines = graphene.List(
        graphene.NonNull(OrderFulfillLineInput),
        required=True,
        description="List of items informing how to fulfill the order.",
    )
    notify_customer = graphene.Boolean(
        description="If true, send an email notification to the customer."
    )


class FulfillmentUpdateTrackingInput(graphene.InputObjectType):
    tracking_number = graphene.String(description="Fulfillment tracking number.")
    notify_customer = graphene.Boolean(
        default_value=False,
        description="If true, send an email notification to the customer.",
    )


class FulfillmentInput(graphene.InputObjectType):
    warehouse_id = graphene.ID(
        description="ID of warehouse where items will be restock.", required=True
    )

    fulfillment_status = OrderFullfillmentStatusEnum(
                                description=(
                                    "Status for Fulfillment"
                                ),
                            )

    shipping_id = graphene.String(
        description="ID of shipping", required=False
    )
    
    shipping_provider = graphene.String(
        description="Provider of shipping", required=False
    )

class FulfillmentClearMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears metadata for fulfillment."
        model = models.Fulfillment
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = True


class FulfillmentUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates metadata for fulfillment."
        model = models.Fulfillment
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = True


class FulfillmentClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clears private metadata for fulfillment."
        model = models.Fulfillment
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = False


class FulfillmentUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates metadata for fulfillment."
        model = models.Fulfillment
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        public = False


class OrderFulfill(BaseMutation):
    fulfillments = graphene.List(
        Fulfillment, description="List of created fulfillments."
    )
    order = graphene.Field(Order, description="Fulfilled order.")

    class Arguments:
        order = graphene.ID(
            description="ID of the order to be fulfilled.", name="order"
        )
        input = OrderFulfillInput(
            required=True, description="Fields required to create an fulfillment."
        )

    class Meta:
        description = "Creates new fulfillments for an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def clean_lines(cls, order_lines, quantities):
        for order_line, line_quantities in zip(order_lines, quantities):
            line_quantity_unfulfilled = order_line.quantity_unfulfilled

            if sum(line_quantities) > line_quantity_unfulfilled:
                msg = (
                    "Only %(quantity)d item%(item_pluralize)s remaining "
                    "to fulfill: %(order_line)s."
                ) % {
                    "quantity": line_quantity_unfulfilled,
                    "item_pluralize": pluralize(line_quantity_unfulfilled),
                    "order_line": order_line,
                }
                order_line_global_id = graphene.Node.to_global_id(
                    "OrderLine", order_line.pk
                )
                raise ValidationError(
                    {
                        "order_line_id": ValidationError(
                            msg,
                            code=OrderErrorCode.FULFILL_ORDER_LINE,
                            params={"order_line": order_line_global_id},
                        )
                    }
                )

    @classmethod
    def check_warehouses_for_duplicates(cls, warehouse_ids):
        for warehouse_ids_for_line in warehouse_ids:
            duplicates = get_duplicated_values(warehouse_ids_for_line)
            if duplicates:
                raise ValidationError(
                    {
                        "warehouse": ValidationError(
                            "Duplicated warehouse ID.",
                            code=OrderErrorCode.DUPLICATED_INPUT_ITEM,
                            params={"warehouse": duplicates.pop()},
                        )
                    }
                )

    @classmethod
    def check_lines_for_duplicates(cls, lines_ids):
        duplicates = get_duplicated_values(lines_ids)
        if duplicates:
            raise ValidationError(
                {
                    "orderLineId": ValidationError(
                        "Duplicated order line ID.",
                        code=OrderErrorCode.DUPLICATED_INPUT_ITEM,
                        params={"order_line": duplicates.pop()},
                    )
                }
            )

    @classmethod
    def check_total_quantity_of_items(cls, quantities_for_lines):
        flat_quantities = sum(quantities_for_lines, [])
        if sum(flat_quantities) <= 0:
            raise ValidationError(
                {
                    "lines": ValidationError(
                        "Total quantity must be larger than 0.",
                        code=OrderErrorCode.ZERO_QUANTITY,
                    )
                }
            )

    @classmethod
    def clean_input(cls, data):
        lines = data["lines"]

        warehouse_ids_for_lines = [
            [stock["warehouse"] for stock in line["stocks"]] for line in lines
        ]
        cls.check_warehouses_for_duplicates(warehouse_ids_for_lines)

        quantities_for_lines = [
            [stock["quantity"] for stock in line["stocks"]] for line in lines
        ]

        lines_ids = [line["order_line_id"] for line in lines]
        cls.check_lines_for_duplicates(lines_ids)
        order_lines = cls.get_nodes_or_error(
            lines_ids, field="lines", only_type=OrderLine
        )

        cls.clean_lines(order_lines, quantities_for_lines)

        cls.check_total_quantity_of_items(quantities_for_lines)

        lines_for_warehouses = defaultdict(list)
        for line, order_line in zip(lines, order_lines):
            for stock in line["stocks"]:
                if stock["quantity"] > 0:
                    warehouse_pk = from_global_id_strict_type(
                        stock["warehouse"], only_type=Warehouse, field="warehouse"
                    )
                    lines_for_warehouses[warehouse_pk].append(
                        {"order_line": order_line, "quantity": stock["quantity"]} 
                    )

        data["order_lines"] = order_lines
        data["quantities"] = quantities_for_lines
        data["lines_for_warehouses"] = lines_for_warehouses
        return data

    @classmethod
    def perform_mutation(cls, _root, info, order, **data):
        order = cls.get_node_or_error(info, order, field="order", only_type=Order)
        data = data.get("input")
        logger.info('Input cleaning started')
        cleaned_input = cls.clean_input(data)
        fulfillment_status = cleaned_input.get("fulfillment_status")
        user = info.context.user
        lines_for_warehouses = cleaned_input["lines_for_warehouses"]
        notify_customer = cleaned_input.get("notify_customer", True)
        logger.info(f'Input Cleaned :: {cleaned_input}')

        try:
            logger.info('Fulfillment creation started')
            fulfillments = create_fulfillments(
                user, order, fulfillment_status, dict(lines_for_warehouses), notify_customer
            )
        except InsufficientStock as exc:
            order_line_global_id = graphene.Node.to_global_id(
                "OrderLine", exc.context["order_line"].pk
            )
            warehouse_global_id = graphene.Node.to_global_id(
                "Warehouse", exc.context["warehouse_pk"]
            )
            raise ValidationError(
                {
                    "stocks": ValidationError(
                        f"Insufficient product stock: {exc.item}",
                        code=OrderErrorCode.INSUFFICIENT_STOCK,
                        params={
                            "order_line": order_line_global_id,
                            "warehouse": warehouse_global_id,
                        },
                    )
                }
            )

        return OrderFulfill(fulfillments=fulfillments, order=order)


class FulfillmentUpdateTracking(BaseMutation):
    fulfillment = graphene.Field(
        Fulfillment, description="A fulfillment with updated tracking."
    )
    order = graphene.Field(
        Order, description="Order for which fulfillment was updated."
    )

    class Arguments:
        id = graphene.ID(required=True, description="ID of an fulfillment to update.")
        input = FulfillmentUpdateTrackingInput(
            required=True, description="Fields required to update an fulfillment."
        )

    class Meta:
        description = "Updates a fulfillment for an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        fulfillment = cls.get_node_or_error(info, data.get("id"), only_type=Fulfillment)
        tracking_number = data.get("input").get("tracking_number") or ""
        fulfillment.tracking_number = tracking_number
        fulfillment.save()
        order = fulfillment.order
        fulfillment_tracking_updated(fulfillment, info.context.user, tracking_number)
        input_data = data.get("input", {})
        notify_customer = input_data.get("notify_customer")
        if notify_customer:
            send_fulfillment_update.delay(order.pk, fulfillment.pk)
        return FulfillmentUpdateTracking(fulfillment=fulfillment, order=order)


class FulfillmentCancel(BaseMutation):
    fulfillment = graphene.Field(Fulfillment, description="A canceled fulfillment.")
    order = graphene.Field(Order, description="Order which fulfillment was cancelled.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of an fulfillment to cancel.")
        input = FulfillmentInput(
            required=True, description="Fields required to cancel an fulfillment."
        )

    class Meta:
        description = "Cancels existing fulfillment and optionally restocks items."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"


    @classmethod
    def perform_mutation(cls, _root, info, **data):
        warehouse_id = data.get("input").get("warehouse_id")
        warehouse = cls.get_node_or_error(
            info, warehouse_id, only_type="Warehouse", field="warehouse_id"
        )
        fulfillment = cls.get_node_or_error(info, data.get("id"), only_type=Fulfillment)

        if not fulfillment.can_edit():
            err_msg = "This fulfillment can't be canceled"
            raise ValidationError(
                {
                    "fulfillment": ValidationError(
                        err_msg, code=OrderErrorCode.CANNOT_CANCEL_FULFILLMENT
                    )
                }
            )

        order = fulfillment.order
        cancel_fulfillment(fulfillment, info.context.user, warehouse)
        fulfillment.refresh_from_db(fields=["status"])
        order.refresh_from_db(fields=["status"])
        return FulfillmentCancel(fulfillment=fulfillment, order=order)

class UpdateFulfillment(BaseMutation):
    fulfillment = graphene.Field(Fulfillment, description="A canceled fulfillment.")
    order = graphene.Field(Order, description="Order which fulfillment was cancelled.")

    class Arguments:
        id = graphene.ID(required=True, description="ID of an fulfillment to update.")
        input = FulfillmentInput(
            required=True, description="Fields required to update an fulfillment."
        )

    class Meta:
        description = "update existing fulfillment and optionally restocks items if canceled."
        permissions = (OrderPermissions.MANAGE_ORDERS,) 
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def store_shipping_data(cls,data,fulfillment):
        input = data.get("input")
        if bool(input.get("shipping_id")) and bool(input.get("shipping_provider")):
            try:
                shipping_fulfillment = models.ShippingFulfillment.objects.get(fulfillment_id = fulfillment.id)
            except models.ShippingFulfillment.DoesNotExist:
                shipping_fulfillment = None

            if shipping_fulfillment == None:
                shipping_fulfillment_created = models.ShippingFulfillment.objects.create(
                    shipping_id = input.get("shipping_id"),
                    shipping_provider = input.get("shipping_provider"),
                    fulfillment = models.Fulfillment.objects.get(pk=fulfillment.id)
                )
                return shipping_fulfillment_created
            else:
                shipping_fulfillment.shipping_id = input.get("shipping_id")
                shipping_fulfillment.shipping_provider = input.get("shipping_provider")
                shipping_fulfillment.save()
                return shipping_fulfillment

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        fulfillment = cls.get_node_or_error(info, data.get("id"), only_type=Fulfillment)
        input = data.get("input")
        fulfillment_status = input.get("fulfillment_status")

        fulfillment = cls.get_node_or_error(info, data.get("id"), only_type=Fulfillment)

        if fulfillment.status == FulfillmentStatus.DELIVERED or fulfillment.status == FulfillmentStatus.SHIPPED :

            if fulfillment_status in (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED) :

                err_msg = "This fulfillment can't be canceled it is already delievered or shipped ."
                raise ValidationError(
                {
                    "fulfillment": ValidationError(
                        err_msg, code=OrderErrorCode.CANNOT_UPDATE_FULFILLMENT
                    )
                }
                )

        if fulfillment_status==FulfillmentStatus.SHIPPED:
            cls.store_shipping_data(data, fulfillment)
        
        platform_code = RequestUtilities.get_platfrom_type_from_headers(info.context)
        
        if not fulfillment.can_edit() and fulfillment_status != FulfillmentStatus.CANCELLED_BY_CUSTOMER:
            err_msg = "This fulfillment can't be Updated it is already canceled."
            raise ValidationError(
                {
                    "fulfillment": ValidationError(
                        err_msg, code=OrderErrorCode.CANNOT_UPDATE_FULFILLMENT
                    )
                }
            )

        order = fulfillment.order

        if fulfillment_status in [FulfillmentStatus.CANCELLATION_PROCESSED,FulfillmentStatus.CANCELLATION_INITIATED,FulfillmentStatus.CANCELLED_BY_CUSTOMER,FulfillmentStatus.RETURN_REQUESTED,FulfillmentStatus.RETURN_INITIATED,FulfillmentStatus.RETURN_COMPLETED]:
            create_freshdesk_ticket_for_cancelled_orders_task.delay(fulfillment.id)

        if fulfillment_status == FulfillmentStatus.CANCELLATION_INITIATED or fulfillment_status == FulfillmentStatus.CANCELLED_BY_CUSTOMER:
            warehouse_id = data.get("input").get("warehouse_id")
            warehouse = cls.get_node_or_error(
                info, warehouse_id, only_type="Warehouse", field="warehouse_id"
            )
            fulfillment = cls.get_node_or_error(info, data.get("id"), only_type=Fulfillment)

            if not fulfillment.can_edit() and fulfillment_status != FulfillmentStatus.CANCELLED_BY_CUSTOMER:
                err_msg = "This fulfillment can't be canceled"
                raise ValidationError(
                    {
                        "fulfillment": ValidationError(
                            err_msg, code=OrderErrorCode.CANNOT_CANCEL_FULFILLMENT
                        )
                    }
                )

            orderline_update_notification(fulfillment,fulfillment_status)
            order = fulfillment.order
            cancel_fulfillment(fulfillment, info.context.user, warehouse)
            if fulfillment_status == FulfillmentStatus.CANCELLED_BY_CUSTOMER:
                fulfillment.status = fulfillment_status
                fulfillment.save()
            fulfillment.refresh_from_db(fields=["status"])
            order.refresh_from_db(fields=["status"])
            cls.update_orderline_metadata(fulfillment.id, fulfillment.status)
            return UpdateFulfillment(fulfillment=fulfillment, order=order) 
        
        orderline_update_notification(fulfillment,fulfillment_status)
        fulfillment.status = fulfillment_status
        fulfillment.updated_by = info.context.user
        fulfillment.save()
        cls.update_orderline_metadata(fulfillment.id, fulfillment.status) 
        cls.deallocate_cancelled_stock(fulfillment.id, fulfillment.status)

        return UpdateFulfillment(fulfillment=fulfillment, order=order) 
    
    
    @staticmethod
    def deallocate_cancelled_stock(fulfillment_id, fulfillment_status):
        """
        updates brand_due_amount, influencer_commission, status
        """
        return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, 
                        FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)
        
        if fulfillment_status in return_or_cancel:
            allocations = warehouse_models.Allocation.objects.filter(order_line_id__in=models.OrderLine.objects.filter(fulfillment_line__fulfillment_id=fulfillment_id).values('id'))

            try:
                allocations.update(quantity_allocated = 0)

            except Exception as e:
                logger.error(str(e))
                

    @staticmethod
    def update_orderline_metadata(fulfillment_id, fulfillment_status):
        """
        updates brand_due_amount, influencer_commission, status
        """
        return_or_cancel = (FulfillmentStatus.CANCELLATION_INITIATED, FulfillmentStatus.CANCELLATION_PROCESSED, FulfillmentStatus.CANCELLED_BY_CUSTOMER,  
                        FulfillmentStatus.RETURN_INITIATED, FulfillmentStatus.RETURN_COMPLETED)

        orderlines = models.OrderLine.objects.filter(fulfillment_line__fulfillment_id=fulfillment_id)

        for order_line in orderlines:
            try:
                if fulfillment_status in return_or_cancel:
                    order_line = set_brand_due_amount_to_orderline_meta_for_cancellation(order_line,order_line.order.voucher)
                    order_line.metadata.update({'influencer_commission': 0})
                    
                    if fulfillment_status == FulfillmentStatus.CANCELLED_BY_CUSTOMER:
                        order_line.metadata.update({
                            'brand_due_amount': "0.000",
                            'platform_fees': "0.000"
                        })
                        
                status = {'status': fulfillment_status}
                order_line.metadata.update(status)
                order_line = update_revenue_in_orderline_meta(order_line)
                
                order_line.save()

            except Exception as e:
                logger.error(str(e))


class UpdateFulfillmentNote(BaseMutation):
    fulfillment_line = graphene.Field(
        FulfillmentLine, description="updated fulfillment line."
    )

    class Arguments:
        id = graphene.ID(required=True, description="ID of the fulfillment_line to update.")
        note = graphene.String(description='text for the field note')

    class Meta:
        description = "Updates note of a fulfillment_line."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        fulfillment_line = cls.get_node_or_error(info, data.get("id"), only_type=FulfillmentLine)
        fulfillment_line.note = data.get("note") or ""
        fulfillment_line.note_creator = info.context.user
        fulfillment_line.save()

        send_whatsapp_fulfillment_note.delay(fulfillment_line_id=fulfillment_line.id)
        send_notification_fulfillment_note(fulfillment_line=fulfillment_line)  

        return UpdateFulfillmentNote(fulfillment_line=fulfillment_line)
    
