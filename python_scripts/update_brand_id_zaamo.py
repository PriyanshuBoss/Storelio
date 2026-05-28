from saleor.product.models import BrandVariantZaamoMapping
from saleor.brand.models import Brand

def run():
    brands = Brand.objects.all()
    for brand in brands:
        brand_name = brand.private_metadata.get('source_name')
        if brand_name is not None:
            BrandVariantZaamoMapping.objects.filter(brand_name=brand_name).update(brand_zaamo=brand)      
    print("Script runed successfully!!")
run()
