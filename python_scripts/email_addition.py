import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saleor.settings")
django.setup()
from saleor.brand.models import BrandEmail, Brand

def email_addition():
    brand_list = Brand.objects.all()
    for brand in brand_list:
        if brand.email:
            if not BrandEmail.objects.filter(brand_id=brand,brand_email=brand.email).exists():
                BrandEmail(brand_id=brand,brand_email=brand.email).save()



email_addition()
