from saleor.core.models import ApiApp
from saleor.account.models import User
from saleor.brand.models import Brand
from saleor.brand.states import BrandSourceEnum
from saleor.product.models import BrandVariantZaamoMapping
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):

    help = "Create App_secret_key and App_id for Brands"

    def add_arguments(self, parser):
        parser.add_argument('brand_id',type = int,help="brand_id whose App Secret key and Id needs to be created")  

    def app_creation(self,**options):

        brand_id = options['brand_id']
        brand = Brand.objects.filter(id=brand_id).first()
        brand.brand_source = BrandSourceEnum.UNICOMMERCE
        brand.save()
        BrandVariantZaamoMapping.objects.filter(brand_zaamo_id = brand_id).update(source='unicommerce')
        user = User.objects.filter(email="admin@admin.com").first()
        api_app = ApiApp.objects.filter(private_metadata__brand_id=brand_id).first()
        data = {}
        if api_app:
            data["app_id"] = api_app.app_id
            data["api_secret_key"] = api_app.api_secret_key
        else:
            api_app = ApiApp()
            api_app.private_metadata["brand_id"] = brand_id
            api_app.created_by= user
            api_app.app_name = brand.brand_name
            api_app.save()

            data["app_id"] = api_app.app_id
            data["api_secret_key"] = api_app.api_secret_key   

        
        self.stdout.write(" username: {}\n password: {}".format(data["app_id"],data["api_secret_key"]))

    def handle(self,**options):
        return self.app_creation(**options)


# command to use 

# python manage.py api_app_creation 37
