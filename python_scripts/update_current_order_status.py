from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.external_services.woo_commerce_service.woocommerce_helper import WooCommerceHelper
from saleor.utilities.api_client import ApiClient
from saleor.order.models import OrderBrandZaamoMapping
from saleor.utilities.mongo_utilities import MongoConn


def shopify_run():
    sh_inst = ShopifyImpl()
    orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='shopify').select_related('brand')

    
    brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='woocommerce').select_related('brand')
    brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}

    for order_m in orders:
        try:
            
            name = order_m.brand.private_metadata.get('source_name')
            result = brand_cred_dict.get(name)
        
            sh_inst = ShopifyImpl()
            store_url = result.url
            sh_inst.update_order_from_webhook(order_m.order_id_brand, store_url)

        except Exception as e:
            print(e)
            continue

def WooCommerce_run():
    
    orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='woocommerce').select_related('brand')
    
    brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='woocommerce').select_related('brand')
    brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}
    
    for order_m in orders:
        try:
            woo_inst = WooCommerceImpl()

            name = order_m.brand.private_metadata.get('source_name')
            
            result = brand_cred_dict.get(name)

            store_url = result.url
            s_url = store_url
            woo_inst.url = store_url
            store_url = woo_inst._clean_url_for_APICLIENT()
            woo_inst.url = store_url

            try:
                token = get_fernet_encoder().decrypt(result.auth_token.encode()).decode('utf-8')
            except:
                token = result.auth_token

            woo_inst.set_authtoken(token)
            api = ApiClient(host=store_url, path=f'wp-json/wc/v3/orders/{order_m.order_id_brand}')
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            api.add_header('Authorization',token)
            api.get(send_body=False)
            order = api.fetch_response()
            if order:
                woo_inst.update_order_status_from_webhook(order,s_url,name)
        except Exception as e:
            print(e)
            continue

WooCommerce_run()
shopify_run()

'''
To Run
from saleor.python_scripts import update_current_order_status
'''