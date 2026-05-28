from saleor.brand.models import BrandCred
from saleor.external_services.woo_commerce_service.constants import BASE_API_PATH, WEBHOOK_PATH
from saleor.external_services.woo_commerce_service.woocommerce_helper import WooCommerceHelper
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
import shopify
from saleor.utilities.api_client import ApiClient

def shopify_update_webhook():
    brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='shopify').select_related('brand')

    for data in brand_cred_shopify:
        store_url = data.url
        store_access_key = data.access_key
        store_access_pass = data.access_pass
        
        shopify_cred_dict = {
            'store_access_key': store_access_key,
            'store_access_pass': store_access_pass,
            'store_url': store_url,
            'api_version': 'unstable'
        }
        shopify_impl_inst = ShopifyImpl(shopify_cred_dict)
        try:
            whs = shopify.Webhook.find(limit=250)
            if not whs:
                continue

            for w in whs:
                if 'prod.zaamo.co' in w.address:
                    s = w.address
                    w.address = s.replace('prod.zaamo.co','production.zaamo.co')
                    
                    print('____________________________________________________________')
                    print(w.address)
                    print('____________________________________________________________')
                    w.save()
        except Exception as e:
            print(e)

            
def woo_update_webhook():
    brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='woocommerce').select_related('brand')
    

    for data in brand_cred_shopify:
        try:
            store_url = data.url
            store_access_key = data.access_key
            store_access_pass = data.access_pass

            print(f'update webhook: {store_url}')
            param = {'consumer_key':store_access_key,
                    'consumer_secret':store_access_pass}
            api = ApiClient(host=store_url, path=BASE_API_PATH+WEBHOOK_PATH)
            api.update_url_params(param)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            api.get(send_body=False)

            whs = api.fetch_response()

            if not whs:
                print(f"Failed : {store_url}")
                continue

            for w in whs:
                if 'prod.zaamo.co' in w['delivery_url']:
                    s = w['delivery_url']
                    address = s.replace('prod.zaamo.co','production.zaamo.co')
                    
                    id_p = f"/{w['id']}"
                    api_2 = ApiClient(host=store_url, path=BASE_API_PATH+WEBHOOK_PATH+id_p)
                    api_2.update_url_params(param)
                    print({'delivery_url':address})
                    api_2.update_body({'delivery_url':address})
                    header = WooCommerceHelper.get_default_header_with_user_agent()
                    api_2.update_headers(header)
                    api_2.put()
                    print(api_2.fetch_response())
                    if not api_2.fetch_response():
                        print(f"Failed : {store_url}")
        except Exception as e:
            print(e)
shopify_update_webhook()
woo_update_webhook()