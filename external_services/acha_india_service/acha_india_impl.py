from collections import defaultdict
import logging
import ujson as json
from saleor.utilities.string_utilities import StringUtilities
from .constants import (BASE_URL,PRODUCT_PATH,STORE_INFO_PATH,PRODUCT_COLLECTION_NAME,STORE_COLLECTION_NAME, STORE_URL)
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.api_client import ApiClient
from .acha_india_helper import AchaIndiaHelper
from saleor.product import bulk_products_import as etl
from saleor.external_services.integrations.acha_india import AchaIndiaIntegration
from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)

class AchaIndiaImpl():

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

    
    def _fetch_product_data_from_Product_ID(self, productID):

        url = BASE_URL
        api = ApiClient(host=url, path='')
        api.params = dict()
        param = {
                 'ctl':'Product',
                 'met':'item',
                 'typ':'json',
                 'product_id':productID   
                }
                
        api.update_url_params(param)
        api.get()
        data = api.fetch_response()
        product_data = data.get('data')

        if not product_data:
            return None
            
        product_data['variants'] = list()
        
        item_ids = [uniq[0] for uniq in product_data['item_row']['product_uniqid'].values()]

        for itemID in item_ids:
            url = BASE_URL
            api = ApiClient(host=url, path='')
            api.params = dict()
            param = {
                    'ctl':'Product',
                    'met':'item',
                    'typ':'json',
                    'item_id':itemID   
                    }
                    
            api.update_url_params(param)
            api.get()
            data = api.fetch_response()
            
            if not data or not data.get('data'):
                continue

            variant_data = data.get('data')['item_row']
            
            if variant_data:
                product_data['variants'].append(variant_data)
            
        return product_data

    def _fetch_product_list_from_acha_indiaAPI(self):

        product_list = []
        page = 1
        url = BASE_URL
        api = ApiClient(host=url, path='')
        api.params = dict()
        param = {
                 'ctl':'Product',
                 'met':'lists',
                 'typ':'json',
                 'curpage':page   
                }
        count = 0
        api.update_url_params(param)

        while True:
            if count==1000:
                return product_list

            api.update_url_params({'curpage':page})
            
            api.get()
            data = api.fetch_response()
            current_page_product_list = data['data'].get('items')
            
            if not current_page_product_list:
                return product_list

            for product in current_page_product_list:
                    
                product_data = self._fetch_product_data_from_Product_ID(product['product_id'])
                if product_data:
                    product_list.append(product_data)

            page+=1
            count+=1

    def insert_mapped_product_data_to_mongo(self, product_data, store_name, store_url):
        mapped_product_list = []
        instance = AchaIndiaIntegration()

        for prod_dict in product_data:
            prod_dict['vendor'] = store_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                mapped_product_list.extend(product_meta)
            
        self.insert_mapped_data_to_gridfs(store_name, mapped_product_list,store_url)

    def insert_mapped_data_to_gridfs(self, store_name, mapped_product_list, store_url):

        p_data = {'store_url': store_url, 'store_name': store_name, 'mapped_product_data': mapped_product_list}
        file_name = f"{store_name}_mapped"

        existing_product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')

        if existing_product_data:
            self._get_instance_of_mongo_connection().delete_gridfs(file_name)
        
        p_data = json.dumps(p_data)
        result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, file_name, encoding='utf-8')

    def insert_product_data_from_acha_india_store(self, shop):
        
        store_name = shop.get('name')
        store_url = STORE_URL
        product_list = self._fetch_product_list_from_acha_indiaAPI()

        post_data = {'store_url': store_url, 'store_name': store_name, 'product_data': json.dumps(product_list)}
        
        existing_product_data = self.fetch_product_data_from_acha_india_store_by_name(store_name)
        s_name = self.get_value_by_key(existing_product_data,'store_name')

        if s_name:
            try:
                self._get_instance_of_mongo_connection().update_data({'store_url': store_url}, {'$set': post_data}, PRODUCT_COLLECTION_NAME)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': store_name}, PRODUCT_COLLECTION_NAME)

        else:
            self._get_instance_of_mongo_connection().insert_data(post_data, PRODUCT_COLLECTION_NAME)

        existing_product_data = self.fetch_product_data_from_acha_india_store_by_name(store_name)
        s_name = self.get_value_by_key(existing_product_data,'store_name')

        if not s_name:

            p_data = {'store_url': store_url, 'store_name': store_name, 'product_data': product_list}
            existing_product_data = self.fetch_product_data_from_gridfs_by_name(store_name)

            if existing_product_data:
                self._get_instance_of_mongo_connection().delete_gridfs(store_name)
            
            p_data = json.dumps(p_data)
            result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, store_name, encoding='utf-8')
        
        self.insert_mapped_product_data_to_mongo(product_list,store_name, store_url)
        
        response_context = dict()
        response_context['result'] = 'Data for products of shop stored successfully'
        response_context['success'] = True
        response_context['product_list'] = product_list

        if not product_list:
            response_context['result'] = 'Server not responding, Please try again later.'
            response_context['success'] = False

        return response_context

    def fetch_product_data_from_acha_india_store(self, store_url) -> dict:

        get_store_data = {'store_url': store_url}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)

        return results

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

    def fetch_product_data_from_acha_india_store_by_name(self, name) -> dict:

        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COLLECTION_NAME)
        
        if results:
            return results

        return None

    def insert_store_data_from_acha_india_store(self):
        
        url = STORE_INFO_PATH
        api = ApiClient(url=url)
        api.get()
        response = api.fetch_response()
        shop = response.get('data')
        response_context = dict()

        if shop:
            existing_shop = self.fetch_store_by_name_from_mongo(shop.get('name'))
            existing_shop_name = self.get_value_by_key(existing_shop,'name')
            shop['store_url'] = STORE_URL
            if existing_shop_name:
                self._get_instance_of_mongo_connection().update_data({'name': shop.get('name')}, {'$set': shop}, STORE_COLLECTION_NAME)

            else:
                self._get_instance_of_mongo_connection().insert_data(shop, STORE_COLLECTION_NAME)

            response_context['shop'] = shop
            response_context['result'] = 'Data for shop stored successfully'
        
        return response_context

    def fetch_store_by_name_from_mongo(self,name) -> dict:

        get_store_data = {'name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, STORE_COLLECTION_NAME)

        return results

    def create_brand_from_AchaIndia(self, shop):
        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(shop.get("name"))

        if brand_id:
            return brand_id

        brand_info = AchaIndiaHelper.create_brand_context_from_acha_india(shop)
        brand_id = etlLoader.create_brand(brand_info)

        return brand_id

    def _create_products_util(self, val_dict, brand_name, from_celery=True, is_mapped=False):
        product_list = []
        instance = AchaIndiaIntegration()

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
        
        for chunks in instance.gen_chunks(product_list):
            instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery

        return {'success': True}

    def create_product_from_AchaIndia(self, shop):
        
        store_url = shop.get('store_url')
        response = {}
        brand_name = shop.get('name')
        
        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        is_mapped = True

        if not product_data:
            is_mapped = False
            product_dict = self.fetch_product_data_from_acha_india_store(store_url)
            
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

    #PDP 2 Functions

    def fetch_categories_tags(self, brand_name):
        data = defaultdict(set)
        
        product_data = self.fetch_product_data_from_acha_india_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')

        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if product_list:

            for product in product_list:
                categories = product.get('cat')

                if categories:

                    for category in categories:
                        category_name = category.get('category_name')

                        if category_name:
                            data['category'].add(category_name)
                            
        return data

    def fetch_product_brand_ids_from_categories(self,categories, brand_name, for_pdp=True):
        category_product_id = defaultdict(list)
        product_data = self.fetch_product_data_from_acha_india_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['item_row']['product_number']
            categories_data = product.get('cat')

            if categories_data:

                for category in categories_data:

                    c_name = category.get('category_name')

                    if not c_name:
                        continue

                    category_product_id[c_name].append(product_id)
        
        if not for_pdp:
            return category_product_id
            
        product_brand_ids = []

        for category in categories:
            product_brand_ids.extend(category_product_id[category])
        
        return product_brand_ids

    def fetch_categories_from_product_id(self,product_id_brand, brand_name):
        category_product_id = defaultdict(list)
        product_data = self.fetch_product_data_from_acha_india_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_data,'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return category_product_id

        for product in product_list:
            product_id = product['item_row']['product_number']
            if product_id_brand == product_id:
                categories_data = product.get('cat')

                if categories_data:

                    for category in categories_data:

                        c_name = category.get('category_name')

                        if not c_name:
                            continue

                        category_product_id[c_name].append(product_id)
                break
        
        return category_product_id

    def get_mapped_product_from_brand_name(self, brand_name):
        
        file_name = f"{brand_name}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        
        if product_data:

            product_data_dict = defaultdict(list)

            for product in product_data:

                product_data_dict[product['product.brand_variant_zaamomapping']['product_id_brand']].append(product)
            
            return product_data_dict

        product_cursor = self.fetch_product_data_from_acha_india_store_by_name(brand_name)
        product_list = self.get_value_by_key(product_cursor,'product_data')

        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        product_data = defaultdict(list)
        
        
        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        if not product_list:
            return product_data
    
        instance = AchaIndiaIntegration()
        
        for prod_dict in product_list:
            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                product_data[prod_dict['item_row']['product_number']] = product_meta

        return product_data
    
    def create_product_from_product_variant_id(self, brand_name, product_id_brand, variant_id_brands):
        
        product_list = self.fetch_product_data_from_gridfs_by_name(f'{brand_name}_mapped',key='mapped_product_data')

        product_to_create = []
        found = False
        for prod_dict in product_list:

            if prod_dict["product.brand_variant_zaamomapping"]['product_id_brand']==product_id_brand:

                for variant_id_brand in variant_id_brands:

                    if variant_id_brand in prod_dict["product.brand_variant_zaamomapping"]["variant_id_brands"]:
                        product_to_create.append(prod_dict)
                        found=True
                        break
                    
                if found==True:
                    break
                    
        instance = AchaIndiaIntegration()
        if not product_to_create:
            return None
        
        instance.push_inventory(product_to_create,from_celery=False)
        return product_to_create[0]
