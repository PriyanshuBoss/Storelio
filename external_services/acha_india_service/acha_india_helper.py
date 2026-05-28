import base64

class AchaIndiaHelper(object):
    @staticmethod
    def create_brand_context_from_acha_india(shop):

        shop_name = shop.get("name",'')
        brand_info = {
                    'brandName': shop_name,
                    'address' :  {
                        'companyName': shop_name,
                        'country': shop.get("Country",'IN')
                    },
                    'returnAddress': {
                        'companyName': shop_name,
                        'country': shop.get("Country",'IN')
                    },
                    'panNumber': '',
                    'brandSource': "ACHAINDIA",
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
