from django.http import JsonResponse
import json
import logging
from saleor.brand.models import BrandCred
from saleor.external_services.shopify_service.tasks import order_create_webhook, order_update_webhook, product_create_webhook,product_delete_webhook,product_update_webhook
from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)


def is_active_brand_from_shopify_url(store_url):
    brand_cred = BrandCred.objects.filter(url=store_url,brand__status__in = ['active','active only for barter']).first()
    
    if brand_cred:
        return True

    return False

def product_created_webhook(request):

    try:
        product_id = json.loads(request.body.decode('utf-8'))['id']
        data = json.loads(request.body.decode('utf-8'))
        url = request.headers.get('x-shopify-shop-domain')
        product_id = NumberUtilities.convert_string_to_number(product_id)

        # if is_active_brand_from_shopify_url(url):
        #     product_create_webhook.delay(product_id, url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})

def product_updated_webhook(request):
    
    try:
        product_id = json.loads(request.body.decode('utf-8'))['id']
        data = json.loads(request.body.decode('utf-8'))
        url = request.headers.get('x-shopify-shop-domain')
        product_id = NumberUtilities.convert_string_to_number(product_id)
        
        # if is_active_brand_from_shopify_url(url):
        #     product_update_webhook.delay(product_id, url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})
    
def product_deleted_webhook(request):

    try:
        product_id = json.loads(request.body.decode('utf-8'))['id']
        data = json.loads(request.body.decode('utf-8'))
        url = request.headers.get('x-shopify-shop-domain')
        product_id = NumberUtilities.convert_string_to_number(product_id)

        # if is_active_brand_from_shopify_url(url):
        #     product_delete_webhook.delay(product_id, url)
        
        return JsonResponse({"success":True})
        
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})

def order_updated_webhook(request):
    
    try:
        order_id = json.loads(request.body.decode('utf-8'))['id']
        data = json.loads(request.body.decode('utf-8'))
        url = request.headers.get('x-shopify-shop-domain')
        order_id = NumberUtilities.convert_string_to_number(order_id)

        # if is_active_brand_from_shopify_url(url):
        #     order_update_webhook.delay(order_id, url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})

def zaamo_order_created_webhook(request):
    
    try:
        order_id = json.loads(request.body.decode('utf-8'))['id']
        data = json.loads(request.body.decode('utf-8'))
        url = request.headers.get('x-shopify-shop-domain')
        order_id = NumberUtilities.convert_string_to_number(order_id)
        order_create_webhook.delay(order_id, url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})
    
def fulfillment_updated_webhook(request):
    
    try:
        fulfillment_id = json.loads(request.body.decode('utf-8'))['id']
        order_id = json.loads(request.body.decode('utf-8'))['order_id']
        url = request.headers.get('x-shopify-shop-domain')
        fulfillment_id = NumberUtilities.convert_string_to_number(fulfillment_id)
        
        # if is_active_brand_from_shopify_url(url):
        #     order_update_webhook.delay(order_id, url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})
