import base64
from collections import defaultdict
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.settings import BACKEND_URL

class WixHelper(object):

    @staticmethod
    def structure_store_details_response(properties,instance_id,refresh_token):
        
        properties['refresh_token'] = refresh_token
        properties['instance_id'] = instance_id

        return properties
    
    @staticmethod
    def get_body_for_initial_oauth(code,WIX_GATEWAY):

        body = {    
            "grant_type": "authorization_code",    
            "client_id": WIX_GATEWAY['WIX_APP_ID'],    
            "client_secret": WIX_GATEWAY['WIX_APP_SECRET'],    
            "code": code  }

        return body
    
    @staticmethod
    def get_body_for_oauth(refresh_token,WIX_GATEWAY):

        body = {    
            "grant_type": "refresh_token",    
            "client_id": WIX_GATEWAY['WIX_APP_ID'],    
            "client_secret": WIX_GATEWAY['WIX_APP_SECRET'],    
            "refresh_token": refresh_token  }

        return body
    
    @staticmethod
    def get_body_for_inventory_api(numeric_id):
        filter = "{\"numericId\": {\"$gt\": {{replacenumericid}} }}"
        filter = filter.replace("{{replacenumericid}}", StringUtilities.convert_number_to_string(numeric_id))
        body = {
                "query":{
                    "sort":"[{\"numericId\": \"asc\"}]",
                    "filter":filter
                    }
                }

        return body
    
    @staticmethod
    def get_body_for_discount_api():
        filter = "{\"dateCreated\": {\"$gte\": \"{{replace_date}}\"},\"specification.active\": {\"$eq\": \"true\"}}"
        filter = filter.replace("{{replace_date}}", StringUtilities.convert_object_to_string(TimeUtilities.convert_date_to_datetime(TimeUtilities.get_n_days_before_date(7)).timestamp()))
        body = {
                "query":{
                    "filter":filter
                    }
                }

        return body

    @staticmethod
    def get_body_for_inventory_api_by_productId(product_id):
        filter = "{\"productId\": {\"$eq\": replacenumericid }}"
        filter = filter.replace("replacenumericid", f"\"{product_id}\"")
        body = {
                "query":{
                    "filter":filter
                    }
                }

        return body
    
    @staticmethod
    def get_body_for_product_api(numeric_id):

        filter = "{\"numericId\": {\"$gt\": {{replacenumericid}} }}"
        filter = filter.replace("{{replacenumericid}}", StringUtilities.convert_number_to_string(numeric_id))
        body = {
                "query":{
                    "sort":"[{\"numericId\": \"asc\"}]",
                    "filter":filter
                    },
                "includeVariants": True
                }

        return body

    @staticmethod
    def create_brand_context_from_wix(shop):

        shop_name = shop.get("store_name") or ''
        address = shop.get("address") or dict()
        street_address1 = address.get('apartmentNumber','')+address.get('streetNumber','')+address.get('street','')
        brand_info = {
                    'brandName': shop_name,
                    'address' :  {
                        'companyName': shop_name,
                        'streetAddress1': street_address1 or '',
                        'city': address.get('city') or'',
                        'postalCode': address.get('zip') or'',
                        'country': address.get('country') or 'IN'
                    },
                    'returnAddress': {
                        'companyName': shop_name,
                        'streetAddress1': street_address1 or '',
                        'city': address.get('city') or'',
                        'postalCode': address.get('zip') or'',
                        'country': address.get('country') or 'IN'
                    },
                    'panNumber': '',
                    'brandSource': "WIX",
                    'companyName': shop_name,
                    'brandContactName':  shop_name,
                    'brandContactNumber': shop.get('phone') or '',
                    'email': shop.get('email') or ''
                }
        return brand_info
        
    @staticmethod
    def prepare_context_for_order(email,billing_address,shipping_address,line_items,total,is_cod,cod_total):

        data = {
                 "order": {
                   "totals": {
                     "subtotal": StringUtilities.convert_number_to_string(total),
                     "total": StringUtilities.convert_number_to_string(total)
                   },
                   "billingInfo": {
                     "address": {
                        "fullName":{
                            "firstName":billing_address.first_name,
                            "lastName":billing_address.last_name
                        },
                       "email": email,
                       "country": StringUtilities.convert_number_to_string(billing_address.country),
                       "city": billing_address.city,
                       "zipCode": billing_address.postal_code,
                       "phone": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else '',
                       "addressLine1":f"street:{billing_address.street_address_1}"

                     }
                   },
                   "shippingInfo": {
                     "shipmentDetails": {
                       "address": {
                        "fullName":{
                            "firstName":shipping_address.first_name,
                            "lastName":shipping_address.last_name
                        },
                        "email": email,
                        "country": StringUtilities.convert_number_to_string(shipping_address.country),
                        "city": shipping_address.city,
                        "zipCode": shipping_address.postal_code,
                        "phone": StringUtilities.convert_number_to_string(shipping_address.phone.national_number) if shipping_address.phone else '',
                        "addressLine1":f"street:{shipping_address.street_address_1}"

                        }
                     }
                   },
                   "paymentStatus": "PAID" if not is_cod else "NOT_PAID",
                   "lineItems": line_items,
                   "channelInfo": {
                     "type": "WEB"
                   }
                 }
               }
               
        if is_cod:
            data['order']['buyerNote']='Cash On Delivery'
            data['order']['totals']['shipping']=StringUtilities.convert_number_to_string(cod_total)

        return data

    
    @staticmethod
    def get_brand_to_zammo_order_status(status):
        
        if not status:
            return None
        
        elif status.lower()=='FULFILLED':
            zaamo_status = 'SHIPPED'
        
        elif status.lower()=='CANCELLED':
            zaamo_status = 'CANCELLATION_INITIATED'

        else:
            zaamo_status = None
            
        return zaamo_status
