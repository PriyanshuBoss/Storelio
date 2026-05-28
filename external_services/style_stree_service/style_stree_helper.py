

from saleor.utilities.string_utilities import StringUtilities


class StyleStreeHelper(object):
    
    @staticmethod
    def create_brand_context_from_style_stree(shop):

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
        data = {'email': user_email, 
                'line_items': line_items,
                "billing_address": {
                    "first_name": billing_address.first_name,
                    "last_name": billing_address.last_name,
                    "address1": billing_address.street_address_1,
                    "address2": billing_address.street_address_2,
                    "city": billing_address.city,
                    "zip": billing_address.postal_code,
                    "country": StringUtilities.convert_object_to_string(billing_address.country),
                    "province": billing_address.country_area,
                    "phone": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else ''
                },
                "Shipping_address" : {
                    "first_name": billing_address.first_name,
                    "last_name": billing_address.last_name,
                    "address1": billing_address.street_address_1,
                    "address2": billing_address.street_address_2,
                    "city": billing_address.city,
                    "zip": billing_address.postal_code,
                    "country": StringUtilities.convert_object_to_string(billing_address.country),
                    "province": billing_address.country_area,
                    "phone": StringUtilities.convert_number_to_string(billing_address.phone.national_number) if billing_address.phone else ''
                }
                }

        return data

    @staticmethod
    def get_brand_to_zammo_order_status(status):
        
        if not status:
            return None

        if status.lower()=='delivered':
            zaamo_status = 'DELIVERED'
        
        elif status.lower()=='placed':
            zaamo_status = 'PLACED'
            
        elif status.lower()=='fulfilled':
            zaamo_status = 'SHIPPED'
        else:
            zaamo_status = None
            
        return zaamo_status