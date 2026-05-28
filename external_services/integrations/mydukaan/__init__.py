
from collections import defaultdict
from saleor.external_services.integrations.base import BaseIntegration
from saleor.external_services.mydukaan_service.constants import COLOR_KEY_LIST, HEX_TO_NAME, SIZE_KEYS
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
from saleor.product.models import BrandPriceRecord, BrandVariantZaamoMapping, ProductImage, Product
from django.db.models import Subquery
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from decimal import Decimal
from saleor.utilities.time_utilities import TimeUtilities
from django.db import transaction
from saleor.warehouse.models import Stock
import re
import logging
logger = logging.getLogger(__name__)

class MyDukaanIntegration(BaseIntegration):

    category = "mydukaan_uncategorized"

    product_type = "mydukaan_product_type"
    
    brand_id = None
    category_id = None

    def get_catagory_id(self, name, **kwrgs):

        if self.category_id is None:
            self.category_id = super().get_catagory_id(name, **kwrgs)

        return self.category_id



    def get_attributes(self, json_items):
        skus = json_items['skus']
        attributes = defaultdict(list)
        for sku in skus:
            options = sku.get('attributes')
            for option in options:
                if option.get('master_attribute').lower() in COLOR_KEY_LIST:
                    option['master_attribute'] = 'color'

                if option.get('master_attribute').lower() not in ['size', 'color']:
                    continue
                
                value_cur = HEX_TO_NAME.get(option.get('value')) or option.get('value')
                if not value_cur in attributes[option['master_attribute'].lower()]:
                    attributes[option['master_attribute'].lower()].append(value_cur)

        attributes_dict = dict()

        for att, values in attributes.items():
            attributes_dict[att] = {"values": values, "is_variant_attribute": True}

        return attributes_dict

    def _get_color_option(self, options):
        color_options = []
        size_options = []

        for name,option in options.items():

            if name.lower() == 'colour':
                option['name'] = 'color'

            if name.lower() == 'color':
                color_options = option.get('values') or []
            
            if name.lower() in SIZE_KEYS or 'size' in name.lower():
                size_options_list = option.get('values') or []
                size_options.extend(size_options_list)

        return {'color': color_options, 'size': size_options}

    def get_variants_data(self, variants, p_name, color):
        
        variants_data = []
        minimal_price_amount = 10**20

        for variant in variants:
            name = None

            _variant_data = {}
            _variant_attr = {}

            if not variant.get('attributes'):
                name = p_name
            
            else:
                values = []

                for option in variant.get('attributes'):
                    if option.get('master_attribute').lower() in SIZE_KEYS:

                        value = option.get('value')

                        if value:
                            values.append(value)
                            
                        _variant_attr['size'] = '/'.join(values)
                        name = '/'.join(values)

                
            track_inventory = True
            inventory_management = variant.get("inventory")

            if not inventory_management:
                track_inventory = False

            cost_price = NumberUtilities.convert_string_to_float(variant.get("original_price"))
            price = NumberUtilities.convert_string_to_float(variant.get("selling_price"))
            
            if price==0:
                continue

            if price>cost_price:
                cost_price = price

            fields = {
                "variant_id_brand": variant.get("uuid"),
                "private_metadata": {'id':variant.get("id")},
                "metadata": {},
                "sku_id_brand": variant.get("sku_code"),
                "name": name if name else p_name,
                "price_amount": price,
                "cost_price_amount": cost_price,
                "default": False,
                "track_inventory": track_inventory
                }

            if price<minimal_price_amount:
                minimal_price_amount=price

            _variant_data["fields"] = fields
            _variant_data["attributes"]= _variant_attr
            stock = variant.get("inventory") or 0
            
            if stock < 0:
                stock = 0
            
            _variant_data["stock"] = {
                'quantity': stock
            }
            variants_data.append(_variant_data)

        # set default variant if it's price is minimal 
        for variant in variants_data:
            if Decimal(variant["fields"]['price_amount']) == minimal_price_amount:
                variant["fields"]['default'] = True
                break
            
        return variants_data,minimal_price_amount
    
    def _prepare_product_description_json(self, json_item):
        
        if json_item.get("description"):
            description = json_item.get("description").replace('\n','')
            description_string = description
        
        return description_string

    def _get_mapped_data(self,data):

        json_item = data['json_item']
        
        images = data.get("images", [])

        description_json = self._prepare_product_description_json(json_item)

        product = {
            "fields": {
                "brand": data['brand'],
                "private_metadata": {'id':json_item.get('id')},
                "metadata": {},
                "name": data['product_name'],
                "description_json": {"description_text": description_json},
            }
        }

        variants,min_price = self.get_variants_data(json_item.get("skus"), data['product_name'], data['color'])

        product['fields']['minimal_variant_price_amount'] = min_price

        if not variants:
            return None

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
            "product.productimage": images,
            "product.product": product,
            "product.productvariant":variants,
            "upload_images_to_ecom": True,
            "product.created_at" : json_item.get('created_at') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time()),
            "product.updated_at" : json_item.get('updated_at') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())
        }
        
        return mapped_data

    def _create_color_attribute_image(self, variant_list, product_name, image_id_url, options_dict):
        color_name_dict = dict()
        color_image_dict = defaultdict(list)
        variant_image_ids = []
        color_values = []

        for variant in variant_list:
            values_excluding_size = []
            options = variant.get('attributes')
            for option in options:
                
                value = option.get('value')

                if not value:
                    continue

                if not value in options_dict['size']:
                    value_cur = HEX_TO_NAME.get(value) or value

                    values_excluding_size.append(value_cur)

            value = '$'.join(values_excluding_size)
            to_check = value.lower().replace('$',' ').split(" ")
            
            for check in to_check:
            
                if check in product_name.lower():
                    
                    color_name_dict[value] = product_name
            
            if not color_name_dict.get(value):
                
                color_name_dict[value] = product_name + ' ' + value

            color_values.append(value)

            if variant.get('primary_image') and image_id_url.get(variant.get('primary_image')):
                
                if not image_id_url.get(variant.get('primary_image')) in color_image_dict[value]:

                    color_image_dict[value].append(variant.get('primary_image'))
                    variant_image_ids.append(variant.get('primary_image'))
                            
        if not color_name_dict:
            color_name_dict['default'] = product_name
            color_image_dict['default'] = [url for url in image_id_url.keys()]
            variant_image_ids = [id for id in image_id_url.keys()]

        for image_id, url in image_id_url.items():

            if not image_id in variant_image_ids:

                for color in color_values:
                    
                    if not image_id in color_image_dict[color]:
                        
                        color_image_dict[color].append(image_id)

        for color in color_values:
            
            if not color_image_dict.get(color):
                color_image_dict[color]=list(image_id_url.keys())

        for id,value in color_image_dict.items():
            color_image_dict[id]= list(set(value))

        return color_name_dict,color_image_dict


    def _get_image_id_url_dict(self,json_item):
        images = json_item.get('all_images')

        if not images:
            images = set()

            for variant in json_item.get('skus',[]):

                images.add(variant.get('primary_image'))
        images = list(images)
        images_dict = dict()

        for image in images:
            images_dict[image] = True

        return images_dict

    def base_product_mapper(self, json_item):
        
        brand = self.get_brand_from_private_metadata(json_item.get("vendor"))
        
        category = self.get_catagory_id(self.category)
        product_list = []

        if not category:
            return []
        
        product_type = self.get_or_create_product_type(product_type=self.product_type)
        
        product_attributes = self.get_attributes(json_item)

        options_dict = self._get_color_option(product_attributes)

        brand_variant_zaamomapping = { 
            "product_id_brand": json_item.get("uuid"),
            "brand_name": json_item.get('vendor'),
            "source": "mydukaan"
        }

        image_id_url_dict = self._get_image_id_url_dict(json_item)
        color_name_dict, color_images_dict = self._create_color_attribute_image(json_item['skus'], 
                                                                                self.clean_product_name(json_item.get('name')), 
                                                                                image_id_url_dict, options_dict)

        data = {
            'brand':brand,
            'category':category,
            'product_type':product_type,
            'brand_variant_zaamomapping':brand_variant_zaamomapping,
            'json_item':json_item,
            'product_attributes':product_attributes
        }
        
        for key in color_name_dict.keys():
            data['product_name'] = self.clean_product_name(color_name_dict[key].replace('$',' '))
            data['color'] = key
            data['images'] = color_images_dict[key]

            mapped_data = self._get_mapped_data(data)

            if mapped_data:
                product_list.append(mapped_data)
                
        return product_list

    def delete_variation_if_removed_from_store(self, data,store_name):
        
        existing_variants = BrandVariantZaamoMapping.objects.filter(product_id_brand = data['uuid']).values_list('variant_id_brand','product_zaamo_id')
        existing_variants_set = set()
        varaint_from_data = set()
        product_variant_brand_dict = defaultdict(list)

        for variant_id in existing_variants:
            existing_variants_set.add(StringUtilities.convert_number_to_string(variant_id[0]))
            product_variant_brand_dict[variant_id[1]].append(StringUtilities.convert_number_to_string(variant_id[0]))

        variant_list_data = data['skus']
        
        for variant in variant_list_data:
            varaint_from_data.add(StringUtilities.convert_number_to_string(variant['uuid']))

        variants_to_rem = existing_variants_set.difference(set(varaint_from_data))

        if variants_to_rem:
            stock_update = Stock.objects.select_for_update().filter(product_variant_id__in=Subquery(
                                BrandVariantZaamoMapping.objects.filter(variant_id_brand__in=variants_to_rem
                                ).values('variant_zaamo_id'))).select_related('product_variant')
            
            with transaction.atomic():
                for stock in stock_update:
                    stock.quantity=0
                    stock.save()
                    cur_variant= stock.product_variant
                    cur_variant.track_inventory = True
                    cur_variant.save()
                                
            product_to_rem = []

            for key, value in product_variant_brand_dict.items():
                diff = set(value).difference(variants_to_rem)

                if not diff:
                    product_to_rem.append(key)
            
            if product_to_rem:
                product_to_update = Product.objects.select_for_update().filter(id__in=product_to_rem)

                with transaction.atomic():
                    for product in product_to_update:
                        product.is_published = False
                        product.save()


    def disable_publish_product_from_postgres_by_product_id_brand(self, product_id):

        product = (Product.objects.select_for_update().filter(id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(
                        product_id_brand=product_id).values
                        ('product_zaamo_id'))))
        
        with transaction.atomic():
            for prod in product:
                prod.is_published = False
                prod.save()

        return product

    def delete_existing_product_images(self,product_id):

        product_images = (ProductImage.objects.filter(product_id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(
                        product_id_brand=product_id).values
                        ('product_zaamo_id'))).delete())

    def clean_variant_data_for_update(self,variants):
        variant_id_info = dict()
        for variant in variants:
            
                
            track_inventory = True
            inventory_management = variant.get("inventory")

            if not inventory_management:
                track_inventory = False
            
            cost_price = NumberUtilities.convert_string_to_float(variant.get("original_price"))
            price = NumberUtilities.convert_string_to_float(variant.get("selling_price"))
            
            if price==0:
                continue

            if price>cost_price:
                cost_price = price

            stock = variant.get("inventory") or 0
            
            quantity = 0

            if stock < 0:
                quantity = 0
            
            else:
                quantity = stock
            
            variant_id_info[variant['uuid']] = {
                'cost_price': cost_price,
                'selling_price': price,
                'quantity': quantity,
                'track_inventory': track_inventory
            }
        
        return variant_id_info

    def update_inventory_and_price(self,new_product_data, brand_name):
        product_id = new_product_data['uuid']
        variants = self.clean_variant_data_for_update(new_product_data.get('skus'))
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id, variant_id_brand__in=list(variants.keys()))

        for brand_mapping in brand_mappings:
            variant_info = variants.get(NumberUtilities.convert_string_to_number(brand_mapping.variant_id_brand))

            if not variant_info:
                continue
            variant = brand_mapping.variant_zaamo

            if not variant:
                continue
            
            if not variant.cost_price_amount == variant_info.get('cost_price') or not variant.price_amount == variant_info.get('selling_price') or not variant.track_inventory == variant_info.get('track_inventory'):
                variant.cost_price_amount = variant_info.get('cost_price')
                variant.price_amount = variant_info.get('selling_price')
                variant.track_inventory = variant_info.get('track_inventory')
                variant.metadata['true_msp'] = variant_info.get('selling_price')
                variant.save()

            stock_to_update = Stock.objects.select_for_update().filter(product_variant_id=variant.id)

            with transaction.atomic():
                
                for stock in stock_to_update:
                    if not stock.quantity==variant_info.get('quantity'):
                        stock.quantity=variant_info.get('quantity')
                        stock.save()

    def update_brand_price_record(self,new_product_data, brand_name,existing_product):
        product_id = new_product_data.get('uuid')
        p_name = new_product_data.get('name')
        new_variants = self.clean_variant_data_for_update(new_product_data.get('skus'))
        exiiting_variants = self.clean_variant_data_for_update(existing_product.get('skus'))
        mapped_data = self.base_product_mapper(new_product_data)
        variant_id_product_variant_name = dict()
        
        for data in mapped_data:

            product_name = data['product.product']['fields']['name']
            variants = data['product.productvariant']

            for variant in variants:
                variant_name = variant['fields']['name']
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

            product_mapping = (BrandVariantZaamoMapping.objects.filter(brand_name=brand_name,
                                                                        product_id_brand=product_id,
                                                                        variant_id_brand=id).select_related('product_zaamo').first())

            if product_mapping:
                data_source = 'postgres'
                is_published = product_mapping.product_zaamo.is_published
            
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
                                    "source" : 'mydukaan',
                                    "current_price_amount" : new_price_amount,
                                    "current_cost_price_amount" : new_cost_price_amount,
                                    "prev_price_amount" : current_price_amount,
                                    "prev_cost_price_amount" : current_cost_price,
                                    "product_name": product_brand_name,
                                    "variant_name":variant_brand_name,
                                    "data_source":data_source,
                                    "is_published":is_published
                                    }

                    brand_record = BrandPriceRecord.objects.update_or_create(product_id_brand=product_id, 
                                                                variant_id_brand=id, defaults=record_data)

                    try:

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

    def update_status_in_fulfillment(self, order_brand_id, variant_id_status_dict):

        variant_mapping = BrandVariantZaamoMapping.objects.filter(variant_id_brand__in = variant_id_status_dict.keys())
        variant_brand_zaamo_dict = {mapping.variant_zaamo_id : variant_id_status_dict.get(NumberUtilities.convert_string_to_number(mapping.variant_id_brand)) for mapping in variant_mapping}

        order_mapping = OrderBrandZaamoMapping.objects.filter(order_id_brand=order_brand_id).select_related('order_line_zaamo')
        fulfillment_status_update = dict()
        for order_map in order_mapping:
            order_line = order_map.order_line_zaamo

            status = variant_brand_zaamo_dict.get(order_line.variant_id)

            if not status:
                continue
            
            ignore_status = [FulfillmentStatus.CANCELLATION_PROCESSED,FulfillmentStatus.CANCELLATION_INITIATED,FulfillmentStatus.DELIVERED,FulfillmentStatus.RETURN_REQUESTED,FulfillmentStatus.RETURN_INITIATED,FulfillmentStatus.RETURN_COMPLETED]
            fulfillments = Fulfillment.objects.filter(id__in = Subquery(FulfillmentLine.objects.filter(order_line_id=order_line.id).values('fulfillment_id'))).exclude(status__in=ignore_status)
            status_ranking = self.order_status_ranking_dict()
        
            for fulfillment in fulfillments:
                try:
                    if fulfillment.status==status.lower().replace('_',' '):
                        continue

                    if status_ranking[fulfillment.status]>status_ranking[status.lower().replace('_',' ')]:
                        continue

                    fulfillment_status_update[fulfillment.id] = status

                except Exception as e:
                    logger.exception(e)

        return fulfillment_status_update
