from django.conf import settings
from django.http import JsonResponse
from saleor.payment.emails import send_cashfree_client_capture_email
from saleor.payment.gateways.cashfree.cashfree_client import CashfreeClient
from saleor.rest_apis.razorpay.views import fetch_razorpay_payment_response
from saleor.utilities.request_utilities import RequestUtilities
from ...graphql.core.utils import from_global_id_strict_type
from saleor.checkout.models import Checkout,CheckoutStore
from ...payment.gateways.cashfree import get_error_message_from_cashfree_error
from django.views.decorators.csrf import csrf_exempt
from urllib import parse
import graphene
from .constants import GRAPHQL_ENDPOINT_URL
import json
import requests
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def fetch_cashfree_payment_response(request):
    url = urlparse(request.META.get('HTTP_ORIGIN', ''))
    host = url.hostname

    razorpay = settings.RAZORPAY.get('active_status', False)

    if 'localhost' in host:
        host_name='localhost'
    elif len(host.split('.')) >=2:  
        host_name = host.split('.')[-2]
    else:
        host_name = ''

    logger.info('host identifiers and razorpay activation %s, %s, %s, %s, %s', url, razorpay, host, len(host.split('.')), host_name)

    app_code =  RequestUtilities.get_app_code_from_headers(request)

    if  app_code:
        razorpay = False
    
    if ( razorpay and  'localhost' in host) or (razorpay and host and len(host.split('.')) >=2 and host.split('.')[-2]=='zaamo'):
        
        if host and ('staging' in host or 'betaistore' in host):
            return fetch_razorpay_payment_response(request)


    order_id = request.GET.get('checkout_id')
    response = ""
    if not order_id:
        return JsonResponse({
            'success': False,
            'error_message': "Invalid checkout ID",
            "status":400
        })
    cashfree_client = CashfreeClient()
    response = ""

    try:
        response = cashfree_client.get_order_details(order_id,True,{})

    except Exception as e:
        error = get_error_message_from_cashfree_error(e)
        return JsonResponse({
            'success': False,
            'error_message': error,
            "status": 500
        })    
    
    if order_id != response['order_id']:
        return JsonResponse({'success': False, 'error_message': "Invalid checkout ID, no response found at Gateway"})

    else:
        
        if response['order_status']=="PAID":
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
    try:
        user = checkout.user
        if not user:
            from saleor.account.models import User
            mobile_no=str(checkout.shipping_address.phone)[-12:]
            generate_user_for_phone(mobile_no=mobile_no)
            user = User.objects.filter(mobile_no=mobile_no).first()
            checkout.user = user
            checkout.save(update_fields=["user", "last_change"])
        else:
            mobile_no=user.mobile_no
    except:
        subject = "Cashfree Webhook: User not Found"
        log_text = f"User not found for cashfree checkout {checkout.token}"
        send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
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

def generate_user_for_phone(mobile_no):
    variables = {
        "mobileNo":mobile_no,
        "registerType":"USER"
    }
    query = GRAPHQL_ENDPOINT_URL.MUTATION_USER_REGISTER
    headers = {}
    response = requests.post(
        GRAPHQL_ENDPOINT_URL.BACKEND_URL,
        headers=headers,
        json={
            'query': query,
            'variables': variables
        }
    )
    return 

@csrf_exempt
def fetch_cashfree_notify_url_response(request):
    response = {}
    subject = "Cashfree Webhook Failure"
    if request.method == 'POST':
        # raw-response or decoded for signature verify
        #raw_response = request.body
        response = parse.parse_qs(request.body.decode('utf-8'))
        log_text = f"CASHFREE_WEBHOOK:: Webhook Received from cashfree, raw response :: {response}"
        logger.info(log_text) 
    if not response:
        #FIXME set mail that webhook failed
        logger.info("CASHFREE_WEBHOOK:: Webhook Received, but no response received") 
    order_id = response.get('orderId')
    checkout_id=""
    if order_id:
        size = len(order_id[0])
        checkout_id = order_id[0][:size-13]
    try:
        checkout = Checkout.objects.get(token=checkout_id)
    except:
        checkout = None
    
    if not checkout:
        logger.error(f"CASHFREE_WEBHOOK:: Webhook Received, but checkout doesnt exists for checkout: {checkout_id}")

    payment_status = response.get('txStatus')[0]
    if payment_status!="SUCCESS":
        subject = "Cashfree Webhook Non Successful Response"
        log_text = f"CASHFREE_WEBHOOK:: Webhook Received, but payment not sucessful for checkout: {checkout_id} and cashfree orderId: {order_id}"
        logger.warn(log_text)
        send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
        return None
    cashfree_signature = response.get('signature')[0]
    print("found payment status",payment_status)
    print("found sig to verify",cashfree_signature)
    #headers = request.get('headers')
    #print("headers from response",headers)
    #timestamp = headers.get('x-cashfree-timestamp')
    #print("timestamp from headers",timestamp)
    # verify signature
    validation  = validate_webhook_response(order_id,payment_status,cashfree_signature, timestamp="")
    if not validation:
        subject = "Cashfree Webhook Validation Failed"
        log_text = f"CASHFREE_WEBHOOK:: Webhook Received, validation failed for checkout: {checkout_id} and cashfree orderId: {order_id}"
        logger.warn(log_text)
        send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
        return None
    
    headers_checkout_complete = set_headers_for_checkout_complete(checkout)
    variables_checkout_complete = set_variables_for_checkout_complete(checkout)
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

    if response.status_code != 200:
        subject = "Cashfree Webhook: Order creation failed"
        log_text = f"CASHFREE_WEBHOOK: Checkout Complete Failed, for checkout: {checkout_id} and cashfree orderId: {order_id}. Response for orderID:{parsed_response} "
        logger.error(log_text)
        send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
        raise Exception("{message}\n extensions: {extensions}".format(
            **parsed_response))
    else:
        log_text = f"CASHFREE_WEBHOOK:: Checkout Completed, order created for checkout: {checkout_id} and cashfree orderId: {order_id}. Response for orderID:{parsed_response} "
        logger.info(log_text)
        subject = "Cashfree Webhook: Order creation sucessful"
        send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})

    return None
    
def validate_webhook_response(order_id,payment_status,cashfree_signature, timestamp):
    # singature verification from fynd code
    # FIXME add verification logic later

    # FIXME add checkout total or gross whichever amount is final after discount 
        #order = order_models.Order.objects.get_by_checkout_token(checkout_token)
        # FIXME check which one of total_net_amount and total_gross_amount is the one 
        # which is reflected when vouchers and coupons are applied
    secret_key = GRAPHQL_ENDPOINT_URL.CASHFREE_SECRET_KEY
    signed_payload = ""
    return True
    '''
    timestamp := 1617695238078; 
signedPayload := $timestamp.$payload;
expectedSignature := Base64Encode(HMACSHA256($signedPayload, $merchantSecretKey));
'''


def manual_order_creation(checkout_id):
    try:
        checkout = Checkout.objects.get(token=checkout_id)
    except:
        checkout = None
    
    if not checkout:
        return None

    headers_checkout_complete = set_headers_for_checkout_complete(checkout)
    print("headers",headers_checkout_complete)
    variables_checkout_complete = set_variables_for_checkout_complete(checkout)
    print("variables",variables_checkout_complete)
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
    print(parsed_response)
    return None