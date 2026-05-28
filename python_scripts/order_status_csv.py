from collections import defaultdict
from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
import shopify
import csv
from saleor.external_services.woo_commerce_service.woocommerce_helper import WooCommerceHelper
from saleor.utilities.api_client import ApiClient
from saleor.order.models import FulfillmentLine, OrderBrandZaamoMapping
import graphene


def shopify_run():
    sh_inst = ShopifyImpl()
    orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='shopify').select_related('brand','order_line_zaamo','order_zaamo')
    order_line_status_dict = defaultdict(str)
    fulfillment_lines = FulfillmentLine.objects.filter(order_line_id__in=orders.values('order_line_zaamo_id')).select_related('fulfillment','order_line')

    for line in fulfillment_lines:
        order_line_status_dict[line.order_line_id] = line.fulfillment.status
    item_list = []

    with open('shopify.csv', 'w',encoding='utf-8',newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['brand_name','order_id_brand', 'order_line_id','order_global_id','product_name','created_date','updated_date','zaamo_status','fulfullment_status','shipping_status'])
        brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='shopify').select_related('brand')
        brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}
    
        for order_m in orders:
            try:
                name = order_m.brand.private_metadata.get('source_name')
                print(name)
                results = brand_cred_dict.get(name)
                
                try:
                    access_pass = get_fernet_encoder().decrypt(results.access_pass.encode()).decode('utf-8')
                except:
                    access_pass = results.access_pass

                sh_inst = ShopifyImpl()
                session_cred = {'store_url': results.url,
                                'api_version': 'unstable',
                                'store_access_pass': access_pass}
        
                sh_inst.create_shopify_session(session_cred)
                order = shopify.Order.find(order_m.order_id_brand)

                fulfillments = shopify.Fulfillment.find(order_id=order.id)
                
                if not fulfillments:
                    continue
                
                order_global = graphene.Node.to_global_id('Order',order_m.order_zaamo_id)
                for fulfillment in fulfillments:

                    for item in fulfillment.line_items:

                        try:
                            if item.id in item_list:
                                continue

                            row = [name,order_m.order_id_brand,item.id,order_global,order_m.order_line_zaamo.product_name,order.created_at,order.updated_at,order_line_status_dict[order_m.order_line_zaamo_id],item.fulfillment_status,fulfillment.shipment_status]
                            item_list.append(item.id)
                            
                            writer.writerow(row)
                            
                        except Exception as e:
                            print(e)
                            continue
            except Exception as e:
                print(e)
                continue

def WooCommerce_run():
    #woo_brand_names = ["Basata","MODE","Maiden","Delan - The style experience","Cameo Outfits"]
    csv_to = [['brand_name','order_id_brand','created_date','order_global_id','product_name','updated_date','zaamo_status','brand_order_status','total_price','payment_method']]

    orders = OrderBrandZaamoMapping.objects.filter(brand__brand_source='woocommerce').select_related('brand','order_line_zaamo','order_zaamo')
    order_line_status_dict = defaultdict()
    fulfillment_lines = FulfillmentLine.objects.filter(order_line_id__in=orders.values('order_line_zaamo_id')).select_related('fulfillment','order_line')
    brand_cred_shopify = BrandCred.objects.filter(brand__brand_source='woocommerce').select_related('brand')
    brand_cred_dict = {cred.brand.private_metadata.get('source_name'):cred for cred in brand_cred_shopify}
    for line in fulfillment_lines:
        order_line_status_dict[line.order_line_id] = line.fulfillment.status
    
    for order_m in orders:
        try:

            name = order_m.brand.private_metadata.get('source_name')
            woo_inst = WooCommerceImpl()
            
            results = brand_cred_dict.get(name)
            store_url = results.url
            woo_inst.url = store_url
            store_url = woo_inst._clean_url_for_APICLIENT()

            try:
                token = get_fernet_encoder().decrypt(results.auth_token.encode()).decode('utf-8')
            except:
                token = results.auth_token

            woo_inst.set_authtoken(token)
            api = ApiClient(host=store_url, path=f'wp-json/wc/v3/orders/{order_m.order_id_brand}')
            header = WooCommerceHelper.get_default_header_with_user_agent()
            api.update_headers(header)
            api.add_header('Authorization',token)
            api.get(send_body=False)
            order = api.fetch_response()
            order_global = graphene.Node.to_global_id('Order',order_m.order_zaamo_id)
            csv_to.append([name,order['id'],order['date_created'],order_global,order_m.order_line_zaamo.product_name,order['date_modified'],order_line_status_dict[order_m.order_line_zaamo_id],order['status'],order['total'],order['payment_method']])
            
        except Exception as e:
            print(e)
            continue

    with open('woocommerce_status.csv', 'w',encoding='utf-8') as f:
        writer = csv.writer(f)
        for row in csv_to:
            writer.writerow(row)

WooCommerce_run()
shopify_run()