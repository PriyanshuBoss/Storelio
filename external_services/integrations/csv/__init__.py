from django.conf import settings
from saleor.external_services.integrations.base import BaseIntegration
from saleor.product.models import ProductType, Product, RejectedShopifyProduct
from saleor.utilities.number_utilities import NumberUtilities

class CsvIntegration(BaseIntegration):

    product_type = "csv_product_type"
    category_name_id_mapping = None
    brand_name_id_mapping = None

    def __init__(self):
        super().__init__()
        product_type = self.get_product_type(name="csv_product_type")
        self.product_type_id=None
        if product_type:
            self.product_type_id = product_type.id
          
    def get_product_type(self, name="csv_product_type"):
        try:
            product_type = ProductType.objects.filter(name=name).first()
        except:
            product_type = None    
        return product_type
    
    def get_brand_name_id_mapping(self, reader_list):
        brand_set = set()
        brand_name_id_mapping = dict()

        for item in reader_list:
            if item.get("brand id"):
                brand_set.add(item.get("brand id"))
            
        for brand in brand_set:
            brand_name_id_mapping[brand] = self.get_brand_id(brand)

        self.brand_name_id_mapping = brand_name_id_mapping
        return self.brand_name_id_mapping

    def get_category_name_id_mapping(self, reader_list):
        category_set = set()
        category_name_id_mapping = dict()

        for item in reader_list:
            if item.get("category"):
                category_set.add(item.get("category"))
            if item.get("sub category"):
                category_set.add(item.get("sub category"))

        for category in category_set:
            category_name_id_mapping[category] = self.get_catagory_id(category)

        self.category_name_id_mapping = category_name_id_mapping
        return self.category_name_id_mapping

    def get_attributes(self, reader_list, product_attribute_list, variant_attributes_list):

        if not product_attribute_list:
            product_attribute_list = []
        
        if not variant_attributes_list:
            variant_attributes_list = []

        product_attributes = {product_atttribute: {'values': [], "is_variant_attribute": False} for product_atttribute in  product_attribute_list}
        variant_attributes = {variant_attribute: {'values': [], "is_variant_attribute": True} for variant_attribute in  variant_attributes_list}

        for row in reader_list:
    
            for key in product_attributes:
                if key in row and row[key] not in product_attributes[key]['values'] and row[key]:
                    product_attributes[key]['values'].append(row[key])

            for key in variant_attributes:
                
                if key in row and row[key] not in variant_attributes[key]['values'] and row[key]:
                    variant_attributes[key]['values'].append(row[key])

        self.product_attributes = product_attributes
        self.variant_attributes = variant_attributes

        return product_attributes, variant_attributes
    
    def prepare_csv_data(self, reader_list):

        products = {}
        for row in reader_list:

            if 'pid' in row:
                if row['pid'] in products:
                    products[row['pid']].append(row)
                else:
                    products[row['pid']]=[row]
            else:
                products.append(row)
        
        return products

    def prepare_variants_data(self, variants):
        variants_list = []
        set_default = True
        min_variant_price = min([NumberUtilities.convert_string_to_number(variant.get('selling price', "0").replace(',', '')) for variant in variants])

        for variant in variants:
            variant_attributes = {}
            if set_default and min_variant_price == NumberUtilities.convert_string_to_number(variant.get('selling price', "0").replace(',', '')):
                default = True 
                set_default = False
            else:
                default = False

            name = ""
            for attr in self.variant_attributes:
                variant_attributes[attr] = [variant.get(attr)]
                name = variant.get(attr)

            variant_data = {
                "attributes": variant_attributes ,
                "fields": {
                "variant_id_brand":variant.get("sku"),
                "private_metadata": {},
                "metadata": {},
                "sku_id_brand": variant.get("sku"),
                "name": name,
                "price_amount": variant.get('selling price', '').replace(',', ''),
                "cost_price_amount": variant.get("mrp", '').replace(',', ''),
                "default": default,
                },
                "stock": {"quantity": variant.get('quantity', '0')}
            }
            variants_list.append(variant_data)

        return variants_list

    def base_product_mapper(self, products):

        json_list= []

        for pid, variants in products.items():
            
            first_variant = variants[0]
            
            if first_variant.get("sub category"):
                category_id = self.category_name_id_mapping.get(first_variant.get("sub category"))
            else:
                category_id = self.category_name_id_mapping.get(first_variant.get("category"))
            
            brand_id = self.brand_name_id_mapping.get(first_variant.get("brand id"))
            brand_source  = self.get_brand_source(brand_id)
            min_variant_price = min([NumberUtilities.convert_string_to_number(variant.get('selling price', "0").replace(',', '')) for variant in variants])
            variants_data = self.prepare_variants_data(variants)
            
            self.product_attributes.update(self.variant_attributes)
            attributes = self.product_attributes

            db_item = {

            "product.category": category_id,

            "product.producttype": self.product_type_id,

            "brand.brand": brand_id,

            "product.attribute": attributes,

            "product.brand_variant_zaamomapping": {
                "product_id_brand": first_variant.get("pid"),
                "brand_name": first_variant.get("brand id"),
                "source": brand_source
            },

            "product.product": {
            "fields": {
                "brand": brand_id,
                "private_metadata": {"hsn": first_variant.get('hsn', ''), "colour": first_variant.get('colour', ''), 
                'material': first_variant.get('material', '')},
                "metadata": {},  
                "name": first_variant.get("product name"),
                "description_json": {"description_text": first_variant.get("description", "")
                },
                "is_published": True,
                "minimal_variant_price_amount": min_variant_price,
                }
            },
            "product.productimage":[
                    first_variant.get('search image url', ''),
                    first_variant.get('back image url', ''),
                    first_variant.get('left image url', ''),
                    first_variant.get('right image url', ''),
                    ],
            "upload_images_to_ecom": True,
            "product.productvariant" : variants_data

            } 

            json_list.append(db_item)

        return json_list
    
    def set_mappings(self, reader_list, product_attribute_list, variant_attributes_list):
        self.get_attributes(reader_list, product_attribute_list=product_attribute_list,
                    variant_attributes_list=variant_attributes_list)
        self.get_brand_name_id_mapping(reader_list)
        self.get_category_name_id_mapping(reader_list)

    def upload_products(self, reader_list, product_attribute_list=None, variant_attributes_list=None):

        self.set_mappings(reader_list, product_attribute_list, variant_attributes_list)
        products = self.prepare_csv_data(reader_list)
        upload_product_json = self.base_product_mapper(products)  
        self.push_inventory_csv(upload_product_json)
           
        return upload_product_json

    def upload_shopify_rejected(self, product_ids):
        products = Product.objects.filter(id__in=product_ids).filter(rejectedshopifyproduct__isnull=True).values_list('id', 'name', 'brand__brand_name')
        objs = []
        for product_id, product_name, brand_name in products:
            objs.append(
                RejectedShopifyProduct(product_id=product_id, product_name=product_name, brand_name=brand_name)
            )
        
        RejectedShopifyProduct.objects.bulk_create(objs=objs, batch_size=1000)
        created = len(objs)
        return created
