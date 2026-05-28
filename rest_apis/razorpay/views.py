from django.http import JsonResponse
import json
from django.conf import settings
from saleor.payment.emails import  send_razorpay_client_capture_email
from saleor.payment.gateways.razorpay import get_client, get_error_message_from_razorpay_error
from saleor.plugins.manager import get_plugins_manager
from ...graphql.core.utils import from_global_id_strict_type
from saleor.payment.models import Payment
from saleor.checkout.models import Checkout,CheckoutStore
from django.views.decorators.csrf import csrf_exempt
from urllib import parse
import graphene
from .constants import GRAPHQL_ENDPOINT_URL
import json
import requests
import logging

logger = logging.getLogger(__name__)


def get_razorpay_client():
    manager = get_plugins_manager()
    gateway_plugin = manager.get_plugin('zaamo.payments.razorpay')
    config = gateway_plugin.config
    razorpay_client = get_client(**config.connection_params)
    return razorpay_client

def fetch_razorpay_payment_response(request):
    
    order_id = request.GET.get('checkout_id')

    if not order_id:
        return JsonResponse({
            'success': False,
            'error_message': "Invalid checkout ID",
            "status":400
        })

    razorpay_client = get_razorpay_client()
    
    try:
        payments =  razorpay_client.order.fetch_all_payments(order_id)
        
    except Exception as e:
        
        logger.info('exception has occurred while fetching payments from razorpay for order_id:: %s and exception is %s', order_id, e)

        error = get_error_message_from_razorpay_error(e)
        return JsonResponse({
            'success': False,
            'error_message': error,
            "status": 500
        })    
    authorised_payments = [item for item in payments['items'] if item['status'] in ['authorized', 'captured']]
    if any(authorised_payments):

        return JsonResponse({'success': True, 'checkout_id': order_id})
            # FIXME can make celery task with delay of 20 min to check if order created or not from webhook      
    else:
        return JsonResponse({
        'success': False,
        'error_message': "Invalid Amounts don't add up"
        })
            # FIXME can make celery task with delay of 20 min to check if updated now or not


def set_headers_for_checkout_complete(checkout):
    headers_to_send = GRAPHQL_ENDPOINT_URL.HEADERS
    platform_code = checkout.platform_code
    store_id = CheckoutStore.objects.get(token=checkout).store.id
    mobile_no = checkout.user.mobile_no
    auth_token = "JWT "+generate_token_for_checkout_complete(mobile_no)
    headers_to_send.update({
        "Authorization": auth_token,
        "x-platform-code":platform_code,
        "x-store-id":str(store_id)
    })
    return headers_to_send

def generate_token_for_checkout_complete(mobile_no):
    variables = {
        "mobile_no":mobile_no
    }
    
    query = GRAPHQL_ENDPOINT_URL.MUTATION_TOKEN_CREATE
    headers = {}
    response = requests.post(
        GRAPHQL_ENDPOINT_URL.BACKEND_URL,
        headers=headers,
        json={
            'query': query,
            'variables': variables
        }
    )
    parsed_response = json.loads(response.text)
    token = parsed_response.get('data')\
        .get('tokenCreate')\
        .get('token')
    return token


def set_variables_for_checkout_complete(checkout):
    checkout_id =graphene.Node.to_global_id("Checkout",checkout.token)
    variable_dict = {
        "checkoutId":checkout_id
    }
    return variable_dict


def verify_signature(request):
    client = get_razorpay_client()
    webhook_signature = request.META['HTTP_X_RAZORPAY_SIGNATURE']
    return client.utility.verify_webhook_signature(request.body, 
    webhook_signature, settings.RAZORPAY['captured_webhook_secret'])

def payment_captured_webhook(request):
    request_data = json.loads(request.body)
    log_text = f"RAZORPAY_WEBHOOK:: Webhook recieved from Razorpay with request data ::{request_data}"
    logger.info(log_text)
    if "HTTP_X_RAZORPAY_SIGNATURE" in request.META.keys():
        
        
        payload = request_data.get('payload', {})
        payment_data = payload.get('payment', {}).get('entity', {})
        order_id = payment_data.get('order_id', '')
        
        payment = Payment.objects.filter(token=order_id).first()
        checkout = payment.checkout
        headers_checkout_complete = set_headers_for_checkout_complete(checkout)
        variables_checkout_complete = set_variables_for_checkout_complete(checkout)
        log_text = f"RAZORPAY_WEBHOOK:: Checkout complete data for razorpay webhook ::{variables_checkout_complete}"
        logger.info(log_text)
        query = GRAPHQL_ENDPOINT_URL.MUTATION_CHECKOUT_COMPLETE
        response = requests.post(
            GRAPHQL_ENDPOINT_URL.BACKEND_URL,
            headers=headers_checkout_complete,
            json={
                'query': query,
                'variables': variables_checkout_complete
            }
        )
        parsed_response = json.loads(response.text)
        checkout_id=checkout.token
        if response.status_code != 200:
            subject = "RazorPay Webhook: Order creation failed"
            log_text = f"RazorPay_WEBHOOK: Checkout Complete Failed, for checkout: {checkout_id} and RazorPay orderId: {order_id}. Response for orderID:{parsed_response} "
            logger.error(log_text)
            send_razorpay_client_capture_email.delay({'subject':subject,'body':log_text})
            raise Exception("{message}\n extensions: {extensions}".format(
                **parsed_response))
        else:
            log_text = f"RazorPay_WEBHOOK:: Checkout Completed, order created for checkout: {checkout_id} and cashfree orderId: {order_id}. Response for orderID:{parsed_response} "
            logger.info(log_text)
            subject = "RazorPay Webhook: Order creation sucessful"
            send_razorpay_client_capture_email.delay({'subject':subject,'body':log_text})

    return JsonResponse({
            'success': True,
            "status":200
        })
