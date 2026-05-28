from collections import defaultdict
from decimal import Decimal
from saleor.external_services.integrations.base import BaseIntegration
from saleor.graphql.product.utils import update_msp_of_variant_using_step_price
from saleor.order import FulfillmentStatus
from saleor.product.models import BrandPriceRecord, BrandVariantZaamoMapping, ProductImage, Product
from django.db import transaction
from saleor.utilities.number_utilities import NumberUtilities
from django.db.models import Subquery
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.warehouse.models import Stock
from saleor.external_services.woo_commerce_service.constants import COLOR_KEY_LIST, SIZE_KEY_LIST
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
import logging
logger = logging.getLogger(__name__)
class WooCommerceIntegration(BaseIntegration):

    category = "woocommerce_uncategorized"

    product_type = "woocommerce_product_type"
    
    brand_id = None
    category_id = None

    def get_catagory_id(self, name, **kwrgs):

        if self.category_id is None:
            self.category_id = super().get_catagory_id(name, **kwrgs)

        return self.category_id

    
    def _structure_variant_data_for_simple_product(self,product):
        
        product_variants = []

        product_price = product.get('price')
        product_regular_price = product.get('regular_price') or product.get('price')

        product_price = NumberUtilities.convert_string_to_float(product_price)
        product_regular_price = NumberUtilities.convert_string_to_float(product_regular_price)

        if product_price>product_regular_price:
            product_regular_price = product_price

        if product_price==0 or product_regular_price==0:
            return None, None
        
        quantity = NumberUtilities.convert_string_to_number(product.get('stock_quantity',0))

        if quantity<0:
            quantity = 0

        track_inventory = True

        if not product['manage_stock'] and product['stock_status']=='instock':
            track_inventory = False

        variant_obj = dict()
        variant_obj['attributes'] = {}
        variant_obj['fields'] = {
                    "variant_id_brand": None,
                    "private_metadata": {},
                    "metadata": {},
                    "sku_id_brand": product.get('sku', ''),
                    "name": product.get('name', '') ,
                    "price_amount": product_price,
                    "cost_price_amount": product_regular_price,
                    "default": True,
                    "track_inventory": track_inventory
                    }
        min_price = Decimal(product_price)
        variant_obj['stock'] = {}
        variant_obj['stock']['quantity'] = quantity

        product_variants.append(variant_obj)

        return product_variants, min_price

    def _structure_variant_data_if_variations_exist(self, variations, product_name, color, product):

        variant_price_id_dict = dict()
        product_variants = list()

        for variant in variations:
            variant_obj = dict()
            attribute = variant.get('attributes')
            variant_attribute = defaultdict(list)
            variant_name = ''
            
            for att in attribute:
                
                if att['name'].lower() in COLOR_KEY_LIST:
                    att['name'] = 'color'

                if 'size' in att['name'].lower():
                    att['name'] = 'size'
                
                if att['name'].lower() in SIZE_KEY_LIST:
                    att['name'] = 'size'
                    
                if not att['name'] in ['size','color']:
                    continue
                
                variant_attribute[att['name']].append(att['option'])
            
            if 'color' in variant_attribute.keys():

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

            variant_price = variant.get('price')
            variant_regular_price = variant.get('regular_price') or variant.get('price')
            
            variant_price = NumberUtilities.convert_string_to_float(variant_price)
            variant_regular_price = NumberUtilities.convert_string_to_float(variant_regular_price)

            if variant_price==0 or variant_regular_price==0:
                continue
            
            if variant_price>variant_regular_price:
                variant_regular_price = variant_price
                
            quantity = NumberUtilities.convert_string_to_number(variant.get('stock_quantity'))

            if quantity<0:
                quantity = 0

            track_inventory = True

            if not variant['manage_stock'] and variant['stock_status']=='instock':
                track_inventory = False

            variant_fields = {
                        "variant_id_brand": variant['id'],
                        "private_metadata": {},
                        "metadata": {},
                        "sku_id_brand": variant.get('sku', '') + StringUtilities.convert_number_to_string(variant['id']),
                        "name": variant_name ,
                        "price_amount": variant_price,
                        "cost_price_amount": variant_regular_price,
                        "default": False,
                        "track_inventory": track_inventory
                        
                        }

            variant_price_id_dict[variant_price] = variant['id']
            variant_obj['fields'] = variant_fields
            variant_obj['stock'] = {}
            variant_obj['stock']['quantity'] = quantity

            product_variants.append(variant_obj)
        return product_variants, variant_price_id_dict


    def _structure_product_attributes(self,product_attributes_values):
        
        product_attributes = dict()
        if product_attributes_values:
            for att in product_attributes_values:

                if att['name'].lower() in COLOR_KEY_LIST:
                    att['name'] = 'color'
                
                if 'size' in att['name'].lower():
                    att['name'] = 'size'

                if att['name'].lower() in SIZE_KEY_LIST:
                    att['name'] = 'size'
                    
                if att['name'].lower() in ['size','color']:
                    product_attributes[att['name'].lower()] = {
                                                'is_variant_attribute': True if att.get('variation') else False,
                                                'values': att['options']
                                            }
        return product_attributes

    def _prepare_variant_and_attribute_data(self, product, color,p_name):
        
        variations = product.get('variations')
        variant_price_id_dict = dict()
        product_variants = []
        min_price = None

        if variations:
            
            product_variants, variant_price_id_dict = self._structure_variant_data_if_variations_exist(variations, p_name, color, product)
        
        else:

            product_variants, min_price = self._structure_variant_data_for_simple_product(product)
        
        if not product_variants:
            return None, None

        if not min_price:
            min_price = min(variant_price_id_dict.keys())
            min_price_id = variant_price_id_dict[min_price]

            for variant in product_variants:

                if variant['fields']['variant_id_brand'] == min_price_id:
                    variant['fields']['default'] = True
                    break
        
                                    
        return product_variants, min_price

    def _prepare_product_description_json(self, json_item):
        
        attributes = json_item.get('attributes')
        attribute_list = []

        for att in attributes:
            
            
            if 'size' in att['name'].lower():
                continue

            if att['name'].lower() in SIZE_KEY_LIST:
                continue

            attr_string = f"<b>{att['name']}</b> : {', '.join(att['options'])}"
            attribute_list.append(attr_string)

        weight = json_item.get('weight')

        if weight:
            attribute_list.append(f"<b>weight</b> : {weight}")

        dimensions = json_item.get('dimensions')
        len = dimensions['length']
        wid = dimensions['width']
        height = dimensions['height']

        if len and wid and height:
            attribute_list.append(f"<b>Dimensions</b> : {len} * {wid} * {height}")
        
        description_string = '<br/>'.join(attribute_list)

        if description_string:
            description_string = '<p>' + description_string + '</p>'
        
        full_description = []

        if json_item.get("description"):
            description = json_item.get("description").replace('\n','')
            full_description.append(description)

        if json_item.get("short_description"):
            short_description = json_item.get("short_description").replace('\n','')
            full_description.append(short_description)
        
        if description_string:
            full_description.append(description_string)
        
        description_response = '<br/>'.join(full_description)
        
        return description_response


    def _get_mapped_data(self,data):

        json_item = data['json_item']
        p_name = data['product_name']
        variants, min_price = self._prepare_variant_and_attribute_data(json_item, data['color'],p_name)

        if not variants:
            return None

        description_json = self._prepare_product_description_json(json_item)

        product = {
            "fields": {
                "brand": data['brand'],
                "private_metadata": {},
                "metadata": {},
                "name": data['product_name'],
                "description_json": {"description_text": description_json},
                "minimal_variant_price_amount": str(min_price),
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

    def _create_color_attribute_image(self, variant_list, product_name,product_images):
        color_name_dict = dict()
        color_image_dict = defaultdict(list)
        image_urls = list()
        for variant in variant_list:
            attributes = variant['attributes']
            v_image_src = None

            v_image = variant.get('image')

            if v_image:
                v_image_src = v_image.get('src')

            for att in attributes:

                if att['name'].lower() in COLOR_KEY_LIST:
                    att['name'] = 'color'
            
                if att['name'].lower()=='color':
                    color_name_dict[att['option']] = product_name + ' ' + att['option']
                    
                    if v_image_src:
                        if not v_image_src in color_image_dict[att['option']]:
                            color_image_dict[att['option']].append(v_image_src)

            if v_image_src:

                if not v_image_src in image_urls:
                    image_urls.append(v_image_src)
        
        if not color_name_dict:
            color_name_dict['default'] = product_name
            color_image_dict['default'] = image_urls
        
        for i_url in product_images:

            if i_url not in image_urls:

                for color in color_name_dict.keys():
                    
                    if not i_url in color_image_dict[color]:
                        color_image_dict[color].append(i_url)

        return color_name_dict,color_image_dict

    def _prepare_simple_image(self,image_list):
        image_url = []

        for image in image_list:
            image_url.append(image['src'])    
        
        return image_url


    def base_product_mapper(self, json_item):

        if json_item.get('status')=='draft':
            return []

        product_list = []
        color_name_dict = dict()
        color_images_dict = dict()

        brand = self.get_brand_from_private_metadata(json_item.get('vendor'))
        
        category = self.get_catagory_id(self.category)

        if not category:
            return []
        
        product_type = self.get_or_create_product_type(product_type=self.product_type)
        
        product_attributes = self._structure_product_attributes(json_item['attributes'])
        brand_variant_zaamomapping = { 
            "product_id_brand": json_item.get("id"),
            "brand_name": json_item.get('vendor'),
            "source": "woocommerce"
        }

        product_images = self._prepare_simple_image(json_item.get('images'))

        if json_item['variations']:

            color_name_dict, color_images_dict = self._create_color_attribute_image(json_item['variations'], self.clean_product_name(json_item.get('name')),product_images)

        else:

            color_name_dict['default'] = self.clean_product_name(json_item.get('name'))
            color_images_dict['default'] = product_images

        data = {
            'brand':brand,
            'category':category,
            'product_type':product_type,
            'brand_variant_zaamomapping':brand_variant_zaamomapping,
            'json_item':json_item,
            'product_attributes':product_attributes
        }

        for key in color_name_dict.keys():
            data['product_name'] = self.clean_product_name(color_name_dict[key])
            data['color'] = key
            data['images'] = color_images_dict[key]

            mapped_data = self._get_mapped_data(data)
            if mapped_data:
                product_list.append(mapped_data)

        return product_list

    #Product Delete functions

    def delete_variation_if_removed_from_store(self, data,shop_name):
        existing_variants = BrandVariantZaamoMapping.objects.filter(product_id_brand = data['id'],brand_name=shop_name).values_list('variant_id_brand','product_zaamo_id')
        existing_variants_set = set()
        varaint_from_data = set()
        product_variant_brand_dict = defaultdict(list)

        for variant_id in existing_variants:
            if variant_id[0]:
                existing_variants_set.add(StringUtilities.convert_number_to_string(variant_id[0]))
                product_variant_brand_dict[variant_id[1]].append(StringUtilities.convert_number_to_string(variant_id[0]))

        variant_list_data = data['variations']

        for variant in variant_list_data:
            varaint_from_data.add(StringUtilities.convert_number_to_string(variant['id']))

        variants_to_rem = existing_variants_set.difference(set(varaint_from_data))

        if variants_to_rem:
            stock_update = (Stock.objects.select_for_update().filter(product_variant_id__in=Subquery(
                                BrandVariantZaamoMapping.objects.filter(variant_id_brand__in=variants_to_rem
                                ).values('variant_zaamo_id')))).select_related('product_variant')
            
            with transaction.atomic():
                for stock in stock_update:
                    stock.quantity = 0
                    stock.save()
                    cur_variant= stock.product_variant
                    cur_variant.track_inventory = True
                    cur_variant.save()

            product_to_rem = []

            for key, value in product_variant_brand_dict.items():
                
                if not value or variants_to_rem:
                    continue
                
                diff = set(value).difference(variants_to_rem)

                if not diff:
                    product_to_rem.append(key)
            
            if product_to_rem:
                product_to_update = Product.objects.select_for_update().filter(id__in=product_to_rem)

                with transaction.atomic():

                    for product in product_to_update:
                        product.is_published = False
                        product.save()
        

    def disable_publish_product_from_postgres_by_product_id_brand(self, product_id,brand_name):

        products_to_update = Product.objects.filter(id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(
                        product_id_brand=product_id,brand_name=brand_name).values
                        ('product_zaamo_id')))
        
        with transaction.atomic():
            for product in products_to_update:
                product.is_published=False
                product.save()

        return products_to_update
        
    
    def delete_existing_product_images(self,product_id):

        product_images = (ProductImage.objects.filter(product_id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(
                        product_id_brand=product_id).values
                        ('product_zaamo_id'))).delete())

    def clean_variant_data_for_update(self,variants):
        variant_id_info = dict()
        for variant in variants:

            variant_price = variant.get('price')
            variant_regular_price = variant.get('regular_price') or variant.get('price')
            
            variant_price = NumberUtilities.convert_string_to_float(variant_price)
            variant_regular_price = NumberUtilities.convert_string_to_float(variant_regular_price)

            if variant_price==0 or variant_regular_price==0:
                continue
            
            if variant_price>variant_regular_price:
                variant_regular_price = variant_price
                
            quantity = NumberUtilities.convert_string_to_number(variant.get('stock_quantity'))

            if quantity<0:
                quantity = 0

            track_inventory = True

            if not variant['manage_stock'] and variant['stock_status']=='instock':
                track_inventory = False
            
            variant_id_info[variant['id']] = {
                'cost_price': variant_regular_price,
                'selling_price': variant_price,
                'quantity': quantity,
                'track_inventory': track_inventory
            }
        
        return variant_id_info
    
    def clean_variant_data_for_update_for_simple_product(self,product):

        variant_id_info = dict()
        product_price = product.get('price')
        product_regular_price = product.get('regular_price') or product.get('price')

        product_price = NumberUtilities.convert_string_to_float(product_price)
        product_regular_price = NumberUtilities.convert_string_to_float(product_regular_price)

        if product_price>product_regular_price:
            product_regular_price = product_price

        if product_price==0 or product_regular_price==0:
            return variant_id_info
        
        quantity = NumberUtilities.convert_string_to_number(product.get('stock_quantity',0))

        if quantity<0:
            quantity = 0

        track_inventory = True

        if not product['manage_stock'] and product['stock_status']=='instock':
            track_inventory = False
        
        variant_id_info[product['id']] = {
            'cost_price': product_regular_price,
            'selling_price': product_price,
            'quantity': quantity,
            'track_inventory': track_inventory
        }
        
        return variant_id_info

    def update_inventory_and_price(self,new_product_data, brand_name):
        product_id = new_product_data['id']
        variations_list = new_product_data.get('variations')

        if variations_list:
            variants = self.clean_variant_data_for_update(variations_list)
            brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id, variant_id_brand__in=list(variants.keys()))

        else:
            variants = self.clean_variant_data_for_update_for_simple_product(new_product_data)
            brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id)

        for brand_mapping in brand_mappings:

            if variations_list:
                variant_info = variants.get(NumberUtilities.convert_string_to_number(brand_mapping.variant_id_brand))

            else:
                variant_info = variants.get(NumberUtilities.convert_string_to_number(brand_mapping.product_id_brand))

            if not variant_info:
                continue

            variant = brand_mapping.variant_zaamo

            if not variant:
                continue
            
            with transaction.atomic():
                
                if not variant.cost_price_amount == variant_info.get('cost_price') or not variant.price_amount == variant_info.get('selling_price') or not variant.track_inventory == variant_info.get('track_inventory'):
                    variant.cost_price_amount = variant_info.get('cost_price')
                    variant.price_amount = variant_info.get('selling_price')
                    variant.track_inventory = variant_info.get('track_inventory')
                    variant.metadata['true_msp'] = variant_info.get('selling_price')
                    variant.save()
                    update_msp_of_variant_using_step_price(variant)

                stock_to_update = Stock.objects.select_for_update().filter(product_variant_id=variant.id)
            
                
                for stock in stock_to_update:
                    if not stock.quantity==variant_info.get('quantity'):
                        stock.quantity=variant_info.get('quantity')
                        stock.save()

    def update_brand_price_record(self,new_product_data, brand_name,existing_product):
        product_id = new_product_data['id']
        variations_list = new_product_data.get('variations')
        p_name = new_product_data.get('name')

        if variations_list:
            new_variants = self.clean_variant_data_for_update(variations_list)
            exiiting_variants = self.clean_variant_data_for_update(existing_product.get('variations'))

            
        else:
            new_variants = self.clean_variant_data_for_update_for_simple_product(new_product_data)
            exiiting_variants = self.clean_variant_data_for_update_for_simple_product(existing_product)
            
        mapped_data = self.base_product_mapper(new_product_data)
        variant_id_product_variant_name = dict()

        for data in mapped_data:

            product_name = data['product.product']['fields']['name']
            variants = data['product.productvariant']

            for variant in variants:
                variant_name = variant['fields']['name']
                if variant['fields'].get('variant_id_brand'):
                    variant_id_product_variant_name[StringUtilities.convert_object_to_string(variant['fields']['variant_id_brand'])] = (product_name,variant_name)


        for id,variant_info in new_variants.items():
            existing_variant_info = exiiting_variants.get(id)
            
            if not existing_variant_info:
                continue

            current_cost_price = existing_variant_info.get('cost_price')
            current_price_amount = existing_variant_info.get('selling_price')
            new_cost_price_amount = variant_info.get('cost_price')
            new_price_amount = variant_info.get('selling_price')
            
            if current_cost_price==new_cost_price_amount and current_price_amount==new_price_amount:
                continue
            
            name = variant_id_product_variant_name.get(StringUtilities.convert_object_to_string(id))

            product_mapping = None

            product_mapping = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name,product_id_brand=product_id,variant_id_brand=id).select_related('product_zaamo').first()

            if not product_mapping:
                product_mapping = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name,product_id_brand=product_id).select_related('product_zaamo').first()
            

            if product_mapping:
                data_source = 'postgres'
                is_published = is_published = product_mapping.product_zaamo.is_published

            
            else:
                data_source = 'mongo'
                is_published = False

            if name:
                product_brand_name = name[0]
                variant_brand_name = name[1]
            
            else:
                product_brand_name = variant_brand_name = p_name

            with transaction.atomic():

                if not current_cost_price==new_cost_price_amount or not current_price_amount==new_price_amount:

                    record_data = {"brand_name" : brand_name,
                                    "product_id_brand" : product_id,
                                    "variant_id_brand" : id,
                                    "source" : 'woocommerce',
                                    "current_price_amount" : new_price_amount,
                                    "current_cost_price_amount" : new_cost_price_amount,
                                    "prev_price_amount" : current_price_amount,
                                    "prev_cost_price_amount" : current_cost_price,
                                    "product_name": product_brand_name,
                                    "variant_name":variant_brand_name,
                                    "data_source":data_source,
                                    "is_published":is_published
                                    }
                                    
                    
                    try:
                        brand_record = BrandPriceRecord.objects.update_or_create(product_id_brand=product_id, 
                                                                variant_id_brand=id,brand_name=brand_name, defaults=record_data)

                        if product_mapping and product_mapping.product_zaamo.metadata.get('value_deal'):
                            
                            if self.is_price_increment_by_n_percent(NumberUtilities.convert_string_to_float(new_price_amount),
                                                                    NumberUtilities.convert_string_to_float(current_price_amount)):
                                product_zaamo = product_mapping.product_zaamo
                                product_zaamo.metadata['value_deal'] = False
                                product_zaamo.metadata['value_updated_at'] = TimeUtilities.get_current_date_time()
                                product_zaamo.save()

                    except Exception as e:
                        logger.exception(e)
      
    def is_price_increment_by_n_percent(self,new_price_amount,current_price_amount,percent=10):

        if not new_price_amount>current_price_amount:
            return False

        diff = new_price_amount - current_price_amount

        if diff>=(current_price_amount*percent*0.01):
            return True
        
        return False

    def update_status_in_fulfillment(self, order_brand_id, zaamo_status,brand_id):
        fulfillment_status_update = dict()
        order_line_brand = OrderBrandZaamoMapping.objects.filter(order_id_brand=order_brand_id, brand_id=brand_id).values('order_line_zaamo_id')
        
        ignore_status = [FulfillmentStatus.CANCELLATION_PROCESSED,FulfillmentStatus.CANCELLATION_INITIATED,FulfillmentStatus.DELIVERED,FulfillmentStatus.RETURN_REQUESTED,FulfillmentStatus.RETURN_INITIATED,FulfillmentStatus.RETURN_COMPLETED]
        
        fulfillments = Fulfillment.objects.filter(id__in = Subquery(FulfillmentLine.objects.filter(order_line_id__in=order_line_brand).values('fulfillment_id'))).exclude(status__in=ignore_status)
        status_ranking = self.order_status_ranking_dict()
        
        for fulfillment in fulfillments:
            try:
                
                if fulfillment.status==zaamo_status.lower().replace('_',' '):
                    continue

                if status_ranking[fulfillment.status]>status_ranking[zaamo_status.lower().replace('_',' ')]:
                    continue

                fulfillment_status_update[fulfillment.id] = zaamo_status

                ful_line = fulfillment.lines.first()
                
                if ful_line.note:
                    continue

                if zaamo_status in ('CANCELLATION_PROCESSED','CANCELLATION_INITIATED'):
                  
                    ful_line.note='System generated, order cancellation by brand'
                    ful_line.save()
                    fulfillment.metadata['brand_cancelled']=True
                    fulfillment.save()

            except Exception as e:
                logger.exception(e)
                
                
        return fulfillment_status_update
