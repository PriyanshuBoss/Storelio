import base64
from collections import defaultdict
from io import BytesIO
import logging
import re
import sys
import datetime
from urllib.parse import urlparse
import uuid
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import transaction
import random
from measurement.measures import Weight
from typing import Type, Union
import graphene
from django.utils.text import slugify
from measurement.measures.time import Time
from saleor.brand.models import Brand
from saleor.brand.states import BrandSourceEnum
import time
from saleor.graphql.core.utils import validate_image_file
from django.conf import settings
import requests
from saleor.core.weight import zero_weight
from saleor.order.models import OrderBrandZaamoMapping
from saleor.product.models import (ProductImage, ProductType, Category, Product, ProductVariant, AssignedProductAttribute, 
AssignedVariantAttribute, Attribute, AttributeValue, AttributeProduct, AttributeVariant, BrandVariantZaamoMapping)
from prices import Money
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.warehouse.models import Warehouse, Stock
from saleor.external_services.integrations.tasks import push_inventory_csv_task, push_inventory_task, push_inventory_sync
from saleor.external_services.woo_commerce_service.woocommerce_helper import WooCommerceHelper


logger = logging.getLogger(__name__)


class BaseProductCreate:

    @property
    def warehouse(self):
        try:
            warehouse = Warehouse.objects.get(slug="zaamo-master-warehouse")
        except:
            warehouse = Warehouse.objects.none()

        return warehouse

    def set_field_as_money(self, defaults, field):
        amount_field = f"{field}_amount"
        if amount_field in defaults and defaults[amount_field] is not None:
            defaults[field] = Money(defaults[amount_field], settings.DEFAULT_CURRENCY)
        
    def create_stocks(self, variant, warehouse=None, **defaults):
        
        stock,_ = Stock.objects.update_or_create(
            warehouse=warehouse, product_variant=variant, defaults=defaults
        )
        stock.set_product_metadata_instock()

    def get_weight(self, weight):
        if not weight:
            return zero_weight()
        value, unit = weight.split(":")
        return Weight(**{unit: value})
    
    def retrieve_image(self, url, file_name):
        try:
            header = WooCommerceHelper.get_default_header_with_user_agent()
            response = requests.get(url, headers=header)
            fobject = BytesIO(response.content)
            
            return InMemoryUploadedFile(fobject,'ImageField',
                file_name + '.png',
                'image/png',
                len(fobject.getbuffer()), None)
        except:

            return None
    
    def retrieve_image_in_base64_encoded(self,url):
        
        try:
            header = WooCommerceHelper.get_default_header_with_user_agent()
            response = requests.get(url, headers=header)
            image_bytes = base64.b64encode(response.content).decode('utf-8')
            return image_bytes
        except:

            return None
    
    def upload_product_image_to_ecom(self, product, url, file_name, alt=''):
        if product and url:
            image_data = self.retrieve_image(url, file_name)

            if image_data:
                validate_image_file(image_data, "image")
                image = product.images.create(image=image_data, alt=alt)

    
    def upload_images_to_content_service(self, product, images_url_list):
        
        mappings = BrandVariantZaamoMapping.objects.filter(product_zaamo=product)

        zaamo_id = graphene.Node.to_global_id("Brand", product.brand.id)
        data = {
            "zaamo_id": zaamo_id,
            "user_type": "BRAND",
            "method": "SHOPIFY",
            "value" : [],
            "tag_product": True,
            "mapping": []
        }
        for mapping in mappings:
            _dict = {
                "product_id": mapping.product_id_brand,
                "sku_id": mapping.sku_id_brand,
                "links": images_url_list, 
                }
            data['value'].append(_dict)
            
            data["mapping"].append({
                "product_id_brand": mapping.product_id_brand,
                "sku_id_brand": mapping.sku_id_brand,
                "productzaamo_id": graphene.Node.to_global_id("Product", mapping.product_zaamo.id),
                "variantzaamo_id": graphene.Node.to_global_id("Variant", mapping.variant_zaamo.id)
            })
        
        response = requests.post(settings.CONTENT_SERVICE_UPLOAD_URL, data=data)
           
        return response
        
    def upload_images(self, product, images_url_list, upload_to_ecom,upload_to_content_service):
        if upload_to_content_service:
            self.upload_images_to_content_service(product, images_url_list)

        if upload_to_ecom:
            for url in images_url_list:
                random_string = StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds())
                time.sleep(0.1)
                file_name = random_string
                self.upload_product_image_to_ecom(product, url, file_name, alt='')


    def get_zaamo_sku(self, product_id):
        try:
            latest_product_varient = ProductVariant.objects.latest('id').id
        except:
            latest_product_varient = 0

        sku = graphene.Node.to_global_id("Product", product_id) + '_' +  StringUtilities.convert_number_to_string(latest_product_varient+1)

        return sku

    def get_brand_variant_zaamo_mappings(self, variant_id_brands = None, **kwargs):

        if variant_id_brands:
            brand_zaamo_mappings = BrandVariantZaamoMapping.objects.filter(**kwargs, variant_id_brand__in=variant_id_brands)

        else:
            brand_zaamo_mappings = BrandVariantZaamoMapping.objects.filter(**kwargs)
            
        return brand_zaamo_mappings
    
    def create_brand_zaamo_mapping(self, product, variant, brand_variant_zaamomapping, variant_id_brand, sku_id_brand):

        brandvarient_zaamo_mapping = BrandVariantZaamoMapping(source=brand_variant_zaamomapping['source'], 
                brand_name=brand_variant_zaamomapping['brand_name'], 
                product_name=product.name, 
                product_id_brand=brand_variant_zaamomapping['product_id_brand'], 
                sku_id_brand=sku_id_brand,
                variant_id_brand= variant_id_brand,
                product_zaamo =product,
                brand_zaamo_id = product.brand_id, 
                variant_zaamo=variant)
        brandvarient_zaamo_mapping.save()

        return brandvarient_zaamo_mapping
    
    def get_catagory_id(self, name, **kwrgs):
        try:
            category = Category.objects.get(name=name)
        except:
            category = None

        if category:
            return category.id
    
    def get_attribute_id(self, slug, **kwrgs):
        try:
            attribute = Attribute.objects.get(slug=slug)
        except:
            attribute = None
        if attribute:
            return attribute.id

    def get_attribute_variant_id(self, attribute, product_type):
        try:
            attribute_variant = AttributeVariant.objects.get(attribute=attribute, product_type=product_type)
        except:
            attribute_variant= None

        if attribute_variant:
            return attribute_variant.id
    
    def get_attribute_product_id(self, attribute, product_type):
        try:
            attribute_variant = AttributeProduct.objects.get(attribute=attribute, product_type=product_type)
        except:
            attribute_variant= None

        if attribute_variant:
            return attribute_variant.id

    def update_attribute_value_in_variant_data(self, variants_data):
        for variant in variants_data:
            attribute_value_mappings = {}
            attributes = variant["attributes"]

            for attribute, values in attributes.items():
                attr_id = self.get_attribute(slugify(attribute))
                _dict = {attr_id: []}
                for value in values:
                    value_id = self.get_attribute_value(attr_id, slugify(value))
                    _dict[attr_id].append(value_id)

                attribute_value_mappings.update(_dict)

            variant["attributes"] = attribute_value_mappings


    def get_attribute(self, slug):

        try: 
            attribute = Attribute.objects.get(slug=slug)
        except:
            attribute = None
        if attribute:
            return attribute.id

    def get_attribute_value(self, attribute_id, slug):
        try: 
            attribute_value = AttributeValue.objects.get(slug=slug, attribute=attribute_id)
        except:
            attribute_value = None
        if attribute_value:
            return attribute_value.id

    def get_assigned_product_attribute(self, product, assignment):
        try: 
            assigned_product_attribute = AssignedProductAttribute.objects.get(product=product, assignment=assignment)
        except:
            assigned_product_attribute = None
        if assigned_product_attribute:
            return assigned_product_attribute.id
    
    def get_assigned_variant_attribute(self, variant, assignment):
        
        try: 
            assigned_variant_attribute = AssignedVariantAttribute.objects.get(variant=variant, assignment=assignment)
        except:
            assigned_variant_attribute = None
        if assigned_variant_attribute:
            return assigned_variant_attribute.id
        
    def get_or_create_product_types(self, product_type):
        defaults = product_type["fields"]
        product_type, _ = ProductType.objects.get_or_create(**defaults, defaults=defaults)
        return product_type
        
    def create_attributes(self, attributes_data):
        attribute_values = {}
        for attribute in attributes_data:
            pk = attribute["pk"]
            defaults = attribute["fields"]
            attr, _ = Attribute.objects.update_or_create(pk=pk, defaults=defaults)

            values = self.create_attributes_values(attr, attribute["attr_value_items"])

            attribute_values.update({attr.id: {"is_variant_attribute": attribute["is_variant_attribute"], 
            "values": values}})

        return attribute_values

    def create_attributes_values(self, attribute, values_data):

        value_id_list = []

        for value in values_data:
            pk = value["pk"]
            defaults = value["fields"]
            defaults["attribute"] = attribute
            attr_value, _ = AttributeValue.objects.update_or_create(pk=pk, defaults=defaults)
            value_id_list.append(attr_value.id)

        return value_id_list
    
    def create_product(self, product):
        pk = product["pk"]
        defaults = product["fields"]
        if defaults.get("weight", None):
            defaults["weight"] = self.get_weight(defaults["weight"])
        defaults["category_id"] = defaults.pop("category")
        defaults["brand_id"] = defaults.pop("brand")
        defaults["product_type_id"] = defaults.pop("product_type")
        product, _ = Product.objects.update_or_create(pk=pk, defaults=defaults)

        return product
        
    def create_product_variants(self, product, brand_variant_zaamomapping, variants_data):

        variant_atribute_values_mapping = {}

        for _variant in variants_data:
            variant_id_brand =  _variant['fields'].pop('variant_id_brand')
            sku_id_brand =  _variant['fields'].pop('sku_id_brand')
            pk = _variant["pk"]

            if not pk:
                _variant["fields"]['sku'] = self.get_zaamo_sku(product.id)

            defaults = _variant["fields"]
            stock = _variant['stock']
            attributes = _variant['attributes']
            defaults["weight"] = self.get_weight(defaults.get("weight", "0:kg"))
            defaults["product"] = product
            
            if not defaults.get('metadata'):
                defaults['metadata'] = dict()
            
            defaults['metadata'].update({'true_msp':defaults['price_amount']})
            
            self.set_field_as_money(defaults, "price_override")
            self.set_field_as_money(defaults, "cost_price")
            is_default_variant = defaults.pop("default", False)
            variant, _ = ProductVariant.objects.update_or_create(pk=pk, defaults=defaults)
            variant_atribute_values_mapping.update({variant.id: attributes})

            if is_default_variant:
                product = variant.product
                product.default_variant = variant
                product.save(update_fields=["default_variant", "updated_at"])
            

            self.create_stocks(variant, warehouse=self.warehouse, quantity=stock.get('quantity', 0))

            if not pk:
                self.create_brand_zaamo_mapping(product, variant, brand_variant_zaamomapping, variant_id_brand, sku_id_brand)

        return variant_atribute_values_mapping
    
    def assign_attributes_to_product_types(
        self,
        association_model: Union[Type[AttributeProduct], Type[AttributeVariant]],
        attributes: list,):

        product_type_assignments = {}

        for value in attributes:
            pk = value["pk"]
            defaults = value["fields"]
            defaults["attribute_id"] = defaults.pop("attribute")
            defaults["product_type_id"] = defaults.pop("product_type")
            assignment, _ = association_model.objects.update_or_create(pk=pk, defaults=defaults)
            product_type_assignments.update({defaults["attribute_id"]: {"assignment": assignment}})

        return product_type_assignments

    def assign_attributes_to_products(self, product_attributes):
        for value in product_attributes:
            pk = value["pk"]
            defaults = value["fields"]
            defaults["product_id"] = defaults.pop("product")
            defaults["assignment"] = defaults.pop("assignment")
            assigned_values = defaults.pop("values")
            assoc, created = AssignedProductAttribute.objects.update_or_create(
                pk=pk, defaults=defaults
            )
            if created:
                assoc.values.set(AttributeValue.objects.filter(pk__in=assigned_values))

    def assign_attributes_to_variants(self, variant_attributes):
        for value in variant_attributes:
            pk = value["pk"]
            defaults = value["fields"]
            defaults["variant_id"] = defaults.pop("variant")
            defaults["assignment"] = defaults.pop("assignment")
            assigned_values = defaults.pop("values")
            
            assoc, created = AssignedVariantAttribute.objects.update_or_create(
                pk=pk, defaults=defaults
            )
            if created:
                assoc.values.set(AttributeValue.objects.filter(pk__in=assigned_values))
    
    def prepare_assign_attributes_to_variants(self, attributes_values_dict,
     product_type_assignments_variant, variant_atribute_values_mapping):
        assign_attribute_to_variant_data = {"product.assignedvariantattribute": []}

        for variant_id, attr_values in variant_atribute_values_mapping.items():
            for attr in attributes_values_dict:
                if attributes_values_dict[attr]['is_variant_attribute'] and attr_values.get(attr):
                    
                    data = {
                        "fields": {
                        "variant": variant_id,
                        "assignment": product_type_assignments_variant[attr]['assignment'],
                        "values": attr_values[attr]
                        }
                    }
                    
                    pk = self.get_assigned_variant_attribute(variant_id, product_type_assignments_variant[attr]["assignment"])
                    data['pk'] = pk
                    assign_attribute_to_variant_data["product.assignedvariantattribute"].append(data)
        
        return assign_attribute_to_variant_data
    
    def prepare_assign_attributes_to_products(self, attributes_values_dict, 
    product_type_assignments_product, product):
        assign_attribute_to_product_data = {"product.assignedproductattribute": []}
        for attr in attributes_values_dict:
            if not attributes_values_dict[attr]['is_variant_attribute']:
                data = {
                    "fields": {
                    "product": product.id,
                    "assignment": product_type_assignments_product[attr]['assignment'],
                    "values": attributes_values_dict[attr]['values']
                    }
                }

                pk = self.get_assigned_product_attribute(product, product_type_assignments_product[attr]['assignment'])
                
                data['pk'] = pk
                
                assign_attribute_to_product_data["product.assignedproductattribute"].append(data)
        
        return assign_attribute_to_product_data

    def prepare_assign_attributes_to_product_types(self, attributes_dict, product_type):

        attribute_products = {"product.attributeproduct": []}
        attribute_variants = {"product.attributevariant": []}
        for attr in attributes_dict:
            data = {
                "fields": {
                "attribute": attr,
                "product_type": product_type
                }
            }

            if attributes_dict[attr].get('is_variant_attribute'):
                pk = self.get_attribute_variant_id(attr, product_type)
                data['pk'] = pk
                attribute_variants["product.attributevariant"].append(data)
            else:
                pk = self.get_attribute_product_id(attr, product_type)
                data['pk'] = pk
                attribute_products["product.attributeproduct"].append(data)

        return attribute_products, attribute_variants   

    def prepare_attributes_and_values(self, attrs):

        attributes_and_values_dict = {"product.attribute": []}

        for attr in attrs:
            attr_id = self.get_attribute_id(slugify(attr))

            attr_dict = {
                'pk': attr_id,
                "is_variant_attribute": attrs[attr].get('is_variant_attribute', False),
                "fields": {
                "slug": slugify(attr),
                "name": attr,
                "input_type": "multiselect",
                "value_required": False,
                "is_variant_only": False,
                "visible_in_storefront": True,
                "filterable_in_storefront": True
                }
            }

            attr_values = attrs[attr]['values']
            attr_value_set = set()
            for value in attr_values:
                if isinstance(value, str):
                    attr_value_set.add(value.lower())
                else:
                    attr_value_set.add(value)

            attr_value_items = []
            for value in attr_value_set:
                attr_value_id = self.get_attribute_value(attr_id, slugify(value))
                attr_value_dict = {
                        "pk": attr_value_id,
                        "fields": {
                        "name": value,
                        "value": "",
                        "slug": slugify(value),
                        "attribute": attr_id
                        }
                    }
                attr_value_items.append(attr_value_dict)

            attr_dict.update({"attr_value_items":attr_value_items})

            attributes_and_values_dict["product.attribute"].append(attr_dict)

        return attributes_and_values_dict

    def prepare_product_input(self, product_type, category, brand, brand_variant_zaamomapping, product_input_dict):

        if 'variant_id_brands' in brand_variant_zaamomapping.keys():
            variant_id_brands = brand_variant_zaamomapping.pop('variant_id_brands')

            if not variant_id_brands:
                variant_id_brands = None

        else:
            variant_id_brands = None
            
        brand_zaamo_mapping = self.get_brand_variant_zaamo_mappings(variant_id_brands,**brand_variant_zaamomapping).first()
        product_input_dict['pk'] = None

        if brand_zaamo_mapping:
            product_input_dict['pk']= brand_zaamo_mapping.product_zaamo_id
        

        product_input_dict['fields'].update(
                {   "product_type": product_type,
                    "category": category,
                    'brand': brand,
                    "publication_date": datetime.date.today(),
                    "slug": slugify(product_input_dict['fields'].get('name', '') + " " + StringUtilities.convert_number_to_string(brand), allow_unicode=True),
                    "updated_at": datetime.datetime.now(),
                    "available_for_purchase": datetime.date.today(),
                    "visible_in_listings": True,
                    "currency": "INR",
                }
        )

        if product_input_dict['pk']:
            product_input_dict['fields'].pop('publication_date')

        product_with_this_slug = Product.objects.filter(slug=product_input_dict['fields']['slug'])

        if product_with_this_slug:
            uniquetoken = StringUtilities.convert_number_to_string(uuid.uuid4())
            product_input_dict['fields']['slug'] = slugify(product_input_dict['fields'].get('name', '') + StringUtilities.convert_number_to_string(brand) + uniquetoken, allow_unicode=True)

        return {"product.product": product_input_dict}

    def prepare_product_variant_input(self, brand_variant_zaamomapping, variant_input_dict):
        for variant in variant_input_dict:
            brand_variant_zaamomapping.update({"sku_id_brand": variant['fields']['sku_id_brand'], "variant_id_brand": variant['fields']['variant_id_brand']})
            brand_zaamo_mapping = self.get_brand_variant_zaamo_mappings(**brand_variant_zaamomapping).first()
            variant['pk'] = None
            
            if brand_zaamo_mapping:
                variant['pk'] = brand_zaamo_mapping.variant_zaamo_id
                

            variant['fields'].update(
                {
                    "currency": "INR"
                }
            )
        return {"product.productvariant": variant_input_dict}

    def prepare_db_items(self, json_input):
        product_type = json_input.get("product.producttype")
        category = json_input.get("product.category")
        brand = json_input.get("brand.brand")
        brand_variant_zaamomapping = json_input.get("product.brand_variant_zaamomapping")
        product_images = json_input.get("product.productimage", [])
        upload_images_to_ecom =  json_input.get("upload_images_to_ecom", True)

        product_data = {"product.producttype": product_type, "product.category": category, 
        "brand.brand": brand, "product.brand_variant_zaamomapping": brand_variant_zaamomapping,
        "product.productimage": product_images , "upload_images_to_ecom": upload_images_to_ecom
        }

        attributes_and_values_dict = self.prepare_attributes_and_values(json_input.get("product.attribute"))
        product_data.update(attributes_and_values_dict)

        product_input_dict = self.prepare_product_input(product_type, category, brand, brand_variant_zaamomapping, json_input.get("product.product"))
        product_data.update(product_input_dict)

        variant_input_dict = self.prepare_product_variant_input(brand_variant_zaamomapping, json_input.get("product.productvariant"))
        product_data.update(variant_input_dict)

        return product_data

    @transaction.atomic
    def create_or_update_db_item(self, data,product_needed=False):
        product_type = data.get("product.producttype")
        catagory = data.get("product.category")
        brand = data.get("brand.brand")
        brand_variant_zaamomapping = data.get("product.brand_variant_zaamomapping")

        attributes_values_dict = self.create_attributes(attributes_data=data["product.attribute"])

        self.update_attribute_value_in_variant_data(data["product.productvariant"])

        product  = self.create_product(
            product=data["product.product"],
        )
        variant_atribute_values_mapping = self.create_product_variants(
            product, brand_variant_zaamomapping,

            variants_data=data["product.productvariant"],
        )

        attribute_products, attribute_variants = self.prepare_assign_attributes_to_product_types(
            attributes_values_dict, product_type)

        product_type_assignments_product = self.assign_attributes_to_product_types(
            AttributeProduct, attributes=attribute_products["product.attributeproduct"]
        )
        product_type_assignments_variant = self.assign_attributes_to_product_types(
            AttributeVariant, attributes=attribute_variants["product.attributevariant"]
        )

        assign_attribute_to_product_data = self.prepare_assign_attributes_to_products(attributes_values_dict, 
        product_type_assignments_product, product)

        self.assign_attributes_to_products(
            product_attributes=assign_attribute_to_product_data["product.assignedproductattribute"]
        )

        assign_attribute_to_variant_data = self.prepare_assign_attributes_to_variants(attributes_values_dict, 
        product_type_assignments_variant, variant_atribute_values_mapping)
        self.assign_attributes_to_variants(
            variant_attributes=assign_attribute_to_variant_data["product.assignedvariantattribute"]
        )
        
        brand_instance = Brand.objects.filter(pk=brand).first()
        if not data["product.product"].get("pk") or (brand_instance and brand_instance.brand_name == "thrift_brand"):
            transaction.on_commit(lambda: self.upload_images(product, data.get("product.productimage", []), data.get("upload_images_to_ecom", True),data.get("upload_to_content_service",True)))
        
        if product_needed:
            return product

    def create_or_update_db_items(self, items_list):

        for item in items_list:
            prepared_json = self.prepare_db_items(item)

            self.create_or_update_db_item(prepared_json)


class BaseIntegration(object):

    name = "Base Integration"

    
    def __init__(self):
        self.base_product_create = BaseProductCreate()


    def clean_product_name(self,text):
        if not text:
            return ''

        text=re.sub("\<.*?\>","",text)
        
        return text
    
    def order_status_ranking_dict(self):
        status_dict = defaultdict(int)
        status_dict.update({
            "shipped":3,
            "placed":1,
            "in process":2,
            "delivered":4,
            "cancellation initiated":5,
            "cancellation processed":6,
            "return initated":6,
            "return completed":7
        })
        return status_dict

    def get_or_create_product_type(self, product_type='', catagory='', sub_catagory=''):
            
        assert any([product_type, catagory, sub_catagory]), "Provide atleast one of (product_type, \
        catagory, sub_catagory)"

        if not product_type and any([catagory, sub_catagory]):
            product_type = catagory
            if sub_catagory:
                product_type = sub_catagory

        product_type_data = {
        "fields": {
          "name": product_type,
          "slug": slugify(product_type, allow_unicode=True),
          "has_variants": True,
          "is_shipping_required": True,
          "is_digital": False
            }
        }
        product_type = self.base_product_create.get_or_create_product_types(product_type_data)

        return product_type.id


    def get_catagory_id(self, name, **kwrgs):
        try:
            category = Category.objects.get(slug=slugify(name))
        except:
            category = None

        if category:

            return  category.id

    def get_brand_source(self,brand_id):
        brand_instance = Brand.objects.filter(id=brand_id).first()
        brand_source = 'csv'

        if brand_instance:
            source = brand_instance.brand_source
            if source == BrandSourceEnum.UNICOMMERCE:
                brand_source = source

        return brand_source        

    def get_brand_id(self, brand_name):
        
        brand_instance = Brand.objects.filter(brand_name=brand_name).first()
        brand_id = None
        
        if brand_instance:
            brand_id = brand_instance.id

        return brand_id
    
    def get_brand_from_private_metadata(self, brand_name):
        
        brand_instance = Brand.objects.filter(private_metadata__source_name=brand_name).first()
        brand_id = None
        
        if brand_instance:
            brand_id = brand_instance.id
        
        else:
            brand_id = self.get_brand_id(brand_name)

        return brand_id

    def push_inventory(self, json_list, from_celery=True):

        if from_celery:
            push_inventory_task.delay(json_list)
        else:
            push_inventory_sync(json_list)
        
        return True

    def push_inventory_csv(self, json_list):

        push_inventory_csv_task.delay(json_list)
        
        return True

    def gen_chunks(self, reader, chunksize=250):
        chunk = []
        for i, line in enumerate(reader):
            if (i % chunksize == 0 and i > 0):
                yield chunk
                del chunk[:]
            chunk.append(line)
        yield chunk

    def base_product_mapper(self, products):

        """
        Map Integration's api data to generic zaamo prodcut create json. 

        """

        raise NotImplementedError("Should be implemented by the new integration")
    
    def save_order_mapping(self,order_lines,order_brand_id,url=None):
        if order_brand_id:

            order = order_lines[0].order
            for line in order_lines:
                metadata = {}
                
                if url:
                    metadata = {'shopify_url':url}

                OrderBrandZaamoMapping.objects.create(brand=line.brand,
                                                order_zaamo=order, 
                                                product_name=line.product_name, 
                                                order_line_zaamo=line,
                                                order_id_brand=order_brand_id,
                                                metadata=metadata)
