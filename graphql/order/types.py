import graphene
from django.core.exceptions import ValidationError
from graphene import relay
from decimal import Decimal
from django.conf import settings
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.time_utilities import TimeUtilities

from ...core.anonymize import obfuscate_address, obfuscate_email
from ...core.exceptions import PermissionDenied
from ...core.permissions import AccountPermissions, OrderPermissions, ProductPermissions
from ...core.taxes import display_gross_prices, zero_taxed_money
from ...graphql.utils import get_user_or_app_from_context
from ...order import OrderStatus, models ,RefundStatus
from ...order.models import FulfillmentStatus, OrderStore
from ...order.utils import get_order_country, get_valid_shipping_methods_for_order, get_voucher_discount_for_orderline
from ...plugins.manager import get_plugins_manager
from ...product.templatetags.product_images import get_product_image_thumbnail
from ...warehouse import models as warehouse_models
from ..account.types import User
from ..account.utils import requestor_has_access
from ..core.connection import CountableDjangoObjectType, StoreDjangoObjectType
from ..core.types.common import Image
from ..core.types.money import Money, TaxedMoney
from ..decorators import one_of_permissions_required, permission_required
from ..giftcard.types import GiftCard
from ..invoice.types import Invoice
from ..meta.deprecated.resolvers import resolve_meta, resolve_private_meta
from ..meta.types import ObjectWithMetadata
from ..payment.types import OrderAction, Payment, PaymentChargeStatusEnum
from ..product.types import ProductVariant
from ..shipping.types import ShippingMethod
from ..warehouse.types import Allocation, Warehouse
from .dataloaders import AllocationsByOrderLineIdLoader
from .enums import OrderEventsEmailsEnum, OrderEventsEnum
from .utils import validate_draft_order
from saleor.graphql.store.types import Store
from django.db.models import Max
from ..analytics.enums import BrandOrderStatus

class OrderEventOrderLineObject(graphene.ObjectType):
    quantity = graphene.Int(description="The variant quantity.")
    order_line = graphene.Field(lambda: OrderLine, description="The order line.")
    item_name = graphene.String(description="The variant name.")


class OrderEvent(CountableDjangoObjectType):
    date = graphene.types.datetime.DateTime(
        description="Date when event happened at in ISO 8601 format."
    )
    type = OrderEventsEnum(description="Order event type.")
    user = graphene.Field(User, description="User who performed the action.")
    message = graphene.String(description="Content of the event.")
    email = graphene.String(description="Email of the customer.")
    email_type = OrderEventsEmailsEnum(
        description="Type of an email sent to the customer."
    )
    amount = graphene.Float(description="Amount of money.")
    payment_id = graphene.String(description="The payment ID from the payment gateway.")
    payment_gateway = graphene.String(description="The payment gateway of the payment.")
    quantity = graphene.Int(description="Number of items.")
    composed_id = graphene.String(description="Composed ID of the Fulfillment.")
    order_number = graphene.String(description="User-friendly number of an order.")
    invoice_number = graphene.String(
        description="Number of an invoice related to the order."
    )
    oversold_items = graphene.List(
        graphene.String, description="List of oversold lines names."
    )
    lines = graphene.List(OrderEventOrderLineObject, description="The concerned lines.")
    fulfilled_items = graphene.List(
        lambda: FulfillmentLine, description="The lines fulfilled."
    )
    warehouse = graphene.Field(
        Warehouse, description="The warehouse were items were restocked."
    )

    class Meta:
        description = "History log of the order."
        model = models.OrderEvent
        interfaces = [relay.Node]
        only_fields = ["id"]

    @staticmethod
    def resolve_user(root: models.OrderEvent, info):
        user = info.context.user
        if (
            user == root.user
            or user.has_perm(AccountPermissions.MANAGE_USERS)
            or user.has_perm(AccountPermissions.MANAGE_STAFF)
        ):
            return root.user
        raise PermissionDenied()

    @staticmethod
    def resolve_email(root: models.OrderEvent, _info):
        return root.parameters.get("email", None)

    @staticmethod
    def resolve_email_type(root: models.OrderEvent, _info):
        return root.parameters.get("email_type", None)

    @staticmethod
    def resolve_amount(root: models.OrderEvent, _info):
        amount = root.parameters.get("amount", None)
        return float(amount) if amount else None

    @staticmethod
    def resolve_payment_id(root: models.OrderEvent, _info):
        return root.parameters.get("payment_id", None)

    @staticmethod
    def resolve_payment_gateway(root: models.OrderEvent, _info):
        return root.parameters.get("payment_gateway", None)

    @staticmethod
    def resolve_quantity(root: models.OrderEvent, _info):
        quantity = root.parameters.get("quantity", None)
        return int(quantity) if quantity else None

    @staticmethod
    def resolve_message(root: models.OrderEvent, _info):
        return root.parameters.get("message", None)

    @staticmethod
    def resolve_composed_id(root: models.OrderEvent, _info):
        return root.parameters.get("composed_id", None)

    @staticmethod
    def resolve_oversold_items(root: models.OrderEvent, _info):
        return root.parameters.get("oversold_items", None)

    @staticmethod
    def resolve_order_number(root: models.OrderEvent, _info):
        return root.order_id

    @staticmethod
    def resolve_invoice_number(root: models.OrderEvent, _info):
        return root.parameters.get("invoice_number")

    @staticmethod
    def resolve_lines(root: models.OrderEvent, _info):
        raw_lines = root.parameters.get("lines", None)

        if not raw_lines:
            return None

        line_pks = []
        for entry in raw_lines:
            line_pks.append(entry.get("line_pk", None))

        lines = models.OrderLine.objects.filter(pk__in=line_pks).all()
        results = []
        for raw_line, line_pk in zip(raw_lines, line_pks):
            line_object = None
            for line in lines:
                if line.pk == line_pk:
                    line_object = line
                    break
            results.append(
                OrderEventOrderLineObject(
                    quantity=raw_line["quantity"],
                    order_line=line_object,
                    item_name=raw_line["item"],
                )
            )

        return results

    @staticmethod
    def resolve_fulfilled_items(root: models.OrderEvent, _info):
        lines = root.parameters.get("fulfilled_items", None)
        return models.FulfillmentLine.objects.filter(pk__in=lines)

    @staticmethod
    def resolve_warehouse(root: models.OrderEvent, _info):
        warehouse = root.parameters.get("warehouse")
        return warehouse_models.Warehouse.objects.filter(pk=warehouse).first()


class FulfillmentLine(CountableDjangoObjectType):
    order_line = graphene.Field(lambda: OrderLine)

    class Meta:
        description = "Represents line of the fulfillment."
        interfaces = [relay.Node]
        model = models.FulfillmentLine
        only_fields = ["id", "quantity", "note", "note_creator", "updated_at","fulfillment"]

    @staticmethod
    def resolve_order_line(root: models.FulfillmentLine, _info):
        return root.order_line


class ShippingFulfillment(CountableDjangoObjectType):
    shipping_id = graphene.String(description="Shipping id of the order")
    shipping_provider = graphene.String(description="Shipping provider for the order")

    class Meta:
        description = (
            "Shipping details of the order "
        )
        model = models.ShippingFulfillment
        interfaces = [relay.Node]
        only_fields = [
            "shipping_id",
            "shipping_provider",
        ]

    @staticmethod
    def resolve_shipping_fulfillment(root: models.Fulfillment, *_args):
        try:
            shipping_fulfillment = models.ShippingFulfillment.objects.get(fulfillment_id = root.id)
        except models.ShippingFulfillment.DoesNotExist:
            shipping_fulfillment = None

        return shipping_fulfillment

class Fulfillment(StoreDjangoObjectType, CountableDjangoObjectType):
    lines = graphene.List(
        FulfillmentLine, description="List of lines for the fulfillment."
    )
    status_display = graphene.String(description="User-friendly fulfillment status.")
    warehouse = graphene.Field(
        Warehouse,
        required=False,
        description=("Warehouse from fulfillment was fulfilled."),
    )
    shipping_fulfillment = graphene.Field(
        ShippingFulfillment,
        required=False,
        description=("Shipping details of a shipped order."),
    )

    class Meta:
        description = "Represents order fulfillment."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Fulfillment
        only_fields = [
            "fulfillment_order",
            "id",
            "created",
            "status",
            "tracking_number",
            "updated_by",
            "created_by",
            "updated_at"
        ]

    @staticmethod
    def resolve_lines(root: models.Fulfillment, _info):
        user = _info.context.user
        brand_id = getattr(_info.context, "brand_id", None)
        
        if brand_id and not isinstance(brand_id, (list, int)):
            brand_id = [brand_id.id]
        
        if hasattr(_info.context, 'authorised_brands'):
            authorised_brands = _info.context.authorised_brands
        else:
            authorised_brands = user.get_authorised_brands()
        
        if not brand_id:
            return root.brand_fulfillment_lines(authorised_brands)

        elif brand_id:
            if set(brand_id).issubset(set([brand.id for brand in authorised_brands])):
                return root.brand_fulfillment_lines(brand_id)
            else:
                return root.lines.none()
        else:
            return root.lines.none()
            

    @staticmethod
    def resolve_status_display(root: models.Fulfillment, _info):
        return root.get_status_display()

    @staticmethod
    def resolve_warehouse(root: models.Fulfillment, _info):
        line = root.lines.first()
        return line.stock.warehouse if line and line.stock else None

    @staticmethod
    @permission_required(OrderPermissions.MANAGE_ORDERS)
    def resolve_private_meta(root: models.Fulfillment, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.Fulfillment, _info):
        return resolve_meta(root, _info)

    @staticmethod
    def resolve_shipping_fulfillment(root: models.Fulfillment, _info):
        return ShippingFulfillment.resolve_shipping_fulfillment(root, _info)

class OrderLine(CountableDjangoObjectType):
    thumbnail = graphene.Field(
        Image,
        description="The main thumbnail for the ordered product.",
        size=graphene.Argument(graphene.Int, description="Size of thumbnail."),
    )
    unit_price = graphene.Field(
        TaxedMoney, description="Price of the single item in the order line."
    )
    total_price = graphene.Field(TaxedMoney, description="Price of the order line.",)
    variant = graphene.Field(
        ProductVariant,
        required=False,
        description=(
            "A purchased product variant. Note: this field may be null if the variant "
            "has been removed from stock at all."
        ),
    )
    translated_product_name = graphene.String(
        required=True, description="Product name in the customer's language"
    )
    translated_variant_name = graphene.String(
        required=True, description="Variant name in the customer's language"
    )
    allocations = graphene.List(
        graphene.NonNull(Allocation),
        description="List of allocations across warehouses.",
    )
    commission = graphene.Decimal(
        description="Commission of product in this orderline based on brand"
        )
    brand = graphene.Field("saleor.graphql.brand.types.Brand", description="Brand of order line")
        
    discounted_price = graphene.Decimal(
        description="Total line price after voucher applied."
        )
    shipping_price = graphene.Decimal(
        description="Total shipping price per line."
        )

    created_at = graphene.String(
        description="Date of order created"
        )
    brand_name = graphene.String(
        description="Name of brand of which order is placed"
        )

    order_id = graphene.String(description="order id of the order line")
    fulfilment = graphene.Field(Fulfillment, description="fulfilment of order line")
    fulfilment_line = graphene.Field(FulfillmentLine, description="fulfilment line of order line")
    brand_order_status = graphene.String(description="Info of brand order status")
    too_many_orders = graphene.Boolean(description="If too many orders was true or false for orderline's brand")
    streak_order = graphene.Boolean(description="boolean value if order was a streak order or not")

    refund_status = graphene.String(description = "Refund status of orderline ")

    refund_amount = graphene.String(description="Refund Amount of orderline ")

    cashgram_link = graphene.String(description = "Refund Cashgram link ")
    tracking_url = graphene.String(description = "Tracking URL from Brand")

    refund_creation_time = graphene.DateTime(
        description="The date and time when the refund was created."
    )

    @classmethod
    def get_queryset(cls, queryset, info):
        
        return super().get_queryset(queryset, info).select_related('order', 'variant', 'brand')

    class Meta:
        description = "Represents order line of particular order."
        model = models.OrderLine
        interfaces = [relay.Node, ObjectWithMetadata]
        only_fields = [
            "digital_content_url",
            "id",
            "is_shipping_required",
            "product_name",
            "variant_name",
            "product_sku",
            "quantity",
            "quantity_fulfilled",
            "tax_rate",
            'metadata',
            'cod'
            
        ]

    def resolve_streak_order(root: models.OrderLine, _info):
        order_store = root.order.order_store.first()
        if order_store:
            return order_store.streak_order
        return None

    @staticmethod
    def resolve_thumbnail(root: models.OrderLine, info, *, size=1080):
        if not root.variant:
            return None
        image = root.variant.get_first_image()
        if image:
            url = get_product_image_thumbnail(image, size, method="thumbnail")
            alt = image.alt
            return Image(alt=alt, url=info.context.build_absolute_uri(url))
        return None

    @staticmethod
    def resolve_unit_price(root: models.OrderLine, _info):
        return root.unit_price

    
    @staticmethod
    def resolve_too_many_orders(root: models.OrderLine, _info):
        return root.metadata.get("too_many_orders", False)

    @staticmethod
    def resolve_total_price(root: models.OrderLine, _info):
        return root.unit_price * root.quantity
    
    def resolve_discounted_price(root: models.OrderLine, _info):
        line_price_undiscounted = root.unit_price_net_amount * root.quantity
        line_price_undiscounted += root.shipping_cost_amount

        if not root.metadata.get('discount_amount'):
            line_discount_amount = get_voucher_discount_for_orderline(root).amount
        else:
            line_discount_amount = Decimal(root.metadata.get('discount_amount'))

        return "{0:.3f}".format(line_price_undiscounted - line_discount_amount)

    def resolve_shipping_price(root:models.OrderLine,_info):
        return root.shipping_cost_amount

    @staticmethod
    def resolve_translated_product_name(root: models.OrderLine, _info):
        return root.translated_product_name

    @staticmethod
    def resolve_translated_variant_name(root: models.OrderLine, _info):
        return root.translated_variant_name

    def resolve_commission(root: models.OrderLine, _info):

        platform_code = RequestUtilities.get_platfrom_type_from_headers(_info.context)

        if platform_code==PlatformTypeEnum.INFLUENCER_HOME:
            orderstore = OrderStore.objects.filter(order_id=root.order_id).first()

            if orderstore and orderstore.streak_order:
                return Decimal(root.commission_percentage) * NumberUtilities.convert_string_to_decimal(settings.STORE_STREAK_COMMISSION)
                
        return Decimal(root.commission_percentage)


    def resolve_created_at(root: models.OrderLine, _info):
        return root.order.created
        
    def resolve_brand_name(root: models.OrderLine, _info):
        brand = root.brand
        if brand:
            if brand.brand_name == "thrift_brand":
                platform_code = RequestUtilities.get_platfrom_type_from_headers(_info.context)
                
                if platform_code == PlatformTypeEnum.ANALYTICS:
                    return brand.brand_name

                product = root.variant.product
                brand_name = product.metadata.get('product_brand_name')
                return brand_name
            else:
                return brand.brand_name
        else:
            return "Brand Does Not exist"

    def resolve_order_id(root: models.OrderLine, _info):
        
        return graphene.Node.to_global_id("Order", root.order_id)

    def resolve_fulfilment(root:models.OrderLine, _info):
        
        fulfilment_line_filter = models.FulfillmentLine.objects.filter(order_line=root
        ).select_related('fulfillment')

        if fulfilment_line_filter:
            
            return fulfilment_line_filter[0].fulfillment

        return None

    def resolve_fulfilment_line(root:models.OrderLine, _info):
        
        fulfilment_line_filter = models.FulfillmentLine.objects.filter(order_line=root
        ).select_related('fulfillment')

        if fulfilment_line_filter:
            
            return fulfilment_line_filter[0]

        return None
    
    def resolve_brand(root:models.OrderLine, _info):

        return root.brand if root.brand else None
        
    def resolve_brand_order_status(root:models.OrderLine, _info):
        order_created = root.order.created
        todays_date = TimeUtilities.get_current_date_time()
        
        if root.fulfillment_line:
            fulfillment_line_instance = root.fulfillment_line.first()
            if fulfillment_line_instance is None:
                brand_order_status = ""
                return brand_order_status

            fulfillment = fulfillment_line_instance.fulfillment
        else:
            return 

        
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
                root.save()

        
        if root.metadata.get('brand_order_status') == 'delayed' and fulfillment_status in fullfillment_status_condition_set:
            diff = fulfillment.updated_at - order_created
            diff_in_days = diff.days
            
            if diff_in_days <= order_processing_days+order_shipping_days:
                delayed_dict = {}
                delayed_dict['brand_order_status'] = 'on_time'
                delayed_dict['brand_order_status_updated_at'] = todays_date
                root.metadata.update(delayed_dict)
                root.save()


        if root.metadata.get('brand_order_status'):
            
            if root.metadata.get('brand_order_status') == 'delayed':
                return BrandOrderStatus.DELAYED
            else:
                return BrandOrderStatus.ON_TIME
            


        # else:
        #     diff = fulfillment.updated_at - order_created
        #     diff_in_days = diff.days
        #     if fulfillment_status in fullfillment_status_condition_set:
        #         if diff_in_days > order_processing_days + order_shipping_days :
        #             brand_order_status = BrandOrderStatus.DELAYED
        #     else:
        #         if diff_in_days > order_processing_days:
        #             brand_order_status = BrandOrderStatus.DELAYED
            
        return brand_order_status
    
    def resolve_refund_status(root:models.OrderLine, _info):

        orderline_cashgram = root.orderline_cashgram.first()
        if orderline_cashgram:
            return orderline_cashgram.refund_status
        else:
            return None
    
    def resolve_refund_amount(root:models.OrderLine,_info):

        orderline_cashgram = root.orderline_cashgram.first()
        if orderline_cashgram:
            return orderline_cashgram.refund_amount
        else:
            return None
    
    def resolve_cashgram_link(root:models.OrderLine,_info):

        orderline_cashgram = root.orderline_cashgram.first()
        if orderline_cashgram:
            if orderline_cashgram.refund_status == RefundStatus.REFUND_INITIATED:
                return orderline_cashgram.cashgram_link
            else:
                return None
        else:
            return None

    def resolve_refund_creation_time(root:models.OrderLine,_info):

        orderline_cashgram = root.orderline_cashgram.first()
        if orderline_cashgram:
            return orderline_cashgram.created_at
        else:
            return None

    def resolve_tracking_url(root:models.OrderLine,_info):
        return root.metadata.get('tracking_url','')

    @staticmethod
    @one_of_permissions_required(
        [ProductPermissions.MANAGE_PRODUCTS, OrderPermissions.MANAGE_ORDERS]
    )
    def resolve_allocations(root: models.OrderLine, info):
        return AllocationsByOrderLineIdLoader(info.context).load(root.id)


class Order(CountableDjangoObjectType):

    created = graphene.String()
    store = graphene.Field(Store, description="Store to which this order is related")

    fulfillments = graphene.List(
        Fulfillment, required=True, description="List of shipments for the order."
    )
    lines = graphene.List(
        lambda: OrderLine, required=True, description="List of order lines."
    )
    actions = graphene.List(
        OrderAction,
        description=(
            "List of actions that can be performed in the current state of an order."
        ),
        required=True,
    )
    available_shipping_methods = graphene.List(
        ShippingMethod,
        required=False,
        description="Shipping methods that can be used with this order.",
    )
    invoices = graphene.List(
        Invoice, required=False, description="List of order invoices."
    )
    number = graphene.String(description="User-friendly number of an order.")
    is_paid = graphene.Boolean(description="Informs if an order is fully paid.")
    payment_status = PaymentChargeStatusEnum(description="Internal payment status.")
    payment_status_display = graphene.String(
        description="User-friendly payment status."
    )
    payments = graphene.List(Payment, description="List of payments for the order.")
    total = graphene.Field(TaxedMoney, description="Total amount of the order.")
    shipping_price = graphene.Field(TaxedMoney, description="Total price of shipping.")
    subtotal = graphene.Field(
        TaxedMoney, description="The sum of line prices not including shipping."
    )
    gift_cards = graphene.List(GiftCard, description="List of user gift cards.")
    status_display = graphene.String(description="User-friendly order status.")
    can_finalize = graphene.Boolean(
        description=(
            "Informs whether a draft order can be finalized"
            "(turned into a regular order)."
        ),
        required=True,
    )
    total_authorized = graphene.Field(
        Money, description="Amount authorized for the order."
    )
    total_captured = graphene.Field(Money, description="Amount captured by payment.")
    events = graphene.List(
        OrderEvent, description="List of events associated with the order."
    )
    total_balance = graphene.Field(
        Money,
        description="The difference between the paid and the order total amount.",
        required=True,
    )
    user_email = graphene.String(
        required=False, description="Email address of the customer."
    )
    is_shipping_required = graphene.Boolean(
        description="Returns True, if order requires shipping.", required=True
    )

    streak_order = graphene.Boolean(description="boolean value if order was a streak order or not")

    class Meta:
        description = "Represents an order in the shop."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Order
        only_fields = [
            "billing_address",
            "created",
            "customer_note",
            "discount",
            "discount_name",
            "display_gross_prices",
            "gift_cards",
            "id",
            "language_code",
            "shipping_address",
            "shipping_method",
            "shipping_method_name",
            "shipping_price",
            "status",
            "token",
            "tracking_client_id",
            "translated_discount_name",
            "user",
            "voucher",
            "weight",
            "checkout_token"
        ]


    @staticmethod
    def resolve_billing_address(root: models.Order, info):
        requester = get_user_or_app_from_context(info.context)
        if requestor_has_access(requester, root.user, OrderPermissions.MANAGE_ORDERS):
            return root.billing_address
        return obfuscate_address(root.billing_address)

    @staticmethod
    def resolve_shipping_address(root: models.Order, info):
        requester = get_user_or_app_from_context(info.context)
        if requestor_has_access(requester, root.user, OrderPermissions.MANAGE_ORDERS):
            return root.shipping_address
        return obfuscate_address(root.shipping_address)

    @staticmethod
    def resolve_shipping_price(root: models.Order, _info):
        return root.shipping_price

    @staticmethod
    def resolve_actions(root: models.Order, _info):
        actions = []
        payment = root.get_last_payment()
        if root.can_capture(payment):
            actions.append(OrderAction.CAPTURE)
        if root.can_mark_as_paid():
            actions.append(OrderAction.MARK_AS_PAID)
        if root.can_refund(payment):
            actions.append(OrderAction.REFUND)
        if root.can_void(payment):
            actions.append(OrderAction.VOID)
        return actions

    @staticmethod
    def resolve_subtotal(root: models.Order, _info):
        
        if root.metadata.get('shopify') and root.metadata.get('zaamo_shopify_order_price'):

            total_price = zero_taxed_money()
            total = NumberUtilities.convert_string_to_decimal(root.metadata.get('zaamo_shopify_order_price'))
            total_price.net.amount = total
            total_price.gross.amount = total
            
            return total_price
        
        return root.get_subtotal()

    @staticmethod
    def resolve_total(root: models.Order, _info):
        return root.total
    
    def resolve_created(root: models.Order, _info):

        if root.created:
            return TimeUtilities.parse_date(root.created, date_format="%d %b %Y")
        return root.created
    
    def resolve_store(root: models.Order, _info):
        return root.order_store.first().store

    def resolve_streak_order(root: models.Order, _info):
        order_store = root.order_store.first()
        if order_store:
            return order_store.streak_order
        return None

    @staticmethod
    def resolve_total_authorized(root: models.Order, _info):
        # FIXME adjust to multiple payments in the future
        return root.total_authorized

    @staticmethod
    def resolve_total_captured(root: models.Order, _info):
        # FIXME adjust to multiple payments in the future
        return root.total_captured

    @staticmethod
    def resolve_total_balance(root: models.Order, _info):
        return root.total_balance

    @staticmethod
    def resolve_fulfillments(root: models.Order, info):
        user = info.context.user
        if user.is_staff:
            qs = root.fulfillments.all()
        else:
            qs = root.fulfillments.exclude(status=FulfillmentStatus.CANCELLATION_INITIATED)
        return qs.order_by("pk")

    @staticmethod
    def resolve_lines(root: models.Order, _info):

        return root.lines.all().order_by("pk")

    @staticmethod
    @permission_required(OrderPermissions.MANAGE_ORDERS)
    def resolve_events(root: models.Order, _info):
        return root.events.all().order_by("pk")

    @staticmethod
    def resolve_is_paid(root: models.Order, _info):
        return root.is_fully_paid()

    @staticmethod
    def resolve_number(root: models.Order, _info):
        return str(root.pk)

    @staticmethod
    def resolve_payment_status(root: models.Order, _info):
        return root.get_payment_status()

    @staticmethod
    def resolve_payment_status_display(root: models.Order, _info):
        return root.get_payment_status_display()

    @staticmethod
    def resolve_payments(root: models.Order, _info):
        return root.payments.all()

    @staticmethod
    def resolve_status_display(root: models.Order, _info):
        return root.get_status_display()

    @staticmethod
    def resolve_can_finalize(root: models.Order, _info):
        if root.status == OrderStatus.DRAFT:
            country = get_order_country(root)
            try:
                validate_draft_order(root, country)
            except ValidationError:
                return False
        return True

    @staticmethod
    def resolve_user_email(root: models.Order, info):
        requester = get_user_or_app_from_context(info.context)
        customer_email = root.get_customer_email()
        if requestor_has_access(requester, root.user, OrderPermissions.MANAGE_ORDERS):
            return customer_email
        return obfuscate_email(customer_email)

    @staticmethod
    def resolve_user(root: models.Order, info):
        requester = get_user_or_app_from_context(info.context)
        if requestor_has_access(requester, root.user, AccountPermissions.MANAGE_USERS):
            return root.user
        raise PermissionDenied()

    @staticmethod
    def resolve_available_shipping_methods(root: models.Order, _info):
        available = get_valid_shipping_methods_for_order(root)
        if available is None:
            return []

        manager = get_plugins_manager()
        display_gross = display_gross_prices()
        for shipping_method in available:
            # Ignore typing check because it is checked in
            # get_valid_shipping_methods_for_order
            taxed_price = manager.apply_taxes_to_shipping(
                shipping_method.price, root.shipping_address  # type: ignore
            )
            if display_gross:
                shipping_method.price = taxed_price.gross
            else:
                shipping_method.price = taxed_price.net
        return available

    @staticmethod
    def resolve_invoices(root: models.Order, info):
        requester = get_user_or_app_from_context(info.context)
        if requestor_has_access(requester, root.user, OrderPermissions.MANAGE_ORDERS):
            return root.invoices.all()
        raise PermissionDenied()

    @staticmethod
    def resolve_is_shipping_required(root: models.Order, _info):
        return root.is_shipping_required()

    @staticmethod
    def resolve_gift_cards(root: models.Order, _info):
        return root.gift_cards.all()

    @staticmethod
    @permission_required(OrderPermissions.MANAGE_ORDERS)
    def resolve_private_meta(root: models.Order, _info):
        return resolve_private_meta(root, _info)

    @staticmethod
    def resolve_meta(root: models.Order, _info):
        return resolve_meta(root, _info)


class MyOrder(Order):

    class Meta:
        description = "Represents an order in the shop."
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Order
        only_fields = [
            "billing_address",
            "created",
            "customer_note",
            "discount",
            "discount_name",
            "display_gross_prices",
            "gift_cards",
            "id",
            "language_code",
            "shipping_address",
            "shipping_method",
            "shipping_method_name",
            "shipping_price",
            "status",
            "token",
            "tracking_client_id",
            "translated_discount_name",
            "user",
            "voucher",
            "weight",
        ]
