from collections import defaultdict
import logging
import ujson as json
import graphene
from django.db.models import Q, Subquery
from saleor.brand.models import Brand, BrandCred
from saleor.brand.states import BrandStatusEnum
from saleor.external_services import get_fernet_encoder
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
from saleor.product.models import BrandVariantZaamoMapping
from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from .constants import (BASE_API, ORDER_CREATE_PATH, PRODUCTS_PATH,
                         STORE_COLLECTION_NAME, PRODUCT_COLLECTION_NAME,
                           STORE_PATH)
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.api_client import ApiClient
from .mydukaan_helper import MyDukaanHelper
from saleor.product import bulk_products_import as etl
from saleor.external_services.integrations.mydukaan import MyDukaanIntegration
from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)

class MyDukaanImpl():


    mongo_conn = None
    authtoken = None

    def __init__(self) -> None:
        
        self.authtoken = None

    def get_authtoken(self):

        return self.authtoken
    
    def set_authtoken(self, a):

        self.authtoken = a
    
    def _get_instance_of_mongo_connection(self):

        if self.mongo_conn is None:
            self.mongo_conn = MongoConn()

        return self.mongo_conn


    def _get_instance_of_etl_loader(self):

        
        etl_loader = etl.ETLDataLoader()

        return etl_loader


    def get_value_by_key(self, results, key):

        for res in results:
            value = res.get(key)

            if value:
                return value
            else:
                return ''

    def get_auth_token(self, id=None, store_name=None):

        if id:
            brand_cred = BrandCred.objects.filter(private_metadata__store_id = id).first()

            if brand_cred:
                token= brand_cred.auth_token
            
        if store_name:

            brand_cred = BrandCred.objects.filter(Q(brand__private_metadata__source_name=store_name) | Q(brand__brand_name = store_name)).first()
            
            if brand_cred:
                token = brand_cred.auth_token

        try:
            token = get_fernet_encoder().decrypt(token.encode()).decode('utf-8')
        
        except:
            pass
        
        return token
    
    def get_store_uuid(self, id=None, store_name=None):
        store_uuid = None
        if id:
            brand_cred = BrandCred.objects.filter(private_metadata__store_id = id).first()

            if brand_cred:
                store_uuid= brand_cred.private_metadata.get('store_uuid')
            
        if store_name:

            brand_cred = BrandCred.objects.filter(Q(brand__private_metadata__source_name=store_name) | Q(brand__brand_name = store_name)).first()
            
            if brand_cred:
                store_uuid= brand_cred.private_metadata.get('store_uuid')

        
        return store_uuid

    def _fetch_product_list_from_mydukaanAPI(self):

        try:
            product_list = []
            api = ApiClient(host=BASE_API, path=PRODUCTS_PATH)
            header = MyDukaanHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            
            api.add_url_param('page',1)

            api.add_header('Authorization',f"Bearer {self.authtoken}")
            api.get()
            if not api.fetch_response():
                return product_list
                    
            page = 1
            count = 0

            while True:
                if count==1000:
                    return product_list

                api.update_url_params({'page':page})
                
                api.get()
                current_page_product_list = api.fetch_response()
                current_page_product_list = current_page_product_list.get('results',[])

                if not current_page_product_list:
                    return product_list

                product_list.extend(current_page_product_list)
                page+=1
                count+=1

        except Exception as e:
            return []

    def insert_mapped_product_data_to_mongo(self, product_data, store_name, store_id):
        mapped_product_list = []
        instance = MyDukaanIntegration()

        for prod_dict in product_data:
            prod_dict['vendor'] = store_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                mapped_product_list.extend(product_meta)
            
        self.insert_mapped_data_to_gridfs(store_name, mapped_product_list,store_id)

    def insert_mapped_data_to_gridfs(self, store_name, mapped_product_list, store_id):

        if not mapped_product_list:
            return 

        p_data = {'store_id': store_id, 'store_name': store_name, 'mapped_product_data': mapped_product_list}
        file_name = f"{store_name}_mapped"

        existing_product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')

        self._get_instance_of_mongo_connection().delete_gridfs(file_name)
        
        p_data = json.dumps(p_data)
        result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, file_name, encoding='utf-8')

    
    def update_brand_record_for_resync(self,product_list,brand_name,product_data_id_existing):
        if not product_list or not product_data_id_existing:
            return
        
        instance = MyDukaanIntegration()

        for product in product_list:
            existing_product = product_data_id_existing.get(product['uuid'])
            
            if not existing_product:
                continue
            
            instance.update_brand_price_record(product,brand_name,existing_product)

    def insert_product_data_from_mydukaan_store(self, shop,resync=False):
        shop_name = shop.get('name')
        store_id = shop.get('id')
        response_context = dict()
        
        store_name = shop_name
        product_list = self._fetch_product_list_from_mydukaanAPI()

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False
            return response_context

        post_data = {'store_id': store_id, 'store_name': store_name, 'product_data': json.dumps(product_list)}
        
        existing_product_data = self.fetch_product_data_from_mydukaan_store_by_name(store_name)

        data_exist = False
        for existing_product in existing_product_data:
            existing_product_data = existing_product
            data_exist = True
            break
        
        if data_exist:
            s_name = existing_product_data.get('store_name')
            product_data_existing = existing_product_data.get('product_data')
            
            if product_data_existing and isinstance(product_data_existing,str):
                product_data_existing = json.loads(product_data_existing)
                
            product_data_id_existing = dict()

            for product in product_data_existing:
                product_data_id_existing[product['uuid']] = product

        else:
            s_name = None
            product_data_id_existing = dict()

        if s_name:
            try:
                if resync:
                    self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)
                    
                self._get_instance_of_mongo_connection().update_data({'store_id': store_id}, {'$set': post_data}, PRODUCT_COLLECTION_NAME)
                self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': store_name}, PRODUCT_COLLECTION_NAME)

        else:
            self._get_instance_of_mongo_connection().insert_data(post_data, PRODUCT_COLLECTION_NAME)

        existing_product_data = self.fetch_product_data_from_mydukaan_store_by_name(store_name)
        s_name = self.get_value_by_key(existing_product_data,'store_name')

        if not s_name:
            p_data = {'store_id': store_id, 'store_name': store_name, 'product_data': product_list}
            existing_product_data = self.fetch_product_data_from_gridfs_by_name(store_name)

            if existing_product_data:
                if resync:
                    
                    product_data_id_existing = dict()

                    for product in existing_product_data:
                        product_data_id_existing[product['uuid']] = product

                    self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)
                
                self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            
            p_data = json.dumps(p_data)
            result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, store_name, encoding='utf-8')
        
        self.insert_mapped_product_data_to_mongo(product_list,store_name, store_id)
        
        brand_collection_create_inst = BrandCollectionCreate()
        brand_collection_create_inst.save_brand_collection_name(store_name)
        
        response_context['result'] = 'Data for products of shop stored successfully'
        response_context['success'] = True
        response_context['product_list'] = product_list

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False

        return response_context

    def fetch_product_data_from_mydukaan_store(self, store_url) -> dict:

        get_store_data = {'store_url': store_url}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)
        response_context = dict()

        if results:
            response_context['result'] = results

        return response_context

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

    def fetch_log_data_from_gridfs_by_url(self, url) -> list:
        log_list = []

        try:
            get_store_data = {'filename': url}
            results = self._get_instance_of_mongo_connection().fetch_one_gridfs(get_store_data)

            if results:

                log_data = json.loads(results.read())
                log_list = log_data.get('log')
        
        except Exception as e:
                logger.exception(f'Error while fetching from gridfs {e}, url :: {url}, key:: log data')

        return log_list

    def fetch_product_data_from_mydukaan_store_by_name(self, name) -> dict:

        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)
        
        if results:
            return results

        return None

    def insert_store_data_from_mydukaan_store(self, bearer_token):
        
        api = ApiClient(host=BASE_API, path=STORE_PATH)
        api.update_headers({'Authorization':f"Bearer {bearer_token}"})
        self.set_authtoken(bearer_token)
        api.get()
        shop = dict()
        if not api.fetch_response():
            message = f'Store not found for the bearer_token :: {bearer_token}'
            logger.exception(message)
            return {'success':False,'error':message}
        else:
            shop = api.fetch_response()

        response_context = dict()

        if shop:
            try:
                shop = shop.get('results')[0]
            except:
                shop = dict()
            
            if not shop:
                
                message = f'Store not found for the bearer_token :: {bearer_token}'
                logger.exception(message)
                return {'success':False,'error':message}
            
            existing_shop = self.fetch_store_by_id_from_mydukaan_store(shop.get('id'))


            existing_shop_details = existing_shop['result']
            existing_shop_name = self.get_value_by_key(existing_shop_details,'name')
            
            if existing_shop_name:
                self._get_instance_of_mongo_connection().update_data({'id': shop.get('id')}, {'$set': shop}, STORE_COLLECTION_NAME)

            else:
                self._get_instance_of_mongo_connection().insert_data(shop, STORE_COLLECTION_NAME)
            shop['token'] = bearer_token
            response_context['shop'] = shop
            response_context['result'] = 'Data for shop stored successfully'
        
        return response_context

    
    def fetch_store_by_id_from_mydukaan_store(self,store_id) -> dict:

        get_store_data = {'id': store_id}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, STORE_COLLECTION_NAME)
        response_context = dict()

        response_context['result'] = results

        return response_context

        
    def _update_productdata_in_mongo(self, product_list, new_product, is_document_large=False,store_name=None):

        response_context = dict()

        if not product_list:
            return response_context

        if is_document_large:
            
            post_data = {'store_url': self.url, 'store_name': store_name, 'product_data': product_list}
            
            self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            data = json.dumps(post_data)

            results = self._get_instance_of_mongo_connection().insert_one_gridfs(data, store_name, encoding='utf-8')
        else:
            filter_query = {'store_url': self.url}
            update_query = {'$set': {'product_data': json.dumps(product_list)}}
            try:
                results = self._get_instance_of_mongo_connection().update_data(filter_query, update_query , PRODUCT_COLLECTION_NAME)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': store_name}, PRODUCT_COLLECTION_NAME)
                return self._update_productdata_in_mongo(self, product_list, new_product, is_document_large=True,store_name=store_name)
            
        instance = MyDukaanIntegration()
        new_product['vendor'] = store_name
        product_meta = instance.base_product_mapper(new_product)
        existing_product_data = self.fetch_product_data_from_gridfs_by_name(f"{store_name}_mapped", key='mapped_product_data')

        mapped_product_list = []

        for mapped_data in existing_product_data:
            
            if mapped_data['product.brand_variant_zaamomapping']['product_id_brand'] == new_product['uuid']:
                continue

            mapped_product_list.append(mapped_data)
        
        mapped_product_list.extend(product_meta)
        
        self.insert_mapped_data_to_gridfs(store_name, mapped_product_list, self.url)
        response_context['result'] = results

        return response_context

    def decode_fernet_encoded(encrypted_string):
        f_encoder = get_fernet_encoder()

    def save_brand_creds(self,brand_global_id,store_credentials):
        brand_id = graphene.Node.from_global_id(brand_global_id)[1]
        f_encoder = get_fernet_encoder()
        
        default = {
                    'access_key': store_credentials.get('uuid'),
                    'auth_token': f_encoder.encrypt(store_credentials.get('token').encode()).decode('utf-8'),
                    'url': store_credentials.get('custom_domain') or store_credentials.get('custom_domain') or store_credentials.get('uuid'),
                    'private_metadata':{'store_id':store_credentials.get('id'),'store_uuid':store_credentials.get('uuid')}
                }
                
        brand_cred = BrandCred.objects.update_or_create(brand_id=brand_id,defaults=default)

    def create_brand_from_MyDukaan(self, shop):
        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(shop.get("name"))

        if brand_id:
            self.save_brand_creds(brand_id,shop)
            return brand_id

        brand_info = MyDukaanHelper.create_brand_context_from_mydukaan(shop)
        brand_id = etlLoader.create_brand(brand_info)
        self.save_brand_creds(brand_id,shop)
        return brand_id

    def _create_products_util(self, val_dict, brand_name, from_celery=True, check_existing=False, is_mapped=False):
        product_list = []
        instance = MyDukaanIntegration()

        if is_mapped:
            
            for chunks in instance.gen_chunks(val_dict):
                instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery

            return {'success': True}

        for prod_dict in val_dict:

            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)

            if product_meta:
                product_list.extend(product_meta)
                
        if not product_list:
            return {'success': False}
        
        if check_existing:
            p_list = []

            for product in product_list:
                mapping_json = product.get('product.brand_variant_zaamomapping',{})
                product_id_brand = mapping_json.get('product_id_brand')
                variant_id_brands = mapping_json.get('variant_id_brands')
                brand_zaamo_mappings = None

                if not product_id_brand:
                    continue

                if variant_id_brands:
                    brand_zaamo_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id_brand, variant_id_brand__in=variant_id_brands)

                else:
                    brand_zaamo_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id_brand)
                
                if not brand_zaamo_mappings:
                    p_list.append(product)
            
            product_list = p_list

        for chunks in instance.gen_chunks(product_list):
            instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery

        return {'success': True}

    def create_product_from_MyDukaan(self, shop):
        
        store_url = shop.get('store_url')
        response = {}
        brand_name = shop.get('name')
        
        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        is_mapped = True

        if not product_data:
            is_mapped = False
            product_data_response = self.fetch_product_data_from_mydukaan_store(store_url)
            product_dict = product_data_response.get('result')
            
            product_data = self.get_value_by_key(product_dict, 'product_data')
            
            if product_data and isinstance(product_data,str):
                product_data = json.loads(product_data)

            if not product_data:
                product_data = self.fetch_product_data_from_gridfs_by_name(shop.get('name'))

            if not product_data:
                response['message'] = "Store Data isn't available"
                response['success'] = False
                return response
                
        resp = self._create_products_util(product_data, brand_name, is_mapped=is_mapped)

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

        for i in range(len(order_lines)):
            item = dict()
            
            variant_brand_id = brand_mappings[i].variant_id_brand
            quantity = order_lines[i].quantity
            if variant_brand_id:
                item = {
                    "sku": variant_brand_id,
                    "quantity": quantity
                }
            
            
                line_items.append(item)

        return line_items

    def _create_order_context_from_mydukaan(self, order_lines, brand_mappings,store_uuid):
        
        order = order_lines[0].order
        billing_address = order.billing_address
        shipping_address = order.shipping_address
        user_email = order.get_customer_email()
        address_context = MyDukaanHelper.get_address_context(billing_address)
        line_items = self._set_line_items(order_lines, brand_mappings)


        data = MyDukaanHelper.prepare_context_for_order(billing_address,line_items,store_uuid,address_context)

        return data
    '''
    
    My Dukaan buyer and address creation to be used when guest orders aren't applicable

    def get_or_create_buyer(self,order_lines,store_uuid):
        order = order_lines[0].order
        response = dict()
        brand_id = order_lines[0].brand_id
        billing_address = order.billing_address
        user_id=order.user_id
        user_email = order.get_customer_email()
        address_context = MyDukaanHelper.get_buyer_context(user_email,billing_address,store_uuid)
        api = ApiClient(host=BASE_API, path=BUYER_CREATE_PATH)
        existing_buyer = MyDukaanBuyerMapping.objects.filter(Q(brand_id=brand_id) & 
                                    Q(Q(user_id=user_id) | Q(mobile=address_context.get('mobile')) | Q(email=user_email))).first()

        if existing_buyer:
            
            response['success']=True
            response['buyer_uuid']=existing_buyer.buyer_uuid
            return response

        api.update_body(address_context)
        api.add_header('Authorization',f"Bearer {self.authtoken}")
        
        api.post()
        address_data = api.fetch_response()

        if not address_data:
            response['success'] = False
            return response

        if address_data.get('data').get('uuid'):
            response['success']=True
            response['buyer_uuid']=address_data.get('data').get('buyer_uuid')
            self.save_buyer_data(response['buyer_uuid'],address_data.get('data').get('buyer_id'),user_id,brand_id,user_email,address_context.get('mobile'),address_context.get('name'))
            return response
        
        else:
            
            response['success'] = False
            return response

    def save_buyer_data(self,buyer_uuid,buyer_id,user_id,brand_id,email,mobile,name):
        instance = MyDukaanBuyerMapping()
        
        instance.buyer_id = buyer_id
        instance.buyer_uuid = buyer_uuid
        instance.name = name
        instance.brand_id = brand_id
        instance.email = email
        instance.mobile = mobile
        instance.user_id = user_id
        instance.save()

    def save_buyer_address_data(self,buyer_uuid,buyer_id,user_id,brand_id,email,mobile):
        instance = MyDukaanBuyerAddressMapping()
        
        instance.address_id = buyer_id
        instance.address_uuid = buyer_uuid
        instance.brand_id = brand_id
        instance.email = email
        instance.mobile = mobile
        instance.user_id = user_id
        instance.save()

    def get_or_create_buyer_address(self,order_lines):
        order = order_lines[0].order
        brand_id = order_lines[0].brand_id
        user_id = order.user_id
        response = dict()
        billing_address = order.billing_address
        address_context = MyDukaanHelper.get_address_context(billing_address)
        user_email = order.get_customer_email()

        existing_buyer_address = MyDukaanBuyerAddressMapping.objects.filter(Q(brand_id=brand_id) & 
                                    Q(Q(user_id=user_id) | Q(mobile=address_context.get('mobile')) | Q(email=user_email))).first()

        if existing_buyer_address:
            
            response['success']=True
            response['address_uuid']=existing_buyer_address.address_uuid
            return response

        api = ApiClient(host=BASE_API, path=BUYER_ADDRESS_CREATE_PATH)
        
        api.update_body(address_context)
        api.add_header('Authorization',f"Bearer {self.authtoken}")
        
        api.post()
        address_data = api.fetch_response()

        if not address_data:
            response['success'] = False
            return response

        if address_data.get('data').get('uuid'):
            response['success']=True
            response['address_uuid']=address_data.get('data').get('uuid')
            self.save_buyer_data(response['addres_uuid'],address_data.get('data').get('id'),user_id,brand_id,user_email,address_context.get('mobile'))
            return response
        
        else:
            
            response['success'] = False
            return response
    '''

    def _create_order(self, order_context):

        try:

            response = dict()
            api = ApiClient(host=BASE_API, path=ORDER_CREATE_PATH)
            
            api.update_body(order_context)
            api.add_header('Authorization',f"Bearer {self.authtoken}")
            
            api.post()

            if not api.fetch_response():
                response['success'] = False
                response['error'] = api.response.text
                return response
                    
            res = api.fetch_response()

            if res:
                response['success'] = True
                response['response'] = res
            
            else:
                response['success'] = False
                response['response'] = {
                                        'context': order_context,
                                        'res': res   
                                        }
                
                try:
                    resp = StringUtilities.convert_object_to_string(api.response.text)

                except Exception as e:
                    resp = f"Null response, error: {e}"

                response['error']=resp

            return response
        
        except Exception as e:
            
            response = f"context :: {order_context}"
            error = f"My Dukaan Order failed order creation. error :: {e}"
            logger.exception(response)
            return {'success':False, 'response': response, 'error':error}
        
    def place_orders_util(self, order_lines, brand_name,brand_mappings):
        
        try:
            auth_token = self.get_auth_token(store_name=brand_name)
            store_uuid = self.get_store_uuid(store_name=brand_name)
            self.set_authtoken(auth_token)
        
        except Exception as e:
            response = f"My Dukaan Order failed while fetching store detail from mongo. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
            logger.exception(response)
            return {'success':False, 'error': response}

        '''
        My Dukaan Address mapping to be used when guest order creation isn't applicable
        
        try:
            buyer = self.get_or_create_buyer(order_lines,store_uuid)
            
            if buyer.get('success'):
                buyer_uuid = buyer['buyer_uuid']
            
            else:

                response = f"My Dukaan Order failed while building customer. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
                logger.exception(response)
                return {'success':False, 'error': response}

            buyer_address = self.get_or_create_buyer_address(order_lines)

            if buyer_address.get('success'):
                address_uuid = buyer_address['address_uuid']
            
            else:
                
                response = f"My Dukaan Order failed while building customer address. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
                logger.exception(response)
                return {'success':False, 'error': response}

        
        except Exception as e:
            
            response = f"My Dukaan Order failed while building customer address. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
            logger.exception(response)
            return {'success':False, 'error': response}
        '''

        try:
            order_context = self._create_order_context_from_mydukaan(order_lines, brand_mappings,store_uuid)
        
        except Exception as e:
            
            response = f"My Dukaan Order failed while building order body. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
            logger.exception(response)
            return {'success':False, 'error': response}

        res_data = self._create_order(order_context)

        if res_data['success']==True:
            api_response = res_data['response']
            if type(api_response.get('data'))==dict:
                instance = MyDukaanIntegration()
                instance.save_order_mapping(order_lines,api_response.get('data').get('uuid'))
            else:
                return {'success':False, 'error': "API response is invalid."}

        return res_data

    #PDP 2 Functions

    
    def fetch_tags_product_id_dict(self, brand_name):
        data = defaultdict(list)
        
        product_data = self.fetch_product_data_from_mydukaan_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if product_list:

            for product in product_list:
                tags = product.get('tags')
                
                if tags:

                    for tag in tags:
                        tag_name = tag.get('name')

                        if tag_name:
                            data[tag_name].append(product.get('uuid'))

        return data

    def fetch_categories_tags(self, brand_name):
        data = defaultdict(set)
        
        product_data = self.fetch_product_data_from_mydukaan_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if product_list:

            for product in product_list:
                categories = product.get('categories')
                tags = product.get('tags')

                if categories:

                    for category in categories:
                        category_name = category.get('name')

                        if category_name:
                            data['category'].add(category_name)
                
                if tags:

                    for tag in tags:
                        tag_name = tag.get('name')

                        if tag_name:
                            data['tag'].add(tag_name)

        return data

    def fetch_categories_from_product_id(self,product_id_brand, brand_name):
        product_id_brand = NumberUtilities.convert_string_to_number(product_id_brand)
        category_product_id = defaultdict(list)
        product_data = self.fetch_product_data_from_mydukaan_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['uuid']

            if product_id_brand == product_id:

                categories_data = product.get('categories')

                if categories_data:

                    for category in categories_data:

                        c_name = category.get('name')

                        if not c_name:
                            continue

                        category_product_id[c_name].append(product_id)
                
                break
        
        return category_product_id


    def fetch_product_brand_ids_from_categories(self,categories, brand_name,for_pdp=True):
        category_product_id = defaultdict(list)
        product_data = self.fetch_product_data_from_mydukaan_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['uuid']
            categories_data = product.get('categories_data')

            if categories_data:

                for category in categories_data:

                    c_name = category.get('name')

                    if not c_name:
                        continue

                    category_product_id[c_name].append(product_id)
        
        if not for_pdp:
            return category_product_id
            
        product_brand_ids = []

        for category in categories:
            product_brand_ids.extend(category_product_id[category])
        
        return product_brand_ids

    def get_mapped_product_from_brand_name(self, brand_name):
        
        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        
        if product_data:

            product_data_dict = defaultdict(list)

            for product in product_data:

                product_data_dict[product['product.brand_variant_zaamomapping']['product_id_brand']].append(product)
            
            return product_data_dict

        product_cursor = self.fetch_product_data_from_mydukaan_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_cursor,'product_data')

        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        product_data = defaultdict(list)
        
        
        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return product_data
    
        instance = MyDukaanIntegration()
        
        for prod_dict in product_list:
            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                product_data[prod_dict['uuid']] = product_meta

        return product_data
    
    def create_product_from_product_variant_id(self, brand_name, product_id_brand, variant_id_brands):
        product_cursor = self.fetch_product_data_from_mydukaan_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_cursor,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)
        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        product_id_brand = NumberUtilities.convert_string_to_number(product_id_brand)
        variant_id_brands = [NumberUtilities.convert_string_to_number(id) for id in variant_id_brands]

        product_data = dict()
        product_to_create = []
        for prod_dict in product_list:

            if prod_dict['uuid']==product_id_brand:
                product_data = prod_dict
                break
        
        if not product_data:
            return None

        instance = MyDukaanIntegration()
        product_data['vendor'] = brand_name
        product_meta = instance.base_product_mapper(product_data)

        if len(product_meta)>1:
            for product in product_meta:
                brand_mapping = product['product.brand_variant_zaamomapping']
                temp_variant_ids = brand_mapping.get('variant_id_brands')
                temp_variant_ids.sort()
                variant_id_brands.sort()

                if temp_variant_ids==variant_id_brands:

                    product_to_create.append(product)
                    break
        else:
            product_to_create=product_meta
            
        if not product_to_create:
            return None
        
        instance.push_inventory(product_to_create,from_celery=False)
        return product_to_create[0]

    def unpublish_product_whose_mapping_not_exist(self,product_id_brands_list,store_name):
        
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=store_name).values_list('product_id_brand', flat=True)
        ids_to_unpublish = set(brand_mappings).difference(set(product_id_brands_list))
        instance = MyDukaanIntegration()

        for product_id in list(ids_to_unpublish):
            try:
                instance.disable_publish_product_from_postgres_by_product_id_brand(product_id)
            except Exception as e:
                logger.exception(e)
                continue


    def _add_product_to_postgres_from_update_webhook(self,data,store_name,exisiting_product=None):
        product_id = data.get('uuid')

        if not product_id:
            return {}

        instance = MyDukaanIntegration()

        instance.update_inventory_and_price(data, store_name)

        if exisiting_product:
            instance.update_brand_price_record(data, store_name,exisiting_product)

        instance.delete_variation_if_removed_from_store(data,store_name)

    def resync_price_and_inventory(self):
        results = self._get_instance_of_mongo_connection().fetch_data({}, STORE_COLLECTION_NAME)
        success_names = []
        fail_names = []
        results.close()
        
        active_brands = Brand.objects.filter(status__in=[BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER],brand_source='mydukaan')
        brand_creds = BrandCred.objects.filter(brand_id__in=active_brands.values('id')).select_related('brand')
        
        f = get_fernet_encoder()
        for document in brand_creds:
            try:

                store_name= document.brand.private_metadata.get('source_name') or document.brand.brand_name
                
                try:
                    token = f.decrypt(document.auth_token.encode()).decode('utf-8')
                except:
                    token = document.auth_token
                self.set_authtoken(token)
                shop = {
                    'name':store_name,
                    'token':token,
                    'id': document.private_metadata.get('store_id')

                }
                response = self.insert_product_data_from_mydukaan_store(shop,resync=True)
                
                if not response.get('success'):
                    continue

                product_data = response.get('product_list')
                
                try:
                    token = f.decrypt(document.auth_token.encode()).decode('utf-8')
                except:
                    token = document.auth_token
            
                if token:
                    self.set_authtoken(token)
                    product_id_brands_list=[]

                    for product in product_data:

                        if not product.get('uuid'):
                            continue

                        product_id_brands_list.append(StringUtilities.convert_object_to_string(product.get('uuid')))

                        self._add_product_to_postgres_from_update_webhook(product,store_name)

                    self.unpublish_product_whose_mapping_not_exist(product_id_brands_list,store_name)
                success_names.append(store_name)

            except Exception as e:
                fail_names.append(document.brand.private_metadata.get('source_name'))
                logger.exception(e)
                continue

        return fail_names,success_names

    def update_order_status_from_webhook(self, order_data,brand_id):
        status = order_data.get('status')
        order_brand_id = order_data.get('uuid')
        
        if not status:
            return
        
        zaamo_status = MyDukaanHelper.get_brand_to_zammo_order_status(status)

        if not zaamo_status:
            return

        instance = MyDukaanIntegration()
        fulfillment_status_update = instance.update_status_in_fulfillment(order_brand_id, zaamo_status,brand_id)

        if not fulfillment_status_update:
            return
            
        etlLoader = self._get_instance_of_etl_loader()

        for id,status in fulfillment_status_update.items():

            etlLoader.update_fulfillment_status(id,status)

    def update_order_status(self):
        orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='mydukaan', 
                        updated_at__gte=TimeUtilities.get_n_days_before_date(90)
                        ).exclude(order_line_zaamo_id__in=Subquery(FulfillmentLine.objects.filter(fulfillment__status=FulfillmentStatus.DELIVERED).values('order_id'))).select_related('brand')
    
        brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='mydukaan').select_related('brand')
        brand_cred_dict = {cred.brand_id:cred for cred in brand_cred_shopify}
        
        for order_m in orders:
            try:
                brand_id = order_m.brand_id
                
                result = brand_cred_dict.get(brand_id)

                try:
                    token = get_fernet_encoder().decrypt(result.auth_token.encode()).decode('utf-8')
                except:
                    token = result.auth_token

                self.set_authtoken(token)

                api = ApiClient(host=BASE_API, path=f'api/order/seller/{order_m.order_id_brand}/order/')
                header = MyDukaanHelper.get_default_header_with_user_agent()
                api.update_headers(header)
                api.add_header('Authorization',f"Bearer {token}")
                api.get()

                if api.fetch_response():
                    order = api.fetch_response().get('data')
                    if order:
                        self.update_order_status_from_webhook(order,brand_id)

            except Exception as e:
                logger.exception(e)
                continue
