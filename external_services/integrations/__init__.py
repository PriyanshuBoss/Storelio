from collections import defaultdict
from saleor.graphql.product.enums import StockAvailability

from saleor.graphql.product.filters import filter_products_by_stock_availability
from .shopify import ShopifyIntegration
from saleor.brand.models import BrandCollection, Brand, BrandTag
from saleor.brand.states import BrandCollectionTypeEnum
from django.db.models import Q
import logging
from saleor.product.models import BrandVariantZaamoMapping, Product, Category
logger = logging.getLogger(__name__)

class Integrations:
    SHOPIFY, WOOCOMMERCE= 'SHOPIFY', "WOOCOMMERCE"

class BrandCollectionCreate:

    def create_brand_collection_obj(self,name_id_dict, brand, 
                                    type, brand_name,zaamo_source=False):

        for name,product_ids in name_id_dict.items():
            
            if not name:
                continue

            try:
                b_collection_obj = BrandCollection.objects.get(brand_id=brand.id,
                                                                name=name,type=type)
            
            except Exception as e:
                b_collection_obj = BrandCollection.objects.create(brand=brand,
                                            type=type,
                                            name=name)

            if zaamo_source:
                b_collection_obj.product.add(product_ids)

            else:
                products = Product.objects.filter(id__in = BrandVariantZaamoMapping.objects.filter(
                                                    brand_name = brand_name,
                                                    product_id_brand__in = product_ids).values('product_zaamo_id'), 
                                                    is_published=True)

                b_collection_obj.product.clear()
                b_collection_obj.product.add(*products)

    def remove_non_existing_brand_collections(self,brand,collection_names):
        BrandCollection.objects.filter(brand_id=brand.id,type__in = 
                [BrandCollectionTypeEnum.CATEGORY,BrandCollectionTypeEnum.COLLECTION]
                ).exclude(name__in=collection_names
                ).delete()


    def save_brand_collection_name(self,brand_name):

        from saleor.graphql.analytics.resolvers import filter_brand_categories,filter_brand_collections        

        try:
            
            brand = Brand.objects.filter(Q(brand_name=brand_name) | Q(private_metadata__source_name=brand_name)).first()
            
            if not brand:
                return

            category_data_dict = filter_brand_categories(brand,[],for_pdp=False)
            collection_data_dict = filter_brand_collections(brand,[],for_pdp=False)
            collection_names = []

            if category_data_dict:
                collection_names.extend(list(category_data_dict.keys()))
                self.create_brand_collection_obj(category_data_dict,brand,BrandCollectionTypeEnum.CATEGORY,brand_name)
            
            if collection_data_dict:
                collection_names.extend(list(collection_data_dict.keys()))
                self.create_brand_collection_obj(collection_data_dict,brand,BrandCollectionTypeEnum.COLLECTION,brand_name)
        
            self.remove_non_existing_brand_collections(brand,collection_names)
        except Exception as e:
            logger.exception(e)
    
    def add_brand_collection_by_publish(self, product_id_brand, brand):

        from saleor.graphql.analytics.resolvers import fetch_category_product_id,fetch_collection_product_id, get_brand_name_from_ob        
        
        try:
            brand_name = get_brand_name_from_ob(brand)
            category_data_dict = fetch_category_product_id(product_id_brand, brand)

            collection_data_dict = fetch_collection_product_id(product_id_brand, brand)

            if category_data_dict:
                self.create_brand_collection_obj(category_data_dict,brand,BrandCollectionTypeEnum.CATEGORY,brand_name)
            
            if collection_data_dict:
                self.create_brand_collection_obj(collection_data_dict,brand,BrandCollectionTypeEnum.COLLECTION,brand_name)
        
        except Exception as e:
            logger.exception(e)

    def add_zaamo_collection_by_publish(self, product_zaamo, brand, category_id=None):

        from saleor.graphql.analytics.resolvers import get_brand_name_from_ob        
        
        try:
            brand_name = get_brand_name_from_ob(brand)
            category_name = product_zaamo.category.name
            
            if category_id:
                category = Category.objects.filter(id=category_id).first()

                if category:
                    category_name=category.name

            if 'uncategorized' in category_name:
                return
                
            category_data_dict = {category_name:product_zaamo}

            self.create_brand_collection_obj(category_data_dict,brand,BrandCollectionTypeEnum.ZAAMOCATEGORY,brand_name,zaamo_source=True)
        
        except Exception as e:
            logger.exception(e)
    
    def save_staff_brand_collection(self,brand_id=None):
        if brand_id:
            brands = Brand.objects.filter(brand_source__in=['staff','manual'], id=brand_id)
        
        else:
            brands = Brand.objects.filter(brand_source__in=['staff','manual'])
        
        for brand in brands:
            try:
                products = Product.objects.filter(brand_id=brand.id,is_published=True).select_related('category')
                name_id_dict = defaultdict(list)
                for product in products:
                    name_id_dict[product.category.name].append(product)
                    
                for name,product_ids in name_id_dict.items():
                    
                    if not name:
                        continue

                    try:
                        b_collection_obj = BrandCollection.objects.get(brand_id=brand.id,
                                                                        name=name,type=BrandCollectionTypeEnum.CATEGORY)
                    
                    except Exception as e:
                        b_collection_obj = BrandCollection.objects.create(brand=brand,
                                                    type=BrandCollectionTypeEnum.CATEGORY,
                                                    name=name)

                    b_collection_obj.product.add(*product_ids)

            except Exception as e:
                print(e)
    
class BrandTagCreate:

    def fetch_brand_source_tag_product_id(self):
        
        from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
        from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl

        sh_inst = ShopifyImpl()
        wo_inst = WooCommerceImpl()
        brands = Brand.objects.filter(brand_source__in=['shopify','woocommerce'])

        tag_product_id_dict = defaultdict(list)
        for brand in brands:
            try:
                brand_name = brand.private_metadata.get('source_name')
                source = brand.brand_source
                print(brand_name)
                
                if source == 'shopify':
                    data = sh_inst.fetch_tags_product_id_dict(brand_name)
                
                else:
                    data = wo_inst.fetch_tags_product_id_dict(brand_name)
                
                for tag_name, product_id_brands in data.items():
                    product_ids_brand=[]
                    product_ids = BrandVariantZaamoMapping.objects.filter(Q(product_id_brand__in=product_id_brands) & Q(brand_zaamo_id=brand.id)).values_list('product_zaamo_id',flat=True)

                    if product_ids:
                        product_ids_brand = list(product_ids)

                    tag_product_id_dict[tag_name].extend(product_ids_brand)

            except Exception as e:
                print(e)

        products = Product.objects.filter(is_published=True, minimal_variant_price_amount__isnull=False)
        products = filter_products_by_stock_availability(products,StockAvailability.IN_STOCK)
        p_ids = [p.id for p in products]
        p_ids = set(p_ids)
        
        for tag, product_ids in tag_product_id_dict.items():
            tag=tag.strip()

            p_to_add = set(product_ids).intersection(p_ids)
            p_to_add = list(p_to_add)
            
            if not tag or not p_to_add:
                continue
            
            try:
                b_tag_obj = BrandTag.objects.get(name=tag)
            
            except Exception as e:
                b_tag_obj = BrandTag.objects.create(name=tag)
            b_tag_obj.product.add(*p_to_add)

class IntegrationFactory(object):
    """Integration Factory"""


    @classmethod
    def create(cls, type, *args, **kwargs):
        integration = None

        if type == Integrations.SHOPIFY:
            integration = ShopifyIntegration
            
        elif type == Integrations.WOOCOMMERCE:
            integration = " add WOOCOMMERCE vender class here"

        return integration(*args, **kwargs)
