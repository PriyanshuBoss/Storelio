from collections import defaultdict
from saleor.product.models import Product, ProductImage, BrandVariantZaamoMapping
from saleor.utilities.mongo_utilities import MongoConn
from saleor.brand.models import Brand
from django.db import transaction
from saleor.external_services.integrations.base import BaseProductCreate
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.utilities.number_utilities import NumberUtilities


def run(brand_id=None):
    products = Product.objects.filter(brand_id=brand_id).exclude(id__in=ProductImage.objects.all().values('product_id'))
    brand_mapping = BrandVariantZaamoMapping.objects.filter(product_zaamo_id__in=products.values('id'))
    product_id_zaamo_dict = dict()
    variant_id_zaamo_dict = defaultdict(list)

    for mapping in brand_mapping:
        product_id_zaamo_dict[mapping.product_zaamo_id] = NumberUtilities.convert_string_to_number(mapping.product_id_brand)
        variant_id_zaamo_dict[mapping.product_zaamo_id].append(NumberUtilities.convert_string_to_number(mapping.variant_id_brand))

    base_instance = BaseProductCreate()
    brand = Brand.objects.get(id=brand_id)
    brand_name = brand.private_metadata.get('source_name') or brand_name
    source = brand.brand_source
    woo_inst = WooCommerceImpl()
    shopify_inst = ShopifyImpl()

    if source=='woocommerce':
        mapped_product = woo_inst.fetch_product_data_from_gridfs_by_name(f"{brand_name}_mapped", key='mapped_product_data')
    
    elif source=='shopify':
        mapped_product = shopify_inst.fetch_product_data_from_gridfs_by_name(f"{brand_name}_mapped", key='mapped_product_data')
    
    variant_mapped_data = dict()
    product_mapped_data = dict()

    for mapped_data in mapped_product:
        product_mapped_data[mapped_data['product.brand_variant_zaamomapping']['product_id_brand']] = mapped_data
        for variant_brand_id in mapped_data['product.brand_variant_zaamomapping']['variant_id_brands']:
            variant_mapped_data[variant_brand_id] = mapped_data

    for product in products:
        variant_ids_brand = variant_id_zaamo_dict[product.id]
        productid_brand = product_id_zaamo_dict.get(product.id)
        data = dict()

        for id in variant_ids_brand:
            data = variant_mapped_data.get(id)
            if data:
                break
        
        if not data and productid_brand:
            data = product_mapped_data.get(productid_brand)
        
        if data:
            print(f'creating images for {product.name}')
            transaction.on_commit(lambda: base_instance.upload_images(product, data.get("product.productimage", []), data.get("upload_images_to_ecom", True),data.get("upload_to_content_service",True)))


'''
TO-RUN:

from saleor.python_scripts.update_images_for_source_product import run
run(brand_id=<brand_id_to_update>)

'''
