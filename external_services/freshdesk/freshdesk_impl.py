import datetime
import time
import graphene
from saleor.order import FulfillmentStatus
from saleor.order.models import FulfillmentLine, Order, OrderLine
from saleor.support.models import FreshDeskTickets, TicketTypeEnum
from saleor.utilities.string_utilities import StringUtilities
from .constants import CREATE_TICKET_URI,CREATE_TICKET_HEADER
from saleor.utilities.time_utilities import TimeUtilities
from django.conf import settings
from django.db.models import Sum, F, ExpressionWrapper,Subquery,Q,Case, When
from saleor.utilities.number_utilities import NumberUtilities
from django.db import models
from saleor.checkout import calculations
from saleor.support.models import FreshDeskTickets, TicketTypeEnum
from saleor.checkout.models import Checkout
from saleor.utilities.api_client import ApiClient
import logging
logger = logging.getLogger(__name__)


def create_freshdesk_ticket_for_initiate_purchases():
    yesterday_date_time = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),days=1)
    past_180_days_date = TimeUtilities.get_n_days_before_date(180)
    
    checkout_limit = NumberUtilities.convert_string_to_number(settings.FRESHDESK_CHECKOUT_TICEKT_LIMIT)
    checkouts = Checkout.objects.filter(last_change__gte=yesterday_date_time,user_id__isnull=False,billing_address_id__isnull=False,lines__isnull=False)\
        .exclude(user__mobile_no__in=Subquery(FreshDeskTickets.objects.filter(created_at__gte=past_180_days_date,ticket_type=TicketTypeEnum.INITIATE_PURCHASE)\
                .values('mobile_no'))).prefetch_related('lines','lines__variant','lines__variant__product','checkoutstore','checkoutstore__store').select_related('billing_address','user')\
                .annotate(cart_amount=Sum(ExpressionWrapper(F('lines__variant__price_amount') * F('lines__quantity'), output_field=models.DecimalField()),output_field=models.DecimalField()))\
                  .order_by('-cart_amount')[:checkout_limit]
    
    tickets_created = []

    count = 0
    for checkout in checkouts:

        try:
            count+=1

            if count>10:

                time.sleep(20)
                count=0

            customer_name = f"{checkout.billing_address.first_name} {checkout.billing_address.last_name}"
            mobile_no = checkout.user.mobile_no
            customer_address = f"{checkout.billing_address.street_address_1}, {checkout.billing_address.city}, {checkout.billing_address.city_area} - {checkout.billing_address.postal_code}"
            products = []

            for line in checkout.lines.all():
                detail = {'\n\n&ensp;&ensp;&ensp;&ensp;<b>product_name</b>':line.variant.product.name, 
                        '&ensp;&ensp;&ensp;&ensp;<b>brand</b>':line.variant.product.brand.brand_name, 
                        '&ensp;&ensp;&ensp;&ensp;<b>price</b>': StringUtilities.convert_object_to_string(line.variant.price_amount), 
                        '&ensp;&ensp;&ensp;&ensp;<b>quantity</b>': StringUtilities.convert_object_to_string(line.quantity)}
                
                products.append(StringUtilities.convert_object_to_line_seperated_string(detail))

            total_cart_value = calculations.checkout_total(
                                        checkout=checkout, lines=checkout.lines.all()).net.amount
            
            store_name = ''
            store_url = ''
            checkoutstore = checkout.checkoutstore.first()

            if checkoutstore:
                store_name = checkoutstore.store.store_name
                store_url = checkoutstore.store.store_url

            created_at = checkout.created
            checkout_global_id = graphene.Node.to_global_id('Checkout',checkout.token)
            info = {
                '<b>checkout_token</b>':StringUtilities.convert_object_to_string(checkout.token),
                '<b>customer_name</b>': customer_name,
                '<b>mobile_no</b>': mobile_no,
                '<b>customer_email</b>': checkout.email,
                '<b>customer_address</b>': customer_address,
                '<b>total_cart_value</b>': StringUtilities.convert_object_to_string(total_cart_value),
                '<b>store_name</b>':store_name,
                '<b>store_url</b>':store_url,
                '<b>created_at</b>':StringUtilities.convert_object_to_string(created_at),
                '<b>products</b>': '\n'.join(products)
            }
            query = {
                    'subject': f'Initiate purchase. checkout_id: {checkout_global_id}',
                    'email':'care@zaamo.co',
                    'message': StringUtilities.convert_object_to_line_seperated_string(info).replace('\n','<br>')
                }
            query['tags'] = [TicketTypeEnum.INITIATE_PURCHASE]
            
            response = create_ticket_freshdesk(query)
            if response:
                ticket = FreshDeskTickets()
                ticket.mobile_no = mobile_no
                ticket.ticket_id = response.get('id')
                ticket.message = query['message']
                ticket.subject = query['subject']
                ticket.ticket_type = TicketTypeEnum.INITIATE_PURCHASE

                tickets_created.append(ticket)

        except Exception as e:
            logger.exception(e)

    FreshDeskTickets.objects.bulk_create(tickets_created)

def create_freshdesk_ticket_for_top_order_users():
    yesterday_date_time = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),days=7)
    past_180_days_date = TimeUtilities.get_n_days_before_date(180)
    
    ticket_limit = NumberUtilities.convert_string_to_number(settings.FRESHDESK_ORDER_TICEKT_LIMIT)
    orders = Order.objects.filter(created__gte=yesterday_date_time,user_id__isnull=False,billing_address_id__isnull=False)\
        .exclude(Q(user__mobile_no__in=Subquery(FreshDeskTickets.objects.filter(
        created_at__gte=past_180_days_date,ticket_type=TicketTypeEnum.TOP_ORDER).values('mobile_no'))) | 
        Q(discount_name__startswith='SZ'))\
        .prefetch_related('lines','order_store','order_store__store').select_related('billing_address','user')\
                  .order_by('-total_net_amount')[:ticket_limit]
    
    tickets_created = []
    
    count = 0
    for order in orders:

        try:
            count+=1

            if count>10:

                time.sleep(20)
                count=0

            mobile_no = order.user.mobile_no
            query = map_order_to_freshdesk_query_obj(order,subject='Top Orders')
            query['tags'] = [TicketTypeEnum.TOP_ORDER]

            response = create_ticket_freshdesk(query)

            if response:
                ticket = FreshDeskTickets()
                ticket.mobile_no = mobile_no
                ticket.ticket_id = response.get('id')
                ticket.message = query['message']
                ticket.subject = query['subject']
                ticket.ticket_type = TicketTypeEnum.TOP_ORDER

                tickets_created.append(ticket)
            
        except Exception as e:
            logger.exception(e)

    FreshDeskTickets.objects.bulk_create(tickets_created)

def create_fresh_desk_order_ticket(fulfillmentline_id,note):

    fulfillmentline_instance = FulfillmentLine.objects.filter(id=fulfillmentline_id).first()

    if not fulfillmentline_instance:
        return None, None

    orderline_instance = fulfillmentline_instance.order_line
    order_id = orderline_instance.order_id

    product_name = orderline_instance.product_name
    subject = product_name + " | Customer Note | Order"

    
    
    orders = Order.objects.filter(id=order_id,user_id__isnull=False,billing_address_id__isnull=False).prefetch_related('lines','order_store','order_store__store').select_related('billing_address','user')\
                  .order_by('-total_net_amount')
    
    if not orders:
        return None,None
    
    order = orders.first()

    try:

        mobile_no = order.user.mobile_no
        query = map_order_to_freshdesk_query_obj(order,subject=subject,note=note)
        query['tags'] = [TicketTypeEnum.ORDER]

        response = create_ticket_freshdesk(query)
        query['message'] = query['message'].replace(product_name,f"<b>{product_name}</b>")

        if response:
            ticket = FreshDeskTickets()
            ticket.mobile_no = mobile_no
            ticket.ticket_id = response.get('id')
            ticket.message = query['message']
            ticket.subject = query['subject']
            ticket.ticket_type = TicketTypeEnum.ORDER
            ticket.save()

            return order,ticket
        
    except Exception as e:
        logger.exception(e)

    return order,None

def create_ticket_freshdesk(query_body):

    create_body = {
        'description':query_body.get('message'),
        'subject':query_body.get('subject'),
        'email':query_body.get('email'),
        'tags':query_body.get('tags',[]),
        'priority':1,
        'status':2,
        'custom_fields':query_body.get('info',{})
    }

    api_url = CREATE_TICKET_URI
    api_client = ApiClient(url=api_url)
    api_client.headers = CREATE_TICKET_HEADER
    api_client.body = create_body
    api_client.post()
    api_response = api_client.fetch_response()
    if api_response:
        return api_response


def update_ticket_freshdesk(create_body,ticket_id):

    api_url = CREATE_TICKET_URI
    api_client = ApiClient(url=f"{api_url}/{ticket_id}")
    api_client.headers = CREATE_TICKET_HEADER
    api_client.body = create_body
    api_client.put()
    api_response = api_client.fetch_response()
    if api_response:
        return api_response
    
def map_order_to_freshdesk_query_obj(order,subject,note=None):
    
    customer_name = f"{order.billing_address.first_name} {order.billing_address.last_name}"
    mobile_no = order.user.mobile_no
    customer_address = f"{order.billing_address.street_address_1}, {order.billing_address.city}, {order.billing_address.city_area} - {order.billing_address.postal_code}"
    products = []

    for line in order.lines.all():
        orderbrandzaamomapping = line.order_line_zaamo.first()
        shopify_url = ''
        tracking_url = ''

        if orderbrandzaamomapping:
            shopify_url = orderbrandzaamomapping.metadata.get('shopify_url')
            tracking_url = orderbrandzaamomapping.metadata.get('tracking_url')

        detail = {'\n\n&ensp;&ensp;&ensp;&ensp;<b>product_name</b>':line.product_name, 
                '&ensp;&ensp;&ensp;&ensp;<b>brand</b>':line.brand.brand_name, 
                '&ensp;&ensp;&ensp;&ensp;<b>price</b>': StringUtilities.convert_object_to_string(line.unit_price_net_amount), 
                '&ensp;&ensp;&ensp;&ensp;<b>shopify_order_url</b>': StringUtilities.convert_object_to_string(shopify_url), 
                '&ensp;&ensp;&ensp;&ensp;<b>tracking_url</b>': StringUtilities.convert_object_to_string(tracking_url),
                '&ensp;&ensp;&ensp;&ensp;<b>quantity</b>': StringUtilities.convert_object_to_string(line.quantity)}
        
        products.append(StringUtilities.convert_object_to_line_seperated_string(detail))

    total_cart_value = order.total_net_amount
    
    store_name = ''
    store_url = ''
    orderstore = order.order_store.first()

    if orderstore:
        store_name = orderstore.store.store_name
        store_url = orderstore.store.store_url

    created_at = order.created
    order_global_id = graphene.Node.to_global_id('Order',order.id)
    info = {
        '<b>order_id</b>':StringUtilities.convert_object_to_string(order.id),
        '<b>customer_name</b>': customer_name,
        '<b>mobile_no</b>': mobile_no,
        '<b>customer_email</b>': order.user_email,
        '<b>customer_address</b>': customer_address,
        '<b>total_cart_value</b>': StringUtilities.convert_object_to_string(total_cart_value),
        '<b>store_name</b>':store_name,
        '<b>store_url</b>':store_url,
        '<b>created_at</b>':StringUtilities.convert_object_to_string(created_at),
        '<b>products</b>': '\n'.join(products)
    }

    if note:
        info['<b>note</b>'] = note

    query = {
            'subject': f'{subject} | order_id: {order_global_id}',
            'email':'care@zaamo.co',
            'message': StringUtilities.convert_object_to_line_seperated_string(info).replace('\n','<br>')
        }
    
    return query
    
def map_order_line_to_freshdesk_query_obj(order_line,subject,note=None):
    billing_address = order_line.order.billing_address
    order = order_line.order
    customer_name = f"{billing_address.first_name} {billing_address.last_name}"
    mobile_no = order.user.mobile_no
    customer_address = f"{billing_address.street_address_1}, {billing_address.city}, {billing_address.city_area} - {billing_address.postal_code}"
    products = []
    orderbrandzaamomapping = order_line.order_line_zaamo.first()
    shopify_url = ''
    tracking_url = ''

    if orderbrandzaamomapping:
        shopify_url = orderbrandzaamomapping.metadata.get('shopify_url')
        tracking_url = orderbrandzaamomapping.metadata.get('tracking_url')

    detail = {'\n\n&ensp;&ensp;&ensp;&ensp;<b>product_name</b>':order_line.product_name, 
            '&ensp;&ensp;&ensp;&ensp;<b>brand</b>':order_line.brand.brand_name, 
            '&ensp;&ensp;&ensp;&ensp;<b>price</b>': StringUtilities.convert_object_to_string(order_line.unit_price_net_amount), 
            '&ensp;&ensp;&ensp;&ensp;<b>shopify_order_url</b>': StringUtilities.convert_object_to_string(shopify_url), 
            '&ensp;&ensp;&ensp;&ensp;<b>tracking_url</b>': StringUtilities.convert_object_to_string(tracking_url), 
            '&ensp;&ensp;&ensp;&ensp;<b>quantity</b>': StringUtilities.convert_object_to_string(order_line.quantity)}
    
    products.append(StringUtilities.convert_object_to_line_seperated_string(detail))

    total_cart_value = order.total_net_amount
    
    store_name = ''
    store_url = ''
    orderstore = order.order_store.first()

    if orderstore:
        store_name = orderstore.store.store_name
        store_url = orderstore.store.store_url

    created_at = order.created
    order_global_id = graphene.Node.to_global_id('Order',order.id)
    info = {
        '<b>order_id</b>':StringUtilities.convert_object_to_string(order.id),
        '<b>customer_name</b>': customer_name,
        '<b>mobile_no</b>': mobile_no,
        '<b>customer_email</b>': order.user_email,
        '<b>customer_address</b>': customer_address,
        '<b>order_status</b>': order_line.metadata.get('status'),
        '<b>order_status_last_updated_At</b>': order_line.fulfillment_last_updated,
        '<b>total_cart_value</b>': StringUtilities.convert_object_to_string(total_cart_value),
        '<b>store_name</b>':store_name,
        '<b>store_url</b>':store_url,
        '<b>created_at</b>':StringUtilities.convert_object_to_string(created_at),
        '<b>product</b>': '\n'.join(products)
    }

    if note:
        info['<b>note</b>'] = note

    query = {
            'subject': f'{subject} | Product Name: {order_line.product_name} | OrderLineID: {order_line.id} | OrderId: {order_global_id}',
            'email':'care@zaamo.co',
            'message': StringUtilities.convert_object_to_line_seperated_string(info).replace('\n','<br>')
        }
    
    return query

def create_fresh_desk_order_ticket_cod_order(order_id,note=None):

    orders = Order.objects.filter(id=order_id,user_id__isnull=False,billing_address_id__isnull=False).prefetch_related('lines','order_store','order_store__store').select_related('billing_address','user')\
                  .order_by('-total_net_amount')
    
    if not orders:
        return None,None
    
    order = orders.first()
    is_cod = False
    lines = order.lines.all()

    for line in lines:
        if line.cod:
            is_cod=True
            break

    if not is_cod:
        return
    
    for line in lines:
        
        orderline_instance = line
        
        product_name = orderline_instance.product_name
        subject = f"COD | {product_name} | Order"
        brand_name_src = orderline_instance.brand.private_metadata.get('source_name')

        if not brand_name_src in ['OUTCAST','Aahwan','GPLT','Emmera Official']: # COD tickets only from GPLT, Outcast and Aahwan brand
            continue

        try:

            mobile_no = order.user.mobile_no
            query = map_order_to_freshdesk_query_obj(order,subject=subject,note=note)
            query['message'] = query['message'].replace(product_name,f"<b>{product_name}</b>")
            query['tags'] = [TicketTypeEnum.COD_ORDER]
            response = create_ticket_freshdesk(query)

            if response:
                ticket = FreshDeskTickets()
                ticket.mobile_no = mobile_no
                ticket.ticket_id = response.get('id')
                ticket.message = query['message']
                ticket.subject = query['subject']
                ticket.ticket_type = TicketTypeEnum.COD_ORDER
                ticket.save()

                return order,ticket
            
        except Exception as e:
            logger.exception(e)

    return order,None

def update_tags_in_freshdesk_tickets(day=1):
    
    yesterdays_date = TimeUtilities.get_n_days_before_date(day)
    page=0
    api_url = CREATE_TICKET_URI
    orders = Order.objects.all().values('id','platform_code')
    order_id_platform_code_dict = {order.get('id'):order.get('platform_code') for order in orders}

    while True:
        
        try:
            page+=1
            if page>300:
                break
            if page%10==0:
                time.sleep(20)
            api_client = ApiClient(url=f"{api_url}?updated_since={yesterdays_date}&page={page}")
            api_client.headers = CREATE_TICKET_HEADER
            api_client.get()
            api_response = api_client.fetch_response() or []
            
            for ticket in api_response:
                to_update = False
                ticket_id = ticket.get('id')
                group_id = ticket.get('group_id')
                tags = ticket.get('tags',[])
                subject = ticket.get('subject')

                order_id = subject.split(' ')[-1]

                if 'cod_order' in tags:
                    continue
                
                try: 
                    order_id = NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(order_id)[1])
                except: 
                    logger.info(f'order_id not decodable for ticket id :: {ticket_id}')
                    
                if order_id_platform_code_dict.get(order_id,'') =='IH':
                    if not 'influencer_query' in tags:
                        tags.append('influencer_query')
                        to_update = True

                elif order_id_platform_code_dict.get(order_id,'') =='IS' or StringUtilities.convert_object_to_string(group_id)=='84000215184':
                    if not 'customer_query' in tags:
                        tags.append('customer_query')
                        to_update = True

                if to_update:
                    update_ticket_freshdesk({'tags':tags},ticket_id)

        except Exception as e:
            logger.exception(f"Tag update in fresh desk failed with error: {e}")
            continue
        
def create_freshdesk_ticket_for_delayed_orders():
    
    past_180_days_date = TimeUtilities.get_n_days_before_date(30)
    
    before_shipping = {
            FulfillmentStatus.PLACED,
            FulfillmentStatus.INPROCESS
        }
    
    freshdesk_already_created_tickets = FreshDeskTickets.objects.filter(ticket_type=TicketTypeEnum.DELAYED_ORDER).values_list('info__order_line_id',flat=True)
    
    orderlines = OrderLine.objects.filter(order__user_id__isnull=False,order__billing_address_id__isnull=False,metadata__fake__isnull=True,created_at__gte=past_180_days_date,metadata__status__in=before_shipping)\
        .exclude(id__in=list(freshdesk_already_created_tickets))\
        .prefetch_related('order__order_store','order__order_store__store').select_related('order','order__billing_address','order__user')\
        

    current_date_time = TimeUtilities.get_current_date_time()
    orderlines = orderlines.annotate(difftime=(current_date_time - F('fulfillment_line__fulfillment__updated_at')))\
        .annotate(
            days=F('brand__order_shipping_days')
        ).annotate(fulfillment_last_updated=F('fulfillment_line__fulfillment__updated_at'))\
            .exclude(difftime=None).exclude(days=None).filter(difftime__gte=datetime.timedelta(seconds=24*3600)*(F('days') + 1))
    
    tickets_created = []
    
    count = 0
    for order_line in orderlines:

        try:
            count+=1

            if count>10:

                time.sleep(20)
                count=0

            mobile_no = order_line.order.user.mobile_no
            query = map_order_line_to_freshdesk_query_obj(order_line,subject='Delayed Order Internal')
            query['tags'] = [TicketTypeEnum.DELAYED_ORDER]
            response = create_ticket_freshdesk(query)

            if response:
                ticket = FreshDeskTickets()
                ticket.mobile_no = mobile_no
                ticket.ticket_id = response.get('id')
                ticket.message = query['message']
                ticket.subject = query['subject']
                ticket.info = {'order_line_id':order_line.id}

                ticket.ticket_type = TicketTypeEnum.DELAYED_ORDER

                tickets_created.append(ticket)
                
        except Exception as e:
            logger.exception(e)

    FreshDeskTickets.objects.bulk_create(tickets_created)

def create_freshdesk_ticket_for_cancelled_orders(fulfillment_id):
    
    freshdesk_already_created_tickets = FreshDeskTickets.objects.filter(ticket_type=TicketTypeEnum.CANCELLED_ORDER).values_list('info__order_line_id',flat=True)
    
    orderlines = OrderLine.objects.filter(fulfillment_line__fulfillment_id=fulfillment_id,order__user_id__isnull=False,
                                          order__billing_address_id__isnull=False,metadata__fake__isnull=True,)\
        .exclude(id__in=list(freshdesk_already_created_tickets))\
        .prefetch_related('order__order_store','order__order_store__store').select_related('order','order__billing_address','order__user')\
    
    orderlines = orderlines.annotate(fulfillment_last_updated=F('fulfillment_line__fulfillment__updated_at'))

    for order_line in orderlines:

        try:
            mobile_no = order_line.order.user.mobile_no
            query = map_order_line_to_freshdesk_query_obj(order_line,subject='Cancelled Order Internal')
            query['tags'] = [TicketTypeEnum.CANCELLED_ORDER]
            
            response = create_ticket_freshdesk(query)

            if response:
                ticket = FreshDeskTickets()
                ticket.mobile_no = mobile_no
                ticket.ticket_id = response.get('id')
                ticket.message = query['message']
                ticket.subject = query['subject']
                ticket.info = {'order_line_id':order_line.id}

                ticket.ticket_type = TicketTypeEnum.CANCELLED_ORDER
                ticket.save()
            
        except Exception as e:
            logger.exception(e)

