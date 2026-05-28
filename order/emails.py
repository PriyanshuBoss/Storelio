import json
import math
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlencode
import graphene
import logging
from django.db.models.aggregates import Sum
from django.db.models import F, DecimalField
from templated_email import send_templated_mail
from saleor.utilities.dictionary_utilities import DictionaryUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from ..account.models import StaffNotificationRecipient, User
from ..celeryconf import app
from ..core.emails import get_email_context
from ..core.utils.url import prepare_url
from ..seo.schema.email import get_order_confirmation_markup
from . import events
from .models import Fulfillment, Order, OrderBrandFailure, OrderLine,OrderStore
from saleor.brand.models import Brand, BrandEmail
from saleor.product.models import BrandVariantZaamoMapping
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.utilities.string_utilities import StringUtilities
from saleor.brand.states import BrandEmailStateEnum

if TYPE_CHECKING:
    from decimal import Decimal

    from ..account.models import User  # noqa: F401

logger = logging.getLogger(__name__)

CONFIRM_ORDER_TEMPLATE = "order/confirm_order"
STAFF_CONFIRM_ORDER_TEMPLATE = "order/staff_confirm_order"
CONFIRM_FULFILLMENT_TEMPLATE = "order/confirm_fulfillment"
UPDATE_FULFILLMENT_TEMPLATE = "order/update_fulfillment"
CONFIRM_PAYMENT_TEMPLATE = "order/payment/confirm_payment"
ORDER_CANCEl_TEMPLATE = "order/order_cancel"
ORDER_REFUND_TEMPLATE = "order/order_refund"


def collect_staff_order_notification_data(
    order_pk: int, template: str, redirect_url: str
) -> dict:
    data = collect_data_for_email(order_pk, template, redirect_url)
    staff_notifications = StaffNotificationRecipient.objects.filter(
        active=True, user__is_active=True, user__is_staff=True
    )
    recipient_emails = [
        notification.get_email() for notification in staff_notifications
    ]
    data["recipient_list"] = recipient_emails
    return data


def collect_data_for_email(
    order_pk: int, template: str, redirect_url: str = ""
) -> dict:
    """Collect the required data for sending emails."""
    order = Order.objects.prefetch_related("lines__variant__product__images").get(
        pk=order_pk
    )
    recipient_email = order.get_customer_email()
    send_kwargs, email_context = get_email_context()

    email_context["order_details_url"] = (
        prepare_order_details_url(order, redirect_url) if redirect_url else ""
    )
    email_context["order"] = order

    # Order confirmation template requires additional information
    if template in [CONFIRM_ORDER_TEMPLATE, STAFF_CONFIRM_ORDER_TEMPLATE]:
        email_markup = get_order_confirmation_markup(order)
        email_context["schema_markup"] = email_markup

    return {
        "recipient_list": [recipient_email],
        "template_name": template,
        "context": email_context,
        **send_kwargs,
    }


def prepare_order_details_url(order: Order, redirect_url: str) -> str:
    params = urlencode({"token": order.token})
    return prepare_url(params, redirect_url)


def collect_data_for_fulfillment_email(order_pk, template, fulfillment_pk):
    fulfillment = Fulfillment.objects.get(pk=fulfillment_pk)
    email_data = collect_data_for_email(order_pk, template)
    lines = fulfillment.lines.all()
    physical_lines = [line for line in lines if not line.order_line.is_digital]
    digital_lines = [line for line in lines if line.order_line.is_digital]
    context = email_data["context"]
    context.update(
        {
            "fulfillment": fulfillment,
            "physical_lines": physical_lines,
            "digital_lines": digital_lines,
        }
    )
    return email_data


@app.task
def send_order_confirmation(order_pk, redirect_url, user_pk=None):
    """Send order confirmation email."""
    email_data = collect_data_for_email(order_pk, CONFIRM_ORDER_TEMPLATE, redirect_url)
    send_templated_mail(**email_data)
    events.email_sent_event(
        order=email_data["context"]["order"],
        user=None,
        user_pk=user_pk,
        email_type=events.OrderEventsEmails.ORDER_CONFIRMATION,
    )


@app.task
def send_staff_order_confirmation(order_pk, redirect_url):
    """Send order confirmation email."""
    staff_email_data = collect_staff_order_notification_data(
        order_pk, STAFF_CONFIRM_ORDER_TEMPLATE, redirect_url
    )
    if staff_email_data["recipient_list"]:
        send_templated_mail(**staff_email_data)


@app.task
def send_fulfillment_confirmation(order_pk, fulfillment_pk):
    email_data = collect_data_for_fulfillment_email(
        order_pk, CONFIRM_FULFILLMENT_TEMPLATE, fulfillment_pk
    )
    send_templated_mail(**email_data)


def send_fulfillment_confirmation_to_customer(order, fulfillment, user):
    # send_fulfillment_confirmation.delay(order.pk, fulfillment.pk)

    events.email_sent_event(
        order=order, user=user, email_type=events.OrderEventsEmails.FULFILLMENT
    )

    # If digital lines were sent in the fulfillment email,
    # trigger the event
    if any((line for line in order if line.variant.is_digital())):
        events.email_sent_event(
            order=order, user=user, email_type=events.OrderEventsEmails.DIGITAL_LINKS
        )


@app.task
def send_fulfillment_update(order_pk, fulfillment_pk):
    email_data = collect_data_for_fulfillment_email(
        order_pk, UPDATE_FULFILLMENT_TEMPLATE, fulfillment_pk
    )
    send_templated_mail(**email_data)


@app.task
def send_payment_confirmation(order_pk):
    """Send the payment confirmation email."""
    email_data = collect_data_for_email(order_pk, CONFIRM_PAYMENT_TEMPLATE)
    send_templated_mail(**email_data)


def send_order_canceled_confirmation(order: "Order", user: Optional["User"]):
    # send_order_canceled.delay(order.pk)
    events.email_sent_event(
        order=order, user=user, email_type=events.OrderEventsEmails.ORDER_CANCEL
    )


@app.task
def send_order_canceled(order_pk: int):
    """Send order cancel email."""
    email_data = collect_data_for_email(order_pk, ORDER_CANCEl_TEMPLATE)
    send_templated_mail(**email_data)


def send_order_refunded_confirmation(
    order: "Order", user: Optional["User"], amount: "Decimal", currency: str
):
    # send_order_refunded.delay(order.pk, amount, currency)
    events.email_sent_event(
        order=order, user=user, email_type=events.OrderEventsEmails.ORDER_REFUND
    )


@app.task
def send_order_refunded(order_pk: int, amount: "Decimal", currency: str):
    """Send order refund email."""
    email_data = collect_data_for_email(order_pk, ORDER_REFUND_TEMPLATE)
    context = email_data["context"]
    context.update({"amount": amount, "currency": currency})
    send_templated_mail(**email_data)

def get_order_pricing_info(order_instance):

    order_lines_sum = order_instance.lines.all().aggregate(total=Sum(F('quantity')*F('unit_price_gross_amount'), output_field = DecimalField())).get('total')
    order_info =  {
        'total_cart_value': StringUtilities.convert_number_to_string(math.ceil(NumberUtilities.convert_string_to_decimal(order_lines_sum))),
        'coupon_amount_applied': "",
        'total_spend': StringUtilities.convert_number_to_string(order_instance.total_net_amount),
        'coupon_code': "",
        'delivery_charges': StringUtilities.convert_number_to_string(order_instance.shipping_price_gross_amount)
        }

    voucher_instance = order_instance.voucher

    if voucher_instance:
        order_info['coupon_code'] = voucher_instance.code
        order_info['coupon_amount_applied']= StringUtilities.convert_number_to_string(order_instance.discount_amount)

    return order_info

def get_brand_shipping_details(brand_shipping_dict):
    brand_shipping_details = []
    for brand_id in brand_shipping_dict:
        brand_name = Brand.objects.filter(pk=brand_id).first().brand_name
        if brand_name=="thrift_brand":
            brand_name = "Thrift"
        data = {
        "brand_name":brand_name,
        "total_brand_shipping" : brand_shipping_dict[brand_id]
        }
        brand_shipping_details.append(data)

    return brand_shipping_details   

def _get_order_confirmation_context(order_id, mail_type, subject,brand_shipping_dict,cod_amount,prepaid_amount):
    try:
        order_instance = Order.objects.get(id = order_id)
    except:
        return {}
    
    items_list = order_instance.get_order_items_details()
    store_details =order_instance.get_order_store_details()
    shipping_address_details = order_instance.get_order_shipping_address()
    recipient_email = order_instance.get_customer_email()
    try:
        brand_shipping_details = get_brand_shipping_details(brand_shipping_dict)
    except Exception as e:
        brand_shipping_details = {}

    mail_type = mail_type
    template_data = {
            "subject": subject,
            "store": store_details,
            "my_orders_url": store_details.get('url','') + "/account/my-orders",
            "order": {
                "id": graphene.Node.to_global_id("Order", order_id),
                "items": items_list
            },
            "shipping_details": shipping_address_details,
            "brand_shippings":brand_shipping_details,
            "cod_amount":cod_amount,
            "amount_paid": prepaid_amount,
            "pay_at_delivery": "{0:.3f}".format(math.ceil(NumberUtilities.convert_string_to_decimal(order_instance.total_net_amount) - NumberUtilities.convert_string_to_decimal(prepaid_amount)))
        }
    
    logger.info("brand_shipping_dict : %s", brand_shipping_details)
    order_values = get_order_pricing_info(order_instance)
    template_data.update(order_values)
    return {'mail_type': mail_type, 'template_data': template_data, 'recipient_email': recipient_email}


def pre_process_item_list_with_brand(items_list):
    
    brand_email_context = {}
  
    for data in items_list:
        brand_email = data.get('brand_email')
        
        if not brand_email:
            continue
        
        if brand_email_context.get(brand_email): 
            brand_email_context[brand_email].get('items').append(data)
            prev_total_value =  brand_email_context[brand_email].get('total_value')
            new_total_value = prev_total_value + (NumberUtilities.convert_string_to_float(data.get('price')))
            brand_email_context[brand_email]['total_value'] = new_total_value
        
        else:
            
            brand_email_context[brand_email] = {
                'items': [data],
                'total_value': NumberUtilities.convert_string_to_float(data.get('price'))
            }
            

    return brand_email_context

def get_order_items_details_from_order_id(order_instance):
    order_lines = order_instance.lines.all()
        
    items_list = []
    
    for order_line in order_lines:
        image_url = order_instance.get_thumbnail_url(order_line)
        brand_variant_zaamo_mapping = BrandVariantZaamoMapping.objects.filter(variant_zaamo_id=order_line.variant_id)
        
        try:
            brand_instance = order_line.brand
            brand_id = brand_instance.id
            brand_name = brand_instance.brand_name
            brand_email = order_instance.get_primary_email(brand_instance)
            brand_product_id = brand_variant_zaamo_mapping[0].product_id_brand
            brand_variant_id = brand_variant_zaamo_mapping[0].variant_id_brand if brand_variant_zaamo_mapping[0].variant_id_brand  else  brand_variant_zaamo_mapping[0].sku_id_brand
            orders_not_allowed = brand_instance.private_metadata.get('orders_not_allowed')
            voucher_code = order_line.metadata.get('voucher_code')
        
        except Exception as e:
            brand_name = ""
            brand_email = ""
            brand_product_id = ""
            brand_variant_id = ""
            brand_id=""
            orders_not_allowed = None
            voucher_code = ""
            

        order_line_context = {
            "img": image_url,
            "brand_name": brand_name,
            "brand_id":brand_id,
            "product_name": order_line.product_name,
            "qty": order_line.quantity,
            "price": StringUtilities.convert_number_to_string(order_line.unit_price_gross_amount * order_line.quantity),
            "size": order_line.variant_name,
            "brand_email": brand_email,
            "brand_product_id": brand_product_id,
            "brand_variant_id": brand_variant_id,
            "orders_not_allowed": orders_not_allowed,
            "voucher_code": voucher_code,
            "is_cod":order_line.cod
        }
        items_list.append(order_line_context)

    return items_list

def _get_order_confirmation_context_for_brands(order_id, mail_type,brand_shipping_dict,brand_cod_charges):
    try:
        order_instance = Order.objects.get(id = order_id)
    except:
        return {}

    items_list = get_order_items_details_from_order_id(order_instance)
    segregated_brand_dict = pre_process_item_list_with_brand(items_list)
    shipping_address_details = order_instance.get_order_shipping_address()
    global_order_id = graphene.Node.to_global_id("Order", order_id)
    email_context_list = []

    for brand_email, order_line_items in segregated_brand_dict.items():

        if not order_line_items:
            continue
        
        try:
            brand_id = order_line_items.get('items')[0].get('brand_id')
            brand_id = StringUtilities.convert_number_to_string(brand_id)
            brand_name = order_line_items.get('items')[0].get('brand_name')
            primary_brand_emails_list = list(BrandEmail.objects.filter(brand_id_id=brand_id, state=BrandEmailStateEnum.PRIMARY).values_list('brand_email', flat=True))
            if brand_email in primary_brand_emails_list:
                primary_brand_emails_list.remove(brand_email)
            
            brand_shippings = {
                "brand_name":brand_name,
                "total_brand_shipping":brand_shipping_dict.get(brand_id)
            }
        except Exception as e:
            brand_shippings = {}

        if brand_cod_charges.get(brand_id):

            mail_subject = "(COD) New Order Received from ZAAMO"
            is_cod = True
            pay_at_delivery = "{0:.3f}".format(math.ceil(NumberUtilities.convert_string_to_float(order_line_items.get('total_value')) + NumberUtilities.convert_string_to_float(brand_cod_charges.get(brand_id))))
            amount_paid = 0
            
        
        else:
            
            mail_subject = "New Order Received from ZAAMO"
            is_cod = False
            amount_paid = "{0:.3f}".format(order_line_items.get('total_value'))
            pay_at_delivery = 0

        orders_not_allowed = order_line_items.get('items')[0].get('orders_not_allowed')
        voucher_code = order_line_items.get('items')[0].get('voucher_code')

        if voucher_code.startswith('SZ_') and orders_not_allowed==True:
            mail_subject = "Barter Order recieved from ZAAMO"
        
        template_data = {
                "subject": mail_subject,
                "order": {
                    "id": global_order_id,
                    "items": order_line_items.get('items'),
                    "shipping_details": shipping_address_details
                },
                "total_cart_value": StringUtilities.convert_number_to_string(order_line_items.get('total_value')),
                "brand_shippings":brand_shippings,
                "cod_amount": StringUtilities.convert_number_to_string(brand_cod_charges.get(brand_id,0)),
                "is_cod": is_cod,
                "amount_paid": amount_paid,
                "pay_at_delivery": pay_at_delivery
            }
            
        email_context = {
            'mail_type':mail_type,
            'template_data': template_data,
            'recipient_email': brand_email,
            'cc': primary_brand_emails_list
        }

        email_context_list.append(email_context)
        
    
    return email_context_list

def _get_thrift_order_confirmation_context_for_influencer(order_id,mail_type,brand_shipping_dict):
    try:
        order_instance = Order.objects.filter(id = order_id).first()
    except:
        return {}
    
    shipping_address_details = order_instance.get_order_shipping_address()
    order_lines = OrderLine.objects.filter(order_id=order_id)
    global_order_id = graphene.Node.to_global_id("Order", order_id)
    order_store_instance = OrderStore.objects.filter(order_id = order_id).first()
    try :
        influencer = order_store_instance.store.store_members.first()
        influencer_email = influencer.user.email
    except:
        logger.info("Unable to get influencer email for order_id : %s" , order_id)
    
    item_list = []
    total_cart_value = 0;
    brand_shippings = {}
    for orderline in order_lines:
        if orderline.brand.brand_name == "thrift_brand":
            brand_id = orderline.brand.id
            brand_id = StringUtilities.convert_number_to_string(brand_id)
            
            brand_shippings = {
                "brand_name":"Thrift",
                "total_brand_shipping":brand_shipping_dict.get(brand_id)
            }

            try:
                brand_name = orderline.variant.product.metadata.get("product_brand_name")
            except Exception as e:
                brand_name = "Thrift" 
            image_url = order_instance.get_thumbnail_url(orderline)
            total_cart_value += NumberUtilities.convert_string_to_float(orderline.unit_price_gross_amount)*orderline.quantity
            order_line_context = {
                    "img": image_url,
                    "brand_name": brand_name,
                    "product_name": orderline.product_name,
                    "qty": orderline.quantity,
                    "price": StringUtilities.convert_number_to_string(orderline.unit_price_gross_amount),
                    "size": orderline.variant_name,
                    "brand_email": ""
                }

            item_list.append(order_line_context)
       
    template_data = {
            "subject": "New Thrift Order Received from ZAAMO",
            "order": {
                "id": global_order_id,
                "items": item_list,
                "shipping_details": shipping_address_details,
            },
            "total_cart_value":total_cart_value,
            "brand_shippings":brand_shippings
            
        }
   
    return {'mail_type': mail_type, 'template_data': template_data, 'recipient_email': influencer_email}

def _get_order_confirmation_context_for_brand_staff(order_id, mail_type, subject, brand_staff_mail,brand_shippings):
    try:
        order_instance = Order.objects.get(id = order_id)
    except:
        return {}
    
    items_list = order_instance.get_order_items_details()
    store_details =order_instance. get_order_store_details()
    shipping_address_details = order_instance.get_order_shipping_address()
    recipient_email = brand_staff_mail

    mail_type = mail_type
    template_data = {
            "subject": subject,
            "store": store_details,
            "order": {
                "id": graphene.Node.to_global_id("Order", order_id),
                "items": items_list
            },
            "shipping_details": shipping_address_details,
            "brand_shippings":brand_shippings
        }

    order_values = get_order_pricing_info(order_instance)
    template_data.update(order_values)
    return {'mail_type': mail_type, 'template_data': template_data, 'recipient_email': recipient_email}

def _get_order_failure_context_for_complete_checkout(order_id,orderline_ids, response):

    data = {}

    if order_id:
        order_instance = Order.objects.filter(pk=order_id).first()
        orderlines = OrderLine.objects.filter(order_id = order_id, id__in=orderline_ids)
    
        order_data = {
            'order_id':order_instance.id,
            'created_at':StringUtilities.convert_object_to_string(order_instance.created),
            'order_price':StringUtilities.convert_object_to_string(order_instance.total_net_amount)
                      }
        orderlines_list = []
        for order_line in orderlines:
            orderline_dict = {
                'order_line_id':order_line.id,
                'product_name':order_line.product_name,
                'variant_name':order_line.variant.name,
                'product_id':order_line.variant.product_id,
                'variant_id':order_line.variant_id,
                'is_cod':order_line.cod
                              }
                
            if order_line.brand:
                brand_instance = order_line.brand
                brand_dict = {
                    'brand_id':brand_instance.id,
                    'brand_name':brand_instance.private_metadata.get('source_name',brand_instance.brand_name),
                    'brand_source':brand_instance.brand_source,
                    'brand_status':brand_instance.status,
                              }
            else:
                brand_dict={}

            orderline_dict["brand_details"] = brand_dict
            orderlines_list.append(orderline_dict)


        data["orderlines_details"] = orderlines_list

        data["order"] = order_data
        data["response"] = response.get('error')
        data = json.dumps(data, indent=4)
        
    return data


def save_failed_order_details(order_id,orderline_ids, response):
    order_lines = OrderLine.objects.filter(id__in=orderline_ids)
    for line in order_lines:
        OrderBrandFailure.objects.update_or_create(brand_id=line.brand_id,
                                    order_id=order_id,
                                    order_line_id=line.id,
                                    defaults={'error':response})

def remove_failed_order_details(orderline_ids):
    order_lines = OrderBrandFailure.objects.filter(order_line_id__in=orderline_ids).delete()


@app.task
def send_zaamo_order_confirmation(order_id,brand_shipping_dict,cod_amount,prepaid_amount):
    mail_type = "order_zaamo"
    subject = "A New Order Has Been Placed"
    params = _get_order_confirmation_context(order_id, mail_type, subject,brand_shipping_dict,cod_amount,prepaid_amount)
    MailImpl.send_mail(**params)


@app.task
def send_customer_order_confirmation(order_id,brand_shipping_dict,cod_amount,prepaid_amount):
    mail_type = "order_customer"
    subject = "Your Order is Confirmed"
    params = _get_order_confirmation_context(order_id, mail_type, subject,brand_shipping_dict,cod_amount,prepaid_amount)
    MailImpl.send_mail(**params)

@app.task
def send_order_confirmation_to_staff(order_id,brand_shipping_dict):
    brand_id_list_qs = OrderLine.objects.filter(order_id=order_id).select_related('brand').values('brand_id','brand__brand_name')
    for brand_id_qs in brand_id_list_qs:
        brand_instance = Brand.get_instance(brand_id_qs.get('brand_id'))
        brand_authorized_users = brand_instance.staff_members.all()
        mail_type = "order_staff"
        subject = "A New Order Has Been Placed"
        brand_id = brand_id_qs.get('brand_id')
        brand_id = StringUtilities.convert_number_to_string(brand_id)
        try:
            brand_shippings = {
                "brand_name":brand_id_qs.get('brand__brand_name'),
                "total_brand_shipping":brand_shipping_dict.get(brand_id)
            }
        except Exception as e:
            brand_shippings = {}

        for brand_authorized_user in brand_authorized_users:
            params = _get_order_confirmation_context_for_brand_staff(order_id, mail_type, subject, brand_authorized_user.email,brand_shippings)
            MailImpl.send_mail(**params)



@app.task
def send_brand_order_confirmation(order_id,brand_shipping_dict,brand_cod_charges):
    mail_type = "order_brand"
    email_context_list = _get_order_confirmation_context_for_brands(order_id, mail_type,brand_shipping_dict,brand_cod_charges)

    for data in email_context_list:
        MailImpl.send_mail(**data)

@app.task
def send_checkout_complete_order_mail(order_id,orderline_ids, response, mail_type):
    
    if mail_type == "order_failure":
        error = response.get('error')
        save_failed_order_details(order_id,orderline_ids, error)
        subject = "Order failed"
        recipient_list = ['priyanshu+order_failure@zaamo.co','nitanshub+order_failure@zaamo.co']
    else:
        subject = "Order success"
        remove_failed_order_details(orderline_ids)

        recipient_list = ['priyanshu+order_success@zaamo.co','nitanshub+order_success@zaamo.co']

    mail_text = _get_order_failure_context_for_complete_checkout(order_id,orderline_ids, response)
    
    for recipient in recipient_list:
        MailImpl.send_mail_without_template(mail_type,mail_text,subject,recipient)

@app.task
def send_order_confirmation_to_influencer_for_thirft(order_id,brand_shipping_dict):
    mail_type = "order_thrift"
    params = _get_thrift_order_confirmation_context_for_influencer(order_id,mail_type,brand_shipping_dict)
    MailImpl.send_mail(**params)

@app.task
def send_cashgram_creation_email(user_email,data):

    mail_type = "orderline_cashgram"
    subject = "Refund CashGram Created"

    MailImpl.send_mail_without_template(mail_type,data,subject,user_email,cc=['refundauth@zaamo.co'])
