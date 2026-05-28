from collections import defaultdict
import logging
import ujson as json
import time
import graphene
import requests
from django.db.models import Q,Subquery
from saleor.brand.models import Brand, BrandCred
from saleor.brand.states import BrandStatusEnum
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.external_services.the_souled_store_service.constants import CREATE_ORDER_ENDPOINT, FETCH_ORDER_ENDPOINT
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
from saleor.product.models import BrandVariantZaamoMapping
from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.api_client import ApiClient
from saleor.utilities.time_utilities import TimeUtilities
from .the_souled_store_helper import SouledStoreHelper
from saleor.product import bulk_products_import as etl
from saleor.external_services.integrations.custom_brand import TheSouledStoreIntegeration
from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)

class TheSouledStoreImpl():


    mongo_conn = None
    
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
    
    def _fetch_and_update_variant_details_in_products(self,current_page_product_list,shop):

        for product_raw in current_page_product_list:
            api = ApiClient(host=shop.get('store_url'), path=f"api/v2/product/{product_raw.get('product_slug')}")
            api.post()
            resp = api.fetch_response()
            if not resp:
                continue

            variants = resp.get('variant',[])
            variant_stock_dict = dict()
            
            for variant in variants:
                variant_stock_dict[variant['id']] = variant['stock']
                
            variants_raw = product_raw.get('variants')
            
            for variant_raw in variants_raw:
                variant_raw['stock'] = variant_stock_dict.get(variant_raw['id'],0)
            
            product_raw['variants'] = variants_raw

        return current_page_product_list

    def _fetch_product_list_from_souled_storeAPI(self,shop):
        try:
            product_list = []
            api = ApiClient(host=shop.get('store_url'), path=shop.get('products_api_endpoint'))
            page = 1
            count = 0

            while True:
                
                if count==1000:
                    return product_list

                body = SouledStoreHelper.fetch_body_for_product_list(page)
                api.update_body(body)
                api.post()
                resp = api.fetch_response()
                data = resp.get('data')
                if not data:
                    return product_list
                
                listing = data.get('listing')
                if not listing:
                    return product_list
                
                current_page_product_list = listing.get('products')

                if not current_page_product_list:
                    return product_list

                # current_page_product_list = self._fetch_and_update_variant_details_in_products(current_page_product_list,shop)

                product_list.extend(current_page_product_list)
                page+=1
                count+=1
                   
        except Exception as e:
            logger.exception(e)
            return product_list
        
    def insert_mapped_product_data_to_mongo(self, product_data, store_name, store_url):
        mapped_product_list = []
        instance = TheSouledStoreIntegeration()

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
        
        instance = TheSouledStoreIntegeration()

        for product in product_list:
            existing_product = product_data_id_existing.get(product['id'])
            
            if not existing_product:
                continue
            
            instance.update_brand_price_record(product,brand_name,existing_product)

    def insert_product_data_from_souled_store_store(self, shop,resync=False):
        
        response_context = dict()
        
        store_name = shop.get('name')
        store_url = shop.get('store_url')
        product_list = self._fetch_product_list_from_souled_storeAPI(shop)
        
        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False
            return response_context

        post_data = {'store_url': store_url, 'store_name': store_name, 'product_data': product_list}
        
        existing_product_data = self.fetch_product_data_from_souled_store_store_by_name(store_name)

        data_exist = False
        for existing_product in existing_product_data:
            existing_product_data = existing_product
            data_exist = True
            break
        

        if data_exist:
            try:
                if resync:
                    
                    if data_exist:
                        s_name = existing_product_data.get('store_name')
                        product_data_existing = existing_product_data.get('product_data')
                        
                        if product_data_existing and isinstance(product_data_existing,str):
                            product_data_existing = json.loads(product_data_existing)
                            
                        product_data_id_existing = dict()

                        for product in product_data_existing:
                            product_data_id_existing[product['id']] = product
                        self.update_brand_record_for_resync(product_list,store_name,product_data_id_existing)

                    else:
                        s_name = None
                        product_data_id_existing = dict()

                    
                self._get_instance_of_mongo_connection().update_data({'store_url': store_url}, {'$set': post_data}, 'souled_store_products')
                self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': store_name}, 'souled_store_products')

        else:
            self._get_instance_of_mongo_connection().insert_data(post_data, 'souled_store_products')

        existing_product_data = self.fetch_product_data_from_souled_store_store_by_name(store_name)
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
        
        self.insert_mapped_product_data_to_mongo(product_list,store_name, store_url)
        
        brand_collection_create_inst = BrandCollectionCreate()
        brand_collection_create_inst.save_brand_collection_name(store_name)
        
        response_context['result'] = 'Data for products of shop stored successfully'
        response_context['success'] = True
        response_context['product_list'] = product_list

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False

        return response_context

    def fetch_product_data_from_souled_store_store(self, store_url) -> dict:

        get_store_data = {'store_url': store_url}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, 'souled_store_products')
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

    def fetch_product_data_from_souled_store_store_by_name(self, name) -> dict:

        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, 'souled_store_products')
        
        if results:
            return results

        return None

    def insert_store_data_from_souled_store_store(self, store_details):
        url = store_details.get('store_url')
        existing_shop = self.fetch_store_by_url_from_souled_store_store(url)


        existing_shop_details = existing_shop['result']
        existing_shop_name = self.get_value_by_key(existing_shop_details,'name')
        
        if existing_shop_name:
            self._get_instance_of_mongo_connection().update_data({'store_url': store_details.get('store_url')}, {'$set': store_details}, 'souled_store_stores')

        else:
            self._get_instance_of_mongo_connection().insert_data(store_details, 'souled_store_stores')
            if store_details.get('_id'):
                store_details.pop('_id')

    
    def fetch_store_by_url_from_souled_store_store(self,url) -> dict:

        get_store_data = {'store_url': url}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, 'souled_store_stores')
        response_context = dict()

        response_context['result'] = results

        return response_context

    def save_brand_creds(self,brand_global_id,store_credentials):
        brand_id = graphene.Node.from_global_id(brand_global_id)[1]
        
        default = {
                    'access_key': '',
                    'access_pass': '',
                    'auth_token': store_credentials.get('auth_token'),
                    'url': store_credentials.get('store_url'),
                    'auth_token': store_credentials.get('api_key')
                }

        brand_cred = BrandCred.objects.update_or_create(brand_id=brand_id,defaults=default)

    def create_brand_from_souled_store(self, shop):
        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(shop.get("name"))

        if brand_id:
            self.save_brand_creds(brand_id,shop)

            return brand_id

        brand_info = SouledStoreHelper.create_brand_context_from_souled_store(shop)
        brand_id = etlLoader.create_brand(brand_info)
        self.save_brand_creds(brand_id,shop)
        return brand_id

    def _create_products_util(self, val_dict, brand_name, from_celery=True, check_existing=False, is_mapped=False):
        product_list = []
        instance = TheSouledStoreIntegeration()

        for chunks in instance.gen_chunks(val_dict):
            instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery

        return {'success': True}


    def create_product_from_souled_store(self, shop):
        
        store_url = shop.get('store_url')
        response = {}
        brand_name = shop.get('name')
        
        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')

        resp = self._create_products_util(product_data, brand_name)

        if resp['success']==True:
            response['message'] = "Product Created successfully"
            response['success'] = True

        else:
            response['message'] = "Product Creation Failed, Please Try again."
            response['success'] = False

        return response

    #PDP 2 Functions

    
    def fetch_tags_product_id_dict(self, brand_name):
        data = defaultdict(list)
        
        product_data = self.fetch_product_data_from_souled_store_store_by_name(brand_name)
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
        
        product_data = self.fetch_product_data_from_souled_store_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if product_list:

            for product in product_list:
                category_name = product.get('category')
                if category_name:
                    data['category'].add(category_name)
        return data

    def fetch_categories_from_product_id(self,product_id_brand, brand_name):
        product_id_brand = NumberUtilities.convert_string_to_number(product_id_brand)
        category_product_id = defaultdict(list)
        product_data = self.fetch_product_data_from_souled_store_store_by_name(brand_name)
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

                c_name = product.get('category')

                category_product_id[c_name].append(product_id)
                
                break
        
        return category_product_id


    def fetch_product_brand_ids_from_categories(self,categories, brand_name,for_pdp=True):
        category_product_id = defaultdict(list)
        product_data = self.fetch_product_data_from_souled_store_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['id']
            c_name = product.get('category',{}).get('name')

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

    
    def create_product_from_product_variant_id(self, brand_name, product_id_brand, variant_id_brands):
        product_data = self.fetch_product_data_from_gridfs_by_name(f"{brand_name}_mapped", key='mapped_product_data')
        product_id_brand = NumberUtilities.convert_string_to_number(product_id_brand)
        variant_id_brands = [NumberUtilities.convert_string_to_number(id) for id in variant_id_brands]
        product_to_create=[]

        for product in product_data:
            brand_mapping = product['product.brand_variant_zaamomapping']
            if product_id_brand==brand_mapping.get('product_id_brand'):
                temp_variant_ids = brand_mapping.get('variant_id_brands')
                temp_variant_ids.sort()
                variant_id_brands.sort()

                if temp_variant_ids==variant_id_brands:

                    product_to_create.append(product)
                    break

            
        if not product_to_create:
            return None

        instance = TheSouledStoreIntegeration()
        
        instance.push_inventory(product_to_create,from_celery=False)
        return product_to_create[0]

    def resync_price_and_inventory(self):
        success_names = []
        fail_names = []
        
        brand_creds = BrandCred.objects.filter(brand__private_metadata__source_name='thesouledstore').select_related('brand')
        insts = TheSouledStoreIntegeration()
        for document in brand_creds:
            try:
                
                existing_shop = self.fetch_store_by_url_from_souled_store_store(document.url)['result']
                for i in existing_shop:
                    shop = i
                    break
                store_name= document.brand.private_metadata.get('source_name') or document.brand.brand_name
                
                response = self.insert_product_data_from_souled_store_store(shop,resync=True)
                
                if not response.get('success'):
                    continue

                product_data = response.get('product_list')
                
                product_id_brands_list=[]

                for product in product_data:

                    if not product.get('id'):
                        continue

                    product_id_brands_list.append(StringUtilities.convert_object_to_string(product.get('id')))

                    insts.update_inventory_and_price(product,store_name)

                insts.disable_publish_product_from_postgres_by_product_id_brand(product_id_brands_list,store_name)
                success_names.append(store_name)

            except Exception as e:
                fail_names.append(document.brand.private_metadata.get('source_name'))
                logger.exception(e)
                continue

        return fail_names,success_names

    def get_brand_cred_inst(self,brand_name):
        brand_cred = BrandCred.objects.filter(brand_id__in=Subquery(Brand.objects.filter(private_metadata__source_name=brand_name).values('id'))).first()
        return brand_cred

    def _set_line_items(self,order_lines, brand_mappings):
        line_items = []

        for i in range(len(order_lines)):
            item = dict()
            variant_brand_id = brand_mappings[i].variant_id_brand
            quantity = order_lines[i].quantity
            
            item = {
                "sku_id": variant_brand_id,
                "quantity": StringUtilities.convert_number_to_string(quantity)
            }

            line_items.append(item)

        return line_items

    def _create_order_context_from_souled_store(self, order_lines, brand_mappings):
        
        order = order_lines[0].order
        shipping_address = order.shipping_address
        billing_address = order.billing_address

        line_items = self._set_line_items(order_lines, brand_mappings)

        user_email = order.get_customer_email()
        
        data = SouledStoreHelper.prepare_context_for_order(user_email,billing_address,shipping_address,line_items)

        return data

    def _create_order(self,order_context,brand_name):
        response = dict()
        try:
            brand_cred = self.get_brand_cred_inst(brand_name)
            order_api = brand_cred.url
            token = brand_cred.auth_token

            api_client = ApiClient(host=order_api,path=f"{CREATE_ORDER_ENDPOINT}{token}")
            api_client.update_body(order_context)
            api_client.post()

            if api_client.fetch_response():
                response = {'success':True,
                            'response':api_client.fetch_response()
                            }
            
            else:
                response = {'success':False,
                            'response':{
                                'context':order_context,
                                'error':StringUtilities.convert_object_to_string(api_client.response.text)
                            }}
        
        except Exception as e:
            response = {'success':False,
                            'response':{
                                'context':order_context,
                                'error':e
                            }}
        return response

    def place_orders_util(self, order_line_obj, brand_name, brand_variant_mappings):
        
        order_context = self._create_order_context_from_souled_store(order_line_obj, brand_variant_mappings)

        res_data = self._create_order(order_context,brand_name)
        
        if res_data['success']==True:
            api_response = res_data['response']
            
            instance = TheSouledStoreIntegeration()
            
            instance.save_order_mapping(order_line_obj, api_response.get('order'))
            
        return res_data

    def update_order_status(self):
        orders = OrderBrandZaamoMapping.objects.filter(brand__private_metadata__source_name__in=['thesouledstore'],
                        updated_at__gte=TimeUtilities.get_n_days_before_date(90)
                        ).exclude(order_line_zaamo_id__in=Subquery(FulfillmentLine.objects.filter(fulfillment__status=FulfillmentStatus.DELIVERED).values('order_id'))).select_related('brand')
    
        order_brand_dict = defaultdict(list)
        brand_name = 'thesouledstore'
        for order in orders:
            order_brand_dict[order.brand.private_metadata.get('source_name')].append(order.order_id_brand)
        
        brand_cred = self.get_brand_cred_inst(brand_name)
        token = brand_cred.auth_token

        order_api = brand_cred.url
        for brand_name,order_list in order_brand_dict.items():
            
            for order_m in order_list:
                try:
                    
                    api = ApiClient(host=order_api,path=f"{FETCH_ORDER_ENDPOINT}{token}/{order_m}")
                    api.get()
                    order = api.fetch_response()
                    if order:
                        self.update_order_status_from_webhook(order,brand_cred.brand_id)

                except Exception as e:
                    logger.exception(e)
                    continue
    
    def update_order_status_from_webhook(self, order_data,brand_id):
        status = order_data.get('status')
        order_brand_id = order_data.get('order_id')

        etlLoader = self._get_instance_of_etl_loader()

        if not status:
            return
        
        zaamo_status = SouledStoreHelper.get_brand_to_zammo_order_status(status)
        
        if not zaamo_status:
            return

        instance = TheSouledStoreIntegeration()
        fulfillment_status_update = instance.update_status_in_fulfillment(order_brand_id, zaamo_status,brand_id)

        if not fulfillment_status_update:
            return

        for id,status in fulfillment_status_update.items():

            etlLoader.update_fulfillment_status(id,status)