from saleor.settings import BACKEND_URL
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities

class ShopifyHelper(object):
    
    @staticmethod
    def deEmojify(inputString):
        try:
            return inputString.encode('ascii', 'ignore').decode('ascii')
        except Exception as e:
            return inputString

    @staticmethod
    def get_url_list(images):
        image_list = []

        for img_idx in range(0, len(images)):
            image_dict = {}
            
            for key, value in images[img_idx].attributes.items():
                image_dict[key] = value

            image_list.append(image_dict)

        return image_list

    @staticmethod
    def get_variant_list(variants):
        variant_list = []

        for variant_idx in range(0, len(variants)):
            variant_dict = {}
            
            for key, value in variants[variant_idx].attributes.items():
                variant_dict[key] = value
            
            variant_list.append(variant_dict)

        return variant_list

    @staticmethod
    def get_option_list(options):
        option_list = []

        for optn_idx in range(0, len(options)):
            options_dict = {}

            for key, value in options[optn_idx].attributes.items():
                options_dict[key] = value
            option_list.append(options_dict)

        return option_list
    
    @staticmethod
    def process_product_list_from_shopify(products,product_collection_dict):
        product_list = []

        for p_idx in range(0, len(products)):
            "will modify this whole function"
            product = {}
            product['id'] = products[p_idx].id
            product['title'] = products[p_idx].title
            product['vendor'] = products[p_idx].vendor.strip()
            product['description'] = products[p_idx].body_html
            product['product_type'] = products[p_idx].product_type
            product['tags'] = products[p_idx].tags
            product['collections'] = product_collection_dict[products[p_idx].id]
            product['handle'] = products[p_idx].handle
            product['status'] = products[p_idx].status
            images = products[p_idx].images
            url_list = ShopifyHelper.get_url_list(images)
            product['url_list'] = url_list
            variants = products[p_idx].attributes['variants']
            variant_list = ShopifyHelper.get_variant_list(variants)
            product['variants_list'] = variant_list
            options = products[p_idx].attributes['options']
            option_list = ShopifyHelper.get_option_list(options)
            product['options'] = option_list
            product['images'] = url_list
            product['created_at'] = products[p_idx].created_at
            product['updated_at'] = products[p_idx].updated_at
            product_list.append(product)

        return product_list

    @staticmethod
    def prepare_address_for_order(address):
        first_name = ShopifyHelper.deEmojify(address.first_name)
        last_name = ShopifyHelper.deEmojify(address.last_name)
        address = {    
                    "first_name": first_name or '',
                    "last_name": last_name if last_name else first_name,
                    "address1": address.street_address_1 or '',
                    "address2": address.street_address_2 or '',
                    "phone": StringUtilities.convert_number_to_string(address.phone.national_number) if address.phone else '',
                    "city": address.city or '',
                    "province":address.country_area or '',
                    "zip": address.postal_code or '',
                    "country_code": StringUtilities.convert_object_to_string(address.country) or "IN",
                    "country": 'India'
                        }

        return address

    @staticmethod
    def prepare_line_items(order_lines, brand_mappings):

        line_items = []

        total = 0.00
        
        for i in range(len(order_lines)):
            item = dict()
            variant_brand_id = brand_mappings[i].variant_id_brand
            quantity = order_lines[i].quantity
            price = StringUtilities.convert_object_to_string(order_lines[i].unit_price_net_amount)
            true_msp = order_lines[i].metadata.get('true_msp',0)
            true_msp = NumberUtilities.convert_string_to_decimal(true_msp)

            item = {
                "variant_id": variant_brand_id,
                "quantity": quantity
            }
            
            if true_msp and order_lines[i].unit_price_net_amount>true_msp and order_lines[i].cod:
                item['price']=price

            total += quantity*NumberUtilities.convert_string_to_float(order_lines[i].unit_price_net_amount)
            line_items.append(item)

        return line_items,total
        
    def get_data_for_webhook(topic, endpoint):
        data = {
                    
                    "format": "json",
                    "fields": ["id","note"],
                    "topic": topic,
                    "address": f"{BACKEND_URL}/webhooks/shopify/{endpoint}"
                    
                    }
        
        if endpoint=='fulfillment_updated':
            data['fields'].append('order_id') 

        return data

    def get_transaction_body(amount):
        body = {"transaction":{"currency":"INR","amount":StringUtilities.convert_number_to_string(amount),"kind":"capture", "source": "external"}}
        return body

    @staticmethod
    def get_brand_to_zammo_order_status_shipment(status):
        
        if not status:
            return None

        if status.lower() in ['label_printed', 'ready_for_pickup', 'confirmed']:
            zaamo_status = 'IN_PROCESS'
        
        elif status.lower() in ['delivered']:
            zaamo_status = 'DELIVERED'
        
        elif status.lower() in ['restocked', 'failure']:
            zaamo_status = 'CANCELLATION_PROCESSED'
        
        elif status.lower() in ['in_transit', 'out_for_delivery','fulfilled']:
            zaamo_status = 'SHIPPED'

        else:
            zaamo_status = None
        
        return zaamo_status
