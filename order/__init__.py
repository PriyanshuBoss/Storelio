class OrderStatus:
    DRAFT = "draft"  # fully editable, not confirmed order created by staff users
    UNFULFILLED = "unfulfilled"  # order with no items marked as fulfilled
    PARTIALLY_FULFILLED = (
        "partially fulfilled"  # order with some items marked as fulfilled
    )
    FULFILLED = "fulfilled"  # order with all items marked as fulfilled
    CANCELED = "canceled"  # permanently canceled order

    CHOICES = [
        (DRAFT, "Draft"),
        (UNFULFILLED, "Unfulfilled"),
        (PARTIALLY_FULFILLED, "Partially fulfilled"),
        (FULFILLED, "Fulfilled"),
        (CANCELED, "Canceled"),
    ]


class FulfillmentStatus:
    
    FULFILLED = "fulfilled"  # group of products in an order marked as fulfilled
    CANCELLATION_INITIATED = "cancellation initiated"  # fulfilled group of products in an order marked as canceled
    CANCELLATION_PROCESSED = "cancellation processed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    PLACED = "placed"
    INPROCESS = "in process"
    RETURN_REQUESTED = "return requested"
    RETURN_INITIATED = "return initiated"
    RETURN_COMPLETED = "return completed"
    EXCHANGE_REQUESTED = "exchange requested"
    EXCHANGE_INITIATED = "exchange initiated"
    EXCHANGE_COMPLETED = "exchange completed"
    CANCELLED_BY_CUSTOMER = "cancelled by customer"

    
    
    CHOICES = [
        (PLACED, "Placed"),
        (INPROCESS, "In Process"),
        (SHIPPED, "Shipped"),
        (DELIVERED, "Delivered"),
        (CANCELLATION_INITIATED, "Cancellation Initiated"),
        (CANCELLATION_PROCESSED, "Cancellation Processed"),
        (RETURN_REQUESTED , "Return Requested"),
        (RETURN_INITIATED , "Return Initiated"),
        (RETURN_COMPLETED , "Return Completed"),
        (FULFILLED, "Fulfilled"),
        (EXCHANGE_REQUESTED, "Exchange Requested"),
        (EXCHANGE_INITIATED, "Exchange Initiated"),
        (EXCHANGE_COMPLETED, "Exchange Completed"),
        (CANCELLED_BY_CUSTOMER, "Cancelled By Customer")
    ]


class OrderEvents:
    """The different order event types."""

    DRAFT_CREATED = "draft_created"
    DRAFT_ADDED_PRODUCTS = "draft_added_products"
    DRAFT_REMOVED_PRODUCTS = "draft_removed_products"

    PLACED = "placed"
    PLACED_FROM_DRAFT = "placed_from_draft"

    OVERSOLD_ITEMS = "oversold_items"
    CANCELED = "canceled"

    ORDER_MARKED_AS_PAID = "order_marked_as_paid"
    ORDER_FULLY_PAID = "order_fully_paid"

    UPDATED_ADDRESS = "updated_address"

    EMAIL_SENT = "email_sent"

    PAYMENT_AUTHORIZED = "payment_authorized"
    PAYMENT_CAPTURED = "payment_captured"
    PAYMENT_REFUNDED = "payment_refunded"
    PAYMENT_VOIDED = "payment_voided"
    PAYMENT_FAILED = "payment_failed"
    EXTERNAL_SERVICE_NOTIFICATION = "external_service_notification"

    INVOICE_REQUESTED = "invoice_requested"
    INVOICE_GENERATED = "invoice_generated"
    INVOICE_UPDATED = "invoice_updated"
    INVOICE_SENT = "invoice_sent"

    FULFILLMENT_CANCELED = "fulfillment_canceled"
    FULFILLMENT_RESTOCKED_ITEMS = "fulfillment_restocked_items"
    FULFILLMENT_FULFILLED_ITEMS = "fulfillment_fulfilled_items"
    TRACKING_UPDATED = "tracking_updated"
    NOTE_ADDED = "note_added"

    # Used mostly for importing legacy data from before Enum-based events
    OTHER = "other"

    CHOICES = [
        (DRAFT_CREATED, "The draft order was created"),
        (DRAFT_ADDED_PRODUCTS, "Some products were added to the draft order"),
        (DRAFT_REMOVED_PRODUCTS, "Some products were removed from the draft order"),
        (PLACED, "The order was placed"),
        (PLACED_FROM_DRAFT, "The draft order was placed"),
        (OVERSOLD_ITEMS, "The draft order was placed with oversold items"),
        (CANCELED, "The order was canceled"),
        (ORDER_MARKED_AS_PAID, "The order was manually marked as fully paid"),
        (ORDER_FULLY_PAID, "The order was fully paid"),
        (UPDATED_ADDRESS, "The address from the placed order was updated"),
        (EMAIL_SENT, "The email was sent"),
        (PAYMENT_AUTHORIZED, "The payment was authorized"),
        (PAYMENT_CAPTURED, "The payment was captured"),
        (EXTERNAL_SERVICE_NOTIFICATION, "Notification from external service"),
        (PAYMENT_REFUNDED, "The payment was refunded"),
        (PAYMENT_VOIDED, "The payment was voided"),
        (PAYMENT_FAILED, "The payment was failed"),
        (INVOICE_REQUESTED, "An invoice was requested"),
        (INVOICE_GENERATED, "An invoice was generated"),
        (INVOICE_UPDATED, "An invoice was updated"),
        (INVOICE_SENT, "An invoice was sent"),
        (FULFILLMENT_CANCELED, "A fulfillment was canceled"),
        (FULFILLMENT_RESTOCKED_ITEMS, "The items of the fulfillment were restocked"),
        (FULFILLMENT_FULFILLED_ITEMS, "Some items were fulfilled"),
        (TRACKING_UPDATED, "The fulfillment's tracking code was updated"),
        (NOTE_ADDED, "A note was added to the order"),
        (OTHER, "An unknown order event containing a message"),
    ]


class OrderEventsEmails:
    """The different order emails event types."""

    PAYMENT = "payment_confirmation"
    SHIPPING = "shipping_confirmation"
    TRACKING_UPDATED = "tracking_updated"
    ORDER_CONFIRMATION = "order_confirmation"
    ORDER_CANCEL = "order_cancel"
    ORDER_REFUND = "order_refund"
    FULFILLMENT = "fulfillment_confirmation"
    DIGITAL_LINKS = "digital_links"

    CHOICES = [
        (PAYMENT, "The payment confirmation email was sent"),
        (SHIPPING, "The shipping confirmation email was sent"),
        (TRACKING_UPDATED, "The fulfillment tracking code email was sent"),
        (ORDER_CONFIRMATION, "The order placement confirmation email was sent"),
        (ORDER_CANCEL, "The order cancel confirmation email was sent"),
        (ORDER_REFUND, "The order refund confirmation email was sent"),
        (FULFILLMENT, "The fulfillment confirmation email was sent"),
        (DIGITAL_LINKS, "The email containing the digital links was sent"),
    ]

class RefundStatus:

    REFUND_INITIATED = 'refund initiated'
    REFUND_TRANSFERRED = 'refund transferred'
    REFUND_EXPIRED = 'refund expired'
    REFUND_FAILED = 'refund failed'

    CHOICES = [
        (REFUND_INITIATED, "Refund Initiated"),
        (REFUND_TRANSFERRED, "Refund Transferred"),
        (REFUND_EXPIRED,"Refund Expired"),
        (REFUND_FAILED,"Refund Failed")
    ]

class SourcingRequestOrderStatusFilter:
    FULFILLED = "fulfilled"
    CANCELLATION_INITIATED = "cancellation initiated"
    CANCELLATION_PROCESSED = "cancellation processed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    PLACED = "placed"
    INPROCESS = "in process"
    RETURN_REQUESTED = "return requested"
    RETURN_INITIATED = "return initiated"
    RETURN_COMPLETED = "return completed"
    EXCHANGE_REQUESTED = "exchange requested"
    EXCHANGE_INITIATED = "exchange initiated"
    EXCHANGE_COMPLETED = "exchange completed"
    NO_ORDER_PLACED = "No Order Placed"

    CHOICES = [
        (PLACED, "Placed"),
        (INPROCESS, "In Process"),
        (SHIPPED, "Shipped"),
        (DELIVERED, "Delivered"),
        (CANCELLATION_INITIATED, "Cancellation Initiated"),
        (CANCELLATION_PROCESSED, "Cancellation Processed"),
        (RETURN_REQUESTED , "Return Requested"),
        (RETURN_INITIATED , "Return Initiated"),
        (RETURN_COMPLETED , "Return Completed"),
        (FULFILLED, "Fulfilled"),
        (EXCHANGE_REQUESTED, "Exchange Requested"),
        (EXCHANGE_INITIATED, "Exchange Initiated"),
        (EXCHANGE_COMPLETED, "Exchange Completed"),
        (NO_ORDER_PLACED, "No Order Placed")
    ]
