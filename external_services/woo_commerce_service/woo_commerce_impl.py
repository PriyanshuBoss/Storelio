from collections import defaultdict
from decimal import Decimal
import logging
import math
import ujson as json
import time
import graphene
import requests
from django.db.models import Q
from saleor.brand.models import Brand, BrandCred,BrandResyncLog
from django.db.models import Subquery
from saleor.brand.states import BrandStatusEnum
from saleor.external_services import get_fernet_encoder, update_order_metadata_with_extra_charge
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
from saleor.product.models import BrandVariantZaamoMapping
from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from .constants import (EMAIL_SETTING_PATH, GENERAL_SETTING_PATH, ORDER_CREATE_PATH, PRODUCTS_PATH,
                        SPECIFIC_PRODUCT_PATH, STORE_COLLECTION_NAME, PRODUCT_COLLECTION_NAME,
                        PRODUCT_FETCH_LIMIT, BASE_API_PATH, WEBHOOK_PATH, VARIANTS_PATH)
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.api_client import ApiClient
from .woocommerce_helper import WooCommerceHelper
from saleor.product import bulk_products_import as etl
from saleor.external_services.integrations.woocommerce import WooCommerceIntegration
from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)

class WooCommerceImpl():


    mongo_conn = None
    url = None
    authtoken = None

    def __init__(self, store_url = None) -> None:
        
        self.url = store_url
        self.authtoken = None

    def get_url(self):

        return self.url
    
    def set_url(self, a):

        self.url = a

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

    def get_store_url_from_woo_commerce_store(self, store_name=None):
        url=''
        brand_cred = BrandCred.objects.filter(Q(brand__private_metadata__source_name=store_name) | Q(brand__brand_name = store_name)).first()

        if brand_cred:
            url = brand_cred.url

        return url

    def get_auth_token(self, store_url=None, store_name=None):

        get_store_token = {}
        
        token = None

        if store_url:
            brand_cred = BrandCred.objects.filter(url = store_url).first()

            if brand_cred:
                token= brand_cred.auth_token

            get_store_token['store_url'] = store_url
            

        if store_name:

            brand_cred = BrandCred.objects.filter(Q(brand__private_metadata__source_name=store_name) | Q(brand__brand_name = store_name)).first()
            
            if brand_cred:
                token = brand_cred.auth_token

        try:
            token = get_fernet_encoder().decrypt(token.encode()).decode('utf-8')
        
        except:
            pass
        
        return token

    
    def _fetch_variant_list_from_Product_ID(self, ProductID, use_auth_param=False,verify=True,retry=0):
        
        retry+=1
        if retry>3:
            return []

        try:
            variant_list = []
            path = VARIANTS_PATH.replace('{{id}}', str(ProductID))
            
            url = self._clean_url_for_APICLIENT()
            api = ApiClient(host=url, path=BASE_API_PATH+path)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            api.add_url_param('per_page',PRODUCT_FETCH_LIMIT)
            api.add_url_param('page',1)
            
            if use_auth_param:
                param = self._fetch_customer_key_and_secret_for_param()
                api.update_url_params(param)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return variant_list
            else:
                api.add_header('Authorization',self.authtoken)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return self._fetch_variant_list_from_Product_ID(ProductID, use_auth_param=True,verify=verify,retry=retry)

            page = 1
            count = 0

            while True:

                if count==1000:
                    break
                
                api.update_url_params({'page':page})
                api.get(send_body=False,verify=verify)
                current_page_variant_list = api.fetch_response()
                
                if not current_page_variant_list:
                    break

                variant_list.extend(current_page_variant_list)
                
                if len(current_page_variant_list)<PRODUCT_FETCH_LIMIT:
                    break
                
                page+=1
                count+=1
            
            return variant_list
        
        except requests.exceptions.SSLError as e:
            return self._fetch_variant_list_from_Product_ID(ProductID, use_auth_param=True,verify=False,retry=retry)
    
    def _fetch_variant_data_from_Variant_ID(self, ProductID,VariantID, use_auth_param=False, verify=True,retry=0):

        retry+=1
        if retry>3:
            return []

        try:
            variant_data = dict()
            path = f"{VARIANTS_PATH.replace('{{id}}', str(ProductID))}/{VariantID}"
            
            url = self._clean_url_for_APICLIENT()
            api = ApiClient(host=url, path=BASE_API_PATH+path)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            api.add_url_param('per_page',PRODUCT_FETCH_LIMIT)
            api.add_url_param('page',1)
            
            if use_auth_param:
                param = self._fetch_customer_key_and_secret_for_param()
                api.update_url_params(param)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return variant_data
            else:
                api.add_header('Authorization',self.authtoken)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return self._fetch_variant_data_from_Variant_ID(ProductID,VariantID, use_auth_param=True,verify=verify, retry=retry)

            api.get(send_body=False,verify=verify)
            variant_data = api.fetch_response()
            
            return variant_data
        
        except requests.exceptions.SSLError as e:
            return self._fetch_variant_data_from_Variant_ID(ProductID,VariantID, use_auth_param=True,verify=False, retry=retry)
    
    
    def _fetch_specific_product_from_woo_commerceAPI(self, productID, use_auth_param=False,verify=True,retry=0):

        
        retry+=1
        if retry>3:
            return []

        try:
            path = SPECIFIC_PRODUCT_PATH.replace('{{id}}', str(productID))
            
            url = self._clean_url_for_APICLIENT()
            api = ApiClient(host=url, path=BASE_API_PATH+path)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            
            if use_auth_param:
                param = self._fetch_customer_key_and_secret_for_param()
                api.update_url_params(param)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()
                if not api_resp:
                    try:
                        resp = api.response.text
                    except Exception as e:
                        resp = f"Null response, error: {e}"

                    logger(f'Api Fetch failed woo commerce response :: {resp}, url :: {url}')
                    return None
            else:
                api.add_header('Authorization',self.authtoken)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return self._fetch_specific_product_from_woo_commerceAPI(productID, use_auth_param=True,verify=verify,retry=retry)

            product_data = api.fetch_response()

            if not product_data:
                try:
                    resp = api.response.text
                except Exception as e:
                    resp = f"Null response, error: {e}"
                logger(f'Api Fetch failed woo commerce response :: {resp}, url :: {url}')
                return None

            if product_data.get('variations'):

                variant_list = self._fetch_variant_list_from_Product_ID(productID)
                product_data['variations']=variant_list

            return product_data

        except requests.exceptions.SSLError as e:
            return self._fetch_specific_product_from_woo_commerceAPI(productID, use_auth_param=False,verify=False,retry=retry)

    def _clean_url_for_APICLIENT(self):
        
        url = self.url
        url = url.replace('http://','')
        url = url.replace('https://','')
        if '/' in url:
            url = url[:url.index('/')]

        return url
        
    def _fetch_product_list_from_woo_commerceAPI(self, use_auth_param=False,verify=True,retry=0):

        retry+=1
        if retry>3:
            return []

        try:
            product_list = []
            url = self._clean_url_for_APICLIENT()
            api = ApiClient(host=url, path=BASE_API_PATH+PRODUCTS_PATH)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            api.add_url_param('per_page',PRODUCT_FETCH_LIMIT)
            
            api.add_url_param('page',1)

            if use_auth_param:
                param = self._fetch_customer_key_and_secret_for_param()
                api.update_url_params(param)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return product_list
            else:
                api.add_header('Authorization',self.authtoken)
                
                api.get(send_body=False,verify=verify)
                api_resp = api.fetch_response()

                if not api_resp:
                    return self._fetch_product_list_from_woo_commerceAPI(use_auth_param=True,verify=verify,retry=retry)
                    
            page = 1
            count = 0

            while True:
                if count==1000:
                    return product_list

                api.update_url_params({'page':page})
                
                
                api.get(send_body=False,verify=verify)
                current_page_product_list = api.fetch_response()
                
                if not current_page_product_list:
                    return product_list

                for product in current_page_product_list:
                    
                    if product.get('variations'):
                        
                        variant_list = self._fetch_variant_list_from_Product_ID(product['id'],use_auth_param=use_auth_param)
                        product['variations']=variant_list

                product_list.extend(current_page_product_list)
                page+=1
                count+=1
        except requests.exceptions.SSLError as e:
            return self._fetch_product_list_from_woo_commerceAPI(use_auth_param=True,verify=False,retry=retry)

    def insert_mapped_product_data_to_mongo(self, product_data, store_name, store_url):
        mapped_product_list = []
        instance = WooCommerceIntegration()

        for prod_dict in product_data:
            prod_dict['vendor'] = store_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                mapped_product_list.extend(product_meta)
            
        self.insert_mapped_data_to_gridfs(store_name, mapped_product_list,store_url)

    def insert_mapped_data_to_gridfs(self, store_name, mapped_product_list, store_url):

        if not mapped_product_list:
            return 

        p_data = {'store_url': store_url, 'store_name': store_name, 'mapped_product_data': mapped_product_list}
        file_name = f"{store_name}_mapped"

        existing_product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')

        self._get_instance_of_mongo_connection().delete_gridfs(file_name)
        
        p_data = json.dumps(p_data)
        result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, file_name, encoding='utf-8')

    
    def update_brand_record_for_resync(self,product_list,brand_name,product_data_id_existing):
        if not product_list or not product_data_id_existing:
            return
        
        instance = WooCommerceIntegration()

        for product in product_list:
            existing_product = product_data_id_existing.get(product['id'])
            
            if not existing_product:
                continue
            
            instance.update_brand_price_record(product,brand_name,existing_product)

    def insert_product_data_from_woo_commerce_store(self, shop_name,resync=False):
        
        response_context = dict()
        
        store_name = shop_name
        store_url = self.url
        product_list = self._fetch_product_list_from_woo_commerceAPI()

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False
            return response_context

        post_data = {'store_url': store_url, 'store_name': store_name, 'product_data': json.dumps(product_list)}
        
        self.insert_mapped_product_data_to_mongo(product_list,store_name, store_url)
        existing_product_data = self.fetch_product_data_from_woo_commerce_store_by_name(store_name)

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
                product_data_id_existing[product['id']] = product

        else:
            s_name = None
            product_data_id_existing = dict()
            

        if s_name:
            try:
                if resync:
                    self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)
                    
                self._get_instance_of_mongo_connection().update_data({'store_url': store_url}, {'$set': post_data}, PRODUCT_COLLECTION_NAME)
                self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': store_name}, PRODUCT_COLLECTION_NAME)

        else:
            self._get_instance_of_mongo_connection().insert_data(post_data, PRODUCT_COLLECTION_NAME)

        existing_product_data = self.fetch_product_data_from_woo_commerce_store_by_name(store_name)
        s_name = self.get_value_by_key(existing_product_data,'store_name')

        if not s_name:
            p_data = {'store_url': store_url, 'store_name': store_name, 'product_data': product_list}
            existing_product_data = self.fetch_product_data_from_gridfs_by_name(store_name)

            if existing_product_data:
                if resync:
                    
                    product_data_id_existing = dict()

                    for product in existing_product_data:
                        product_data_id_existing[product['id']] = product

                    self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)
                
                self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            
            p_data = json.dumps(p_data)
            result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, store_name, encoding='utf-8')
        
        
        brand_collection_create_inst = BrandCollectionCreate()
        brand_collection_create_inst.save_brand_collection_name(store_name)
        
        response_context['result'] = 'Data for products of shop stored successfully'
        response_context['success'] = True
        response_context['product_list'] = product_list

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False

        return response_context

    def fetch_product_data_from_woo_commerce_store(self, store_url) -> dict:

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

    def fetch_product_data_from_woo_commerce_store_by_name(self, name) -> dict:

        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)
        
        if results:
            return results

        return None

    def insert_store_data_from_woocommerce_store(self, woocommerce_cred_dict):
        
        url = self._clean_url_for_APICLIENT()
        api = ApiClient(host=url, path='wp-json/')
        header = WooCommerceHelper.get_default_header_with_user_agent()
        api.update_headers(header)
        api.get(send_body=False)
        token = WooCommerceHelper.generate_woocommerce_auth_token(woocommerce_cred_dict.get('store_access_key'),woocommerce_cred_dict.get('store_access_pass'))
        self.set_authtoken(token)
        woocommerce_cred_dict['auth_token']=token

        if not api.fetch_response():

            shop = dict()
            shop['url'] = self.url
        else:
            shop = api.fetch_response()

        response_context = dict()
        existing_shop = self.fetch_store_by_url_from_woo_commerce_store()

        if shop:
            woocommerce_cred_dict['name']=shop.get('name') or shop.get('url')
            
            store_details = WooCommerceHelper.structure_store_details_response(shop)

            existing_shop_details = existing_shop['result']
            existing_shop_name = self.get_value_by_key(existing_shop_details,'name')
            
            if existing_shop_name:
                self._get_instance_of_mongo_connection().update_data({'store_url': store_details.get('store_url') or self.url}, {'$set': store_details}, STORE_COLLECTION_NAME)

            else:
                self._get_instance_of_mongo_connection().insert_data(store_details, STORE_COLLECTION_NAME)

            response_context['shop'] = woocommerce_cred_dict
            response_context['result'] = 'Data for shop stored successfully'
        
        return response_context

    
    def fetch_store_by_url_from_woo_commerce_store(self) -> dict:

        get_store_data = {'store_url': self.url}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, STORE_COLLECTION_NAME)
        response_context = dict()

        response_context['result'] = results

        return response_context

    def _make_webhook_api_call(self,data,use_auth_param=False):
        
        url = self._clean_url_for_APICLIENT()
        api = ApiClient(host=url, path=BASE_API_PATH+WEBHOOK_PATH)
        header = WooCommerceHelper.get_default_header_with_user_agent()
        api.update_headers(header)

        
        if use_auth_param:
            param = self._fetch_customer_key_and_secret_for_param()
            api.update_url_params(param)
            api.get(send_body=False)
        else:
            api.add_header('Authorization',self.authtoken)
            api.get(send_body=False)
            if not api.fetch_response():
                return self._make_webhook_api_call(data, use_auth_param=True)

        api.add_url_param('per_page',PRODUCT_FETCH_LIMIT)
        
        api.add_url_param('page',1)
        page = 1
        count = 0
        delivery_url_list = []

        while True:
            if count==100:
                break

            api.update_url_params({'page':page})
            api = api.get(send_body=False)
            current_page_webhook_list = api.fetch_response()

            if not current_page_webhook_list:
                break

            url_list = [webhook['delivery_url'] for webhook in current_page_webhook_list]
            delivery_url_list.extend(url_list)
            page+=1
            count+=1

        if not data['delivery_url'] in delivery_url_list:
            
            url = self._clean_url_for_APICLIENT()
            api = ApiClient(host=url, path=BASE_API_PATH+WEBHOOK_PATH)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            
            if use_auth_param:
                param = self._fetch_customer_key_and_secret_for_param()
                api.update_url_params(param)
                api.post()

            else:
                api.add_header('Authorization',self.authtoken)
                api.post()
                if not api.fetch_response():
                    return self._make_webhook_api_call(data, use_auth_param=True)
            
            api.update_body(data)
            api.post()

    def create_webhooks_for_woo_commerce_store(self):
        
        if IS_BETA:
            return

        data = WooCommerceHelper.get_product_create_webhook_data()
        self._make_webhook_api_call(data)
            
        data = WooCommerceHelper.get_product_update_webhook_data()
        self._make_webhook_api_call(data)

        data = WooCommerceHelper.get_product_delete_webhook_data()
        self._make_webhook_api_call(data)

        data = WooCommerceHelper.get_order_update_webhook_data()
        self._make_webhook_api_call(data)
        
        
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
            
        instance = WooCommerceIntegration()
        new_product['vendor'] = store_name
        product_meta = instance.base_product_mapper(new_product)
        existing_product_data = self.fetch_product_data_from_gridfs_by_name(f"{store_name}_mapped", key='mapped_product_data')

        mapped_product_list = []

        for mapped_data in existing_product_data:
            
            if mapped_data['product.brand_variant_zaamomapping']['product_id_brand'] == new_product['id']:
                continue

            mapped_product_list.append(mapped_data)
        
        mapped_product_list.extend(product_meta)
        
        self.insert_mapped_data_to_gridfs(store_name, mapped_product_list, self.url)
        response_context['result'] = results

        return response_context


    def _add_product_to_postgres_from_webhook(self,data):

        product_data = []
        instance = WooCommerceIntegration()

        brand_cred = BrandCred.objects.filter(url=self.url).first()
        
        if brand_cred:
            shop_name = brand_cred.brand.private_metadata.get('source_name')
        
            product_data.append(data)
            
            resp = self._create_products_util(product_data, shop_name,from_celery=False, check_existing=True)
        
    def _add_product_to_postgres_from_update_webhook(self,data,shop_name,exisiting_product=None):
        product_id = data.get('id')

        if not product_id:
            return {}
        
        get_store_token = {'store_url': self.url}

        instance = WooCommerceIntegration()

        '''
        mapping = BrandVariantZaamoMapping.objects.filter(brand_name = shop_name, product_id_brand=product_id)
        
        if not mapping:
            token = self.get_auth_token(store_url=self.url)
            self.set_authtoken(token)
            self.add_new_product_to_store_from_webhook(data)
            return {'message': 'product created'}
        '''
        instance.update_inventory_and_price(data, shop_name)

        if exisiting_product:
            instance.update_brand_price_record(data, shop_name,exisiting_product)

        instance.delete_variation_if_removed_from_store(data,shop_name)

    def add_new_product_to_store_from_webhook(self, data):

        if data.get('type')=='variation':
            return {'message': 'Variant data is already added'}

        
        if not data.get('variations') or not data.get('attributes'):
            data = self._fetch_specific_product_from_woo_commerceAPI(data.get('id'))

        '''
        is_document_large = False
        product_response = self.fetch_product_data_from_woo_commerce_store(self.url)
        product_data = product_response['result']
        product_list = self.get_value_by_key(product_data, 'product_data')
        store = self.fetch_store_by_url_from_woo_commerce_store().get('result')
        store_name = self.get_value_by_key(store,'name')
        
        if not store_name:
            return {'message': 'Product import failed'}

        if not product_list:
            is_document_large = True
            product_list = self.fetch_product_data_from_gridfs_by_name(store_name)

        if not product_list:
            return {'message': 'Product import failed'}

        product_list.append(data)
        response = self._update_productdata_in_mongo(product_list,data, is_document_large, store_name)
        '''
        self._add_product_to_postgres_from_webhook(data)
        result = 'Product Added Successfully'

        return {'message': result}


    def update_product_to_store_from_webhook(self, data):

        if not data.get('id'):
            logger.exception(f'Woocommerce Update Data with no id recieved {self.url}')
            return

        if data.get('type','')=='variation':
            p_id = data.get('parentID')

            if not p_id:
                p_id = data.get('parent_id')
            
            data = self._fetch_specific_product_from_woo_commerceAPI(p_id)

        else:
            data = self._fetch_specific_product_from_woo_commerceAPI(data.get('id'))
        
        if not data:
            logger.exception(f'Woocommerce Update api fetching failed {self.url} \n {data}')
            return

        existing_product = dict()
        product_response = self.fetch_product_data_from_woo_commerce_store(self.url)
        product_data = product_response['result']
        product_list = self.get_value_by_key(product_data, 'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        store = self.fetch_store_by_url_from_woo_commerce_store().get('result')
        store_name = self.get_value_by_key(store,'name')
        
        if not store_name:
            return {'message': 'Product import failed'}

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(store_name)

        if not product_list:
            return {'message': 'Product import failed'}

        for product in product_list:
            
            if product and data and product.get('id')==data.get('id'):
                existing_product = product
                continue

        '''
        response = self._update_productdata_in_mongo(product_list_updated,data, is_document_large,store_name)
        '''
        self._add_product_to_postgres_from_update_webhook(data,store_name, existing_product)

        result = 'Product Updated Successfully'
        
        return {'message': result}
    
    def delete_product_from_store(self, product_id,url):

        brand_cred = BrandCred.objects.filter(url=self.url).first()
        
        if not brand_cred:
            return {'message':'Credentials not found'}

        shop_name = brand_cred.brand.private_metadata.get('source_name')
        instance = WooCommerceIntegration()
        instance.disable_publish_product_from_postgres_by_product_id_brand(product_id,shop_name)

        result = 'Product Deleted'
        
        return {'message': result}

    def _structure_brand_information_response(self, settings_response_list):
        store_info = {}

        for response in settings_response_list:
            id = response.get('id')
        
            if id == 'woocommerce_store_address':
                store_info['Address'] = response.get('value') or ''

            elif id == 'woocommerce_store_address_2':
                address2 = response.get('value')

                if address2:
                    store_info['Address'] = store_info['Address'] + address2

            elif id == 'woocommerce_store_city': 
                store_info['City'] = response.get('value') or ''

            elif id == 'woocommerce_default_country':
                country_state_code = response.get('value')
                
                if country_state_code:
                    country = country_state_code.split(':')[0]
                    store_info['Country'] = country or ''
                
            elif id == 'woocommerce_store_postcode':
                store_info['ZipCode'] = response.get('value') or ''

        return store_info


    def _get_store_information_from_woo(self, use_auth_param=False):
        store_info = {}
        url = self._clean_url_for_APICLIENT()
        api = ApiClient(host=url, path=BASE_API_PATH+GENERAL_SETTING_PATH)
        header = WooCommerceHelper.get_default_header_with_user_agent()
        api.update_headers(header)
        
        if use_auth_param:
            param = self._fetch_customer_key_and_secret_for_param()
            api.update_url_params(param)
            api.get(send_body=False)
            if not api.fetch_response():
                return store_info
        else:
            api.add_header('Authorization',self.authtoken)
            api.get(send_body=False)
            if not api.fetch_response():
                return self._get_store_information_from_woo(use_auth_param=True)

        settings_response_list = api.fetch_response()
        store_info = self._structure_brand_information_response(settings_response_list)

        api = ApiClient(host=url, path=BASE_API_PATH+EMAIL_SETTING_PATH)
        header = WooCommerceHelper.get_default_header_with_user_agent()
        api.update_headers(header)

        
        if use_auth_param:
            param = self._fetch_customer_key_and_secret_for_param()
            api.update_url_params(param)
            api.get(send_body=False)
            if not api.fetch_response():
                return store_info
        else:
            api.add_header('Authorization',self.authtoken)
            api.get(send_body=False)
            if not api.fetch_response():
                return self._get_store_information_from_woo(use_auth_param=True)
                
        email_response = api.fetch_response()

        store_email = email_response.get('default') if email_response.get('default') else email_response.get('value')
        store_info['Email'] = store_email or ''

        return store_info

    def decode_fernet_encoded(encrypted_string):
        f_encoder = get_fernet_encoder()

    def save_brand_creds(self,brand_global_id,store_credentials):
        brand_id = graphene.Node.from_global_id(brand_global_id)[1]
        f_encoder = get_fernet_encoder()
        
        default = {
                    'access_key': f_encoder.encrypt(store_credentials.get('store_access_key').encode()).decode('utf-8'),
                    'access_pass': f_encoder.encrypt(store_credentials.get('store_access_pass').encode()).decode('utf-8'),
                    'auth_token': f_encoder.encrypt(store_credentials.get('auth_token').encode()).decode('utf-8'),
                    'url': store_credentials.get('store_url')
                }

        brand_cred = BrandCred.objects.update_or_create(brand_id=brand_id,defaults=default)

    def create_brand_from_WooCommerce(self, shop):
        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(shop.get("name"))

        if brand_id:
            self.save_brand_creds(brand_id,shop)

            return brand_id

        brand_info_response = self._get_store_information_from_woo()
        brand_info_response['Name'] = shop.get("name")
        brand_info = WooCommerceHelper.create_brand_context_from_woocommerce(brand_info_response)
        brand_id = etlLoader.create_brand(brand_info)
        self.save_brand_creds(brand_id,shop)
        return brand_id

    def _create_products_util(self, val_dict, brand_name, from_celery=True, check_existing=False, is_mapped=False):
        product_list = []
        instance = WooCommerceIntegration()

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

    def create_product_from_WooCommerce(self, shop):
        
        store_url = shop.get('store_url')
        response = {}
        brand_name = shop.get('name')
        
        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        is_mapped = True

        if not product_data:
            is_mapped = False
            product_data_response = self.fetch_product_data_from_woo_commerce_store(store_url)
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
            product_brand_id = brand_mappings[i].product_id_brand
            variant_brand_id = brand_mappings[i].variant_id_brand
            quantity = order_lines[i].quantity
            true_msp = order_lines[i].metadata.get('true_msp',0)
            true_msp = NumberUtilities.convert_string_to_decimal(true_msp)
            price = StringUtilities.convert_object_to_string(order_lines[i].unit_price_net_amount*quantity)

            if variant_brand_id:
                item = {
                    "product_id": product_brand_id,
                    "variation_id": variant_brand_id,
                    "quantity": quantity
                }
            
            else:

                item = {
                    "product_id": product_brand_id,
                    "quantity": quantity
                }

            if true_msp and order_lines[i].unit_price_net_amount>true_msp and order_lines[i].cod:
                item['total']=price

            line_items.append(item)

        return line_items

    def _create_order_context_from_woo_commerce(self, order_lines, brand_mappings):
        
        order = order_lines[0].order
        shipping_address = order.shipping_address
        billing_address = order.billing_address

        line_items = self._set_line_items(order_lines, brand_mappings)

        user_email = order.get_customer_email()

        is_cod = order_lines[0].cod
        cod_total = 0
        is_zaamo_shopify = order.metadata.get('shopify')

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


        data = WooCommerceHelper.prepare_context_for_order(user_email,billing_address,shipping_address,line_items,is_cod,cod_total)

        return data

    def _create_order(self, order_context,use_auth_param=False, sslverify=True, delay=False):
        
        try:
            response = dict()
            url = self._clean_url_for_APICLIENT()
            api = ApiClient(host=url, path=BASE_API_PATH+ORDER_CREATE_PATH)
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            
            if use_auth_param:
                param = self._fetch_customer_key_and_secret_for_param()
                api.update_body(order_context)
                api.update_url_params(param)

                if sslverify:
                    api.post()

                    if delay:
                        time.sleep(0.1)

                else:
                    api.post(verify=False)

                    if delay:
                        time.sleep(0.1)

                if not api.fetch_response():
                    response['success'] = False
                    response['response'] = {
                                        'context': order_context
                                        }
                    
                    try:
                        resp = StringUtilities.convert_object_to_string(api.response.text)
                    except Exception as e:
                        resp = f"Null response, error: {e}"
                    response['error'] = resp

            else:
                api.update_body(order_context)
                api.add_header('Authorization',self.authtoken)
                
                if sslverify:
                    api.post()

                else:
                    api.post(verify=False)

                if not api.fetch_response():
                    return self._create_order(order_context, use_auth_param=True)
                    
            res = api.fetch_response()

            if not type(res)==dict:
                res = api.response.text.encode('utf-8').decode('utf-8-sig')
                res = json.loads(res)
                
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
        
        except requests.exceptions.SSLError as se:

            logger.exception(se)
            if sslverify==True:
                return self._create_order(order_context, sslverify=False)
            
            return {'success':False, 'response': response, 'error':se}
        
        except Exception as e:

            if not use_auth_param:
                return self._create_order(order_context, use_auth_param=True, delay=True)
            
            response = f"context :: {order_context}"
            error = f"Woo Commerce Order failed order creation. error :: {e}"
            logger.exception(response)
            return {'success':False, 'response': response, 'error':error}
        
    def place_orders_util(self, order_lines, brand_mappings, brand_name):
        
        try:
            auth_token = self.get_auth_token(store_name=brand_name)
            store_url = self.get_store_url_from_woo_commerce_store(store_name=brand_name)
            self.set_authtoken(auth_token)
            self.set_url(store_url)
        
        except Exception as e:
            response = f"Woo Commerce Order failed while fetching store detail from mongo. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
            logger.exception(response)
            return {'success':False, 'error': response}

        try:
            order_context = self._create_order_context_from_woo_commerce(order_lines, brand_mappings)
        
        except Exception as e:
            
            response = f"Woo Commerce Order failed while building order body. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_lines]}"
            logger.exception(response)
            return {'success':False, 'error': response}

        res_data = self._create_order(order_context)

        if res_data['success']==True:
            api_response = res_data['response']
            if type(api_response)==dict:
                instance = WooCommerceIntegration()
                instance.save_order_mapping(order_lines,api_response.get('id'))
            else:
                return {'success':False, 'error': "API response is invalid."}

        return res_data

    #PDP 2 Functions

    
    def fetch_tags_product_id_dict(self, brand_name):
        data = defaultdict(list)
        
        product_data = self.fetch_product_data_from_woo_commerce_store_by_name(brand_name)
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
                            data[tag_name].append(product.get('id'))

        return data

    def fetch_categories_tags(self, brand_name):
        data = defaultdict(set)
        
        product_data = self.fetch_product_data_from_woo_commerce_store_by_name(brand_name)
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
        product_data = self.fetch_product_data_from_woo_commerce_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['id']

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
        product_data = self.fetch_product_data_from_woo_commerce_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['id']
            categories_data = product.get('categories')

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

        product_cursor = self.fetch_product_data_from_woo_commerce_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_cursor,'product_data')

        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        product_data = defaultdict(list)
        
        
        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return product_data
    
        instance = WooCommerceIntegration()
        
        for prod_dict in product_list:
            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                product_data[prod_dict['id']] = product_meta

        return product_data
    
    def create_product_from_product_variant_id(self, brand_name, product_id_brand, variant_id_brands):
        product_cursor = self.fetch_product_data_from_woo_commerce_store_by_name(brand_name)
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

            if prod_dict['id']==product_id_brand:
                product_data = prod_dict
                break
        
        if not product_data:
            return None

        instance = WooCommerceIntegration()
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

    def _fetch_customer_key_and_secret_for_param(self,brand_creds=None):
        if not brand_creds:
            brand_creds = BrandCred.objects.filter(url=self.url).first()

        f = get_fernet_encoder()
        if brand_creds:
            try:
                param = {'consumer_key':f.decrypt(brand_creds.access_key.encode()).decode('utf-8'),
                        'consumer_secret':f.decrypt(brand_creds.access_pass.encode()).decode('utf-8')}
            except:
                param = {'consumer_key':brand_creds.access_key,
                        'consumer_secret':brand_creds.access_pass}
            
            return param
        
        return {}


    def unpublish_product_whose_mapping_not_exist(self,product_id_brands_list,store_name):
        
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=store_name).values_list('product_id_brand', flat=True)
        ids_to_unpublish = set(brand_mappings).difference(set(product_id_brands_list))
        instance = WooCommerceIntegration()

        for product_id in list(ids_to_unpublish):
            try:
                instance.disable_publish_product_from_postgres_by_product_id_brand(product_id,store_name)
            except Exception as e:
                logger.exception(e)
                continue

    def get_brand_ids_for_resync(self):
        active_brands = Brand.objects.filter(status__in=[BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER],brand_source='woocommerce').exclude(Q(private_metadata__is_key_valid__isnull=False)&Q(private_metadata__is_key_valid=False)).values_list('id',flat=True)
        return list(active_brands)
        

    def resync_price_and_inventory(self,brand_ids):
        
        success_names = []
        error_log = []
        failed_brand = []
        start_time = TimeUtilities.get_current_date_time()
        f = get_fernet_encoder()
        brand_creds = BrandCred.objects.filter(brand_id__in=brand_ids).select_related('brand')
        
        for document in brand_creds:
            try:
                url = document.url
                self.url = url

                store_name= document.brand.private_metadata.get('source_name') or document.brand.brand_name
                
                response = self.insert_product_data_from_woo_commerce_store(store_name,resync=True)
                
                if not response.get('success'):
                    failed_brand.append(StringUtilities.convert_number_to_string(document.brand_id))
                    
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

                        if not product.get('id'):
                            continue

                        product_id_brands_list.append(StringUtilities.convert_object_to_string(product.get('id')))

                        self._add_product_to_postgres_from_update_webhook(product,store_name)

                    self.unpublish_product_whose_mapping_not_exist(product_id_brands_list,store_name)
                success_names.append(store_name)

            except Exception as e:
                name = document.brand.private_metadata.get('source_name')
                failed_brand.append(StringUtilities.convert_number_to_string(document.brand_id))
                error_log.append(f"{name}:{e}")
                logger.exception(e)
                continue

        BrandResyncLog.objects.create(
            failed_brands = ', '.join(failed_brand),
            error_log = ', '.join(error_log),
            success_brands = ', '.join(success_names),
            source = 'woocommerce',
            start_time = start_time

        )

    def check_variant_stock_from_brand(self, brand_mapping):
        try:
            variant_id_brand = brand_mapping.variant_id_brand
            product_id_brand = brand_mapping.product_id_brand

            brand_name = brand_mapping.brand_name
            auth_token = self.get_auth_token(store_name=brand_name)
            store_url = self.get_store_url_from_woo_commerce_store(store_name=brand_name)
            self.set_authtoken(auth_token)
            self.set_url(store_url)
            
            if variant_id_brand:
                data = self._fetch_variant_data_from_Variant_ID(product_id_brand,variant_id_brand)

                if not data:
                    data = self._fetch_specific_product_from_woo_commerceAPI(product_id_brand)
            else:
                data = self._fetch_specific_product_from_woo_commerceAPI(product_id_brand)
                
            if data:
                stock_status = data.get('stock_status')
                
                if stock_status=='outofstock':
                    return False
            
            return True

        except Exception as e:
            logger.exception(f'exception while woocommerce stock check: {e}')
            return True

    def update_order_status_from_webhook(self, order_data, url,brand_name=None):
        status = order_data.get('status')
        order_brand_id = order_data.get('id')
        self.url = url

        if not brand_name:
            store_resp = self.fetch_store_by_url_from_woo_commerce_store()['result']
            brand_name = self.get_value_by_key(store_resp,'name')

        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(brand_name)
        brand_id = graphene.Node.from_global_id(brand_id)[1]
        
        if not status:
            return
        
        zaamo_status = WooCommerceHelper.get_brand_to_zammo_order_status(status)
        
        if not zaamo_status:
            return

        instance = WooCommerceIntegration()
        fulfillment_status_update = instance.update_status_in_fulfillment(order_brand_id, zaamo_status,brand_id)
        

        if not fulfillment_status_update:
            return
            
        etlLoader = self._get_instance_of_etl_loader()
        
        for id,status in fulfillment_status_update.items():

            etlLoader.update_fulfillment_status(id,status)

    def update_order_status(self):
        
        orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='woocommerce', 
                        updated_at__gte=TimeUtilities.get_n_days_before_date(60)
                        ).exclude(order_line_zaamo_id__in=Subquery(FulfillmentLine.objects.filter(fulfillment__status=FulfillmentStatus.DELIVERED).values('order_line_id'))).select_related('brand')
    
        brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='woocommerce').select_related('brand')
        brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}
        
        for order_m in orders:
            try:
                name = order_m.brand.private_metadata.get('source_name')
                
                result = brand_cred_dict.get(name)

                store_url = result.url
                s_url = store_url
                self.url = store_url
                store_url = self._clean_url_for_APICLIENT()
                self.url = store_url

                try:
                    token = get_fernet_encoder().decrypt(result.auth_token.encode()).decode('utf-8')
                except:
                    token = result.auth_token

                self.set_authtoken(token)
                api = ApiClient(host=store_url, path=f'wp-json/wc/v3/orders/{order_m.order_id_brand}')
                header = WooCommerceHelper.get_default_header_with_user_agent()
                api.update_headers(header)
                api.add_header('Authorization',token)
                param = self._fetch_customer_key_and_secret_for_param(result)
                api.update_url_params(param)
                api.get(send_body=False,verify=False)
                order = api.fetch_response()
                if order:
                    self.update_order_status_from_webhook(order,s_url,name)

            except Exception as e:
                logger.exception(e)
                continue
