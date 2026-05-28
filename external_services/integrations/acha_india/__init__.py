from collections import defaultdict
from decimal import Decimal
from saleor.external_services.integrations.base import BaseIntegration
from saleor.utilities.number_utilities import NumberUtilities
from django.db.models import Subquery
from saleor.utilities.string_utilities import StringUtilities
from saleor.order.models import OrderBrandZaamoMapping
from saleor.utilities.time_utilities import TimeUtilities

class AchaIndiaIntegration(BaseIntegration):

    category = "acha_india_uncategorized"

    product_type = "acha_india_product_type"
    
    brand_id = None
    category_id = None

    def get_catagory_id(self, name, **kwrgs):

        if self.category_id is None:
            self.category_id = super().get_catagory_id(name, **kwrgs)

        return self.category_id

    def _structure_variant_data_if_variations_exist(self, variations, product_name, color, product):

        variant_price_id_dict = dict()
        product_variants = list()

        for variant in variations:
            variant_obj = dict()
            attribute = variant.get('item_spec')
            variant_attribute = defaultdict(list)
            variant_name = ''
            
            for att in attribute:
                
                if not att['name'].lower() in ['size','color']:
                    continue
                
                variant_attribute[att['name']].append(StringUtilities.convert_object_to_string(att['item']['name']))
            
            if not color in variant_attribute['color']:
                continue

            variant_name = variant_attribute.get('size')
            
            if not variant_name:
                variant_name = product_name

            else:
                variant_name = ' - '.join(variant_name)

            if variant_attribute.get('color'):
                variant_attribute.pop('color')

            variant_obj['attributes'] = variant_attribute

            variant_price = variant.get('item_cost_price') or variant.get('item_platform_price')
            variant_regular_price = variant.get('item_market_price') or variant_price
            
            variant_price = NumberUtilities.convert_string_to_float(variant_price)
            variant_regular_price = NumberUtilities.convert_string_to_float(variant_regular_price)

            if variant_price==0 or variant_regular_price==0:
                continue
            
            if variant_price>variant_regular_price:
                variant_regular_price = variant_price
                
            quantity = NumberUtilities.convert_string_to_number(variant.get('item_quantity'))

            if quantity<0:
                quantity = 0

            track_inventory = True

            variant_fields = {
                        "variant_id_brand": variant['item_number'],
                        "private_metadata": {'item_id':variant['item_id']},
                        "metadata": {},
                        "sku_id_brand": variant.get('sku', '') + StringUtilities.convert_number_to_string(variant['item_number']),
                        "name": variant_name ,
                        "price_amount": variant_price,
                        "cost_price_amount": variant_regular_price,
                        "default": False,
                        "track_inventory": track_inventory
                        
                        }

            variant_price_id_dict[variant_price] = variant['item_number']
            variant_obj['fields'] = variant_fields
            variant_obj['stock'] = {}
            variant_obj['stock']['quantity'] = quantity

            product_variants.append(variant_obj)

        return product_variants, variant_price_id_dict


    def _structure_product_attributes(self,product_attributes_values):
        
        product_attributes = dict()

        if product_attributes_values:

            for att in product_attributes_values:

                if att['name'].lower() in ['size','color']:
                    product_attributes[att['name'].lower()] = {
                                                'is_variant_attribute': True ,
                                                'values': [value['name'] for value in att['item']]
                                            }
        return product_attributes

    def _prepare_variant_and_attribute_data(self, product, color):
        
        variations = product.get('variants')
        variant_price_id_dict = dict()
        product_variants = []
        min_price = None

        if variations:
            
            product_variants, variant_price_id_dict = self._structure_variant_data_if_variations_exist(variations, product.get('product_name', ''), color, product)
        
        if not product_variants:
            print(product['product_id'])
            return None, None

        min_price = min(variant_price_id_dict.keys())
        min_price_id = variant_price_id_dict[min_price]

        for variant in product_variants:

            if variant['fields']['variant_id_brand'] == min_price_id:
                variant['fields']['default'] = True
                break
        
                                    
        return product_variants, min_price

    def _prepare_product_description_json(self, json_item):
        
        full_description = []

        if json_item.get("product_detail"):
            description = json_item.get("product_detail").replace('\n','')
            full_description.append(description)
        
        description_response = '<br/>'.join(full_description)
        
        return description_response


    def _get_mapped_data(self,data):

        json_item = data['json_item']

        variants, min_price = self._prepare_variant_and_attribute_data(json_item, data['color'])

        if not variants:
            return None

        description_json = self._prepare_product_description_json(json_item)

        product = {
            "fields": {
                "brand": data['brand'],
                "private_metadata": {'product_id': json_item['product_id']},
                "metadata": {},
                "name": data['product_name'],
                "description_json": {"description_text": description_json},
                "minimal_variant_price_amount": StringUtilities.convert_object_to_string(min_price),
            }
        }

        variant_ids = []
        
        for variant in variants:
            id = variant['fields'].get('variant_id_brand')
            if id:
                variant_ids.append(id)

        brand_mapping = dict()
        brand_mapping['product_id_brand'] = data['brand_variant_zaamomapping']['product_id_brand']
        brand_mapping['brand_name'] = data['brand_variant_zaamomapping']['brand_name']
        brand_mapping['source'] = data['brand_variant_zaamomapping']['source']
        brand_mapping['variant_id_brands'] = variant_ids

        mapped_data = {
            "product.category" : data['category'],
            "product.producttype": data['product_type'],
            "brand.brand": data['brand'],
            "product.attribute": data['product_attributes'],
            "product.brand_variant_zaamomapping": brand_mapping,
            "product.productimage": data['images'],
            "product.product": product,
            "product.productvariant":variants,
            "upload_images_to_ecom": True,
            "product.created_at" : json_item.get('date_created') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time()),
            "product.updated_at" : json_item.get('date_modified') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())
        }
        
        return mapped_data

    def _create_color_attribute_image(self, variant_list, product_name, product_images):
        color_name_dict = dict()
        color_image_dict = defaultdict(list)
        image_urls = list()
        
        for variant in variant_list:
            attributes = variant['item_spec']

            v_image = variant.get('item_image_row') or []

            for att in attributes:
            
                if att['name'].lower()=='color':
                    color_name_dict[att['item']['name']] = product_name + ' ' + att['item']['name']
                    
                    if v_image:

                        for v_image_src in v_image:

                            if not v_image_src in color_image_dict[att['item']['name']]:
                                color_image_dict[att['item']['name']].append(v_image_src)

            for v_image_src in v_image:

                if not v_image_src in image_urls:

                    image_urls.append(v_image_src)
        
        if not color_name_dict:
            color_name_dict['default'] = product_name
            color_image_dict['default'] = product_images
            
        for color in color_name_dict.keys():
            
            if not color in color_image_dict.keys():
                color_image_dict[color] = product_images

        return color_name_dict,color_image_dict

    def _prepare_simple_image(self,image_list):
        image_url = []

        for image in image_list.values():
            image_url.append(image)    
        
        return image_url


    def base_product_mapper(self, json_item):

        product_list = []
        color_name_dict = dict()
        color_images_dict = dict()

        brand = self.get_brand_from_private_metadata(json_item.get('vendor'))
        
        category = self.get_catagory_id(self.category)

        if not category:
            return []
        
        product_type = self.get_or_create_product_type(product_type=self.product_type)
        json_item_row = json_item['item_row']
        product_attributes = self._structure_product_attributes(json_item_row['product_spec'])
        brand_variant_zaamomapping = { 
            "product_id_brand": json_item_row.get("product_number"),
            "brand_name": json_item.get('vendor'),
            "source": "achaindia"
        }

        product_images = self._prepare_simple_image(json_item_row.get('product_spec_image_row'))
        json_item_row['variants'] = json_item['variants']
        if json_item['variants']:

            color_name_dict, color_images_dict = self._create_color_attribute_image(json_item['variants'], json_item_row.get('product_name'), product_images)

        else:

            color_name_dict['default'] = json_item_row.get('product_name')
            color_images_dict['default'] = product_images

        data = {
            'brand':brand,
            'category':category,
            'product_type':product_type,
            'brand_variant_zaamomapping':brand_variant_zaamomapping,
            'json_item':json_item_row,
            'product_attributes':product_attributes
        }

        for key in color_name_dict.keys():
            data['product_name'] = color_name_dict[key]
            data['color'] = key
            data['images'] = color_images_dict[key]

            mapped_data = self._get_mapped_data(data)
            if mapped_data:
                product_list.append(mapped_data)

        return product_list
