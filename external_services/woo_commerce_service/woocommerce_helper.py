import base64
from saleor.utilities.string_utilities import StringUtilities
from saleor.settings import BACKEND_URL

class WooCommerceHelper(object):
    @staticmethod
    def generate_woocommerce_auth_token(key, secret):

        if key and secret:
            concatinat_key_pass = (key + ':' + secret).encode('ascii')
            woo_commerce_auth = base64.b64encode(concatinat_key_pass).decode('ascii')
            return 'Basic ' + woo_commerce_auth

    @staticmethod
    def get_default_header_with_user_agent():

        header = {"Accept":'*/*',
                "content-type":"application/json",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36"
        }

        return header

    @staticmethod
    def structure_store_details_response(shop):

        shop_name = shop.get("name")

        if not shop_name:
            shop_name = shop.get("url")

        post_store_details = {
                            "name":shop_name,
                            "description":shop.get("description"),
                            "store_url":shop.get("url"),
                            "site_icon_url":f"{shop.get('url')}/favicon.ico",
                            }

        return post_store_details
    
    @staticmethod
    def create_brand_context_from_woocommerce(shop):

        shop_name = shop.get("Name",'')
        brand_info = {
                    'brandName': shop_name,
                    'address' :  {
                        'companyName': shop_name,
                        'streetAddress1': shop.get("Address",''),
                        'city': shop.get("City",''),
                        'postalCode': shop.get("ZipCode",''),
                        'country': shop.get("Country",'IN')
                    },
                    'returnAddress': {
                        'companyName': shop_name,
                        'streetAddress1': shop.get("Address",''),
                        'city': shop.get("City",''),
                        'postalCode': shop.get("ZipCode",''),
                        'country': shop.get("Country",'IN')
                    },
                    'panNumber': '',
                    'brandSource': "WOOCOMMERCE",
                    'companyName': shop_name,
                    'brandContactName':  shop_name,
                    'brandContactNumber': ''
                }

        return brand_info
        

    @staticmethod
    def unbase64(id):
        
        decoded_id = base64.b64decode(id).decode('utf-8')
        _id = decoded_id.split(':')[-1]

        return _id

    @staticmethod
    def prepare_context_for_order(user_email,billing_address,shipping_address,line_items,is_cod,cod_total):

        data = {
                "status":"processing",
                "payment_method": "bacs" if not is_cod else "cod",
                "payment_method_title": "Direct Bank Transfer" if not is_cod else "Cash On Delivery",
                "set_paid": False if is_cod else True,
                "billing": {
                    "first_name": billing_address.first_name,
                    "last_name": billing_address.last_name,
                    "address_1": billing_address.street_address_1,
                    "address_2": billing_address.street_address_2,
                    "city": billing_address.city,
                    "postcode": billing_address.postal_code,
                    "country": StringUtilities.convert_object_to_string(billing_address.country),
                    "state": billing_address.country_area,
                    "phone": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else ''
                },
                "shipping": {
                    "first_name": shipping_address.first_name,
                    "last_name": shipping_address.last_name,
                    "address_1": shipping_address.street_address_1,
                    "address_2": shipping_address.street_address_2,
                    "city": shipping_address.city,
                    "state": shipping_address.country_area,
                    "postcode": shipping_address.postal_code,
                    "country": StringUtilities.convert_object_to_string(shipping_address.country),
                },
                "line_items": line_items,
                "shipping_lines": [
                    {
                        "method_id": "flat_rate",
                        "method_title": "Flat Rate",
                        "total": "0.00"
                    }
                ]
            }
        
        if is_cod:

            fee_lines = [
                    {
                        "name": "Cash On Delivery",
                        "total": StringUtilities.convert_object_to_string(cod_total)
                    }
                ]

            data['fee_lines'] = fee_lines

        if user_email:
            data['billing']['email'] = user_email
            
        return data

    @staticmethod
    def get_product_create_webhook_data():
        data = {
                "name": "Product Created",
                "topic": "product.created",
                "delivery_url": f"{BACKEND_URL}/webhooks/woocommerce/product_created"
            }

        return data
    
    @staticmethod
    def get_product_update_webhook_data():
        data = {
                "name": "Product Updated",
                "topic": "product.updated",
                "delivery_url": f"{BACKEND_URL}/webhooks/woocommerce/product_updated"
            }

        return data

    @staticmethod
    def get_product_delete_webhook_data():
        data = {
                "name": "Product Deleted",
                "topic": "product.deleted",
                "delivery_url": f"{BACKEND_URL}/webhooks/woocommerce/product_deleted"
            }

        return data
    
    @staticmethod
    def get_order_update_webhook_data():
        data = {
                "name": "Order Update",
                "topic": "order.updated",
                "delivery_url": f"{BACKEND_URL}/webhooks/woocommerce/order_updated"
            }

        return data


    @staticmethod
    def get_brand_to_zammo_order_status(status):
        
        if not status:
            return None

        if status.lower()=='cancelled':
            zaamo_status = 'CANCELLATION_INITIATED'
        
        elif status.lower()=='completed':
            zaamo_status = 'DELIVERED'
        
        elif status.lower()=='refunded':
            zaamo_status = 'RETURN_COMPLETED'
        
        elif status.lower()=='processing':
            zaamo_status = 'IN_PROCESS'

        else:
            zaamo_status = None
            
        return zaamo_status
