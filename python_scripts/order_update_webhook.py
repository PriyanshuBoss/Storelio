from saleor.external_services.shopify_service.shopify_helper import ShopifyHelper
from saleor.external_services.woo_commerce_service.constants import BASE_API_PATH, WEBHOOK_PATH
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.woo_commerce_service.woocommerce_helper import WooCommerceHelper
from saleor.utilities.mongo_utilities import MongoConn
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
import shopify
from saleor.utilities.api_client import ApiClient

def shopify_update_webhook():
    mongo_conn = MongoConn()
    results = mongo_conn.fetch_data({}, 'shopify_stores')

    for data in results:
        store_url = data.get('store_url')
        store_access_key = data.get('access_key')
        store_access_pass = data.get('access_pass')
        api_version = data.get('api_version')
        
        shopify_cred_dict = {
            'store_access_key': store_access_key,
            'store_access_pass': store_access_pass,
            'store_url': store_url,
            'api_version': api_version
        }
        shopify_impl_inst = ShopifyImpl(shopify_cred_dict)
        try:
            webhook_topic_endpoint = {
                                'orders/updated': 'order_updated',
                                'fulfillments/update': 'fulfillment_updated',
                                }

            response_context = {'success': True}

            for topic, endpoint in webhook_topic_endpoint.items():
                
                data = ShopifyHelper.get_data_for_webhook(topic, endpoint)

                webhook = shopify.Webhook()
                webhook.format = data['format']
                webhook.fields = data['fields']
                webhook.topic = data['topic']
                webhook.address = data['address']
                response = webhook.save()
        except Exception as e:
            print(e)

            
def woo_update_webhook():
    mongo_conn = MongoConn()
    results = mongo_conn.fetch_data({}, 'woocommerce_stores')

    for data in results:
        try:
            store_url = data.get('store_url')
            store_access_key = data.get('consumer_key')
            store_access_pass = data.get('client_secret')
            woo_inst = WooCommerceImpl(store_url)
            store_url = woo_inst._clean_url_for_APICLIENT()
            woo_inst.url = store_url
            token = woo_inst.get_auth_token(store_url=store_url)
            
            if token:
                woo_inst.set_authtoken(token)
                print(f'update webhook: {store_url}')
                woo_inst.create_webhooks_for_woo_commerce_store()

        except Exception as e:
            print(e)

shopify_update_webhook()
woo_update_webhook()


'''
To Run
from saleor.python_scripts import order_update_webhook
'''