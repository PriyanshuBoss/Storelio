import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saleor.settings")
django.setup()
from saleor.brand.models import Brand

def run():
    brands = Brand.objects.all()
    for brand in brands:
        brand.private_metadata = {'source_name': brand.brand_name}
        brand.save()
        print(f"{brand.brand_name} updated!")
    
run()
