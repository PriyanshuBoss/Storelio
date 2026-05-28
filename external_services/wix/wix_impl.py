from collections import defaultdict
from decimal import Decimal
import json
import math
from pprint import pprint
import graphene
from saleor.brand.models import Brand, BrandCred,BrandResyncLog
from django.db.models import Subquery
from saleor.brand.states import BrandStatusEnum
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.external_services import get_fernet_encoder, update_order_metadata_with_extra_charge
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.external_services.wix.constants import COLLECTION_PATH, INVENTORY_PATH, ORDER_PATH, DISCOUNT_PATH, PRODUCT_COLLECTION_NAME, PRODUCTS_GET_PATH, PRODUCTS_PATH, STORE_COLLECTION_NAME, STORE_DETAILS_PATH
from saleor.product.models import BrandVariantZaamoMapping
from saleor.settings import IS_BETA,WIX_GATEWAY
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.api_client import ApiClient
from saleor.utilities.string_utilities import StringUtilities
from .wix_helper import WixHelper
from saleor.product import bulk_products_import as etl
from saleor.external_services.integrations.wix import WixIntegration
import logging
import time
logger = logging.getLogger(__name__)

class WixImpl():
    mongo_conn = None
    refresh_token = None
    auth_token = None
    auth_generated_time = None
    instance_id = None

    def set_instance_id(self, instance_id):
        self.instance_id = instance_id
    
    def set_refresh_token(self, refresh_token):
        self.refresh_token = refresh_token

    def _get_instance_of_mongo_connection(self):

        if self.mongo_conn is None:
            self.mongo_conn = MongoConn()

        return self.mongo_conn


    def _get_instance_of_etl_loader(self):

        
        etl_loader = etl.ETLDataLoader()

        return etl_loader


    def _get_value_by_key(self, results, key):

            for res in results:
                value = res.get(key)

                if value:
                    return value
                else:
                    return ''

    def request_to_confirm_oauth_flow(self,auth):
        api_client = ApiClient(url=f"{WIX_GATEWAY['WIX_INSTALLER_URL']}token-received")
        headers = {'Authorization': auth}
        api_client.update_headers(headers)
        api_client.post()

    def _update_refresh_token_in_mongo(self):
        access_pass = self.refresh_token
        BrandCred.objects.filter(private_metadata__instance_id=self.instance_id).update(access_pass=get_fernet_encoder().encrypt(access_pass.encode()).decode('utf-8'))

    def generate_access_refresh_token(self):

        if self.auth_generated_time and self.refresh_token and self.access_token:
            time_dif = time.time()-self.auth_generated_time
            
            if time_dif<180:

                response = {'refresh_token': self.refresh_token, 'access_token': self.access_token}
                return response

        api_client = ApiClient(url=WIX_GATEWAY['WIX_OAUTH_URL'])
        headers = {'Content-Type': 'application/json'}
        api_client.update_headers(headers)
        body = WixHelper.get_body_for_oauth(self.refresh_token,WIX_GATEWAY)
        api_client.update_body(body)
        api_client.post()

        if api_client.fetch_response():
            response = api_client.fetch_response()
            self.refresh_token = response.get('refresh_token')
            self._update_refresh_token_in_mongo()
            self.access_token = response.get('access_token')
            self.auth_generated_time = time.time()

            return response
        
        return None
    
    def generate_initial_access_refresh_token(self,code):
        api_client = ApiClient(url=WIX_GATEWAY['WIX_OAUTH_URL'])
        headers = {'Content-Type': 'application/json'}
        api_client.update_headers(headers)
        body = WixHelper.get_body_for_initial_oauth(code,WIX_GATEWAY)
        api_client.update_body(body)
        api_client.post()

        if api_client.fetch_response():
            response = api_client.fetch_response()
            self.refresh_token = response.get('refresh_token')
            return response
        
        return None

    def _fetch_store_by_instance_id_from_wix_store(self, instance_id) -> dict:

        f_encoder = get_fernet_encoder()
        brand_cred = BrandCred.objects.filter(private_metadata__instance_id=self.instance_id,brand__status__in = ['active','active only for barter']).first()
        
        return brand_cred
    
    def _fetch_store_by_name_from_wix_store(self, name) -> dict:

        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, STORE_COLLECTION_NAME)

        return results

    def _fetch_product_data_by_instance_id_from_wix_store(self, instance_id) -> dict:

        get_store_data = {'instance_id': instance_id}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)

        return results
    
    def _fetch_product_data_by_name_from_wix_store(self, name) -> dict:

        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)

        return results

    def insert_store_data_from_wix_store(self, instance_id):
        
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=STORE_DETAILS_PATH)
        token = self.generate_access_refresh_token()
        
        if not token:
            return None

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)
        api.get(send_body=False)

        if not api.fetch_response():    
            return None

        shop = api.fetch_response()
        
        if shop:
            store_details = dict()
            store_name = shop.get('properties').get('businessName')

            if not store_name:
                
                store_name = shop.get('properties').get('siteDisplayName')
            
            if not store_name:
                store_name = instance_id

            existing_shop = self._fetch_store_by_name_from_wix_store(store_name)

            store_details = shop.get('properties')
            store_details['store_name'] = store_name
        

            existing_shop_name = self._get_value_by_key(existing_shop,'store_name')
            
            if existing_shop_name:
                self._get_instance_of_mongo_connection().update_data({'store_name': store_name}, {'$set': store_details}, STORE_COLLECTION_NAME)

            else:
                self._get_instance_of_mongo_connection().insert_data(store_details, STORE_COLLECTION_NAME)
                
            store_details = WixHelper.structure_store_details_response(store_details,instance_id,self.refresh_token)

            return store_details
            
        return None

    
    def _fetch_inventory_variant_dict_by_productId(self,productID):
        variant_stock = dict()
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=INVENTORY_PATH)
        token = self.generate_access_refresh_token()
        
        if not token:
            return None

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)

        body = WixHelper.get_body_for_inventory_api_by_productId(productID)
        api.update_body(body)
        api.post()
        current_response = api.fetch_response()

        if not current_response:    
            return None

        if current_response.get('totalResults')==0:
            return None

        inventory_items = current_response.get('inventoryItems')
        for inventory_item in inventory_items:

            if inventory_item.get('trackQuantity'):

                for variant in inventory_item.get('variants'):
                    variant_stock[variant['variantId']]= variant.get('quantity',0)

        return variant_stock


    def _fetch_inventory_variant_dict(self):
        variant_stock = dict()
        last_numeric_id = 0
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=INVENTORY_PATH)
        token = self.generate_access_refresh_token()
        
        if not token:
            return None

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)
        count = 0

        while True:

            if count==500:
                break
            
            count+=1
            body = WixHelper.get_body_for_inventory_api(last_numeric_id)
            api.update_body(body)
            api.post()
            current_response = api.fetch_response()
            
            if not current_response:    
                break

            if current_response.get('totalResults')==0:
                break

            inventory_items = current_response.get('inventoryItems')
            for inventory_item in inventory_items:

                if inventory_item.get('trackQuantity'):

                    for variant in inventory_item.get('variants'):
                        
                        variant_stock[variant['variantId']]= variant.get('quantity',0)
            
            last_numeric_id = inventory_items[-1]['numericId']

        return variant_stock

    def _fetch_collections_for_product(self):
        collection_dict = dict()
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=COLLECTION_PATH)
        token = self.generate_access_refresh_token()
        
        if not token:
            return collection_dict

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)
        api.post()

        if not api.fetch_response():
            return collection_dict
        
        collections = api.fetch_response()['collections']
        
        for collection in collections:
            collection_dict[collection['id']] = collection

        return collection_dict


    def _fetch_product_list_from_wixAPI(self):
        inventory_variant_dict = self._fetch_inventory_variant_dict()
        collection_dict = self._fetch_collections_for_product()
        product_list = []
        last_numeric_id = 0
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=PRODUCTS_PATH)
        token = self.generate_access_refresh_token()
        
        if not token:
            return None

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)
        count = 0

        while True:

            if count==500:
                break
            
            count+=1
            body = WixHelper.get_body_for_product_api(last_numeric_id)
            api.update_body(body)
            api.post()
            current_response = api.fetch_response()
            
            if not current_response:    
                break

            if current_response.get('totalResults')==0:
                break

            products_data = current_response.get('products')
            for product in products_data:
                
                if product['manageVariants']==True:

                    variants = product['variants']

                    for variant in variants:
                        variant['quantity'] = inventory_variant_dict.get(variant['id']) or 0

                    product['variants'] = variants
                
                collection_data = []

                for c_id in product['collectionIds']:
                    collection = collection_dict.get(c_id)

                    if collection:
                        collection_data.append(collection)

                product['collections_data'] = collection_data

            last_numeric_id = products_data[-1]['numericId']
            product_list.extend(products_data)

        return product_list
   
    def fetch_product_data_from_gridfs_by_name(self, name, key='product_data') -> list:
        product_list = []

        try:
            get_store_data = {'filename': name}
            results = self._get_instance_of_mongo_connection().fetch_one_gridfs(get_store_data)

            if results:
                
                product_data = json.loads(results.read())
                product_list = product_data.get(key)
        
        except Exception as e:
            logger.exception(f'Error while fetching from gridfs {e}, brand_name :: {name}, key:: {key}')
    
        return product_list

    def insert_product_data_from_wix_store(self, shop_name,resync=False):
        
        storename = shop_name
        product_list = self._fetch_product_list_from_wixAPI()
        
        if not product_list:
            return
            
        existing_product_data = self._fetch_product_data_by_instance_id_from_wix_store(self.instance_id)
        data_exist = False

        for existing_product in existing_product_data:
            existing_product_data = existing_product
            data_exist = True
            break
        
        if data_exist:
            store_name = existing_product_data.get('store_name')
            product_data_existing = existing_product_data.get('product_data') or []
            
            if product_data_existing and isinstance(product_data_existing,str):
                product_data_existing = json.loads(product_data_existing)

            product_data_id_existing = dict()

            for product in product_data_existing:
                product_data_id_existing[product['id']] = product
        
        else:
            store_name = None
            product_data_id_existing = dict()
        post_data = {'instance_id': self.instance_id, 'store_name': storename, 'product_data': json.dumps(product_list)}
        self.insert_mapped_product_data_to_mongo(product_list,storename)
        
        if store_name:
            try:
                if resync:
                    self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)
                    
                self._get_instance_of_mongo_connection().update_data({'instance_id': self.instance_id}, {'$set': post_data}, PRODUCT_COLLECTION_NAME)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'instance_id': self.instance_id}, PRODUCT_COLLECTION_NAME)
            
        else:
            self._get_instance_of_mongo_connection().insert_data(post_data, PRODUCT_COLLECTION_NAME)
        
        
        existing_product_data = self._fetch_product_data_by_instance_id_from_wix_store(self.instance_id)

        store_name = self._get_value_by_key(existing_product_data,'store_name')

        if not store_name:
            p_data ={'instance_id': self.instance_id, 'store_name': storename, 'product_data': product_list}

            existing_product_data = self.fetch_product_data_from_gridfs_by_name(storename)

            if existing_product_data:

                if resync:

                    product_data_id_existing = dict()

                    for product in existing_product_data:
                        product_data_id_existing[product['id']] = product
                        
                    self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)
                
                self._get_instance_of_mongo_connection().delete_gridfs(storename)
            
            p_data = json.dumps(p_data)
            result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, storename, encoding='utf-8')

        brand_collection_create_inst = BrandCollectionCreate()
        brand_collection_create_inst.save_brand_collection_name(storename)

        response_context = dict()
        response_context['result'] = 'Data for products of shop stored successfully'
        response_context['success'] = True

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False
            
        return response_context

    def insert_mapped_product_data_to_mongo(self, product_data, store_name):

        mapped_product_list = []
        instance = WixIntegration()

        for prod_dict in product_data:
            
            prod_dict['vendor'] = store_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                mapped_product_list.extend(product_meta)

        self.insert_mapped_data_to_gridfs(store_name, mapped_product_list)

    def insert_mapped_data_to_gridfs(self, store_name, mapped_product_list):

        if not mapped_product_list:
            return

        p_data = {'instance_id': self.instance_id, 'store_name': store_name, 'mapped_product_data': mapped_product_list}
        file_name = f"{store_name}_mapped"
        existing_product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')

        if existing_product_data:
            self._get_instance_of_mongo_connection().delete_gridfs(file_name)
        
        p_data = json.dumps(p_data)
        result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, file_name, encoding='utf-8')

    def update_brand_record_for_resync(self,product_list,brand_name,product_data_id_existing):
        if not product_list or not product_data_id_existing:
            return
        
        instance = WixIntegration()

        for product in product_list:
            existing_product = product_data_id_existing.get(product['id'])
            
            if not existing_product:
                continue
            
            instance.update_brand_price_record(product,brand_name,existing_product)

    def save_brand_creds(self,brand_global_id,store_credentials):
        brand_id = graphene.Node.from_global_id(brand_global_id)[1]
        f_encoder = get_fernet_encoder()

        default = {'access_key':f_encoder.encrypt(store_credentials.get('instance_id').encode()).decode('utf-8'),
                    'access_pass':f_encoder.encrypt(store_credentials.get('refresh_token').encode()).decode('utf-8'),
                    'url':store_credentials.get('store_name'),
                    'auth_token':None,
                    'private_metadata':{'instance_id':store_credentials.get('instance_id')}}

        brand_cred = BrandCred.objects.update_or_create(brand_id=brand_id,defaults=default)

    def create_brand_from_wix(self, shop):
        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(shop.get("store_name"))
        
        if brand_id:
            self.save_brand_creds(brand_id,shop)
            return brand_id

        brand_info = WixHelper.create_brand_context_from_wix(shop)
        brand_id = etlLoader.create_brand(brand_info)
        self.save_brand_creds(brand_id,shop)

        return brand_id


    def _create_products_util(self, val_dict, brand_name,check_variant_update=False,from_celery=True):

        product_list = []
        instance = WixIntegration()
        product_mapping_list = []
        for prod_dict in val_dict:

            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)

            if product_meta:
                product_list.extend(product_meta)
            
            if check_variant_update:
                for product in product_meta:
                    product_mapping_list.append(product['product.brand_variant_zaamomapping'].copy())

        if not product_list:
            return {'success': False}
        
        for chunks in instance.gen_chunks(product_list):
            instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery
        
        if check_variant_update:
            instance.delete_variation_if_removed_from_store(product_mapping_list)

        return {'success': True}

    def create_product_from_Wix(self, shop):

        response = {}
        product_data = self.fetch_product_data_from_mongo(shop.get('store_name'))

        if not product_data:
            response['message'] = "Store Data isn't available"
            response['success'] = False
            return response

        brand_name = shop.get('store_name')
        resp = self._create_products_util(product_data, brand_name)

        if resp['success']==True:
            response['message'] = "Product Created successfully"
            response['success'] = True

        else:
            response['message'] = "Product Creation Failed, Please Try again."
            response['success'] = False

        return response

    #Functions For order Placing 
    def _set_line_items(self,order_lines, brand_mappings):
        line_items = []
        total_price = 0
        product_variant_not_decrement_dict = defaultdict(list)
        product_quantity_decrement_dict = dict()

        for i in range(len(order_lines)):
            item = dict()
            product_brand_id = brand_mappings[i].product_id_brand
            variant_brand_id = brand_mappings[i].variant_id_brand
            variant = brand_mappings[i].variant_zaamo
            quantity = order_lines[i].quantity
            price = variant.price_amount * quantity
            total_price+=price

            private_meta = variant.private_metadata
            product_name = private_meta.pop('product_name')

            if private_meta.get('is_variant_brand_null'):
                variant_brand_id = '00000000-0000-0000-0000-000000000000'
                product_variant_not_decrement_dict[product_brand_id].append(variant.id)
                product_quantity_decrement_dict[product_brand_id] = quantity
                private_meta.pop('is_variant_brand_null')
            
            options = []
            for key,value in private_meta.items():
                options.append({'option':key,'selection':value})
            
            item = {
                "productId":product_brand_id,
                "variantId": variant_brand_id,
                "options":options,
                "lineItemType":"PHYSICAL",
                "quantity":quantity,
                "name":product_name,
                "priceData": {
                    "price": StringUtilities.convert_number_to_string(price)
                    }
                }
            
            line_items.append(item)

        return line_items, product_variant_not_decrement_dict, product_quantity_decrement_dict, total_price

    def _create_order_context_from_wix(self, order_lines, brand_mappings):
        
        order = order_lines[0].order
        shipping_address = order.shipping_address
        billing_address = order.billing_address
        
        is_zaamo_shopify = order.metadata.get('shopify')

        line_items, product_variant_decrement, product_quantity_decrement, total_price = self._set_line_items(order_lines, brand_mappings)

        user_email = order.get_customer_email()

        is_cod = order_lines[0].cod
        cod_total = 0

        if is_zaamo_shopify:

            cod_total = Decimal(0)

            if is_cod:
                cod_total += Decimal(100/order.lines.all().values('brand_id').distinct().count())
                
            for line in order_lines:

                try:
                    cod_total += line.variant.variant_zaamo_shopify_mapping.first().extra_charges * line.quantity

                except:
                    cod_total += Decimal(0)
                
            if cod_total:
                update_order_metadata_with_extra_charge(order_lines,cod_total,is_cod)


        data = WixHelper.prepare_context_for_order(user_email,billing_address,shipping_address,line_items,total_price,is_cod,cod_total)

        return data, product_variant_decrement, product_quantity_decrement

    def _create_order(self, order_context):
        response = dict()
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=ORDER_PATH)
        token = self.generate_access_refresh_token()
        
        if not token:
            
            response['success'] = False
            response['error'] = 'Service down. Try again later.'
            return response

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)
        api.update_body(order_context)
        api.post()

        res = api.fetch_response()

        if res:
            response['success'] = True
            response['response'] = res

        else:
            response['success'] = False
            response['error'] = api.response.text

        return response

    def place_orders_util(self, order_lines, brand_name,brand_mappings):

        store = BrandCred.objects.filter(brand__private_metadata__source_name=brand_name).first()

        if not store:
            return {'success': False}
        try:
            self.instance_id = get_fernet_encoder().decrypt(store.access_key.encode()).decode('utf-8')
            self.refresh_token = get_fernet_encoder().decrypt(store.access_pass.encode()).decode('utf-8')
        except:
            self.instance_id = store.access_key
            self.refresh_token = store.access_pass


        order_context, product_variant_not_decrement_dict, product_quantity_decrement_dict = self._create_order_context_from_wix(order_lines, brand_mappings)
        res_data = self._create_order(order_context)

        if res_data['success']:
            instance = WixIntegration()
            instance.save_order_mapping(res_data['response'],order_lines)

        return res_data
    
    #Webhook Functions

    def _fetch_product_data_from_wix_by_id(self, product_id):
        _path = PRODUCTS_GET_PATH+'/'+product_id
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=_path)
        collection_dict = self._fetch_collections_for_product()
        token = self.generate_access_refresh_token()
        
        if not token:
            return None

        inventory_variant_dict = self._fetch_inventory_variant_dict_by_productId(product_id)

        if not inventory_variant_dict:
            return None

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)
        api.get()

        if not api.fetch_response():
            return None

        current_response = api.fetch_response()
        
        product = current_response.get('product')

        if product['manageVariants']==True:

            variants = product['variants']

            for variant in variants:
                variant['quantity'] = inventory_variant_dict.get(variant['id']) or 0

            product['variants'] = variants
        
        collection_data = []

        for c_id in product['collectionIds']:
            collection = collection_dict.get(c_id)

            if collection:
                collection_data.extend(collection)

        product['collections_data'] = collection_data

        return product
    
    def _update_delete_product_data_in_collection(self,data,delete=False):
        
        response = self._fetch_product_data_by_instance_id_from_wix_store(self.instance_id)
        product_data = self._get_value_by_key(response,'product_data')

        for i in range(len(product_data)):
            if product_data[i]['id']==data['id']:
                product_data.pop(i)
                break
        
        if not delete:
            product_data.append(data)

        filter_query = {'instance_id': self.instance_id}
        update_query = {'$set': {'product_data': product_data}}
        results = self._get_instance_of_mongo_connection().update_data(filter_query, update_query , PRODUCT_COLLECTION_NAME)
        response_context = dict()
        response_context['result'] = results

    def add_new_product_from_webhook(self, data):

        store = self._fetch_store_by_instance_id_from_wix_store(self.instance_id)

        if not store:
            return
        
        try:
            self.refresh_token = get_fernet_encoder().decrypt(store.access_pass.encode()).decode('utf-8')
        except:
            self.refresh_token = store.access_pass

        brandName = store.brand.private_metadata.get('source_name')
        product_data = self._fetch_product_data_from_wix_by_id(data.get('productId'))
        
        if not product_data:
            return
        
        # self._update_delete_product_data_in_collection(product_data)

        self._create_products_util([product_data], brandName)

    
    def delete_product_from_webhook(self, data):

        instance = WixIntegration()
        instance.disable_publish_product_from_postgres_by_product_id_brand(data.get('productId'))

    
    def update_product_from_webhook(self, data,cur_product_data=False,resync=False):

        store = self._fetch_store_by_instance_id_from_wix_store(self.instance_id)

        if not store:
            return
        
        try:
            self.refresh_token = get_fernet_encoder().decrypt(store.access_pass.encode()).decode('utf-8')

        except:
            self.refresh_token = store.access_pass

        brand_name = store.brand.private_metadata.get('source_name')
        
        if not cur_product_data:
            new_product_data = self._fetch_product_data_from_wix_by_id(data.get('productId'))
            if new_product_data:
                new_product_data = [new_product_data]

        else:
            new_product_data = [data]

        #is_document_large = False
        '''
        product_list.append(new_product_data[0])
        val_dict = {'product_data': new_product_data}
        response = self._update_productdata_in_mongo(product_list, shop_id, new_product_data[0], brand_name, is_document_large=is_document_large)
        '''

        instance = WixIntegration()

        #instance.delete_existing_product_images(product_id)
        '''
        mapping = BrandVariantZaamoMapping.objects.filter(brand_name = brand_name, product_id_brand=product_id)

        if not mapping:
            self.add_new_product_to_store_from_webhook(product_id, store_url)
            return {'message': 'product created'}
        '''

        if not new_product_data:
            return

        product_mapping_list = []
        prod_dict = new_product_data[0]
        prod_dict['vendor'] = brand_name
        product_meta = instance.base_product_mapper(prod_dict)

        for product in product_meta:
            product_mapping_list.append(product['product.brand_variant_zaamomapping'].copy())

        instance.delete_variation_if_removed_from_store(product_mapping_list)

        instance.update_inventory_and_price(new_product_data[0], brand_name)

        if not resync:
            
            product_list = self.fetch_product_data_from_mongo(brand_name)

            exisiting_product = dict()
            for i in range(len(product_list)):

                if not isinstance(product_list[i],dict):
                    continue

                if product_list[i]['id']==data.get('productId',''):
                    exisiting_product = product_list.pop(i)
                    break
            instance.update_brand_price_record(new_product_data[0], brand_name,exisiting_product)


    def fetch_categories_tags(self, brand_name):
        data = defaultdict(set)
        
        product_data = self.fetch_product_data_from_mongo(brand_name)

        product_list = self._get_value_by_key(product_data,'product_data')

        if not product_list:
            return data

        for product in product_list:
            collections_data = product.get('collections_data')

            if collections_data:

                for collection in collections_data:
                    collection_name = collection.get('name')

                    if collection_name:
                        data['collection'].add(collection_name)

        return data

    def fetch_product_brand_ids_from_collections(self,collections, brand_name, for_pdp=True):
        collection_product_id = defaultdict(list)
        product_list = self.fetch_product_data_from_mongo(brand_name)

        for product in product_list:
            product_id = product['id']
            collection_data = product.get('collections_data')
            if collection_data:
                for collection in collection_data:

                    c_name = collection.get('name')

                    if not c_name:
                        continue

                    collection_product_id[c_name].append(product_id)
        
        if not for_pdp:
            return collection_product_id

        product_brand_ids = []

        for collection in collections:
            product_brand_ids.extend(collection_product_id[collection])
        
        return product_brand_ids

    def get_mapped_product_from_brand_name(self, brand_name):

        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        
        if product_data:

            product_data_dict = defaultdict(list)

            for product in product_data:

                product_data_dict[product['product.brand_variant_zaamomapping']['product_id_brand']].append(product)
            
            return product_data_dict

        category_product_id = defaultdict(list)
        product_list = self.fetch_product_data_from_mongo(brand_name)

        product_data = defaultdict(list)
        instance = WixIntegration()
        
        for prod_dict in product_list:
            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                product_data[prod_dict['id']] = product_meta

        return product_data
    
    def create_product_from_product_variant_id(self, brand_name, product_id_brand, variant_id_brands):
       
        product_meta = self.fetch_product_data_from_gridfs_by_name(f"{brand_name}_mapped",key='mapped_product_data')
        instance = WixIntegration()
        product_to_create = []
        
        for product in product_meta:
            brand_mapping = product['product.brand_variant_zaamomapping']
            
            if not brand_mapping['product_id_brand']==product_id_brand:
                continue
            temp_variant_ids = brand_mapping.get('variant_id_brands')
            
            temp_variant_ids.sort()
            variant_id_brands.sort()

            if temp_variant_ids==variant_id_brands:

                product_to_create.append(product)
                break

        if not product_to_create:
            return None
            
        instance.push_inventory(product_to_create,from_celery=False)
        return product_to_create[0]

    def unpublish_product_whose_mapping_not_exist(self,product_id_brands_list,store_name):
        
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=store_name).values_list('product_id_brand', flat=True)
        ids_to_unpublish = set(brand_mappings).difference(set(product_id_brands_list))
        instance = WixIntegration()

        for product_id in list(ids_to_unpublish):
            try:
                instance.disable_publish_product_from_postgres_by_product_id_brand(product_id)
            except Exception as e:
                logger.exception(e)
                continue

    def fetch_product_data_from_mongo(self,store_name):
        
        if not self.instance_id:
            result = self._fetch_product_data_by_name_from_wix_store(store_name)
            product_data = self._get_value_by_key(result,'product_data')

        else:
            result = self._fetch_product_data_by_instance_id_from_wix_store(self.instance_id)
            product_data = self._get_value_by_key(result,'product_data')

        if product_data and isinstance(product_data,str):
            product_data = json.loads(product_data)
            
        if not product_data:
            product_data = self.fetch_product_data_from_gridfs_by_name(store_name)
        
        if not product_data:
            return []

        return product_data


    def get_brand_ids_for_resync(self):
        active_brands = Brand.objects.filter(status__in=[BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER],brand_source='wix').values_list('id',flat=True)
        return list(active_brands)
        
    def resync_price_and_inventory(self,brand_ids):
        
        success_names = []
        fail_names = []
        start_time = TimeUtilities.get_current_date_time()
        f = get_fernet_encoder()
        brand_creds = BrandCred.objects.filter(brand_id__in=brand_ids).select_related('brand')
        for document in brand_creds:

            try:
                
                try:
                    self.instance_id = f.decrypt(document.access_key.encode()).decode('utf-8')
                    self.refresh_token = f.decrypt(document.access_pass.encode()).decode('utf-8')
                except:
                    self.instance_id = document.access_key
                    self.refresh_token = document.access_pass
                
                
                store_name= document.brand.private_metadata.get('source_name') or document.brand.brand_name

                if not store_name:
                    continue

                self.insert_product_data_from_wix_store(store_name,resync=True)

                product_data = self.fetch_product_data_from_mongo(store_name)

                if not product_data:
                    continue

                product_id_brands_list = []

                for product in product_data:
                    
                    if not product.get('id'):
                        fail_names.append(store_name)
                        continue

                    product_id_brands_list.append(StringUtilities.convert_object_to_string(product.get('id')))
                    
                    self.update_product_from_webhook(product, cur_product_data=True,resync=True)

                self.unpublish_product_whose_mapping_not_exist(product_id_brands_list,store_name)

                self.access_token=None
                self.refresh_token=None
                self.auth_generated_time=None
                
                success_names.append(store_name)
            
            except Exception as e:
                name = document.brand.private_metadata.get('source_name') or document.brand.brand_name
                fail_names.append(name)
                logger.exception(e)
    
                self.access_token=None
                self.auth_generated_time=None
                self.refresh_token=None
                continue

        BrandResyncLog.objects.create(
            failed_brands = fail_names,
            success_brands = success_names,
            source = 'wix',
            start_time = start_time

        )

    def fetch_discount_list(self,brand_cred):
        discounts = []
        api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=DISCOUNT_PATH)
        token = self.generate_access_refresh_token()
        brand_name_private = brand_cred.brand.private_metadata.get('source_name')
        brand_name = brand_cred.brand.brand_name
        product_data = self._fetch_product_data_by_name_from_wix_store(brand_name_private)

        if product_data and isinstance(product_data,str):
            product_data = json.loads(product_data)
            
        if not product_data:
            product_data = self.fetch_product_data_from_gridfs_by_name(brand_name_private)
        
        collection_product_dict = defaultdict(list)

        for product in product_data:
            collection_data= product.get('collections_data',[])
            for collection in collection_data:
                collection_product_dict[collection['name']].append(product.get('name'))

        if not token:
            return discounts

        headers = {'Authorization': self.access_token}
        api.update_headers(headers)

        body = WixHelper.get_body_for_discount_api()
        api.update_body(body)
        api.post()
        current_response = api.fetch_response()
        coupons = current_response.get('coupons')
        
        if not coupons:
            return discounts
        
        for coupon in coupons:
            details = coupon.get('specification')
            active = details.get('active')

            if not active:
                continue

            code = details.get('code')
            start = TimeUtilities.convert_epoch_to_datetime(details.get('startTime'))
            expiry = TimeUtilities.convert_epoch_to_datetime(details.get('expirationTime'))
            code_type = details.get('type')
            limitPerCustomer = details.get('limitPerCustomer') or 'No Limit'
            usageLimit = details.get('usageLimit') or 'No Limit'
            minimum_subtotal = details.get('minimumSubtotal') or 0

            if code_type=='MoneyOff':

                value = details.get('moneyOffAmount')

            elif code_type=='PercentOff':

                value = details.get('percentOffRate')

            elif code_type=='FreeShipping':

                value = 'Free Shipping'

            elif code_type=='FixedPrice':

                value = details.get('fixedPriceAmount')

            elif code_type=='BuyXGetY':

                value = f"Buy {details.get('buyXGetY').get('x')} Get {details.get('buyXGetY').get('y')} Free"

            displayData = coupon.get('displayData')


            if displayData:
                products = []
                group_type = coupon['scope']['group']['name']

                if group_type=='collection':
                    collection_name = displayData['name']
                    product_join = collection_product_dict[collection_name]
                
                elif group_type=='product':
                    product_join = displayData['name']
            
            if not product_join:
                product_join = ['All Products']


            discounts.append([brand_name, 
                'wix', 
                code, 
                value, 
                code_type,
                True if code_type =='FreeShipping' else False,
                minimum_subtotal,
                ', '.join(product_join),
                start,
                expiry,
                limitPerCustomer,
                usageLimit])

        return discounts

    
    def update_order_status_from_webhook(self, order_data):
        
        store = self._fetch_store_by_instance_id_from_wix_store(self.instance_id)

        if not store:
            return
        
        brandName = store.brand.private_metadata.get('source_name')
        status = order_data.get('fulfillmentStatus')
        order_brand_id = order_data.get('id')
        
        brand_id = store.brand_id
        
        if not status:
            return
        
        zaamo_status = WixHelper.get_brand_to_zammo_order_status(status)
        
        if not zaamo_status:
            return

        instance = WixIntegration()
        fulfillment_status_update = instance.update_status_in_fulfillment(order_brand_id, zaamo_status,brand_id)

        if not fulfillment_status_update:
            return
            
        etlLoader = self._get_instance_of_etl_loader()

        for id,status in fulfillment_status_update.items():

            etlLoader.update_fulfillment_status(id,status)

    
    def update_order_status(self):
        
        orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='wix',
                        updated_at__gte=TimeUtilities.get_n_days_before_date(60)
                        ).exclude(order_line_zaamo_id__in=Subquery(FulfillmentLine.objects.filter(fulfillment__status=FulfillmentStatus.DELIVERED).values('order_line_id'))).select_related('brand')

        brand_cred_wix = BrandCred.objects.filter(brand__brand_source='wix').select_related('brand')
        brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_wix}

        for order_m in orders:
            try:
                name = order_m.brand.private_metadata.get('source_name')
                result = brand_cred_dict.get(name)
                
                try:
                    self.instance_id = get_fernet_encoder().decrypt(result.access_key.encode()).decode('utf-8')
                    self.refresh_token = get_fernet_encoder().decrypt(result.access_pass.encode()).decode('utf-8')
                except:
                    self.instance_id = result.private_metadata.get('instance_id')
                    self.refresh_token = result.access_pass
                self.access_token = None
                api = ApiClient(host=WIX_GATEWAY['WIX_BASE_URL'], path=f"{ORDER_PATH}/{order_m.order_id_brand}")
                token = self.generate_access_refresh_token()
                
                if not token:
                    continue

                headers = {'Authorization': self.access_token}
                api.update_headers(headers)
                api.get(send_body=False)

                order = api.fetch_response()
                
                if order:
                    order_data = order.get('order')
                    
                    self.update_order_status_from_webhook(order_data)

            except Exception as e:
                logger.exception(e)
                continue
