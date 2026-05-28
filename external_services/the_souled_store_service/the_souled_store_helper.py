from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities


class SouledStoreHelper(object):
    
    @staticmethod
    def fetch_body_for_product_list(page=1):

        body = {"query": "\n        {\n          listing(\n              page: {},\n              size: 100,\n              category: [],\n              sort: LATEST,\n              gender:1\n              filters: {\n                price: []\n              }\n              tags: []\n              ){\n            products{\n                meta{\n                    desc\n                }\n              id\n              product\n              stock\n              tags{\n                  name\n              }\n              prodQty\n              category{name}\n              price\n              splPrice\n              exclusivePrice\n              variants{\n                  name\n                  stock\n                  prodType\n                  id\n                  images\n                  attributes{\n                      name\n                      value\n                  }\n                  price\n                  \n                  splPrice\n              }\n              images\n              jitValue\n              product_slug: productSlug\n              created\n              prodType\n            }\n          }\n        }\n        "}
        body['query'] =body['query'].replace('{}',f'{page}')
        return body
        
    @staticmethod
    def create_brand_context_from_souled_store(shop):

        shop_name = shop.get("name",'')
        brand_info = {
                    'brandName': shop_name,
                    'address' :  {
                        'companyName': shop_name,
                        'streetAddress1': '',
                        'city': '',
                        'postalCode': '',
                        'country': 'IN'
                    },
                    'returnAddress': {
                        'companyName': shop_name,
                        'streetAddress1': '',
                        'city': '',
                        'postalCode': '',
                        'country': 'IN'
                    },
                    'panNumber': '',
                    'brandSource': "CUSTOM",
                    'companyName': shop_name,
                    'brandContactName':  shop_name,
                    'brandContactNumber': ''
                }

        return brand_info

    @staticmethod
    def prepare_context_for_order(user_email,billing_address,shipping_address,line_items):
        data = {"user": {
                    "gender":"F",
                    "firstname": billing_address.first_name,
                    "lastname": billing_address.last_name,
                    "email": user_email,
                    "phone": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else ''
                }, 
                "order":{
                    "line_items": line_items,
                    "order_date":StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time()),
                    "order_id":"11"
                    },
                "address": {
                    "address1": billing_address.street_address_1 or '-',
                    "address2": billing_address.street_address_2 or '-',
                    "city": billing_address.city or '-',
                    "state": billing_address.country_area or '-',
                    "pincode": billing_address.postal_code or '-',
                    "country": "IN",
                    "landmark": "-"
                },
                "return_url":"xxxx"
                
                }
    
        return data

    @staticmethod
    def get_brand_to_zammo_order_status(status):
        
        if not status:
            return None

        if status.lower()=='delivered':
            zaamo_status = 'DELIVERED'
        
        elif status.lower()=='order_placed':
            zaamo_status = 'PLACED'
            
        elif status.lower()=='fulfilled':
            zaamo_status = 'SHIPPED'
        else:
            zaamo_status = None
            
        return zaamo_status