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

class StyleStreeBrandIntegeration(BaseIntegration):

    category = "custom_brand_uncategorized"

    product_type = "custom_brand_product_type"
    
    brand_id = None
    category_id = None

    def get_catagory_id(self, name, **kwrgs):

        if self.category_id is None:
            self.category_id = super().get_catagory_id(name, **kwrgs)

        return self.category_id

    def _structure_variant_data_if_variations_exist(self, variations):

        variant_price_id_dict = dict()
        product_variants = list()

        for variant in variations:
            variant_obj = dict()
            variant_name = variant.get('size')
            

            variant_obj['attributes'] = {'size':variant_name}

            variant_price = variant.get('selling_price')
            variant_regular_price = variant.get('retail_price')
            
            variant_price = NumberUtilities.convert_string_to_float(variant_price)
            variant_regular_price = NumberUtilities.convert_string_to_float(variant_regular_price)

            if variant_price==0 or variant_regular_price==0:
                continue
            
            if variant_price>variant_regular_price:
                variant_regular_price = variant_price
                
            track_inventory = True
            stock = variant.get('in_stock')
            quantity = NumberUtilities.convert_string_to_number(stock)

            if quantity<0:
                quantity = 0


            variant_fields = {
                        "variant_id_brand": variant['variant_id'],
                        "private_metadata": {},
                        "metadata": {},
                        "sku_id_brand": variant.get('sku_code', ''),
                        "name": variant_name ,
                        "price_amount": variant_price,
                        "cost_price_amount": variant_regular_price,
                        "default": False,
                        "track_inventory": track_inventory
                        
                        }

            variant_price_id_dict[variant_price] = variant['variant_id']
            variant_obj['fields'] = variant_fields
            variant_obj['stock'] = {}
            variant_obj['stock']['quantity'] = quantity

            product_variants.append(variant_obj)
        return product_variants, variant_price_id_dict

    def _prepare_variant_and_attribute_data(self, product):
        
        variations = product.get('variants')
        
        if not variations:
            
            return None,None
        variant_price_id_dict = dict()
        product_variants = []
        min_price = None

            
        product_variants, variant_price_id_dict = self._structure_variant_data_if_variations_exist(variations)
        
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

    def get_images_from_variant(self,variants):

        image_list = set()

        for variant in variants:
            image_list.add(variant['image_url'])
        
        return list(image_list)

    def _get_mapped_data(self,data):

        json_item = data['json_item']
        p_name = json_item['product_name']
        variants, min_price = self._prepare_variant_and_attribute_data(json_item)
        if not variants:
            return None
        data['images'] = self.get_images_from_variant(json_item.get('variants',[]))
        product = {
            "fields": {
                "brand": data['brand'],
                "private_metadata": {},
                "metadata": {},
                "name": json_item['product_name'],
                "description_json": {"description_text": ''},
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
            "product.attribute": {},
            "product.brand_variant_zaamomapping": brand_mapping,
            "product.productimage": data['images'],
            "product.product": product,
            "product.productvariant":variants,
            "upload_images_to_ecom": True,
            "product.created_at" : json_item.get('date_created') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time()),
            "product.updated_at" : json_item.get('date_modified') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())
        }
        
        return mapped_data

    def base_product_mapper(self, json_item):

        product_list = []

        brand = self.get_brand_from_private_metadata(json_item.get('vendor'))
        
        category = self.get_catagory_id(self.category)

        if not category:
            return []
        
        product_type = self.get_or_create_product_type(product_type=self.product_type)
        
        brand_variant_zaamomapping = { 
            "product_id_brand": json_item.get("product_id"),
            "brand_name": json_item.get('vendor'),
            "source": "custom"
        }

        data = {
            'brand':brand,
            'category':category,
            'product_type':product_type,
            'brand_variant_zaamomapping':brand_variant_zaamomapping,
            'json_item':json_item,
        }

        mapped_data = self._get_mapped_data(data)
        if mapped_data:
            product_list.append(mapped_data)

        return product_list

    #Product Delete functions

    def delete_variation_if_removed_from_store(self, data,shop_name):
        existing_variants = BrandVariantZaamoMapping.objects.filter(product_id_brand = data['product_id'],brand_name=shop_name).values_list('variant_id_brand','product_zaamo_id')
        existing_variants_set = set()
        varaint_from_data = set()
        product_variant_brand_dict = defaultdict(list)

        for variant_id in existing_variants:
            if variant_id[0]:
                existing_variants_set.add(StringUtilities.convert_number_to_string(variant_id[0]))
                product_variant_brand_dict[variant_id[1]].append(StringUtilities.convert_number_to_string(variant_id[0]))

        variant_list_data = data['variations']

        for variant in variant_list_data:
            varaint_from_data.add(StringUtilities.convert_number_to_string(variant['variant_id']))

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
        

    def disable_publish_product_from_postgres_by_product_id_brand(self, product_ids,brand_name):

        products_to_update = Product.objects.filter(id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(brand_name=brand_name).
                        exclude(product_id_brand__in=product_ids).values('product_zaamo_id')))
        
        with transaction.atomic():
            for product in products_to_update:
                product.is_published=False
                product.save()

        return products_to_update
        
    
    def update_inventory_and_price(self,new_product_data, brand_name):
        product_id = new_product_data['product_id']
        variations_list = new_product_data.get('variants')

        if not variations_list:
            return

        variants = self.clean_variant_data_for_update(variations_list)
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id, variant_id_brand__in=list(variants.keys()))

        for brand_mapping in brand_mappings:

            variant_info = variants.get(NumberUtilities.convert_string_to_number(brand_mapping.variant_id_brand))

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

    def clean_variant_data_for_update(self, variations_list):
        variant_id_info = dict()
        for variant in variations_list:

            variant_id_info[variant['variant_id']] = {
                    'name':variant['size'],
                    'cost_price': variant['retail_price'],
                    'selling_price': variant['selling_price'],
                    'quantity': variant['in_stock'],
                    'track_inventory': True
                }
        return variant_id_info


    def update_brand_price_record(self,new_product_data, brand_name,existing_product):
        product_id = new_product_data['product_id']
        variations_list = new_product_data.get('variants')
        p_name = new_product_data.get('product_name')

        if not variations_list:
            return

        new_variants = self.clean_variant_data_for_update(variations_list)
        exiiting_variants = self.clean_variant_data_for_update(existing_product.get('variants'))

        variant_id_product_variant_name = dict()

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

            with transaction.atomic():

                if not current_cost_price==new_cost_price_amount or not current_price_amount==new_price_amount:

                    record_data = {"brand_name" : brand_name,
                                    "product_id_brand" : product_id,
                                    "variant_id_brand" : id,
                                    "source" : 'custom',
                                    "current_price_amount" : new_price_amount,
                                    "current_cost_price_amount" : new_cost_price_amount,
                                    "prev_price_amount" : current_price_amount,
                                    "prev_cost_price_amount" : current_cost_price,
                                    "product_name": p_name,
                                    "variant_name":variant_info.get('name',''),
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

            except Exception as e:
                logger.exception(e)

        return fulfillment_status_update



class TheSouledStoreIntegeration(BaseIntegration):

    category = "custom_brand_uncategorized"

    product_type = "custom_brand_product_type"
    
    brand_id = None
    category_id = None

    def get_catagory_id(self, name, **kwrgs):

        if self.category_id is None:
            self.category_id = super().get_catagory_id(name, **kwrgs)

        return self.category_id

    def _structure_variant_data_if_variations_exist(self, product):
        variant_price_id_dict = dict()
        product_variants = list()
        price_amount = product.get('exclusivePrice') or product.get('splPrice')
        cost_price = product.get('price') or price_amount
        price_amount = NumberUtilities.convert_string_to_float(price_amount)
        cost_price = NumberUtilities.convert_string_to_float(cost_price)
        
        variations = product.get('variants')

        for variant in variations:
            variant_obj = dict()
            attributes = variant.get('attributes')

            for attribute in attributes:
                if  attribute.get('name') and attribute.get('name').lower() in SIZE_KEY_LIST:
                    variant_name = attribute.get('value')
                    break
            
            variant_obj['attributes'] = {'size':variant_name}

            variant_price = variant.get('splPrice') or variant.get('extraPrice')
            variant_regular_price = variant.get('price') or variant_price
            
            variant_price = NumberUtilities.convert_string_to_float(variant_price)
            variant_regular_price = NumberUtilities.convert_string_to_float(variant_regular_price)

            if variant_price==0 or variant_regular_price==0:
                variant_price = price_amount
                variant_regular_price = cost_price
            
            if variant_price==0 or variant_regular_price==0:
                continue

            if variant_price>variant_regular_price:
                variant_regular_price = variant_price
                
            track_inventory = True
            quantity = NumberUtilities.convert_string_to_number(variant.get('stock',0))

            if quantity<0:
                quantity = 0


            variant_fields = {
                        "variant_id_brand": variant['id'],
                        "private_metadata": {},
                        "metadata": {},
                        "sku_id_brand": variant.get('id', ''),
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

    def _prepare_variant_and_attribute_data(self, product):
        
        variations = product.get('variants')
        
        if not variations:
            
            return None,None

        variant_price_id_dict = dict()
        product_variants = []
        min_price = None

        
        product_variants, variant_price_id_dict = self._structure_variant_data_if_variations_exist(product)
        
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

    def get_images_from_variant(self,json_item):

        image_list = set()
        url = "https://prod-img.thesouledstore.com/public/theSoul/uploads/catalog/product/"
        images = json_item.get('images',[])

        for image in images:
            image_list.add(url+image)
        
        return list(image_list)

    def _get_mapped_data(self,data):

        json_item = data['json_item']
        p_name = json_item['product']
        variants, min_price = self._prepare_variant_and_attribute_data(json_item)

        if not variants:
            return None

        data['images'] = self.get_images_from_variant(json_item)
        desc = json_item['meta'].get('desc')
        product = {
            "fields": {
                "brand": data['brand'],
                "private_metadata": {},
                "metadata": {},
                "name": p_name,
                "description_json": {"description_text": desc},
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
            "product.attribute": {},
            "product.brand_variant_zaamomapping": brand_mapping,
            "product.productimage": data['images'],
            "product.product": product,
            "product.productvariant":variants,
            "upload_images_to_ecom": True,
            "product.created_at" : json_item.get('created') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time()),
            "product.updated_at" : json_item.get('created') or StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())
        }
        
        return mapped_data

    def base_product_mapper(self, json_item):

        product_list = []

        brand = self.get_brand_from_private_metadata(json_item.get('vendor'))
        
        category = self.get_catagory_id(self.category)

        if not category:
            return []
        
        product_type = self.get_or_create_product_type(product_type=self.product_type)
        
        brand_variant_zaamomapping = { 
            "product_id_brand": json_item.get("id"),
            "brand_name": json_item.get('vendor'),
            "source": "custom"
        }

        data = {
            'brand':brand,
            'category':category,
            'product_type':product_type,
            'brand_variant_zaamomapping':brand_variant_zaamomapping,
            'json_item':json_item,
        }

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
        

    def disable_publish_product_from_postgres_by_product_id_brand(self, product_ids,brand_name):

        products_to_update = Product.objects.filter(id__in=Subquery(
                        BrandVariantZaamoMapping.objects.filter(brand_name=brand_name).
                        exclude(product_id_brand__in=product_ids).values('product_zaamo_id')))
        
        with transaction.atomic():
            for product in products_to_update:
                product.is_published=False
                product.save()

        return products_to_update
        
    
    def update_inventory_and_price(self,new_product_data, brand_name):
        product_id = new_product_data['id']
        variations_list = new_product_data.get('variants')

        if not variations_list:
            return

        variants = self.clean_variant_data_for_update(new_product_data)
        brand_mappings = BrandVariantZaamoMapping.objects.filter(brand_name=brand_name, product_id_brand=product_id, variant_id_brand__in=list(variants.keys()))

        for brand_mapping in brand_mappings:

            variant_info = variants.get(NumberUtilities.convert_string_to_number(brand_mapping.variant_id_brand))

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

    def clean_variant_data_for_update(self, product):
        variant_id_info = dict()
        variations_list,_ = self._structure_variant_data_if_variations_exist(product)
        for variant in variations_list:

            variant_id_info[variant['fields']['variant_id_brand']] = {
                    'name':variant['fields']['name'],
                    'cost_price': variant['fields']['cost_price_amount'],
                    'selling_price': variant['fields']['price_amount'],
                    'quantity': variant['stock']['quantity'],
                    'track_inventory': True
                }
        return variant_id_info


    def update_brand_price_record(self,new_product_data, brand_name,existing_product):
        product_id = new_product_data['id']
        variations_list = new_product_data.get('variants')
        p_name = new_product_data.get('product')

        if not variations_list:
            return

        new_variants = self.clean_variant_data_for_update(new_product_data)
        exiiting_variants = self.clean_variant_data_for_update(existing_product)

        variant_id_product_variant_name = dict()

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

            with transaction.atomic():

                if not current_cost_price==new_cost_price_amount or not current_price_amount==new_price_amount:

                    record_data = {"brand_name" : brand_name,
                                    "product_id_brand" : product_id,
                                    "variant_id_brand" : id,
                                    "source" : 'custom',
                                    "current_price_amount" : new_price_amount,
                                    "current_cost_price_amount" : new_cost_price_amount,
                                    "prev_price_amount" : current_price_amount,
                                    "prev_cost_price_amount" : current_cost_price,
                                    "product_name": p_name,
                                    "variant_name":variant_info.get('name',''),
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

            except Exception as e:
                logger.exception(e)

        return fulfillment_status_update
