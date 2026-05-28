import base64
from collections import defaultdict
from decimal import Decimal
import math
import ujson as json
import requests
from datetime import datetime
import logging
import time
import graphene
from django.db.models import Subquery,Q,Sum,OuterRef
from django.db.models.functions import Coalesce
import shopify
from saleor.brand.models import Brand, BrandCred,BrandResyncLog, BrandShippingData
from saleor.brand.states import BrandStatusEnum
from saleor.checkout.manual_order_impl import ManualOrderCreate
from saleor.discount import VoucherOwner
from saleor.external_services import get_fernet_encoder, update_order_metadata_with_extra_charge
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.external_services.integrations.shopify import ShopifyIntegration
from saleor.external_services.shopify_service.shopify_manager import ShopifyManager
from saleor.brand.states import BrandStatusEnum
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, Order, OrderBrandZaamoMapping, OrderLine
from saleor.product.models import BrandVariantZaamoMapping, Category, Product, ZaamoShopifyCategoryMapping, ZaamoShopifyProductMapping
from saleor.settings import IS_BETA
from saleor.utilities.api_client import ApiClient
from saleor.warehouse.models import Stock
from .shopify_helper import ShopifyHelper
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities
from .constants import  SHOPIFY_FETCH_LIMIT
from saleor.product import bulk_products_import as etl
from .constants import STORE_COLLECTION_NAME, PRODUCT_COOLECTION_NAME
from saleor.utilities.string_utilities import StringUtilities
logger = logging.getLogger(__name__)

class ShopifyImpl(ShopifyManager):


    etl_loader = None
    mongo_conn = None
    shopify_session = None

    def __init__(self, shopify_cred_dict = None) -> None:
        
        self.create_shopify_session(shopify_cred_dict)


    def create_shopify_session(self, shopify_cred_dict = None):
        
        if shopify_cred_dict:
            shop_url = shopify_cred_dict.get('store_url')
            api_version = shopify_cred_dict.get('api_version')
            store_access_pass = shopify_cred_dict.get('store_access_pass')
            session = shopify.Session(shop_url, api_version, store_access_pass)
            shopify.ShopifyResource.activate_session(session)
            self.shopify_session = session
        return self.shopify_session
        
    def _get_instance_of_etl_loader(self):

        if self.etl_loader is None:
            self.etl_loader = etl.ETLDataLoader()

        return self.etl_loader

    def _get_instance_of_mongo_connection(self):

        if self.mongo_conn is None:
            self.mongo_conn = MongoConn()

        return self.mongo_conn

    def _create_products_util(self, val_dict, brand_name,from_celery=True, check_existing=False, is_mapped=False):
        
        product_list = []
        instance = ShopifyIntegration()
        
        if is_mapped:

            for chunks in instance.gen_chunks(val_dict.get('product_data',[])):
                instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery

            return {'success': True}
            
        for prod_dict in val_dict.get('product_data', []):
            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                product_list.extend(product_meta)

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

        if product_list:
            for chunks in instance.gen_chunks(product_list):
                instance.push_inventory(chunks, from_celery=from_celery) # Set argument (product_list, False) to not use celery

    def _fetch_product_list_from_shopifyAPI(self):
        
        product_list_total = []

        product_list = shopify.Product.find(limit=SHOPIFY_FETCH_LIMIT)
        product_list_total.extend(product_list)
        count = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                next_page_product = product_list.next_page()
                product_list_total.extend(next_page_product)
                product_list = next_page_product

            except IndexError as e:
                break

        return product_list_total

    def get_current_shop_obj(self):

        shop = shopify.Shop.current()
         
        return shop

    def _fetch_collection_for_product_dict(self):
        collections = []

        collection = shopify.CustomCollection.find(limit=SHOPIFY_FETCH_LIMIT)
        collections.extend(collection)
        count = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                next_page_collection = collection.next_page()
                collections.extend(next_page_collection)
                collection = next_page_collection

            except IndexError as e:
                break
        
        return collections
    
    def _fetch_smartcollection_for_product_dict(self):
        collections = []

        collection = shopify.SmartCollection.find(limit=SHOPIFY_FETCH_LIMIT)
        collections.extend(collection)
        count = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                next_page_collection = collection.next_page()
                collections.extend(next_page_collection)
                collection = next_page_collection

            except IndexError as e:
                break
        
        return collections
    
    def _fetch_collects_for_product_dict(self):
        collects = []

        collect = shopify.Collect.find(limit=SHOPIFY_FETCH_LIMIT)
        collects.extend(collect)
        count = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                next_page_collect = collect.next_page()
                collects.extend(next_page_collect)
                collect = next_page_collect

            except IndexError as e:
                break
        
        return collects

    def _fetch_collection_name_product_dict(self):

        collections = self._fetch_collection_for_product_dict()
        smartcollections = self._fetch_smartcollection_for_product_dict()
        collects = self._fetch_collects_for_product_dict()
        product_collection_dict = defaultdict(list)

        collection_names = dict()
        
        for collection in collections:
            collection_names[collection.id] = collection.title
        
        
        for collection in smartcollections:

            collection_names[collection.id] = collection.title
            products = collection.products()

            for product in products:
                product_collection_dict[product.id].append(collection.title)
        
        for collect in collects:
            product_collection_dict[collect.product_id].append(collection_names[collect.collection_id])

        return product_collection_dict

    def insert_mapped_product_data_to_mongo(self, product_data, store_name, store_id):
        mapped_product_list = []
        instance = ShopifyIntegration()

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
        
        instance = ShopifyIntegration()

        for product in product_list:
            existing_product = product_data_id_existing.get(product['id'])
            
            if not existing_product:
                continue
            
            instance.update_brand_price_record(product,brand_name,existing_product)

    def insert_product_data_from_shopify_store(self, store,brand_name_postgres=None,resync=False):
        store_id = store.id
        brand_name = store.name.strip()
        product_list = self._fetch_product_list_from_shopifyAPI()
        product_collection_dict = self._fetch_collection_name_product_dict()
        product_list = ShopifyHelper.process_product_list_from_shopify(product_list,product_collection_dict)

        result = self.fetch_product_data_from_shopify_store(store_id)
        existing_product_data = result['result']
        
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

        post_data = {'store_id': store_id, 'store_name': brand_name, 'product_data': json.dumps(product_list)}
        
        if not brand_name_postgres:
            brand_name_postgres = brand_name

        self.insert_mapped_product_data_to_mongo(product_list,brand_name_postgres, store_id)
        
        if store_name:
            try:
                if resync:
                    self.update_brand_record_for_resync(product_list,brand_name,product_data_id_existing)
                    
                self._get_instance_of_mongo_connection().update_data({'store_id': store_id},{'$set': post_data}, PRODUCT_COOLECTION_NAME)
            
            except Exception as e:
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': brand_name_postgres}, PRODUCT_COOLECTION_NAME)

        else:
            self._get_instance_of_mongo_connection().insert_data(post_data, PRODUCT_COOLECTION_NAME)
        
        result = self.fetch_product_data_from_shopify_store(store_id)
        existing_product_data = result['result']
        store_name = self.get_value_by_key(existing_product_data,'store_name')

        if not store_name:
            p_data = {'store_id': store_id, 'store_name': brand_name, 'product_data': product_list}
            existing_product_data = self.fetch_product_data_from_gridfs_by_name(brand_name)

            if existing_product_data:

                if resync:

                    product_data_id_existing = dict()

                    for product in existing_product_data:
                        product_data_id_existing[product['id']] = product
                        
                    self.update_brand_record_for_resync(product_list,brand_name,product_data_id_existing)
                
                self._get_instance_of_mongo_connection().delete_gridfs(brand_name)
            
            p_data = json.dumps(p_data)
            result = self._get_instance_of_mongo_connection().insert_one_gridfs(p_data, brand_name, encoding='utf-8')

        brand_collection_create_inst = BrandCollectionCreate()
        brand_collection_create_inst.save_brand_collection_name(brand_name_postgres)
        respone_context = dict()
        respone_context['result'] = 'Data for products of shop stored successfully'

        return respone_context

    def fetch_product_data_from_shopify_store(self, store_id) -> dict:
        get_store_data = {'store_id': store_id}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COOLECTION_NAME)
        respone_context = dict()
        respone_context['result'] = results

        return respone_context
    
    def fetch_product_data_from_shopify_store_by_name(self, name):
        get_store_data = {'store_name': name}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, PRODUCT_COOLECTION_NAME)
        product_data = self.get_value_by_key(results, 'product_data')
        
        if product_data and isinstance(product_data,str):
            product_data = json.loads(product_data)
            
        return product_data

    def get_value_by_key(self, results, key):
        value = ''
        for res in results:
            try:
                value = res[key]
                break
            except:
                pass
        return value

    def get_store_access_pass(self, url,brand_cred=None):

        if not brand_cred:
            brand_cred = BrandCred.objects.filter(url=url).first()
        
        if brand_cred:
            try:
                return get_fernet_encoder().decrypt(brand_cred.access_pass.encode()).decode('utf-8')
            except Exception as e:
                return brand_cred.access_pass

        return None

    def generate_shopify_auth_token(self, test_store_access_key, test_store_access_pass):
        concatinat_key_pass = (test_store_access_key + ':' + test_store_access_pass).encode('ascii')
        shopify_auth = base64.b64encode(concatinat_key_pass).decode('ascii')

        return 'Basic ' + shopify_auth


    def get_shopify_store_url(self, brand_name):
        brand_cred = BrandCred.objects.filter(brand__private_metadata__source_name=brand_name).first()
        
        if brand_cred:
            return brand_cred.url

        return None

    def get_shopify_store_name(self, store_url):
        brand_cred = BrandCred.objects.filter(url=store_url).first()
        
        if brand_cred:
            return brand_cred.brand.private_metadata.get('source_name')

        return None
    
    def _get_shipping_and_refund_policy(self):
        policies = shopify.Policy.find()
        refund_policy = ''
        shipping_policy = ''

        for policy in policies:
            if policy.handle=='shipping-policy':
                shipping_policy = policy.body

            if policy.handle=='refund-policy':
                refund_policy = policy.body
        
        return refund_policy,shipping_policy

    def insert_store_data_from_shopify_store(self, store_access_key, store_access_pass, shopify_auth_token, 
                                                store_url, api_version):
        shop = shopify.Shop.current()
        post_store_details = {}

        refund_policy, shipping_policy = self._get_shipping_and_refund_policy()

        for key, value in shop.attributes.items():
            post_store_details[key] = value
            
        post_store_details['shop_id'] = shop.id
        post_store_details['store_name'] = shop.name.strip()
        post_store_details['store_url'] = shop.myshopify_domain
        post_store_details['api_version'] = api_version
        post_store_details['shipping_policy'] = shipping_policy
        post_store_details['refund_policy'] = refund_policy

        existing_shop = self.fetch_store_by_id_from_shopify_store(shop.id)
        existing_shop_details = existing_shop['result']
        existing_shop_name = self.get_value_by_key(existing_shop_details,'store_name')

        if existing_shop_name:
            self._get_instance_of_mongo_connection().update_data({'shop_id': shop.id},{'$set':post_store_details}, STORE_COLLECTION_NAME)

        else:
            self._get_instance_of_mongo_connection().insert_data(post_store_details, STORE_COLLECTION_NAME)

        respone_context = dict()
        respone_context['shop'] = shop
        respone_context['result'] = 'Data for shop stored successfully'

        return respone_context

    def fetch_store_by_id_from_shopify_store(self, shop_id) -> dict:
        get_store_data = {'shop_id': shop_id}
        results = self._get_instance_of_mongo_connection().fetch_data(get_store_data, STORE_COLLECTION_NAME)
        respone_context = dict()

        respone_context['result'] = results

        return respone_context
    
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

    def _create_brand_context_from_shopify(self, shop, shipping_policy, refund_policy):
        shop_name = shop.name.strip()

        brand_info = {
                    'brandName': shop_name,
                    'address' :  {
                        'companyName': shop_name,
                        'streetAddress1': shop.address1 or '',
                        'city': shop.city  or '',
                        'postalCode': shop.zip  or '',
                        'country': shop.country or 'IN',
                    },
                    'returnAddress': {
                        'companyName': shop_name,
                        'streetAddress1': shop.address1  or '',
                        'city': shop.city  or '',
                        'postalCode': shop.zip or '',
                        'country': shop.country or 'IN',
                    },
                    'panNumber': '',
                    'brandSource': "SHOPIFY",
                    'companyName': shop_name,
                    'brandContactName':  shop.shop_owner,
                    'brandContactNumber': shop.phone if shop.phone else '',
                    'shippingReturnPolicy': {
                                                'shipping_policy': shipping_policy,
                                                'return_policy': refund_policy
                                            }
                }

        return brand_info
    
    def _fetch_shipping_policy(self,shop_id):

        _shop = self.fetch_store_by_id_from_shopify_store(shop_id)
        shop_details = _shop['result']
        
        shipping_policy = self.get_value_by_key(shop_details,'shipping_policy')

        return shipping_policy

    def _fetch_refund_policy(self,shop_id):

        _shop = self.fetch_store_by_id_from_shopify_store(shop_id)
        shop_details = _shop['result']
        
        refund_policy = self.get_value_by_key(shop_details,'refund_policy')

        return refund_policy
    
    def save_brand_creds(self,brand_global_id,store_credentials):
        brand_id = graphene.Node.from_global_id(brand_global_id)[1]
        f_encoder = get_fernet_encoder()
        token = self.generate_shopify_auth_token(store_credentials.get('store_access_key'),store_credentials.get('store_access_pass'))
        
        default = {
            'access_key': f_encoder.encrypt(store_credentials.get('store_access_key').encode()).decode('utf-8'),
            'access_pass': f_encoder.encrypt(store_credentials.get('store_access_pass').encode()).decode('utf-8'),
            'auth_token': f_encoder.encrypt(token.encode()).decode('utf-8'),
            'url': store_credentials.get('store_url')
        }

        brand_cred = BrandCred.objects.update_or_create(brand_id=brand_id, defaults=default)

    def create_brand_from_shopify(self, shop,store_credentials):
        etlLoader = self._get_instance_of_etl_loader()

        brand_id = etlLoader.get_brand_by_source_name_in_private_metadata(shop.name.strip())

        if brand_id:
            self.save_brand_creds(brand_id,store_credentials)
            return brand_id

        shipping_policy = self._fetch_shipping_policy(shop.id)
        refund_policy = self._fetch_refund_policy(shop.id)

        brand_info = self._create_brand_context_from_shopify(shop, shipping_policy, refund_policy)
        
        brand_id = etlLoader.create_brand(brand_info)
        
        self.save_brand_creds(brand_id,store_credentials)

        return brand_id
                
    def create_products_in_shopify(self, shop):

        file_name = f"{shop.name.strip()}_mapped"
        product_data = self.fetch_product_data_from_gridfs_by_name(file_name, key='mapped_product_data')
        is_mapped = True

        if not product_data:
            is_mapped = False
            shopify_product_data_dict = self.fetch_product_data_from_shopify_store(shop.id)
            result = shopify_product_data_dict.get('result', [])
            product_data = self.get_value_by_key(result,'product_data')
            
            if product_data and isinstance(product_data,str):
                product_data = json.loads(product_data)

            if not product_data:
                product_data= self.fetch_product_data_from_gridfs_by_name(shop.name.strip())
            
            if not product_data:
                return {'message':'product data does not exist'}

        self._create_products_util({'product_data':product_data}, shop.name.strip(),is_mapped=is_mapped)

    def check_brand_barter(self,brand_name):
        brand_instance = Brand.objects.filter(private_metadata__source_name=brand_name).first()
        
        if brand_instance.brand_barter:

            return True
        
        else:
            return False

    def create_order(self, request_json, brand_name, store_url):
        api_resp =''
        try:
            api_response = 'api call not triggered successfully.'
            response_json = dict()
            if not store_url:
                store_url = self.get_shopify_store_url(brand_name)
            api_version = "unstable"
            access_pass = self.get_store_access_pass(store_url)

            if not access_pass:
                response = {'error':"Api Key are invalid or doesn't exist",
                            'context':request_json
                            }
                
                response_json['success']=False
                response_json['response']=response
                response_json['error']="Api Key are invalid or doesn't exist"
                return response_json

            credentials = {
                'store_url': store_url,
                'api_version': api_version,
                'store_access_pass': access_pass
            }
            
            session = self.create_shopify_session(credentials)

            order_obj = shopify.Order()

            order_obj.email = request_json['email']
            order_obj.financial_status = request_json['financial_status']
            order_obj.line_items = request_json['line_items']
            order_obj.billing_address = request_json['billing_address']
            order_obj.shipping_address = request_json['shipping_address']
            order_obj.tags = request_json.get('tags')

            if request_json.get('tax_line'):
                order_obj.tax_lines = [request_json.get('tax_line')]
                order_obj.taxes_included = True
            
            if request_json.get('shipping_line'):
                order_obj.shipping_lines = [request_json.get('shipping_line')]

            api_response = order_obj.save()
            
            if not api_response:
                api_response = order_obj.errors.errors
                
                response = {
                            'context':request_json
                            }
                
                response_json['success']=False
                response_json['response']=api_response
                response_json['error']=StringUtilities.convert_object_to_string(api_response)[:200]
                
                f_response = f"Shopify Order failed while placing order. error :: {api_response}, brand :: {brand_name}, context :: {request_json}"
                logger.exception(f_response)
                return response_json

            response_json['success']=True
            response_json['response']=api_response
            response_json['order_id']=order_obj.id
            response_json['url']=order_obj.order_status_url
            response_json['total_price']=order_obj.total_price

        except Exception as e:
            
            api_resp = api_response
            response = {
                        'context':request_json
                        }
            
            response_json['success']=False
            response_json['response']=response
            response_json['error']=StringUtilities.convert_object_to_string(api_resp)[:100] + " " + StringUtilities.convert_object_to_string(e)[:100]
            
            f_response = f"Shopify Order failed while placing order. error :: {e}, brand :: {brand_name}, context :: {request_json}"
            logger.exception(f_response)

        return response_json

    def create_order_context_from_shopify(self,order_line_obj, brand_variant_mappings):
        send_transaction = True
        order = order_line_obj[0].order
        shipping_address = order.shipping_address
        billing_address = order.billing_address
        email = order.get_customer_email()

        is_zaamo_shopify = order.metadata.get('shopify')

        if not billing_address or not shipping_address:
            return None
        
        line_items,total_price = ShopifyHelper.prepare_line_items(order_line_obj,brand_variant_mappings)

        billingAddress = ShopifyHelper.prepare_address_for_order(billing_address)

        shippingAddress = ShopifyHelper.prepare_address_for_order(shipping_address)

        is_cod = False
        cod_total = 0
        for line in order_line_obj:
            
            if line.cod:
                is_cod=True
                cod_total=NumberUtilities.convert_string_to_float(line.metadata.get('cod_price'))
                break
                
        request_json = {
                        
                        "email": email,
                        "financial_status": "paid" if not is_cod else 'pending',
                        "line_items" : line_items,
                        "billing_address" : billingAddress,
                        "shipping_address" : shippingAddress
                    
                    }
        
        brand_private_meta = order_line_obj[0].brand.private_metadata
        tax_rate = brand_private_meta.get('tax_rate')
        shipping_price = brand_private_meta.get('shipping_price')

        if tax_rate:
            
            tax_line = {
                        'rate':tax_rate,
                        'price': total_price * tax_rate,
                        'title': brand_private_meta.get('tax_title') or ''
                        }
            request_json['tax_line'] = tax_line

        if shipping_price:
            shipping_line = {
                                'price':StringUtilities.convert_object_to_string(shipping_price) or '0.00',
                                'title':brand_private_meta.get('shipping_title') or 'FREE SHIPPING'
                            }
            request_json['shipping_line'] = shipping_line
        
        request_json['tags'] = 'Zaamo'
            
        if order.voucher and order.voucher.owner==VoucherOwner.BRAND:
            request_json['tags'] = 'Zaamo, Brand_Barter'

            if brand_private_meta.get('send_free_sourcing_order'):
                #to send amount as 0 for brand which have key sourcing_order_brand true and suffice above voucher conditions
                send_transaction = False
                for line in request_json['line_items']:
                    line.update({"price":0.0})

        if is_zaamo_shopify:

            cod_total = Decimal(0)

            if is_cod:
                cod_total += Decimal(100/order.lines.all().values('brand_id').distinct().count())
                
            for line in order_line_obj:

                try:
                    cod_total += line.variant.variant_zaamo_shopify_mapping.first().extra_charges * line.quantity

                except:
                    cod_total += Decimal(0)
                
            if cod_total:
                update_order_metadata_with_extra_charge(order_line_obj,cod_total,is_cod)

        if is_cod:
            request_json['tags'] = f"{request_json['tags']}, Cash On Delivery"
            

            shipping_line = {
                                'price':StringUtilities.convert_object_to_string(cod_total),
                                'title':'COD_Charges'
                            }
            request_json['shipping_line'] = shipping_line

        return request_json,is_cod,send_transaction

    def _decrement_inventory_level(self,request_json):
        line_items = request_json['line_items']
        variant_id_quantity = {item['variant_id']:item['quantity'] for item in line_items}

        response = {
                    "success":True,
                    "failed_decrement": []
                }

        for variant_id, quantity in variant_id_quantity.items():
            try:
                variant = shopify.Variant.find(variant_id)
                
                if not variant.inventory_management:
                    continue

                inventory_level = shopify.InventoryLevel.find(inventory_item_ids=variant.inventory_item_id)
                
                quantity = -NumberUtilities.convert_string_to_number(quantity)
                inventory_adjust = shopify.InventoryLevel.adjust(inventory_item_id=inventory_level[0].inventory_item_id,
                                                location_id=inventory_level[0].location_id, 
                                                available_adjustment=quantity)
                if not inventory_adjust:
                    response['success'] = False
                    response['failed_decrement'].append(variant_id)
            
            except Exception as e:
                response['success'] = False
                response['failed_decrement'].append(variant_id)
        
        return response
            
            

    def _create_transaction_for_order(self, url, order_id, amount):
        api = ApiClient(host=url, path=f'admin/api/2022-01/orders/{order_id}/transactions.json')
        access_pass = self.get_store_access_pass(url)
        api.headers = dict()
        api.params = dict()
        api.add_header('X-Shopify-Access-Token',access_pass)
        transaction_body = ShopifyHelper.get_transaction_body(amount)
        api.update_body(transaction_body)
        api.post()

        if not api.fetch_response():
            
            try:
                resp = api.response.text
            except Exception as e:
                resp = e

            failed_response = f'url :: {url}, order_id :: {order_id}, headers :: {api.headers}, amount :: {amount}, pass :: {access_pass}, api_response :: {resp}, body :: {transaction_body}'
            logger.exception(failed_response)
            return {'success':False, 'response': failed_response}
            
        else:
            return {'success':True,'response':api.fetch_response()}
        
    def place_orders_util(self, order_line_obj, brand_name, brand_variant_mappings):
        
        is_cod=False

        try:
            request_json,is_cod,send_transaction = self.create_order_context_from_shopify(order_line_obj,brand_variant_mappings)
        
        except Exception as e:

            response = f"Shopify order failed while building order body. error :: {e}, brand :: {brand_name}, order_lines_id :: {[line.id for line in order_line_obj]}"
            logger.exception(response)

            return {'success':False, 'error': response}

        response = {'success':False, 'error':'order Details missing'}
        store_url = self.get_shopify_store_url(brand_name)

        if request_json:

            res_data = self.create_order(request_json, brand_name, store_url)

            if res_data.get('success'):
                
                instance = ShopifyIntegration()
                instance.save_order_mapping(order_line_obj,res_data.get('order_id'),res_data.get('url',''))
                decrement_resp = self._decrement_inventory_level(request_json)

                if not is_cod and send_transaction:
                    transaction_response = self._create_transaction_for_order(store_url,res_data.get('order_id'),res_data.get('total_price'))

                    if transaction_response.get('success'):

                        response = {
                            'success': True,
                            'response': 'Order placed.'
                            }
                    
                    else:

                        response = {
                            'success': False,
                            'error': f"Order Placed but Transaction creation failed :: {transaction_response.get('response')}"
                            }
                            
                        return response
                
                if decrement_resp.get('success'):

                    response = {
                        'success': True,
                        'response': 'Order placed.'
                        }
                
                else:

                    response = {
                        'success': False,
                        'error': 'Order Placed but Inventory decrement failed'
                        }
                    
                    return response

                return response

                
            response = res_data

        return response

    def create_webhooks_for_shopify_store(self):

        if IS_BETA:
            return 
            
        webhook_topic_endpoint = {
                                'products/create': 'product_created',
                                'products/update': 'product_updated',
                                'products/delete': 'product_deleted',
                                'orders/updated': 'order_updated',
                                'fulfillments/update': 'fulfillment_updated'
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
            
            if not response:
                response_context['success'] = False
                
        return response_context

    def _update_productdata_in_mongo(self, product_list, shop_id, new_product, brand_name, is_document_large=False):
        response_context = dict()

        if not product_list:
            return response_context
        if is_document_large:
            
            post_data = {'store_id': shop_id, 'store_name': brand_name, 'product_data': product_list}
            
            self._get_instance_of_mongo_connection().delete_gridfs(brand_name)
            data = json.dumps(post_data)

            results = self._get_instance_of_mongo_connection().insert_one_gridfs(data, brand_name, encoding='utf-8')
            
        else:
            filter_query = {'store_id': shop_id}
            update_query = {'$set': {'product_data': json.dumps(product_list)}}
            try:
                results = self._get_instance_of_mongo_connection().update_data(filter_query, update_query , PRODUCT_COOLECTION_NAME)
            
            except Exception as e:
                
                logger.exception(e)
                self._get_instance_of_mongo_connection().delete_data({'store_name': brand_name}, PRODUCT_COOLECTION_NAME)
                return self._update_productdata_in_mongo(product_list, shop_id, new_product, brand_name, is_document_large=True)

        instance = ShopifyIntegration()
        new_product['vendor'] = brand_name
        product_meta = instance.base_product_mapper(new_product)
        existing_product_data = self.fetch_product_data_from_gridfs_by_name(f"{brand_name}_mapped", key='mapped_product_data')

        mapped_product_list = []

        for mapped_data in existing_product_data:

            if mapped_data['product.brand_variant_zaamomapping']['product_id_brand'] == new_product['id']:
                continue

            mapped_product_list.append(mapped_data)
        
        mapped_product_list.extend(product_meta)
        
        self.insert_mapped_data_to_gridfs(brand_name, mapped_product_list, shop_id)
        response_context['result'] = results

        return response_context

    def _fetch_product_collection_name_from_product_id(self, productid):
        
        product_collection = defaultdict(list)
        
        try:
            collections = shopify.CustomCollection.find(product_id=productid)
            smartcollections = shopify.SmartCollection.find(product_id=productid)
            
            time.sleep(0.7)

            for collection in collections:
                product_collection[productid].append(collection.title)
            
            for collection in smartcollections:
                product_collection[productid].append(collection.title)

        except Exception as e:
            logger.exception(e)

        return product_collection
    
    def fetch_last_7_days_price_rules_from_brand_cred(self,brand_cred):
        
        credentials = {
            'store_url': brand_cred.url,
            'api_version': 'unstable',
            'store_access_pass': self.get_store_access_pass(brand_cred.url,brand_cred)
        }
        
        session = self.create_shopify_session(credentials)
        price_rules = []

        product_list = shopify.PriceRule.find(limit=SHOPIFY_FETCH_LIMIT,created_at_min=TimeUtilities.convert_date_to_datetime(TimeUtilities.get_n_days_before_date(7)))
        price_rules.extend(product_list)
        count = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                next_page_product = product_list.next_page()
                price_rules.extend(next_page_product)
                product_list = next_page_product

            except IndexError as e:
                break

        return price_rules

    def fetch_collection_name_id_from_brand_cred(self,brand_cred):
        
        credentials = {
            'store_url': brand_cred.url,
            'api_version': '2021-10',
            'store_access_pass': self.get_store_access_pass(brand_cred.url,brand_cred)
        }
        
        session = self.create_shopify_session(credentials)
        collections = []
        collection_name_id_dict =dict()

        collection_list = shopify.CustomCollection.find(limit=SHOPIFY_FETCH_LIMIT)
        collections.extend(collection_list)
        count = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                next_page_product = collection_list.next_page()
                collections.extend(next_page_product)
                collection_list = next_page_product

            except IndexError as e:
                break
        
        for collection in collections:
            collection_name_id_dict[collection.id]=collection.title
        
        smartcollections = self._fetch_smartcollection_for_product_dict()

        for collection in smartcollections:

            collection_name_id_dict[collection.id] = collection.title
            
        return collection_name_id_dict
       
    def fetch_product_data_from_id(self, product_id,store_url):
        api_version = "2021-10"
        access_pass = self.get_store_access_pass(store_url)

        if not api_version or not access_pass:
            return None

        credentials = {
            'store_url': store_url,
            'api_version': api_version,
            'store_access_pass': access_pass
        }
        
        session = self.create_shopify_session(credentials)
        time.sleep(0.7)
        
        product_data = shopify.Product.find(product_id)
        time.sleep(0.7)
        product_collection = self._fetch_product_collection_name_from_product_id(product_id)
        product_data = ShopifyHelper.process_product_list_from_shopify([product_data],product_collection)

        return product_data
        
    def _get_product_list_from_store_id(self, store_id):
        product_response = self.fetch_product_data_from_shopify_store(store_id)
        product_data = product_response['result']
        product_list = self.get_value_by_key(product_data, 'product_data')
        
        if product_list and isinstance(product_list,str):
            product_list = json.loads(product_list)

        return product_list

    def add_new_product_to_store_from_webhook(self, product_id, store_url):
        
        new_product_data = self.fetch_product_data_from_id(product_id, store_url)
        brand_name = self.get_shopify_store_name(store_url)

        '''
        product_list = self._get_product_list_from_store_id(shop_id)
        is_document_large = False

        if not product_list:
            is_document_large = True
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        for i in range(len(product_list)):
            if product_list[i]['id']==product_id:
                product_list.pop(i)
                break

        product_list.append(new_product_data[0])
        response = self._update_productdata_in_mongo(product_list, shop_id, new_product_data[0], brand_name, is_document_large=is_document_large)
        '''

        val_dict = {'product_data': new_product_data}

        instance = ShopifyIntegration()
        self._create_products_util(val_dict, brand_name, from_celery=False, check_existing=True)

        result = 'Product Added Successfully'
        
        return {'message': result}
    
    def update_product_from_webhook(self, product_id, store_url, product_data=None,resync=False):
        
        if not product_data:
            new_product_data = self.fetch_product_data_from_id(product_id, store_url)
        
        else:
            new_product_data = [product_data]

        brand_name = self.get_shopify_store_name(store_url)
        
        
        #is_document_large = False
        '''
        product_list.append(new_product_data[0])
        val_dict = {'product_data': new_product_data}
        response = self._update_productdata_in_mongo(product_list, shop_id, new_product_data[0], brand_name, is_document_large=is_document_large)
        '''

        instance = ShopifyIntegration()

        #instance.delete_existing_product_images(product_id)
        '''
        mapping = BrandVariantZaamoMapping.objects.filter(brand_name = brand_name, product_id_brand=product_id)

        if not mapping:
            self.add_new_product_to_store_from_webhook(product_id, store_url)
            return {'message': 'product created'}
        '''
        instance.delete_variation_if_removed_from_store(new_product_data[0])

        instance.update_inventory_and_price(new_product_data[0], brand_name)

        if not resync:
            
            product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)

            if not product_list:
                product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

            if not product_list:
                return {'message': 'no existing product found'}

            exisiting_product = dict()
            for i in range(len(product_list)):

                if not isinstance(product_list[i],dict):
                    continue

                if product_list[i]['id']==product_id:
                    exisiting_product = product_list.pop(i)
                    break
            instance.update_brand_price_record(new_product_data[0], brand_name,exisiting_product)

        result = 'Product Updated Successfully'
        
        return {'message': result}

    def delete_product_from_webhook_response(self, product_id, store_url):

        instance = ShopifyIntegration()
        instance.disable_publish_product_from_postgres_by_product_id_brand(product_id)

        result = 'Product Deleted'
        
        return {'message': result}

    def fetch_tags_product_id_dict(self, brand_name):

        data = defaultdict(list)
        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        for product in product_list:
            tags = product.get('tags')
            tags = tags.split(',')

            for tag in tags:
                data[tag].append(product.get('id'))

        return data

    def fetch_categories_tags_collections(self, brand_name):

        data = defaultdict(set)
        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        for product in product_list:
            product_type = product.get('product_type')
            if product_type:
                data['category'].add(product_type)
            tags = product.get('tags')
            tags = tags.split(',')
            collections = product.get('collections')

            for tag in tags:
                data['tag'].add(tag)
            
            for collection in collections:
                data['collection'].add(collection)

        return data
        
    def fetch_product_brand_ids_from_collections(self,collections, brand_name,for_pdp=True):

        collection_product_id = defaultdict(list)
        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)
        
        if not product_list:

            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        for product in product_list:
            product_id = product['id']
            collection_data = product.get('collections')

            if collection_data:
                for c_name in collection_data:

                    collection_product_id[c_name].append(product_id)
        
        if not for_pdp:
            return collection_product_id
            
        product_brand_ids = []

        for collection in collections:
            product_brand_ids.extend(collection_product_id[collection])

        return product_brand_ids
    
    def fetch_collections_from_product_id(self,product_id_brand, brand_name):
        
        collection_product_id = defaultdict(list)

        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)
        product_id_brand = NumberUtilities.convert_string_to_number(product_id_brand)
        
        if not product_list:

            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        for product in product_list:
            product_id = product['id']

            if product_id_brand == product_id:
                collection_data = product.get('collections')

                if collection_data:

                    for c_name in collection_data:

                        collection_product_id[c_name].append(product_id)

                break
        
        return collection_product_id

    def fetch_categories_from_product_id(self,product_id_brand, brand_name):
        category_product_id = defaultdict(list)
        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        product_id_brand = NumberUtilities.convert_string_to_number(product_id_brand)

        for product in product_list:
            product_id = product['id']

            if product_id == product_id_brand:
                category = product.get('product_type')

                category_product_id[category].append(product_id)
                break
            
        return category_product_id

    def fetch_product_brand_ids_from_categories(self,categories, brand_name,for_pdp=True):
        category_product_id = defaultdict(list)
        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        for product in product_list:
            product_id = product['id']
            category = product.get('product_type')

            category_product_id[category].append(product_id)
        
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

        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)

        if not product_list:
            product_list = self.fetch_product_data_from_gridfs_by_name(brand_name)

        product_data = defaultdict(list)
        instance = ShopifyIntegration()
        
        for prod_dict in product_list:
            prod_dict['vendor'] = brand_name
            product_meta = instance.base_product_mapper(prod_dict)
            
            if product_meta:
                product_data[prod_dict['id']] = product_meta

        return product_data
    
    def create_product_from_product_variant_id(self, brand_name, product_id_brand, variant_id_brands):
        product_list = self.fetch_product_data_from_shopify_store_by_name(brand_name)
        
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

        instance = ShopifyIntegration()
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
        
    def unpublish_product_whose_mapping_not_exist(self,product_id_brands_list,store_name):
        
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=store_name).values_list('product_id_brand', flat=True)
        ids_to_unpublish = set(brand_mappings).difference(set(product_id_brands_list))
        instance = ShopifyIntegration()

        for product_id in list(ids_to_unpublish):
            try:
                instance.disable_publish_product_from_postgres_by_product_id_brand(product_id)
            except Exception as e:
                logger.exception(e)
                continue

    
    def get_brand_ids_for_resync(self):
        active_brands = Brand.objects.filter(status__in=[BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER],
                                             brand_source='shopify').exclude(Q(private_metadata__is_key_valid__isnull=False)&Q(private_metadata__is_key_valid=False)).values_list('id',flat=True)
        return list(active_brands)
    
    
    def get_brand_ids_for_resync_failed(self):
        time_from = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),hours=12)
        failed_brands = BrandResyncLog.objects.filter(start_time__gte=time_from,source='shopify').values_list('failed_brands',flat=True)
        failed_brand_ids = []

        for fail_brand in failed_brands:
            fail_brands = fail_brand.split(',')
            for b_id in fail_brands:

                brand_failed_id = NumberUtilities.convert_string_to_number(b_id.strip())

                if not brand_failed_id or brand_failed_id in failed_brand_ids:
                    continue
                
                failed_brand_ids.append(brand_failed_id)
        
        return failed_brand_ids


    def resync_price_and_inventory(self,brand_ids):
        
        success_names = []
        error_log = []
        failed_brand = []
        start_time = TimeUtilities.get_current_date_time()
        f = get_fernet_encoder()
        brand_creds = BrandCred.objects.filter(brand_id__in=brand_ids).select_related('brand')
        for document in brand_creds:

            try:
                
                store_name= document.brand.private_metadata.get('source_name') or document.brand.brand_name

                url = document.url

                try:
                    access_pass = f.decrypt(document.access_pass.encode()).decode('utf-8')
                except:
                    access_pass = document.access_pass

                session_cred = {'store_url': document.url,
                                'api_version':'2021-10',
                                'store_access_pass': access_pass} 
            
                self.create_shopify_session(session_cred)
                shop = shopify.Shop.current()
                self.insert_product_data_from_shopify_store(shop,brand_name_postgres=store_name,resync=True)

                product_data = self.fetch_product_data_from_shopify_store_by_name(store_name)

                if product_data and isinstance(product_data,str):
                    product_data = json.loads(product_data)
                    
                if not product_data:
                    product_data = self.fetch_product_data_from_gridfs_by_name(store_name)

                if not product_data:
                    failed_brand.append(StringUtilities.convert_number_to_string(document.brand_id))
                    continue
                
                product_id_brands_list = []
                for product in product_data:
                    
                    if not product.get('status')=='active' or not product.get('id'):
                        continue

                    product_id_brands_list.append(StringUtilities.convert_object_to_string(product.get('id')))
                    
                    self.update_product_from_webhook(product.get('id'), url, product_data=product,resync=True)

                self.unpublish_product_whose_mapping_not_exist(product_id_brands_list,store_name)

                success_names.append(store_name)
            
            except Exception as e:
                name= document.brand.private_metadata.get('source_name') or document.brand.brand_name
                failed_brand.append(StringUtilities.convert_number_to_string(document.brand_id))
                error_log.append(f"{name}:{e}")
                logger.exception(e)
                continue
        
        BrandResyncLog.objects.create(
            failed_brands = ', '.join(failed_brand),
            error_log = ', '.join(error_log),
            success_brands = ', '.join(success_names),
            source = 'shopify',
            start_time = start_time

        )

    def check_variant_stock_from_brand(self, brand_mapping):
        try:
            variant_id_brand = brand_mapping.variant_id_brand
            product_id_brand = brand_mapping.product_id_brand
            brand_name = brand_mapping.brand_name
            store_url = self.get_shopify_store_url(brand_name)
            api_version = "2021-10"
            access_pass = self.get_store_access_pass(store_url)

            credentials = {
                'store_url': store_url,
                'api_version': api_version,
                'store_access_pass': access_pass
            }
            
            session = self.create_shopify_session(credentials)
            variant = shopify.Variant.find(variant_id_brand)

            if variant.inventory_quantity <=0:
                return False

            return True

        except Exception as e:
            logger.exception(f'exception while shopify stock check: {e}')
            return True

    def update_order_from_webhook(self, order_id, store_url):
        
        api_version = "unstable"
        access_pass = self.get_store_access_pass(store_url)

        if not api_version or not access_pass:
            return None

        credentials = {
            'store_url': store_url,
            'api_version': api_version,
            'store_access_pass': access_pass
        }
        
        session = self.create_shopify_session(credentials)

        order = shopify.Order.find(order_id)
        variant_id_fulfillment_dict = dict()
        fulfillment_lines = order.fulfillments

        if not fulfillment_lines:
            return None

        for fulfillment in fulfillment_lines:
            
            zaamo_status = None
            
            shipping_status =  fulfillment.shipment_status
            if shipping_status:
                zaamo_status = ShopifyHelper.get_brand_to_zammo_order_status_shipment(shipping_status)

            if order.cancelled_at:
                zaamo_status = 'CANCELLATION_INITIATED'
                
            for item in fulfillment.line_items:
                variant_id_tracking_dict = dict()
                if not zaamo_status:
                    item_status = ShopifyHelper.get_brand_to_zammo_order_status_shipment(item.fulfillment_status)
                
                else:
                    item_status = zaamo_status
                
                if not item_status:
                    continue

                variant_id_fulfillment_dict[item.variant_id] = item_status
                variant_id_tracking_dict[item.variant_id] = (fulfillment.tracking_url or None,fulfillment.tracking_number,fulfillment.tracking_company)
            
        instance = ShopifyIntegration()
        fulfillment_status_update = instance.update_status_in_fulfillment(order_id,variant_id_fulfillment_dict,variant_id_tracking_dict)
        etlLoader = self._get_instance_of_etl_loader()
        
        for id,status in fulfillment_status_update.items():

            etlLoader.update_fulfillment_status(id,status)

    def update_order_status(self):
        orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='shopify',
                        updated_at__gte=TimeUtilities.get_n_days_before_date(60)
                        ).exclude(order_line_zaamo_id__in=Subquery(FulfillmentLine.objects.filter(fulfillment__status=FulfillmentStatus.DELIVERED).values('order_line_id'))).select_related('brand')
        

        brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='shopify').select_related('brand')
        brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}


        for order_m in orders:
            try:
                
                name = order_m.brand.private_metadata.get('source_name')
                result = brand_cred_dict.get(name)
                
                store_url = result.url
                self.update_order_from_webhook(order_m.order_id_brand, store_url)

            except Exception as e:
                logger.exception(e)
                continue

class ZaamoShopifyImpl(ShopifyImpl):
    def __init__(self):
        brand_cred = BrandCred.objects.filter(brand__private_metadata__source_name='Zaamo',brand__brand_source='shopify').first()
        self.access_pass = self.get_store_access_pass(brand_cred.url,brand_cred)

        if brand_cred:
            credentials = {
            'store_url': brand_cred.url,
            'api_version': '2021-10',
            'store_access_pass': self.get_store_access_pass(brand_cred.url,brand_cred)
            }
            self.create_shopify_session(credentials)
    
    def _fetch_collection_name_id_dict(self):

        collections = self._fetch_collection_for_product_dict()
        smartcollections = self._fetch_smartcollection_for_product_dict()

        collection_names = dict()
        
        for collection in collections:
            collection_names[collection.id] = collection.title
        
        
        for collection in smartcollections:

            collection_names[collection.id] = collection.title
        

        return collection_names

    def save_zaamo_shopify_mapping(self):
        collection_id_name_dict = self._fetch_collection_name_id_dict()
        categories = Category.objects.all().values('name','id')
        categories_name_id_dict = {category['name'].strip().lower():category['id'] for category in categories}
        
        to_create = []

        already_exisiting = list(ZaamoShopifyCategoryMapping.objects.all().values_list('shopify_category_name',flat=True))

        for category_id,category_name in collection_id_name_dict.items():

            if category_name in already_exisiting:
                continue

            zaamo_shopify_category_inst = ZaamoShopifyCategoryMapping()

            zaamo_category_id = categories_name_id_dict.get(category_name.strip().lower())

            if zaamo_category_id:
                zaamo_shopify_category_inst.zaamo_category_id=zaamo_category_id
                zaamo_shopify_category_inst.shopify_category_id=category_id
                zaamo_shopify_category_inst.shopify_category_name=category_name
                to_create.append(zaamo_shopify_category_inst)

        ZaamoShopifyCategoryMapping.objects.bulk_create(to_create)
    
    def map_variants_to_shopify_obj(self,product):
        size_values = []
        variants = product.variants.all()
        variants_list = []
        variant_name_obj_dict = dict()
        extra_charge = product.brand.cod_base_price or 0 

        if not extra_charge:
            brand_shipping = product.brand.brand_shipping.first()
            if brand_shipping:
                extra_charge = NumberUtilities.convert_string_to_float(brand_shipping.shipping_cost_same_state_amount) or 0

        for variant in variants:

            shopify_variant = shopify.Variant()
            shopify_variant.title = variant.name
            price_amount = math.ceil(NumberUtilities.convert_string_to_float(variant.price_amount)+extra_charge)
            cost_price_amount = math.ceil(NumberUtilities.convert_string_to_float(variant.cost_price_amount)+extra_charge)

            shopify_variant.price = StringUtilities.convert_object_to_string(price_amount)
            shopify_variant.compare_at_price = StringUtilities.convert_object_to_string(cost_price_amount)

            shopify_variant.inventory_management = None

            if variant.track_inventory:
                shopify_variant.inventory_management = 'shopify'
            
            shopify_variant.fulfillment_service = 'manual'
            shopify_variant.option1 = variant.name
            shopify_variant.inventory_quantity = variant.get_inventory()
            variants_list.append(shopify_variant)
            size_values.append(variant.name)
            variant_name_obj_dict[variant.name.strip()]=variant

        return size_values,variants_list,variant_name_obj_dict

    def fetch_size_chart_from_brand(self,brand_id,product_id):

        try:
            brand_id_global = graphene.Node.to_global_id('Brand',brand_id)
            product_id_global = graphene.Node.to_global_id('Product',product_id)
            api = ApiClient(url=f'https://prodcontent.zaamo.co/streaming/api/size_chart?brand_id={brand_id_global}&product_id={product_id_global}')
            api.headers = {
                            'Service-Token': '2900ba48-85f6-4929-b19d-0c0da14dbc14'
                            }
            
            api.get()

            response = api.fetch_response()
            
            content_size_chart = response.get('image_url')
            return content_size_chart

        except Exception as e:
            logger.exception(e,f"size chart fetch failed for {brand_id},{product_id}")
            return ''

    def map_image_to_shopify_obj(self,product):
        
        images = product.images.all()
        images_list = []
        for image in images:
            shopify_image = shopify.Image()
            shopify_image.alt = product.name
            shopify_image.width = 2048
            shopify_image.height = 3071
            shopify_image.src = image.image.url
            images_list.append(shopify_image)

        content_size_chart = self.fetch_size_chart_from_brand(product.brand_id,product.id)

        if content_size_chart:
            
            shopify_image = shopify.Image()
            shopify_image.alt = product.name
            shopify_image.width = 2048
            shopify_image.height = 3071
            shopify_image.src = content_size_chart
            images_list.append(shopify_image)

        return images_list
    
    def save_in_product_id_in_metadata(self,product,shopify_product,variant_name_obj_dict):

        shopify_variants = shopify_product.variants

        extra_charge = product.brand.cod_base_price or 0 

        if not extra_charge:
            brand_shipping = product.brand.brand_shipping.first()

            if brand_shipping:
                extra_charge = brand_shipping.shipping_cost_same_state_amount or 0

        for shopify_variant in shopify_variants:
            variant = variant_name_obj_dict.get(shopify_variant.title.strip())
            
            if variant:
                variant_zaamo_mapping = variant.variant_zaamo.first()
                
                zaamo_shopify_mapping_inst = ZaamoShopifyProductMapping()
                zaamo_shopify_mapping_inst.product_id_brand = shopify_product.id
                zaamo_shopify_mapping_inst.variant_id_brand = shopify_variant.id
                zaamo_shopify_mapping_inst.brand_variant_zaamo_mapping = variant_zaamo_mapping
                zaamo_shopify_mapping_inst.product_zaamo = product
                zaamo_shopify_mapping_inst.variant_zaamo = variant
                zaamo_shopify_mapping_inst.status = shopify_product.status
                zaamo_shopify_mapping_inst.extra_charges = NumberUtilities.convert_string_to_decimal(extra_charge)
                zaamo_shopify_mapping_inst.save()

        product.metadata['shopify'] = True
        product.save()

    def map_description_to_shopify_obj(self,product):
        description = product.description_json.get('description_text','')
        return_policy = product.brand.shipping_return_policy or {}
        return_shipping_policy={'Shipping Policy': return_policy.get('shipping_policy'), 'Return Policy':return_policy.get('return_policy')}

        for header,policy in return_shipping_policy.items():
            description+=f"<div style='text-align: center;'><strong><span></span></strong></div><div style='text-align: center;'><strong><span></span></strong></div><div style='text-align: center;'><strong></strong></div><p data-mce-fragment='1' style='text-align: left;'><strong data-mce-fragment='1'><span data-mce-fragment='1'>{header}</span></strong><br></p><p data-mce-fragment='1'>{policy}<br>"
        
        return description
    
    def push_product_to_shopify(self,product_id,category_name):
        try:
            shopify_product = shopify.Product()
            product = Product.objects.filter(id=product_id).first()

            shopify_product.title = product.name
            shopify_product.vendor = product.brand.brand_name

            shopify_product.body_html = self.map_description_to_shopify_obj(product)

            if category_name:
                shopify_product.product_type = category_name

            shopify_product.handle = product.slug
            shopify_product.status = 'active'
            shopify_product.template_suffix = 'emprall'

            size_values,variants_list,variant_name_obj_dict = self.map_variants_to_shopify_obj(product)
            images_list = self.map_image_to_shopify_obj(product)
            
            shopify_product.options = [{'name':'Size','values':size_values}]
            shopify_product.variants = variants_list
            shopify_product.images = images_list
            shopify_product.save()
            self.save_in_product_id_in_metadata(product,shopify_product,variant_name_obj_dict)
        
        except Exception as e:
            logger.exception(f"error while pushing product to shopify:: {e}")
            product = Product.objects.filter(id=product_id).first()
            product.metadata['shopify']=False
            product.save()
    
    def map_order_details_to_create_order(self,order,product_zaamo_shopify_mappings_dict):
        
        order_details = dict()

        if not order.email:
            logger.exception(f'No email for order_id: {order.id} while creating manual shopify order')
            return
        
        order_details['email'] = order.email
        order_details['cod'] = order.financial_status != 'paid'
        line_items = order.line_items
        billing = order.billing_address
        customer_name = billing.first_name
        
        if ' ' in customer_name:
            first_name, last_name = customer_name.split(' ')[:2]

        else:

            first_name = customer_name
            last_name = billing.last_name or 'Z'

        order_details['first_name'] = first_name
        order_details['last_name'] = last_name
        order_details['address'] = billing.address1
        order_details['city'] = billing.city
        order_details['zip'] = billing.zip
        order_details['state'] = billing.province
        order_details['phone'] = billing.phone or order.shipping_address.phone
        order_details['order_id'] = order.id
        order_details['zaamo_shopify_order_price'] = order.total_price
        line_items = order.line_items
        line_item_list = []

        if not order_details.get('phone'):
            return None
        
        for line in line_items:
            product_id_brand = StringUtilities.convert_object_to_string(line.product_id)
            variant_id_brand = StringUtilities.convert_object_to_string(line.variant_id)

            if not product_id_brand or not variant_id_brand:
                continue

            variant_id = product_zaamo_shopify_mappings_dict.get((product_id_brand,variant_id_brand))

            if not variant_id:
                continue

            line_item_list.append({'variant_id':variant_id,'quantity':line.quantity})
        
        if not line_item_list:
            return None

        order_details['line_items'] = line_item_list

        discount_codes = order.discount_codes or []

        for discount_code in discount_codes:
            order_details['discount_code'] = discount_code.code
            break

        try:
            code_shipping = order.shipping_lines[0].code
            if 'PP10' in code_shipping:
                order_details['discount_code'] = 'PP10'

        except:
            pass
        return order_details


    def create_order_from_webhook(self, order_id=None,order=None):
        
        if not order:
            order = shopify.Order.find(order_id)

        is_already_existing = Order.objects.filter(metadata__zaamo_shopify_order_id=order_id).exists()

        product_zaamo_shopify_mappings = ZaamoShopifyProductMapping.objects.all()
        product_zaamo_shopify_mappings_dict = {(mapping.product_id_brand,mapping.variant_id_brand):mapping.variant_zaamo_id for mapping in product_zaamo_shopify_mappings}

        if is_already_existing:
            return
        
        if not ('Confirmed' in  order.tags or 'GoKwik' in order.tags) and order.financial_status=='pending':
            return
        
        order_details = self.map_order_details_to_create_order(order,product_zaamo_shopify_mappings_dict)
        
        if order_details:
            manual_order_inst = ManualOrderCreate()
            order_zaamo = manual_order_inst.perform_mutations(order_details)

            if not order_zaamo:
                logger.exception(f"Zaamo shopify order failed with id :: {order_id}")
            
        else:
            logger.exception(f"Zaamo shopify order failed with details :: {order_details}")
    

    def check_create_order_from_webhook(self, shopify_order_lines_brand_dict,shopify_order_lines_dict,order_id=None,order=None):
        
        if not order:
            order = shopify.Order.find(order_id)

        is_already_existing = shopify_order_lines_dict.get(order_id)
        order_details = shopify_order_lines_brand_dict.get(order_id,[])

        brand_names,brand_source,product_names = [],[],[]

        for line in order_details:
            product_names.append(line[0])
            brand_names.append(line[1])
            brand_source.append(line[2])

        if is_already_existing:
            return [is_already_existing.order_id,order_id,','.join(set(is_already_existing.order.order_zaamo.all().values_list('order_id_brand',flat=True))),True,order.created_at,', '.join(product_names),', '.join(brand_names),', '.join(brand_source)]
        
        return ['',order_id,'',False,order.created_at]
    
    def manual_create_order_for_zaamo(self,days=1):
        yesterday_created_at = TimeUtilities.get_n_days_before_date(days)
        yesterday_created_at = TimeUtilities.convert_datetime_to_string(yesterday_created_at,'%Y-%m-%dT%H:%M:%S.%f%z')
        
        orders = shopify.Order.find(created_at_min=yesterday_created_at)

        for order_data in orders:
            try:
                
                self.create_order_from_webhook(order_id=order_data.id,order=order_data)

            except Exception as e:
                logger.exception(e)
                continue
    
    def fetch_placed_order_csv(self,start_date,end_date):
        start_date = TimeUtilities.convert_datetime_to_string(start_date,'%Y-%m-%dT%H:%M:%S.%f%z')
        end_date = TimeUtilities.convert_datetime_to_string(end_date,'%Y-%m-%dT%H:%M:%S.%f%z')
        
        orders_inst = shopify.Order.find(created_at_min=start_date,created_at_max=end_date)
        orders = []
        data = []
        count = 0
        total_order_placed_in_shopify = 0
        total_order_placed_in_zaamo = 0
        total_order_placed_in_brand = 0

        while True:
            count+=1

            if count==1000:
                break

            try:
                orders.extend(orders_inst)
                orders_inst = orders_inst.next_page()
                orders_inst = orders_inst

            except IndexError as e:
                break
        shopify_order_lines = OrderLine.objects.filter(metadata__shopify=True).select_related('brand','order')
        shopify_order_lines_dict = {shopify_order_line.order.metadata.get('zaamo_shopify_order_id'):shopify_order_line for shopify_order_line in shopify_order_lines}
        shopify_order_lines_brand_dict = defaultdict(list)

        for shopify_order_line in shopify_order_lines:
            shopify_order_lines_brand_dict[shopify_order_line.order.metadata.get('zaamo_shopify_order_id')].append((shopify_order_line.product_name,shopify_order_line.brand.brand_name,shopify_order_line.brand.brand_source))
            
        for order_data in orders:
            try:
                
                row = self.check_create_order_from_webhook(shopify_order_lines_brand_dict,shopify_order_lines_dict,order_id=order_data.id,order=order_data)
                total_order_placed_in_shopify+=1
                
                if row[3]:
                    total_order_placed_in_zaamo+=1

                if row[2]:
                    total_order_placed_in_brand+=1

                data.append(row)

            except Exception as e:
                logger.exception(e)
                continue
        data.append([])    
        data.append(['<<--SUMMARY-->>'])    
        data.append(['total_order_placed_in_shopify',total_order_placed_in_shopify])
        data.append(['total_order_placed_in_zaamo',total_order_placed_in_zaamo])
        data.append(['total_order_placed_in_brand',total_order_placed_in_brand])
        return data
    
    def update_product_status_shopify_product_zaamo(self,product_id,status):
        product = Product.objects.filter(id=product_id).first()
        product_zaamo_shopify_mapping = product.product_zaamo_shopify_mapping.first()

        if product_zaamo_shopify_mapping:

            product_id_brand = product_zaamo_shopify_mapping.product_id_brand
            self.update_product_status_shopify(product_id_brand,status,product.id)

    def update_sales_channel(self,shopify_product_id,status=False):

        channels = [
            {"channelHandle":"online_store","channelId":"gid://shopify/Channel/118071984414","publicationId":"gid://shopify/Publication/118071984414"},{"channelHandle":"Facebook & Instagram","channelId":"gid://shopify/Channel/118072017182","publicationId":"gid://shopify/Publication/118072017182"},{"channelHandle":"Google & YouTube","channelId":"gid://shopify/Channel/122886160670","publicationId":"gid://shopify/Publication/122886160670"},{"channelHandle":"Snapchat Ads","channelId":"gid://shopify/Channel/126141497630","publicationId":"gid://shopify/Publication/126141497630"},{"channelHandle":"Interakt - Sell on WhatsApp","channelId":"gid://shopify/Channel/126153163038","publicationId":"gid://shopify/Publication/126153163038"},{"channelHandle":"Gokwik","channelId":"gid://shopify/Channel/225596637470","publicationId":"gid://shopify/Publication/225596637470"},
                    ]

        if not status:
            payload = json.dumps({"query":"mutation productUnpublish($input: ProductUnpublishInput!) {\n  productUnpublish(input: $input) {\n    product {\n      id\n    }\n    shop {\n      # Shop fields\n      id\n    }\n    userErrors {\n      field\n      message\n    }\n  }\n}\n","variables":{"input":{"id":f"gid://shopify/Product/{shopify_product_id}","productPublications":channels}}})

        else:
            payload = json.dumps({"query":"mutation productPublish($input: ProductPublishInput!) {\n  productPublish(input: $input) {\n    product {\n      id\n    }\n    shop {\n      # Shop fields\n      id\n    }\n    userErrors {\n      field\n      message\n    }\n  }\n}\n","variables":{"input":{"id":f"gid://shopify/Product/{shopify_product_id}","productPublications":channels}}})

        

        url = "https://zaamo.myshopify.com/admin/api/2023-10/graphql.json"


        headers = {
                'X-Shopify-Access-Token': self.access_pass,
                'Content-Type': 'application/json'
                }
        
        api_response = requests.request("POST", url, headers=headers, data=payload)
        response = api_response.json()

        if response:
            return True

        return False

    def update_product_status_shopify(self,product_id_brand,status,product_zaamo_id):
        product = Product.objects.filter(id=product_zaamo_id).first()
        product_shopify = shopify.Product.find(product_id_brand)

        if product_shopify:
            status_value = 'active' if (status and (product.metadata.get('instock')==True) and not product.brand.status=='inactive') else 'archived'

            if status_value == 'archived':

                product_shopify.status = 'archived'
                ZaamoShopifyProductMapping.objects.filter(product_id_brand=product_id_brand).update(status='archived')
                product_shopify.save()
                meta = product.metadata
                meta.pop('shopify')
                product.metadata = meta
                self.update_sales_channel(product_shopify.id,False)
                product.save()
                
            else: 
            
                product_shopify.status = status_value
                product_shopify.save()
                self.update_sales_channel(product_shopify.id,True)
                ZaamoShopifyProductMapping.objects.filter(product_id_brand=product_id_brand).update(status=status_value)
    
    def fetch_product_list_to_resync_zaamo_shopify(self,celery=1):
        
        try:
            yesterday_created_at = TimeUtilities.get_n_days_before_date(10)
            shopify_variants = ZaamoShopifyProductMapping.objects.filter(Q(variant_zaamo__updated_at__gte=yesterday_created_at) | Q(variant_zaamo_id__in=Subquery(Stock.objects.filter(updated_at__gte=yesterday_created_at).values('product_variant_id'))) | Q(product_zaamo__updated_at__gte=yesterday_created_at)).filter(product_zaamo__metadata__shopify=True)

            distinct_product_id = shopify_variants.values_list('product_zaamo_id',flat=True).order_by('product_id_brand').distinct()
            distinct_product_id = list(distinct_product_id)

            half_product = len(distinct_product_id)//2

            if celery==1:
                return distinct_product_id[:half_product]
            else:
                return distinct_product_id[half_product:]
        
        except:
            return []


    def resync_price_inventory_for_zaamo_shopify(self,product_id_list=list()):

        if product_id_list:
            shopify_variants = ZaamoShopifyProductMapping.objects.filter(product_zaamo_id__in=product_id_list,product_zaamo__metadata__shopify=True)
        else:
            yesterday_created_at = TimeUtilities.get_n_days_before_date(10)
            shopify_variants = ZaamoShopifyProductMapping.objects.filter(Q(variant_zaamo__updated_at__gte=yesterday_created_at) | Q(variant_zaamo_id__in=Subquery(Stock.objects.filter(updated_at__gte=yesterday_created_at).values('product_variant_id'))) | Q(product_zaamo__updated_at__gte=yesterday_created_at)).filter(product_zaamo__metadata__shopify=True)

        if not shopify_variants:
            return
        
        brand_shipping_subquery = BrandShippingData.objects.filter(brand=OuterRef('id')).order_by('id').values('shipping_cost_same_state_amount')[:1]
        
        brand_obj_list = Brand.objects.filter(id__in = shopify_variants.values('product_zaamo__brand_id')).annotate(shipping_price=Subquery(brand_shipping_subquery)).values('id','cod_base_price','shipping_price','status')
        brand_status_dict = dict()
        
        brand_shipping_dict = dict()
        
        for shipping_data in brand_obj_list:
            brand_status_dict[shipping_data.get('id')] = False if shipping_data.get('status')=='inactive' else True

            if shipping_data.get('cod_base_price'):
                brand_shipping_dict[shipping_data.get('id')] = shipping_data.get('cod_base_price')
                continue
            
            if shipping_data.get('shipping_price'):
                brand_shipping_dict[shipping_data.get('id')] = shipping_data.get('shipping_price')

        shopify_variants_dict = {shopify_variant.variant_id_brand:shopify_variant for shopify_variant in shopify_variants}
        
        stocks = Stock.objects.filter(product_variant_id__in=shopify_variants.values('variant_zaamo_id')).values('product_variant_id').annotate(quantity_available=Coalesce(Sum("quantity"), 0)).order_by('product_variant_id')

        stocks_variant_dict = {stock['product_variant_id']:stock['quantity_available'] for stock in stocks}
        
        distinct_product_id_brands = shopify_variants.values_list('product_id_brand',flat=True).order_by('product_id_brand').distinct()
        
        for product_id_brand in distinct_product_id_brands:
            
            try:
                product_obj = shopify.Product.find(product_id_brand)
                time.sleep(0.7)

                shopify_product = shopify_variants_dict.get(StringUtilities.convert_object_to_string(product_obj.variants[0].id))

                if not shopify_product:
                    continue

                product = shopify_product.product_zaamo
                product_obj.title = product.name
                product_obj.vendor = product.brand.brand_name

                product_obj.body_html = self.map_description_to_shopify_obj(product)

                product_obj.handle = product.slug
                
                sales_channel = True

                if product.is_published and brand_status_dict.get(product.brand_id):
                    status = 'active'
                
                else:
                    status = 'archived'
                    sales_channel = False

                if not product_obj.status==status:

                    product_obj.status = status

                    self.update_sales_channel(product_obj.id,sales_channel)

                extra_charge = 0

                if brand_shipping_dict.get(product.brand_id):
                    extra_charge = NumberUtilities.convert_string_to_float(brand_shipping_dict.get(product.brand_id))
                
                for variant_obj in product_obj.variants:
                    shopify_variant = shopify_variants_dict.get(StringUtilities.convert_object_to_string(variant_obj.id))
                    shopify_variant.status = product_obj.status

                    if not shopify_variant:
                        continue

                    variant = shopify_variant.variant_zaamo
                    price_amount = math.ceil(NumberUtilities.convert_string_to_float(variant.price_amount)+extra_charge)
                    cost_price_amount = math.ceil(NumberUtilities.convert_string_to_float(variant.cost_price_amount)+extra_charge)
                    variant_obj.price = StringUtilities.convert_object_to_string(price_amount)
                    variant_obj.compare_at_price = StringUtilities.convert_object_to_string(cost_price_amount)
                    
                    if NumberUtilities.convert_string_to_float(shopify_variant.extra_charges)!= extra_charge:
                        shopify_variant.extra_charges = NumberUtilities.convert_string_to_decimal(extra_charge)


                    if variant.track_inventory:
                        variant_obj.inventory_management = 'shopify'
                        inventory_item = shopify.InventoryItem.find(variant_obj.inventory_item_id)
                        time.sleep(0.7)

                        if not inventory_item.tracked ==True:
                            inventory_item.tracked = True
                            inventory_item.save()
                            time.sleep(0.7)

                    else:
                        variant_obj.inventory_management = None
                        inventory_item = shopify.InventoryItem.find(variant_obj.inventory_item_id)
                        time.sleep(0.7)

                        if not inventory_item.tracked ==False: 
                            inventory_item.tracked = False
                            inventory_item.save()
                            time.sleep(0.7)

                    shopify_variant.save()
                    time.sleep(0.7)

                    if not variant_obj.inventory_management:
                        continue

                    inventory_level = shopify.InventoryLevel.find(inventory_item_ids=variant_obj.inventory_item_id)
                    time.sleep(0.7)
                    
                    if inventory_level:
                        quantity = NumberUtilities.convert_string_to_number(stocks_variant_dict.get(variant.id,0))
                        inventory_adjust = shopify.InventoryLevel.set(inventory_item_id=inventory_level[0].inventory_item_id,
                                                        location_id=inventory_level[0].location_id, 
                                                        available=quantity)
                        time.sleep(0.7)
                        
                product_obj.save()
                time.sleep(0.7)
            
            except Exception as e:
                
                time.sleep(1)
                logger.exception(e)
                continue
        
    def change_product_status_with_brand_status(self,brand_id):
        
        shopify_variants = ZaamoShopifyProductMapping.objects.filter(product_zaamo_id__brand_id=brand_id)
        brand = Brand.objects.filter(id=brand_id).first()

        if not shopify_variants or not brand:
            return
        
        brand_status = 'archived' if brand.status=='inactive' else 'active'
        sales_status = False if brand.status=='inactive' else True

        if brand_status =='active':
            shopify_variants = shopify_variants.filter(product_zaamo__is_published=True,product_zaamo__metadata__in_stock=True)

            if not shopify_variants:
                return

        shopify_variants.update(status=brand_status)

        shopify_variants_dict = {shopify_variant.variant_id_brand:shopify_variant for shopify_variant in shopify_variants}
        
        distinct_product_id_brands = shopify_variants.values_list('product_id_brand',flat=True).order_by('product_id_brand').distinct()
        
        products_zaamo = []

        for variant in shopify_variants:

            if not variant.product_zaamo in products_zaamo:
                prd_inst = variant.product_zaamo
                prd_inst.metadata['shopify']= True if brand_status=='active' else False

                products_zaamo.append(prd_inst)

        Product.objects.bulk_update(products_zaamo,['metadata'],batch_size=1000)

        for product_id_brand in distinct_product_id_brands:
            
            try:
                product_obj = shopify.Product.find(product_id_brand)
                time.sleep(0.7)

                shopify_product = shopify_variants_dict.get(StringUtilities.convert_object_to_string(product_obj.variants[0].id))

                if not shopify_product:
                    continue

                status = brand_status

                product_obj.status = status
                product_obj.save()
                time.sleep(0.7)
                self.update_sales_channel(product_id_brand,sales_status)
            
            except Exception as e:
                time.sleep(0.7)
                # logger.exception(e)
                continue
