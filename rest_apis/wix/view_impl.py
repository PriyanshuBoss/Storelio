import json
import jwt
from django.http import JsonResponse
from django.shortcuts import redirect
import os
from saleor.external_services.wix.wix_impl import WixImpl
from saleor.external_services.wix.tasks import initiate_product_onboarding_wix
from saleor.settings import WIX_GATEWAY
import logging
logger = logging.getLogger(__name__)


def redirect_to_installer(request):
    token = request.GET.get('token')
    url = f"{WIX_GATEWAY['WIX_INSTALLER_URL']}install?token={token}&appId={WIX_GATEWAY['WIX_APP_ID']}&redirectUrl={WIX_GATEWAY['WIX_REDIRECT_URL']}"
    return redirect(url)

def wix_onboarding(request):

    try:

        code = request.GET.get('code')
        response = {'success':False, "message":"Try again!"}

        if not code:
            response["message"] = "No Auth Code received, Please Try Again!"
            return JsonResponse(response)

        instanceid = request.GET.get('instanceId')

        if not instanceid:
            response["message"] = "No instance id received, Please Try Again!"
            return JsonResponse(response)

        wix_impl_inst = WixImpl()
        wix_impl_inst.set_instance_id(instanceid)
        token_response = wix_impl_inst.generate_initial_access_refresh_token(code)
        
        if token_response:
            access_token = token_response['access_token']
            wix_impl_inst.request_to_confirm_oauth_flow(access_token)

            store = wix_impl_inst.insert_store_data_from_wix_store(instanceid)

            if not store:
                return JsonResponse(response)

            if store.get('_id'):
                store.pop('_id')

            initiate_product_onboarding_wix.delay(store)
            response = {'success':True}

            return redirect('https://zaamo.co/')
        
        else:
            return JsonResponse(response)


    except Exception as e:
        logger.exception(e)    
        return JsonResponse(response)


def product_created_webhook(request):

    try:
        body = request.body
        response = {'message': "Succeeded"}
        p_key = None
        path = 'saleor/rest_apis/wix/webhook_public_key.json'
        full_path = os.path.join(os.getcwd(),path)

        with open(full_path,'r') as r:
            p_key = json.load(r)['public_key']

            if p_key:
                body = jwt.decode(body, p_key, algorithms=['RS256']).get('data')
                data = json.loads(body)
                product_data = json.loads(data.get('data'))
                instance_id = data['instanceId']
                
            r.close()
            from saleor.external_services.wix.tasks import product_created_webhook
            
            product_created_webhook.delay(product_data,instance_id)
        
        return JsonResponse(response)
    
    except Exception as e:
        logger.exception(e)
        response = {'message': "Server error"}
        return JsonResponse(response)

def product_updated_webhook(request):

    try:
        body = request.body
        response = {'message': "Succeeded"}
        p_key = None
        path = 'saleor/rest_apis/wix/webhook_public_key.json'
        full_path = os.path.join(os.getcwd(),path)

        with open(full_path,'r') as r:
            p_key = json.load(r)['public_key']

            if p_key:
                body = jwt.decode(body, p_key, algorithms=['RS256']).get('data')
                data = json.loads(body)
                product_data = json.loads(data.get('data'))
                instance_id = data['instanceId']
                
            r.close()
            from saleor.external_services.wix.tasks import product_updated_webhook
            
            product_updated_webhook.delay(product_data,instance_id)
        
        return JsonResponse(response)
    
    except Exception as e:
        logger.exception(e)
        response = {'message': "Server error"}
        return JsonResponse(response)

    
    
def product_deleted_webhook(request):
    
    try:
        
        body = request.body
        response = {'message': "Succeeded"}
        p_key = None

        with open('saleor/rest_apis/wix/webhook_public_key.json','r') as r:
            p_key = json.load(r)['public_key']

        if p_key:
            body = jwt.decode(body, p_key, algorithms=['RS256']).get('data')
            data = json.loads(body)
            product_data = json.loads(data.get('data'))
            instance_id = data['instanceId']
            r.close()
            from saleor.external_services.wix.tasks import product_deleted_webhook
            
            product_deleted_webhook.delay(product_data,instance_id)
        
        return JsonResponse(response)
    
    except Exception as e:
        logger.exception(e)
        response = {'message': "Server error"}
        return JsonResponse(response)

def order_updated_webhook(request):
    
    try:
        
        body = request.body
        response = {'message': "Succeeded"}
        p_key = None

        with open('saleor/rest_apis/wix/webhook_public_key.json','r') as r:
            p_key = json.load(r)['public_key']

        if p_key:
            body = jwt.decode(body, p_key, algorithms=['RS256']).get('data')
            data = json.loads(body)
            order_data = json.loads(data.get('data'))
            instance_id = data['instanceId']
            r.close()
            from saleor.external_services.wix.tasks import order_updated_webhook
            
            order_updated_webhook.delay(order_data,instance_id)
        
        return JsonResponse(response)
    
    except Exception as e:
        logger.exception(e)
        response = {'message': "Server error"}
        return JsonResponse(response)
