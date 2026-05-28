from decimal import Decimal
from email.policy import default
from operator import attrgetter
from pyexpat import model
from re import match
from typing import Optional
from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import JSONField  # type: ignore
from django.db.models import F, Max, Sum
from django.utils.timezone import now
from django_measurement.models import MeasurementField
from django_prices.models import MoneyField, TaxedMoneyField
from measurement.measures import Weight
from prices import Money

from saleor.product.templatetags.product_images import get_product_image_thumbnail

from ..account.models import Address, User
from ..core.models import  ModelWithCreateTimestamp, ModelWithCreateUpdateTimestamp, ModelWithMetadata
from ..core.permissions import OrderPermissions
from ..core.taxes import zero_money, zero_taxed_money
from ..core.utils.json_serializer import CustomJsonEncoder
from ..core.weight import WeightUnits, zero_weight
from ..discount.models import Voucher
from ..giftcard.models import GiftCard
from ..payment import ChargeStatus, TransactionKind
from ..shipping.models import ShippingMethod
from . import FulfillmentStatus, OrderEvents, OrderStatus, RefundStatus
from saleor.store import models as store_models
from saleor.utilities.string_utilities import StringUtilities
from saleor.brand.models import Brand, BrandEmail
from saleor.brand.states import BrandEmailStateEnum
from saleor.utilities.request_utilities import PlatformTypeEnum

class OrderQueryset(models.QuerySet):
    def get_by_checkout_token(self, token):
        """Return non-draft order with matched checkout token."""
        return self.confirmed().filter(checkout_token=token).first()

    def confirmed(self):
        """Return non-draft orders."""
        return self.exclude(status=OrderStatus.DRAFT)

    def drafts(self):
        """Return draft orders."""
        return self.filter(status=OrderStatus.DRAFT)

    def ready_to_fulfill(self):
        """Return orders that can be fulfilled.

        Orders ready to fulfill are fully paid but unfulfilled (or partially
        fulfilled).
        """
        statuses = {OrderStatus.UNFULFILLED, OrderStatus.PARTIALLY_FULFILLED}
        qs = self.filter(status__in=statuses, payments__is_active=True)
        qs = qs.annotate(amount_paid=Sum("payments__captured_amount"))
        return qs.filter(total_gross_amount__lte=F("amount_paid"))

    def ready_to_capture(self):
        """Return orders with payments to capture.

        Orders ready to capture are those which are not draft or canceled and
        have a preauthorized payment. The preauthorized payment can not
        already be partially or fully captured.
        """
        qs = self.filter(
            payments__is_active=True, payments__charge_status=ChargeStatus.NOT_CHARGED
        )
        qs = qs.exclude(status={OrderStatus.DRAFT, OrderStatus.CANCELED})
        return qs.distinct()

    def store_orders(self, stores: list):
  
        return self.filter(order_store__store_id__in=stores).order_by("pk")

class Order(ModelWithMetadata):
    created = models.DateTimeField(default=now, editable=False)
    status = models.CharField(
        max_length=32, default=OrderStatus.UNFULFILLED, choices=OrderStatus.CHOICES
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        related_name="orders",
        on_delete=models.SET_NULL,
    )
    language_code = models.CharField(max_length=35, default=settings.LANGUAGE_CODE)
    tracking_client_id = models.CharField(max_length=36, blank=True, editable=False)
    billing_address = models.ForeignKey(
        Address, related_name="+", editable=False, null=True, on_delete=models.SET_NULL
    )
    shipping_address = models.ForeignKey(
        Address, related_name="+", editable=False, null=True, on_delete=models.SET_NULL
    )
    user_email = models.EmailField(blank=True, default="")

    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
        default=settings.DEFAULT_CURRENCY,
    )

    shipping_method = models.ForeignKey(
        ShippingMethod,
        blank=True,
        null=True,
        related_name="orders",
        on_delete=models.SET_NULL,
    )
    shipping_method_name = models.CharField(
        max_length=255, null=True, default=None, blank=True, editable=False
    )

    shipping_price_net_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
        editable=False,
    )
    shipping_price_net = MoneyField(
        amount_field="shipping_price_net_amount", currency_field="currency"
    )

    shipping_price_gross_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
        editable=False,
    )
    shipping_price_gross = MoneyField(
        amount_field="shipping_price_gross_amount", currency_field="currency"
    )

    shipping_price = TaxedMoneyField(
        net_amount_field="shipping_price_net_amount",
        gross_amount_field="shipping_price_gross_amount",
        currency_field="currency",
    )

    token = models.CharField(max_length=36, unique=True, blank=True)
    # Token of a checkout instance that this order was created from
    checkout_token = models.CharField(max_length=36, blank=True)

    total_net_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )
    total_net = MoneyField(amount_field="total_net_amount", currency_field="currency")

    total_gross_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )
    total_gross = MoneyField(
        amount_field="total_gross_amount", currency_field="currency"
    )

    total = TaxedMoneyField(
        net_amount_field="total_net_amount",
        gross_amount_field="total_gross_amount",
        currency_field="currency",
    )

    voucher = models.ForeignKey(
        Voucher, blank=True, null=True, related_name="+", on_delete=models.SET_NULL
    )
    gift_cards = models.ManyToManyField(GiftCard, blank=True, related_name="orders")
    discount_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )
    discount = MoneyField(amount_field="discount_amount", currency_field="currency")
    discount_name = models.CharField(max_length=255, blank=True, null=True)
    translated_discount_name = models.CharField(max_length=255, blank=True, null=True)
    display_gross_prices = models.BooleanField(default=True)
    customer_note = models.TextField(blank=True, default="")
    weight = MeasurementField(
        measurement=Weight, unit_choices=WeightUnits.CHOICES, default=zero_weight
    )

    platform_code = models.CharField(
        max_length=32, default=PlatformTypeEnum.INFLUENCER_STORE, choices=PlatformTypeEnum.CHOICES
    )
    app_code = models.CharField(max_length=50,default="")
    objects = OrderQueryset.as_manager()

    class Meta:
        ordering = ("-pk",)
        permissions = ((OrderPermissions.MANAGE_ORDERS.codename, "Manage orders."),)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = str(uuid4())
        return super().save(*args, **kwargs)

    def is_fully_paid(self):

        total_paid = self._total_paid()
        if self.metadata.get('prepaid_amount'):
            total_gross = Decimal(self.metadata.get('prepaid_amount'))
        
        else:
            total_gross = self.total.gross.amount

        return total_paid.gross.amount >= total_gross

    def is_partly_paid(self):
        total_paid = self._total_paid()
        return total_paid.gross.amount > 0

    def get_customer_email(self):
        return self.user.email if self.user and self.user.email else self.user_email

    def _total_paid(self):
        # Get total paid amount from partially charged,
        # fully charged and partially refunded payments
        payments = self.payments.filter(
            charge_status__in=[
                ChargeStatus.PARTIALLY_CHARGED,
                ChargeStatus.FULLY_CHARGED,
                ChargeStatus.PARTIALLY_REFUNDED,
            ]
        )
        total_captured = [payment.get_captured_amount() for payment in payments]
        total_paid = sum(total_captured, zero_taxed_money())
        return total_paid

    def _index_billing_phone(self):
        return self.billing_address.phone

    def _index_shipping_phone(self):
        return self.shipping_address.phone

    def __iter__(self):
        return iter(self.lines.all())

    def __repr__(self):
        return "<Order #%r>" % (self.id,)

    def __str__(self):
        return "#%d" % (self.id,)

    def get_last_payment(self):
        return max(self.payments.all(), default=None, key=attrgetter("pk"))

    def get_payment_status(self):
        last_payment = self.get_last_payment()
        if last_payment:
            return last_payment.charge_status
        return ChargeStatus.NOT_CHARGED

    def get_payment_status_display(self):
        last_payment = self.get_last_payment()
        if last_payment:
            return last_payment.get_charge_status_display()
        return dict(ChargeStatus.CHOICES).get(ChargeStatus.NOT_CHARGED)

    def is_pre_authorized(self):
        return (
            self.payments.filter(
                is_active=True,
                transactions__kind=TransactionKind.AUTH,
                transactions__action_required=False,
            )
            .filter(transactions__is_success=True)
            .exists()
        )

    def is_captured(self):
        return (
            self.payments.filter(
                is_active=True,
                transactions__kind=TransactionKind.CAPTURE,
                transactions__action_required=False,
            )
            .filter(transactions__is_success=True)
            .exists()
        )

    @property
    def quantity_fulfilled(self):
        return sum([line.quantity_fulfilled for line in self])

    def is_shipping_required(self):
        return any(line.is_shipping_required for line in self)

    def get_subtotal(self):
        subtotal_iterator = (line.get_total() for line in self)
        return sum(subtotal_iterator, zero_taxed_money())

    def get_total_quantity(self):
        return sum([line.quantity for line in self])

    def is_draft(self):
        return self.status == OrderStatus.DRAFT

    def is_open(self):
        statuses = {OrderStatus.UNFULFILLED, OrderStatus.PARTIALLY_FULFILLED}
        return self.status in statuses

    def can_cancel(self):
        return (
            not self.fulfillments.exclude(status__in=[FulfillmentStatus.CANCELLATION_INITIATED,FulfillmentStatus.CANCELLATION_PROCESSED]).exists()
        ) and self.status not in {OrderStatus.CANCELED, OrderStatus.DRAFT}

    def can_capture(self, payment=None):
        if not payment:
            payment = self.get_last_payment()
        if not payment:
            return False
        order_status_ok = self.status not in {OrderStatus.DRAFT, OrderStatus.CANCELED}
        return payment.can_capture() and order_status_ok

    def can_void(self, payment=None):
        if not payment:
            payment = self.get_last_payment()
        if not payment:
            return False
        return payment.can_void()

    def can_refund(self, payment=None):
        if not payment:
            payment = self.get_last_payment()
        if not payment:
            return False
        return payment.can_refund()

    def can_mark_as_paid(self):
        return len(self.payments.all()) == 0

    @property
    def total_authorized(self):
        payment = self.get_last_payment()
        if payment:
            return payment.get_authorized_amount()
        return zero_money()

    @property
    def total_captured(self):
        payment = self.get_last_payment()
        if payment and payment.charge_status in (
            ChargeStatus.PARTIALLY_CHARGED,
            ChargeStatus.FULLY_CHARGED,
            ChargeStatus.PARTIALLY_REFUNDED,
        ):
            return Money(payment.captured_amount, payment.currency)
        return zero_money()

    @property
    def total_balance(self):
        return self.total_captured - self.total.gross

    def get_total_weight(self):
        return self.weight

    def get_order_items_details(self):
        order_lines = self.lines.all()
        
        items_list = []
        for order_line in order_lines:
            image_url = self.get_thumbnail_url(order_line)
            
            try:
                brand_instance = order_line.variant.product.brand
                brand_name = brand_instance.brand_name
                if brand_name=="thrift_brand":
                    brand_name = order_line.variant.product.metadata.get("product_brand_name")
                brand_email = self.get_primary_email(brand_instance)
            
            except Exception as e:
                brand_name = ""
                brand_email = ""
                

            order_line_context = {
                "img": image_url,
                "brand_name": brand_name,
                "product_name": order_line.product_name,
                "qty": order_line.quantity,
                "price": StringUtilities.convert_number_to_string(order_line.unit_price_gross_amount * order_line.quantity),
                "size": order_line.variant_name,
                "brand_email": brand_email,
                "is_cod": order_line.cod
            }
            items_list.append(order_line_context)
        return items_list


    def get_thumbnail_url(self,order_line):
        url = ""
        try:
            product_image = order_line.variant.product.get_first_image()
            product_thumbnail = get_product_image_thumbnail(product_image, 1080, method="thumbnail")
            url = product_thumbnail
        except Exception as e:
            url = ""
        
        return url

    def get_primary_email(self,brand_instance):
        brand_email=""
        brand_filter = BrandEmail.objects.filter(brand_id=brand_instance,state=BrandEmailStateEnum.PRIMARY)
        brand_filter_secondary = BrandEmail.objects.filter(brand_id=brand_instance,state=BrandEmailStateEnum.SECONDARY)
        if brand_filter.exists():
            brand_email_instance = brand_filter.first()
            brand_email = brand_email_instance.brand_email
        elif brand_filter_secondary.exists():
            brand_email_instance = brand_filter_secondary.first()
            brand_email = brand_email_instance.brand_email
            
        return brand_email

    def get_order_store_details(self):
        order_store = self.order_store.all()
        store_instance = order_store.first().store

        store_details = {
                "name": store_instance.store_name,
                "url": store_instance.store_url,
                "collection_url": store_instance.store_url,
                "products_url": store_instance.store_url + '/products',
                "support_url": store_instance.store_url + '/support'
            }
        return store_details


    def get_order_shipping_address(self):
        order_shipping_address = self.shipping_address
        shipping_address_details = {
                "name": order_shipping_address.first_name + ' ' + order_shipping_address.last_name,
                "address": order_shipping_address.street_address_1 + ' ' + order_shipping_address.street_address_2 + ' ' +  order_shipping_address.city,
                "phone": StringUtilities.convert_number_to_string(order_shipping_address.phone.national_number),
                'pincode': order_shipping_address.postal_code,
                "state": order_shipping_address.country_area,
                "email": self.get_customer_email(),
            }
        return shipping_address_details


class OrderLineQueryset(models.QuerySet):
    def digital(self):
        """Return lines with digital products."""
        for line in self.all():
            if line.is_digital:
                yield line

    def physical(self):
        """Return lines with physical products."""
        for line in self.all():
            if not line.is_digital:
                yield line
            
    def brand_order_lines(self, brand_id, qs=None):

        if isinstance(brand_id, list):
            
            if not qs:
                qs = self.all()

            return qs.filter(brand__in=brand_id)

            
        
        if qs:
            returned_qs = qs.filter(brand=brand_id)
        else:
            returned_qs = self.filter(brand=brand_id)
    
        return returned_qs  


class OrderLine(ModelWithCreateTimestamp, ModelWithMetadata):
    order = models.ForeignKey(
        Order, related_name="lines", editable=False, on_delete=models.CASCADE
    )
    variant = models.ForeignKey(
        "product.ProductVariant",
        related_name="order_lines",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    brand = models.ForeignKey("brand.Brand", 
    related_name="order_lines",
    on_delete=models.SET_NULL,
    blank=True,
    null=True)

    commission_percentage = models.FloatField(default=0.0)

    # max_length is as produced by ProductVariant's display_product method
    product_name = models.CharField(max_length=386)
    variant_name = models.CharField(max_length=255, default="", blank=True)
    translated_product_name = models.CharField(max_length=386, default="", blank=True)
    translated_variant_name = models.CharField(max_length=255, default="", blank=True)
    product_sku = models.CharField(max_length=255)
    is_shipping_required = models.BooleanField()
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    quantity_fulfilled = models.IntegerField(
        validators=[MinValueValidator(0)], default=0
    )

    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
        default=settings.DEFAULT_CURRENCY,
    )
    shipping_cost_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0
    )
    unit_price_net_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES
    )
    unit_price_net = MoneyField(
        amount_field="unit_price_net_amount", currency_field="currency"
    )

    unit_price_gross_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
    )
    unit_price_gross = MoneyField(
        amount_field="unit_price_gross_amount", currency_field="currency"
    )

    unit_price = TaxedMoneyField(
        net_amount_field="unit_price_net_amount",
        gross_amount_field="unit_price_gross_amount",
        currency="currency",
    )

    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.0")
    )

    cod = models.BooleanField(default=False)

    objects = OrderLineQueryset.as_manager()

    class Meta:
        ordering = ("pk",)

    def __str__(self):
        return (
            f"{self.product_name} ({self.variant_name})"
            if self.variant_name
            else self.product_name
        )

    def get_total(self):
        return self.unit_price * self.quantity

    @property
    def quantity_unfulfilled(self):
        return self.quantity - self.quantity_fulfilled

    @property
    def is_digital(self) -> Optional[bool]:
        """Check if a variant is digital and contains digital content."""
        if not self.variant:
            return None
        is_digital = self.variant.is_digital()
        has_digital = hasattr(self.variant, "digital_content")
        return is_digital and has_digital

    def influencer_earning(self):

        commission_percent = 0
        commission = self.variant.product.brand.commission.first()
        if commission:
            commission_percent = commission.commission_percentage
        total = self.unit_price_gross_amount * self.quantity
        earning = total*Decimal(commission_percent)/100

        return earning      

def get_fulfillment_default_user():

    user = User.objects.filter(email='admin@admin.com').first()
    if user:
        user_id=user.id
    else:
         user_id=None
    return user_id


class Fulfillment(ModelWithMetadata):
    fulfillment_order = models.PositiveIntegerField(editable=False)
    order = models.ForeignKey(
        Order, related_name="fulfillments", editable=False, on_delete=models.CASCADE
    )
    status = models.CharField(
        max_length=32,
        default=FulfillmentStatus.FULFILLED,
        choices=FulfillmentStatus.CHOICES,
    )
    tracking_number = models.CharField(max_length=255, default="", blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL,
        default=get_fulfillment_default_user,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='updated_fulfillments'
        )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
        default=get_fulfillment_default_user,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='created_fulfillments'
        )

    class Meta:
        ordering = ("pk",)

    def __str__(self):
        return f"Fulfillment #{self.composed_id}"

    def __iter__(self):
        return iter(self.lines.all())

    def save(self, *args, **kwargs):
        """Assign an auto incremented value as a fulfillment order."""
        if not self.pk:
            groups = self.order.fulfillments.all()
            existing_max = groups.aggregate(Max("fulfillment_order"))
            existing_max = existing_max.get("fulfillment_order__max")
            self.fulfillment_order = existing_max + 1 if existing_max is not None else 1
        return super().save(*args, **kwargs)

    @property
    def composed_id(self):
        return "%s-%s" % (self.order.id, self.fulfillment_order)

    def can_edit(self):
        return self.status != FulfillmentStatus.CANCELLATION_PROCESSED and self.status != FulfillmentStatus.CANCELLED_BY_CUSTOMER

    def get_total_quantity(self):
        return sum([line.quantity for line in self])
    
    @property
    def is_tracking_number_url(self):
        return bool(match(r"^[-\w]+://", self.tracking_number))
    
    def brand_fulfillment_lines(self, brand_id):
    
        if isinstance(brand_id, (list, models.QuerySet)):
            return self.lines.select_related("order_line", "order_line__brand").filter(order_line__brand__in=brand_id)

        return self.lines.select_related("order_line", "order_line__brand").filter(order_line__brand=brand_id)


class FullfillmentLineQueryset(models.QuerySet):
            
    def brand_fulfullment_lines(self, brand_id):
        return self.all().select_related("order_line", "order_line__variant__product").filter(order_line__variant__product__brand=brand_id)


class FulfillmentLine(ModelWithCreateUpdateTimestamp):
    order_line = models.ForeignKey(
        OrderLine, related_name="fulfillment_line", on_delete=models.CASCADE
    )
    fulfillment = models.ForeignKey(
        Fulfillment, related_name="lines", on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField()
    stock = models.ForeignKey(
        "warehouse.Stock",
        related_name="fulfillment_lines",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    note = models.TextField(blank=True)
    note_creator = models.ForeignKey(User, related_name="fulfillment_notes", on_delete=models.SET_NULL, blank=True, null=True)

    objects = FullfillmentLineQueryset.as_manager()

class OrderEvent(models.Model):
    """Model used to store events that happened during the order lifecycle.

    Args:
        parameters: Values needed to display the event on the storefront
        type: Type of an order

    """

    date = models.DateTimeField(default=now, editable=False)
    type = models.CharField(
        max_length=255,
        choices=[
            (type_name.upper(), type_name) for type_name, _ in OrderEvents.CHOICES
        ],
    )
    order = models.ForeignKey(Order, related_name="events", on_delete=models.CASCADE)
    parameters = JSONField(blank=True, default=dict, encoder=CustomJsonEncoder)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ("date",)

    def __repr__(self):
        return f"{self.__class__.__name__}(type={self.type!r}, user={self.user!r})"


class OrderStore(ModelWithCreateTimestamp):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name ='order_store')
    store = models.ForeignKey(store_models.StoreInfo, on_delete=models.CASCADE, related_name ='order_store')
    streak_order = models.BooleanField(default=False)
    
    @staticmethod
    def create_instance(info):

        if OrderStore.is_order_store_exists(info.get('order_instance'), info.get('store_instance')):
            return
            
        instance = OrderStore()
        instance.order = info.get('order_instance')
        instance.store = info.get('store_instance')
        instance.streak_order = info.get('streak_order', False)
        instance.save()

    @staticmethod
    def is_order_store_exists(order_instance, store_instance):
        
        return OrderStore.objects.filter(order=order_instance, store=store_instance).exists()


class ShippingFulfillment(models.Model):
    shipping_id = models.CharField(max_length=100)
    shipping_provider = models.CharField(max_length=100, null=True)
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.shipping_id} {self.shipping_provider}"

class OrderBrandZaamoMapping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    order_id_brand = models.CharField(max_length=255, blank=True, null=True)
    order_zaamo = models.ForeignKey(Order, on_delete=models.CASCADE,related_name='order_zaamo')
    order_line_zaamo = models.ForeignKey(OrderLine, on_delete=models.CASCADE,related_name='order_line_zaamo')

    def save(self, *args, **kwargs):
        super(self.__class__, self).save(*args, **kwargs)


class OrderBrandFailure(ModelWithCreateUpdateTimestamp):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    order_line = models.ForeignKey(OrderLine, on_delete=models.CASCADE)
    error = models.TextField(default="")

    def save(self, *args, **kwargs):
        super(self.__class__, self).save(*args, **kwargs)

class OrderLineCashgram(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    orderline = models.ForeignKey(OrderLine, on_delete=models.CASCADE,related_name ='orderline_cashgram')
    refund_by_user = models.ForeignKey(User,on_delete=models.CASCADE,related_name = 'orderline_cashgram',null=True,blank=True)
    cashgram_id = models.CharField(max_length=50,null=True)
    reference_id = models.CharField(max_length=50,null=True)
    cashgram_link = models.CharField(max_length=2048,null=True)
    refund_amount = models.CharField(max_length=15,null=True)
    refund_status = models.CharField(
                max_length=50,
                default=RefundStatus.REFUND_INITIATED,
                choices=RefundStatus.CHOICES,
            )
