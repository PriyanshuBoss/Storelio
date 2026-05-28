import base64
import uuid
from saleor.utilities.string_utilities import StringUtilities
from saleor.settings import BACKEND_URL

class MyDukaanHelper(object):
    @staticmethod
    def generate_mydukaan_auth_token(key, secret):

        if key and secret:
            concatinat_key_pass = (key + ':' + secret).encode('ascii')
            mydukaan_auth = base64.b64encode(concatinat_key_pass).decode('ascii')
            return 'Basic ' + mydukaan_auth

    @staticmethod
    def get_default_header_with_user_agent():

        header = {"Accept":'*/*',
                "content-type":"application/json",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36"
        }

        return header
    
    @staticmethod
    def create_brand_context_from_mydukaan(shop):

        shop_name = shop.get("name",'')
        brand_info = {
                    'brandName': shop_name,
                    'address' :  {
                        'companyName': shop_name,
                        'streetAddress1': shop.get("full_address",''),
                        'city': shop.get("City",''),
                        'postalCode': shop.get("zonal_delivery_pincode",''),
                        'country': shop.get("Country",'IN')
                    },
                    'returnAddress': {
                        'companyName': shop_name,
                        'streetAddress1': shop.get("full_address",''),
                        'city': shop.get("City",''),
                        'postalCode': shop.get("zonal_delivery_pincode",''),
                        'country': shop.get("Country",'IN')
                    },
                    'panNumber': '',
                    'brandSource': "MYDUKAAN",
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
    def get_address_context(billing_address):
        name = billing_address.first_name or '' + billing_address.last_name or ''
        address =  {
                    "name": name,
                    "signature": StringUtilities.convert_object_to_string(uuid.uuid1()),
                    "line": billing_address.street_address_1,
                    "city": billing_address.city,
                    "pin": billing_address.postal_code,
                    "country": 'in',
                    "country_code": "+91",
                    "state": billing_address.country_area,
                    "mobile": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else ''
                }
        
        if billing_address.street_address_2:
            
            address["line_1"]= billing_address.street_address_2
        
        return address

    @staticmethod
    def get_buyer_context(user_email,billing_address,store_uuid):
        
        name = billing_address.first_name or '' + billing_address.last_name or ''
        return  {
            
                    "store": store_uuid,
                    "email": user_email,
                    "name": name,
                    "mobile": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else ''
                }

    @staticmethod
    def prepare_context_for_order(billing_address,line_items,store_uuid,address_context):
        data = {
                    "store": store_uuid,
                    "campaign": None,
                    "is_kiosk_order": False,
                    "source": None,
                    "line_items": line_items,
                    "mobile": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else '',
                    "address": address_context,
                    "coupon_code": None,
                    "manual_ship_charge": None,
                    "payment_mode": 1,
                    "is_prepaid_order": True
                    }
        
        return data
        
    @staticmethod
    def get_brand_to_zammo_order_status(status):
        
        if not status:
            return None
        
        if status==3:
            zaamo_status = 'SHIPPED'
        
        elif status==6:
            zaamo_status = 'DELIVERED'
        
        elif status==1:
            zaamo_status = 'IN_PROCESS'

        else:
            zaamo_status = None
            
        return zaamo_status
