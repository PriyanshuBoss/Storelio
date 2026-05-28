from django.http import JsonResponse
import json
import logging
from saleor.brand.models import BrandCred
from saleor.external_services.woo_commerce_service.tasks import product_update_webhook,product_create_webhook,product_delete_webhook,order_update_webhook
logger = logging.getLogger(__name__)

def is_active_brand_from_woocommerce_url(store_url):
    brand_cred = BrandCred.objects.filter(url=store_url,brand__status__in = ['active','active only for barter']).first()
    
    if brand_cred:
        return True

    return False

def product_created_webhook(request):
    try:
    
        if request.POST.get('webhook_id'):
            response = {'message': 'Webhook id recieved'}
            return JsonResponse(response)
        
        data = json.loads(request.body.decode('utf-8'))

        url = request.headers.get('x-wc-webhook-source')[:-1]

        if not data or not url:
            return JsonResponse({"success":False})
        
        # if is_active_brand_from_woocommerce_url(url):
        #     product_create_webhook.delay(data,url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})

def product_updated_webhook(request):
    
    try:
        if request.POST.get('webhook_id'):
            response = {'message': 'Webhook id recieved'}
            return JsonResponse(response)
        
        data = json.loads(request.body.decode('utf-8'))

        url = request.headers.get('x-wc-webhook-source')[:-1]

        if not data or not url:
            return JsonResponse({"success":False})
            
        # if is_active_brand_from_woocommerce_url(url):
        #     product_update_webhook.delay(data,url)

        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})

def product_deleted_webhook(request):
    
    try:
        if request.POST.get('webhook_id'):
            response = {'message': 'Webhook id recieved'}
            return JsonResponse(response)
        
        product_id = json.loads(request.body.decode('utf-8'))['id']

        url = request.headers.get('x-wc-webhook-source')[:-1]
        
        if not product_id or not url:
            return JsonResponse({"success":False})
            
        # if is_active_brand_from_woocommerce_url(url):
        #     product_delete_webhook.delay(product_id,url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})


def order_updated_webhook(request):
    
    try:
        if request.POST.get('webhook_id'):
            response = {'message': 'Webhook id recieved'}
            return JsonResponse(response)
        
        order_data = json.loads(request.body.decode('utf-8'))

        url = request.headers.get('x-wc-webhook-source')[:-1]
        
        if not order_data or not url:
            return JsonResponse({"success":False})

        # if is_active_brand_from_woocommerce_url(url):
        #     order_update_webhook.delay(order_data,url)
        
        return JsonResponse({"success":True})
    
    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})
