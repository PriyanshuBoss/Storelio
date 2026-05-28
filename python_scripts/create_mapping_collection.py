import json
from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
import shopify

def create_woocommerce_mapped_data():
    woo_inst = WooCommerceImpl()
    results = woo_inst._get_instance_of_mongo_connection().fetch_data({}, 'woocommerce_stores')
    
    for document in results:
        try:
            
            url = document.get('store_url')
            
            store_name = document.get('name')
            woo_inst.url = url
            existing_product_data = woo_inst.fetch_product_data_from_woo_commerce_store_by_name(store_name)
            product_data = woo_inst.get_value_by_key(existing_product_data,'product_data')

            if product_data and isinstance(product_data,str):
                product_data = json.loads(product_data)

            if not product_data:
                product_data = woo_inst.fetch_product_data_from_gridfs_by_name(store_name)

            if product_data:
                woo_inst.insert_mapped_product_data_to_mongo(product_data,store_name, url)
        
        except Exception as e:
            print(e)
            woo_inst.insert_product_data_from_woo_commerce_store(document.get('name'))
        
def create_shopify_mapped_data():
    sh_inst = ShopifyImpl()
    results = sh_inst._get_instance_of_mongo_connection().fetch_data({}, 'shopify_stores')
    brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='shopify').select_related('brand')
    brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}
    
    for document in results:
        try:
            url = document.get('store_url')
            
            store_name = document.get('store_name')
            store_id = document.get('shop_id')
            result = sh_inst.fetch_product_data_from_shopify_store(store_id)['result']
            product_data = sh_inst.get_value_by_key(result,'product_data')
            
            if product_data and isinstance(product_data,str):
                product_data = json.loads(product_data)
                
            if not product_data:
                product_data = sh_inst.fetch_product_data_from_gridfs_by_name(store_name)

            if product_data:
                sh_inst.insert_mapped_product_data_to_mongo(product_data,store_name, store_id)
        
        except Exception as e:
            print(e)
            credential = brand_cred_dict.get(document.get('store_name'))
            
            try:
                access_pass = get_fernet_encoder().decrypt(credential.access_pass.encode()).decode('utf-8')
            except:
                access_pass = document.access_pass

            session_cred = {'store_url': credential.url,
                                'api_version': 'unstable',
                                'store_access_pass': access_pass} 
                                
            sh_inst1 = ShopifyImpl()
            sh_inst1.create_shopify_session(session_cred)
            shop = shopify.Shop.current()
            sh_inst1.insert_product_data_from_shopify_store(shop)

create_woocommerce_mapped_data()
create_shopify_mapped_data()