from collections import defaultdict
from email.policy import default
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saleor.settings")
django.setup()
from saleor.product.models import Product, ProductVariant, BrandVariantZaamoMapping
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl

def update_woo_commerce_variant_names_without_id(woo_variant_without_id):
    print(f"woocommerce variants without id updating {woo_variant_without_id}")

    variants = ProductVariant.objects.filter(id__in=woo_variant_without_id)
    for variant in variants:
        variant.name = variant.product.name
        variant.save()

def update_woo_commerce_variant_names(woocommerce_brand_variant_id_dict):
    print(f"woocommerce variants updating: {woocommerce_brand_variant_id_dict}")

    woo_impl = WooCommerceImpl()

    for brand,variant_ids in woocommerce_brand_variant_id_dict.items():
        variant_names = dict()
        product_data = woo_impl.fetch_product_data_from_woo_commerce_store_by_name(brand)

        for product in product_data:
            variants = product.get('variations', [])

            for v in variants:
                atts = v.get('attributes')

                for att in atts:
                    if att['name'].lower() == 'size':
                        variant_names[v['id']] = att['option']
            
        for v_id in variant_ids:
            name = variant_names.get(int(v_id))

            if not name:
                continue
            
            variant_mapping = BrandVariantZaamoMapping.objects.filter(brand_name=brand,variant_id_brand=v_id).first()
            ProductVariant.objects.filter(id = variant_mapping.variant_zaamo_id).update(name=name)

def update_shopify_commerce_variant_names(shopify_brand_variant_id_dict):
    print(f"shopify variants updating: {shopify_brand_variant_id_dict}")

    shopify_impl = ShopifyImpl()

    for brand,variant_ids in shopify_brand_variant_id_dict.items():
        variant_names = dict()
        product_data = shopify_impl.fetch_product_data_from_shopify_store_by_name(brand)

        for product in product_data:
            sizeoptions = []
            options = product.get('options')
            option_names = ['option1', 'option2', 'option3']

            if not options:
                continue
            
            for option in options:
                if option['name'].lower() == 'size':
                    sizeoptions = option.get('values', [])
                
            variants = product.get('variants_list')

            for variant in variants:

                for opt in option_names:
                    current_option = variant.get(opt)
                    
                    if not current_option:
                        continue

                    if current_option in sizeoptions:
                        variant_names[variant['id']] = current_option
                        break

        for v_id in variant_ids:
            
            name = variant_names.get(int(v_id))
            variant_mapping = BrandVariantZaamoMapping.objects.filter(brand_name=brand,variant_id_brand=v_id).first()

            if not name:
                variant_to_update = ProductVariant.objects.filter(id = variant_mapping.variant_zaamo_id).first()
                product_name = variant_to_update.product.name
                variant_to_update.name = product_name
                variant_to_update.save()
                continue
            
            ProductVariant.objects.filter(id = variant_mapping.variant_zaamo_id).update(name=name)
    

def run():
    shopify_brand_variant_id_dict = defaultdict(list)
    woocommerce_brand_variant_id_dict = defaultdict(list)
    variant_without_name = ProductVariant.objects.filter(name='').values('id')

    mapping = BrandVariantZaamoMapping.objects.filter(variant_zaamo_id__in = variant_without_name)
    woo_variant_without_id = []

    for map in mapping:
        if map.source=='woocommerce':
            if map.variant_id_brand:
                woocommerce_brand_variant_id_dict[map.brand_name].append(map.variant_id_brand)
            else:
                woo_variant_without_id.append(map.variant_zaamo_id)

        if map.source=='shopify':
            shopify_brand_variant_id_dict[map.brand_name].append(map.variant_id_brand)

    update_shopify_commerce_variant_names(shopify_brand_variant_id_dict)
    update_woo_commerce_variant_names(woocommerce_brand_variant_id_dict)
    update_woo_commerce_variant_names_without_id(woo_variant_without_id)


run()
