from collections import defaultdict
import json
from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
import shopify
from django.db.models import Subquery
import csv
from saleor.external_services.woo_commerce_service.woocommerce_helper import WooCommerceHelper
from saleor.utilities.api_client import ApiClient
from saleor.order.models import OrderBrandZaamoMapping, OrderLine
import graphene
from saleor.utilities.mongo_utilities import MongoConn


def shopify_run():
    results = BrandCred.objects.filter(brand__brand_source='shopify').select_related('brand')
    
    with open('shopify_order.csv', 'w',encoding='utf-8',newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['customer_name','contact','email','address','product_name','date','price','brand_name', 'order_id_brand', 'product_id_brand','variant_id_brand'])
        x = 0

        for result in results:
            try:

                all_orders = []
                sh_inst = ShopifyImpl()
                brand_name = result.brand.private_metadata.get('source_name')
                
                try:
                    access_pass = get_fernet_encoder().decrypt(result.access_pass.encode()).decode('utf-8')
                except:
                    access_pass = result.access_pass

                session_cred = {'store_url': result.url,
                                'api_version': 'unstable',
                                'store_access_pass': access_pass}
        
                sh_inst.create_shopify_session(session_cred)
                order_list = shopify.Order.find(limit=250,status='any')
                all_orders.extend(order_list)

                while True:

                    try:
                        next_page_product = order_list.next_page()
                        all_orders.extend(next_page_product)
                        order_list = next_page_product

                    except Exception as e:
                        break
                for order in all_orders:
                    for line in order.line_items or []:
                        try:
                            customer_bill = order.billing_address or order.customer.default_address
                            address = f"{customer_bill.address1}, {customer_bill.address2}, {customer_bill.city}, {customer_bill.province}, {customer_bill.zip}"
                            phone = customer_bill.phone or order.phone
                            row = [customer_bill.first_name + customer_bill.last_name,phone,order.contact_email,address,line.name,order.created_at,line.price,brand_name,order.id, line.product_id, line.variant_id]
                            print(row)
                            writer.writerow(row)
                        
                        except Exception as e:
                            print(e)
                            continue
                        
            except Exception as e:
                print(e)
                continue

def WooCommerce_run():
    results = BrandCred.objects.filter(brand__brand_source='shopify').select_related('brand')
    
    with open('woocommerce_status.csv', 'w',encoding='utf-8',newline='') as f:
        
        writer = csv.writer(f)
        writer.writerow(['customer_name','contact','email','address','product_name','date','price','brand_name', 'order_id_brand', 'product_id_brand','variant_id_brand'])

        for result in results:
            try:
                woo_inst = WooCommerceImpl()
                store_url = result.url
                woo_inst.url = store_url
                brand_name = result.brand.private_metadata.get('source_name')
                
                store_url = woo_inst._clean_url_for_APICLIENT()
                
                try:
                    token = get_fernet_encoder().decrypt(result.auth_token.encode()).decode('utf-8')
                except:
                    token = result.auth_token

                woo_inst.set_authtoken(token)
                api = ApiClient(host=store_url, path=f'wp-json/wc/v3/orders')
                header = WooCommerceHelper.get_default_header_with_user_agent()
                api.update_headers(header)
                api.add_header('Authorization',token)
                param = woo_inst._fetch_customer_key_and_secret_for_param()
                api.update_url_params(param)
                api.get(send_body=False)

                order_list = []
                api.add_url_param('per_page',90)
                
                api.add_url_param('page',1)
                
                page = 1
                count = 0

                while True:
                    if count==1000:
                        break

                    api.update_url_params({'page':page})
                    
                    api.get(send_body=False)
                    current_page_product_list = api.fetch_response()
                    
                    if not current_page_product_list:
                        break

                    order_list.extend(current_page_product_list)
                    page+=1
                    count+=1

                for order in order_list:
                    for item in order.get('line_items',[]):
                        billing_shipping = order.get('billing') or order.get('shipping')
                        address = billing_shipping.get('address_1','') + billing_shipping.get('address_2','') + billing_shipping.get('city','') + billing_shipping.get('state','') + billing_shipping.get('postcode','')
                        row = [billing_shipping.get('first_name')+billing_shipping.get('last_name'), billing_shipping.get('phone',''),billing_shipping.get('email',''),address, item.get('name'), order.get('date_created'),item.get('total'),brand_name,order.get('id'),item.get('product_id'),item.get('variation_id')]
                        print(row)
                        writer.writerow(row)
                    
            except Exception as e:
                print(e)
                continue

WooCommerce_run()
shopify_run()

'''
To Run in shell
from saleor.python_scripts import create_customer_data_csv
'''