from saleor.brand.models import BrandCred,Brand
from saleor.external_services import get_fernet_encoder
from saleor.utilities.mongo_utilities import MongoConn

def save_brand_cred(brand_id,defaults):
    try:
        print(defaults)
        BrandCred.objects.update_or_create(brand_id=brand_id,defaults=defaults)
    except Exception as e:
        print(e)

def run():
    brands = Brand.objects.filter(brand_source__in=['shopify','woocommerce'])
    brand_name_id_dict = dict()

    for brand in brands:
        brand_name = brand.private_metadata.get('source_name') or brand.brand_name
        brand_name_id_dict[brand_name] = brand.id

    mongo_conn = MongoConn()
    shopify_results = mongo_conn.fetch_data({}, 'shopify_stores')
    shopify_store_data = [data for data in shopify_results]
    shopify_results.close()
    
    woo_results = mongo_conn.fetch_data({}, 'woocommerce_stores')
    woo_store_data = [data for data in woo_results]
    woo_results.close()

    for shopify_data in shopify_store_data:
        brand_id = brand_name_id_dict.get(shopify_data.get('store_name'))
        if not brand_id:
            continue

        save_brand_cred(brand_id,{
            'access_key': get_fernet_encoder().encrypt(shopify_data.get('store_access_key').encode()).decode('utf-8'),
            'access_pass': get_fernet_encoder().encrypt(shopify_data.get('store_access_pass').encode()).decode('utf-8'),
            'auth_token': get_fernet_encoder().encrypt(shopify_data.get('auth_token').encode()).decode('utf-8'),
            'url': shopify_data.get('store_url')
        })

    for woo_data in woo_store_data:
        brand_id = brand_name_id_dict.get(woo_data.get('name'))

        if not brand_id:
            continue

        save_brand_cred(brand_id, {
                    'access_key': get_fernet_encoder().encrypt(woo_data.get('consumer_key').encode()).decode('utf-8'),
                    'access_pass': get_fernet_encoder().encrypt(woo_data.get('client_secret').encode()).decode('utf-8'),
                    'auth_token': get_fernet_encoder().encrypt(woo_data.get('auth_token').encode()).decode('utf-8'),
                    'url': woo_data.get('store_url')
                })

run()

'''
TO RUN:
from saleor.python_scripts import update_brand_creds
'''