from collections import defaultdict
import uuid
from saleor.external_services.integrations.base import BaseIntegration
from saleor.external_services.wix.constants import COLOR_KEYS
from saleor.graphql.product.utils import update_msp_of_variant_using_step_price
from saleor.order import FulfillmentStatus
from saleor.order.models import Fulfillment, FulfillmentLine, OrderBrandZaamoMapping
from saleor.product.models import BrandPriceRecord, BrandVariantZaamoMapping, ProductImage, ProductVariant, Product
from saleor.utilities.time_utilities import TimeUtilities
from saleor.warehouse.models import Stock
from saleor.utilities.number_utilities import NumberUtilities
from django.db.models import Subquery, Q
from saleor.utilities.string_utilities import StringUtilities
from django.db import transaction
import logging
logger = logging.getLogger(__name__)

class WixIntegration(BaseIntegration):

    category = "wix_uncategorized"

    product_type = "wix_product_type"
    
    brand_id = None
    category_id = None

    def get_catagory_id(self, name, **kwrgs):

        if self.category_id is None:
            self.category_id = super().get_catagory_id(name, **kwrgs)

        return self.category_id

    def _prepare_variant_object_without_manage_variant(self,variant_obj,size,is_default,product_id):
        current_variant_obj = variant_obj.copy()
        current_variant_obj['fields'] = variant_obj['fields'].copy()
        current_variant_obj['attributes'] = {'size': [size]}
        current_variant_obj['fields']['name'] = size
        current_variant_obj['fields']['default'] = is_default
        current_variant_obj['fields']['private_metadata'] = variant_obj['fields']['private_metadata'].copy()
        current_variant_obj['fields']['private_metadata']['size'] = size
        current_variant_obj['fields']['variant_id_brand'] = self._get_unique_id_for_no_variant(current_variant_obj['fields']['private_metadata'],product_id)
        return current_variant_obj

    def _clean_private_meta_for_comparision(self,meta):

        if meta.get('product_name'):
            meta.pop('product_name')

        if meta.get('is_variant_brand_null'):
            meta.pop('is_variant_brand_null')
        
        return meta

    def _get_unique_id_for_no_variant(self,variant_meta,product_id):
        mappings = BrandVariantZaamoMapping.objects.filter(product_id_brand=product_id)

        for mapping in mappings:
            current_variant_meta = self._clean_private_meta_for_comparision(variant_meta.copy())
            existing_variant_meta = self._clean_private_meta_for_comparision(mapping.variant_zaamo.private_metadata)

            if current_variant_meta == existing_variant_meta:
                id = mapping.variant_id_brand
                return id

        id = StringUtilities.convert_number_to_string(uuid.uuid4())

        return id

    def _structure_variant_data_for_simple_product(self,product,color):
        
        product_variants = []
        product_options = product.get('productOptions')
        size_option = []

        if product_options:
            for option in product_options:
                if option.get('name').lower()=='size':
                    size_option = [item['value'] for item in option.get('choices',[])]

        product_price = product.get('priceData')

        stock = product['stock']
        quantity = NumberUtilities.convert_string_to_number(stock.get('quantity',0))

        if quantity<0:
            quantity = 0

        track_inventory = stock.get('trackInventory',False)
        in_stock = stock.get('inStock')

        if in_stock==False:
            track_inventory=True
            quantity=0

        private_meta = {'is_variant_brand_null':True,
                        'product_name': product.get('name')}

        if not color=='default':
            private_meta.update({'color':color})

        null_variant_id = self._get_unique_id_for_no_variant(private_meta,product.get('id'))
        variant_obj = dict()
        variant_obj['attributes'] = {}
        variant_obj['fields'] = {
                    "variant_id_brand": null_variant_id,
                    "private_metadata": private_meta,
                    "metadata": {},
                    "sku_id_brand": product.get('sku', ''),
                    "name": product.get('name', '') ,
                    "default": True,
                    "price_amount": NumberUtilities.convert_string_to_float(product_price.get('discountedPrice', 0)),
                    "cost_price_amount": NumberUtilities.convert_string_to_float(product_price.get('price', 0)),
                    "track_inventory": track_inventory
                    }
                    
        min_price = variant_obj['fields']['price_amount']
        variant_obj['stock'] = {}
        variant_obj['stock']['quantity'] = quantity

        if size_option:
            
            is_default = True
            for size in size_option:
                
                variant_object = self._prepare_variant_object_without_manage_variant(variant_obj,size,is_default,product.get('id'))
                product_variants.append(variant_object)
                is_default = False

        else:
            product_variants.append(variant_obj)

        return product_variants, min_price

    def _structure_variant_data_if_variations_exist(self, product, color):
        variations = product.get('variants')
        product_name = product.get('name')
        variant_price_id_dict = dict()
        product_variants = list()

        for variant in variations:
            variant_obj = dict()
            attribute = variant.get('choices')
            variant_name = ''
            variant_attribute = dict()

            for key,value in attribute.items():
                
                if key.lower() in COLOR_KEYS:
                    key='color'

                variant_attribute[key.lower()] = [value.lower()]
            
            
            if 'color' in variant_attribute.keys():

                if not color in variant_attribute['color']:
                    continue
            
            private_meta = dict()

            if variant_attribute:
                att=dict()

                for key,value in variant_attribute.items():
                    att[key] = value[0]

                private_meta=att

            private_meta.update({'product_name': product_name})
            variant_name = variant_attribute.get('size')
            
            if not variant_name:
                variant_name = product_name

            else:
                variant_name = variant_name[0]

            if variant_attribute.get('color'):
                variant_attribute.pop('color')

            variant_obj['attributes'] = variant_attribute

            price_data = variant['variant'].get('priceData')
            variant_regular_price = price_data.get('price')
            variant_price = price_data.get('discountedPrice')

            if not variant_price or not variant_regular_price:
                continue

            quantity = NumberUtilities.convert_string_to_number(variant.get('quantity',0))

            if quantity<0:
                quantity = 0

            track_inventory = None

            if variant.get('stock') and not variant['stock'].get('trackQuantity')==None:
            
                track_inventory = variant['stock'].get('trackQuantity')
                in_stock = variant['stock'].get('inStock')

                if in_stock==False:
                    track_inventory=True
                    quantity=0
            
            else:

                track_inventory = product['stock'].get('trackInventory',False)
                in_stock = product['stock'].get('inStock')

                if in_stock==False:
                    track_inventory=True
                    quantity=0

            variant_fields = {
                        "variant_id_brand": variant['id'],
                        "private_metadata": private_meta,
                        "metadata": {},
                        "sku_id_brand": variant['id'],
                        "name": variant_name ,
                        "price_amount": NumberUtilities.convert_string_to_float(variant_price),
                        "cost_price_amount": NumberUtilities.convert_string_to_float(variant_regular_price),
                        "default": False,
                        "track_inventory": track_inventory
                        
                        }

            variant_price_id_dict[NumberUtilities.convert_string_to_float(variant_price)] = variant['id']
            variant_obj['fields'] = variant_fields
            variant_obj['stock'] = {}
            variant_obj['stock']['quantity'] = quantity

            product_variants.append(variant_obj)

        return product_variants, variant_price_id_dict


    def _structure_product_attributes(self,product_attributes_values):
        
        product_attributes = dict()
        if product_attributes_values:
            for att in product_attributes_values:

                if att['name'].lower() in ['size']:
                    values = []

                    for choice in att['choices']:
                        if choice.get('visible'):
                            values.append(choice['value'])

                    product_attributes[att['name'].lower()] = {
                                                'is_variant_attribute': True,
                                                'values': values
                                            }
        return product_attributes

    def _prepare_variant_data(self, product, color):
        
        variations = product.get('manageVariants')
        variant_price_id_dict = dict()
        product_variants = []
        min_price = None

        if variations:
            
            product_variants, variant_price_id_dict = self._structure_variant_data_if_variations_exist(product, color)
        
        else:

            product_variants, min_price = self._structure_variant_data_for_simple_product(product,color)
        
        if not product_variants:
            return None, None
        
        if not min_price and variant_price_id_dict.keys():
            min_price = min(variant_price_id_dict.keys())
            min_price_id = variant_price_id_dict[min_price]

            for variant in product_variants:

                if variant['fields']['variant_id_brand'] == min_price_id:
                    variant['fields']['default'] = True
                    break
        
                                    
        return product_variants, min_price

    def _prepare_product_description_json(self, json_item):
        
        attribute_list = []

        weight = json_item.get('weight')

        if weight:
            attribute_list.append(f"<b>weight</b> : {weight}")

        
        description_string = '<br/>'.join(attribute_list)

        if description_string:
            description_string = '<p>' + description_string + '</p>'

        additional_info = json_item.get('additionalInfoSections')
        
        full_description = []

        if json_item.get("description"):
            description = json_item.get("description")
            full_description.append(description)
        
        if description_string:
            full_description.append(description_string)

        if additional_info:
            for info in additional_info:
                full_description.append(f"<b>{info['title']}</b>")    
                full_description.append(info['description'])    
        
        description_response = '<br/>'.join(full_description)
        
        return description_response


    def _get_mapped_data(self,data):

        json_item = data['json_item']

        variants, min_price = self._prepare_variant_data(json_item, data['color'])

        if not variants:
            return None

        description_json = self._prepare_product_description_json(json_item)

        private_meta = dict()

        if not data['color'].lower()== 'default':
            private_meta['attribute'] = {'color':data['color']}

        product = {
            "fields": {
                "brand": data['brand'],
                "private_metadata": private_meta,
                "metadata": {},
                "name": data['product_name'],
                "description_json": {"description_text": description_json},
                "minimal_variant_price_amount": StringUtilities.convert_number_to_string(min_price),
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
            "product.productvariant":variants or [],
            "upload_images_to_ecom": True,
            "product.created_at" : json_item.get('createdDate') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time()),
            "product.updated_at" : json_item.get('lastUpdated') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())
        
        }
        
        return mapped_data

    def _create_color_attribute_image(self, product_options, product_name,product_images):
        color_name_dict = dict()
        color_image_dict = defaultdict(list)
        image_urls = list()
        
        for option in product_options:
            if option['name'].lower() in COLOR_KEYS:
                option['name'] ='color'

            if option['name'].lower()=='color':
                choices = option['choices']

                for choice in choices:
                    color_name_dict[choice['description'].lower()] = product_name + ' ' + choice['description'].lower()
                    images_list = []

                    if choice.get('media'):
                        images_list = self._prepare_simple_image(choice.get('media'))
                        
                    color_image_dict[choice['description'].lower()] = images_list
                    image_urls.extend(color_image_dict[choice['description'].lower()])
        
        if not color_name_dict:
            color_name_dict['default'] = product_name
            color_image_dict['default'] = image_urls
        
        for i_url in product_images:

            if i_url not in image_urls:

                for color in color_name_dict.keys():
                    
                    if not i_url in color_image_dict[color]:
                        color_image_dict[color].append(i_url)

        return color_name_dict,color_image_dict

    def _prepare_simple_image(self,media_dict):
        image_url = set()

        main_media = media_dict.get('mainMedia')
        image_list = media_dict.get('items')

        if main_media:
            try:
                image_url.add(main_media['image']['url'])
            except:
                pass

        for item in image_list:
            try:
                image_url.add(item['image']['url']) 

            except:
                continue   
        
        return list(image_url)


    def base_product_mapper(self, json_item):

        if not json_item.get('visible'):
            return []

        product_list = []
        color_name_dict = dict()
        color_images_dict = dict()

        brand = self.get_brand_from_private_metadata(json_item.get('vendor'))
        
        category = self.get_catagory_id(self.category)
        
        if not category:
            return []
        
        product_type = self.get_or_create_product_type(product_type=self.product_type)
        
        product_attributes = self._structure_product_attributes(json_item['productOptions'])
        brand_variant_zaamomapping = { 
            "product_id_brand": json_item.get("id"),
            "brand_name": json_item.get('vendor'),
            "source": "wix"
        }

        product_images = self._prepare_simple_image(json_item.get('media'))

        color_name_dict, color_images_dict = self._create_color_attribute_image(json_item['productOptions'], json_item.get('name'),product_images)

        data = {
            'brand':brand,
            'category':category,
            'product_type':product_type,
            'brand_variant_zaamomapping':brand_variant_zaamomapping,
            'json_item':json_item,
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

    #Product Delete functions

    def delete_variation_if_removed_from_store(self, mappings):
        if not mappings:
            return
        existing_variants = BrandVariantZaamoMapping.objects.filter(product_id_brand = mappings[0]['product_id_brand']).values_list('variant_id_brand','product_zaamo_id')
        existing_variants_set = set()
        product_variant_brand_dict = defaultdict(list)

        for variant_id in existing_variants:
            existing_variants_set.add(variant_id[0])
            product_variant_brand_dict[variant_id[1]].append(variant_id[0])

        variant_data = []
        for mapping in mappings:

            variant_from_data = mapping.get('variant_id_brands')
            
            if not variant_from_data:
                continue
            
            variant_data.extend(variant_from_data)


        variants_to_rem = existing_variants_set.difference(set(variant_data))
        
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

        products_to_update = Product.objects.filter(id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(
                        product_id_brand=product_id).values('product_zaamo_id')))
        
        with transaction.atomic():
            for product in products_to_update:
                product.is_published=False
                product.save()
        
    
    def delete_existing_product_images(self,product_id):

        product_images = (ProductImage.objects.filter(product_id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(
                        product_id_brand=product_id).values
                        ('product_zaamo_id'))).delete())

    def decrement_stock_for_variant(self,product_variant_decrement_dict, product_quantity_decrement_dict):

        variant_ids_to_not_decrement = []
        variant_product_id_dict = dict()
        for value in product_variant_decrement_dict.values():
            variant_ids_to_not_decrement.extend(value)

        brand_mapping = BrandVariantZaamoMapping.objects.filter(product_id_brand__in=product_variant_decrement_dict.keys()).exclude(variant_zaamo_id__in=variant_ids_to_not_decrement).distinct('variant_zaamo_id')
        variant_ids = []

        for mapping in brand_mapping:
            variant_ids.append(mapping.variant_zaamo_id)
            variant_product_id_dict[mapping.variant_zaamo_id] = mapping.product_id_brand

        variants = (ProductVariant.objects.filter(id__in=variant_ids).exclude(track_inventory=False)).values('id')

        stocks = Stock.objects.filter(product_variant_id__in=variants)
        for stock in stocks:
            product_brand_id = variant_product_id_dict.get(stock.product_variant_id)
            quantity = product_quantity_decrement_dict.get(product_brand_id)

            if quantity:
                try:
                    stock.decrease_stock(quantity)
                except Exception as e:
                    continue

    def clean_variant_data_for_update(self,product):
        variants = product.get('variants')

        variant_id_info = dict()
        for variant in variants:

            price_data = variant['variant'].get('priceData')
            variant_regular_price = price_data.get('price')
            variant_price = price_data.get('discountedPrice')
            variant_price = NumberUtilities.convert_string_to_float(variant_price)
            variant_regular_price = NumberUtilities.convert_string_to_float(variant_regular_price)

            if variant_price==0 or variant_regular_price==0:
                continue
            
            if variant_price>variant_regular_price:
                variant_regular_price = variant_price
                
            quantity = NumberUtilities.convert_string_to_number(variant.get('quantity',0))

            if quantity<0:
                quantity = 0

            track_inventory = None

            if variant.get('stock') and not variant['stock'].get('trackQuantity')==None:
            
                track_inventory = variant['stock'].get('trackQuantity')
                in_stock = variant['stock'].get('inStock')

                if in_stock==False:
                    track_inventory=True
                    quantity=0
            
            else:

                track_inventory = product['stock'].get('trackInventory',False)
                in_stock = product['stock'].get('inStock')

                if in_stock==False:
                    track_inventory=True
                    quantity=0
            
            variant_id_info[variant['id']] = {
                'cost_price': variant_regular_price,
                'selling_price': variant_price,
                'quantity': quantity,
                'track_inventory': track_inventory
            }
        
        return variant_id_info
    
    def clean_variant_data_for_update_for_simple_product(self,product):

        variant_id_info = dict()
        price_data = product.get('priceData')

        stock = product['stock']
        quantity = NumberUtilities.convert_string_to_number(stock.get('quantity',0))

        if quantity<0:
            quantity = 0

        track_inventory = stock.get('trackInventory',False)
        in_stock = stock.get('inStock')

        if in_stock==False:
            track_inventory=True
            quantity=0

        product_price = price_data.get('price')
        product_regular_price = price_data.get('discountedPrice') or product.get('price')

        product_regular_price = price_data.get('price')
        product_price = price_data.get('discountedPrice') or product.get('price')

        if product_price>product_regular_price:
            product_regular_price = product_price

        if product_price==0 or product_regular_price==0:
            return variant_id_info
        
        
        variant_id_info[product['id']] = {
            'cost_price': product_regular_price,
            'selling_price': product_price,
            'quantity': quantity,
            'track_inventory': track_inventory
        }
        
        return variant_id_info

    def update_inventory_and_price(self,new_product_data, brand_name):
        product_id = new_product_data['id']
        manageVariants = new_product_data.get('manageVariants')

        if manageVariants:
            variants = self.clean_variant_data_for_update(new_product_data)
            brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id, variant_id_brand__in=list(variants.keys()))

        else:
            variants = self.clean_variant_data_for_update_for_simple_product(new_product_data)
            brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id)

        for brand_mapping in brand_mappings:

            if manageVariants:
                variant_info = variants.get(brand_mapping.variant_id_brand)

            else:
                variant_info = variants.get(brand_mapping.product_id_brand)

            if not variant_info:
                continue

            variant = brand_mapping.variant_zaamo

            if not variant:
                continue

            variant.cost_price_amount = variant_info.get('cost_price')
            variant.price_amount = variant_info.get('selling_price')
            variant.track_inventory = variant_info.get('track_inventory')
            variant.metadata['true_msp'] = variant_info.get('selling_price')
            variant.save()
            update_msp_of_variant_using_step_price(variant)

            stock_to_update = Stock.objects.select_for_update().filter(product_variant_id=variant.id)
            
            with transaction.atomic():
                
                for stock in stock_to_update:

                    stock.quantity=variant_info.get('quantity')
                    stock.save()

    def update_brand_price_record(self,new_product_data, brand_name,existing_product):
        product_id = new_product_data['id']
        manageVariants = new_product_data.get('manageVariants')
        p_name = new_product_data.get('name')

        if manageVariants:
            new_variants = self.clean_variant_data_for_update(new_product_data)
            exiiting_variants = self.clean_variant_data_for_update(existing_product)

            
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

    def save_order_mapping(self, api_response,order_lines):
        if api_response.get('order'):
            order_id = api_response.get('order').get('id')
            order = order_lines[0].order
            for line in order_lines:
                OrderBrandZaamoMapping.objects.create(brand=line.brand,
                                                order_zaamo=order, 
                                                product_name=line.product_name, 
                                                order_line_zaamo=line,
                                                order_id_brand=order_id)

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
