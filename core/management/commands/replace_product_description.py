from saleor.product.models import Product
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):

    help = "Replace String in Description Json of product with another string"

    def add_arguments(self, parser):
        parser.add_argument('brand_id',type = int,help="brand_id whose products needs to be updated")
        parser.add_argument('string_to_be_replaced',type = str, help = "string to be search and replaced")
        parser.add_argument('string_replaced_by',type=str,help = "string which will come in the replaced place")

    def replace_text_inproduct_description(self,**options):

        brand_id = options['brand_id']
        to_replace = options['string_to_be_replaced']
        replace_by = options['string_replaced_by']

        products = Product.objects.filter(brand_id = brand_id,description_json__description_text__icontains=to_replace)
        updated_prods = []
        for product in products:
            json = product.description_json
            final_text = json.get("description_text").replace(to_replace, replace_by)
            product.description_json["description_text"] = final_text
            updated_prods.append(product)

        try:
            Product.objects.bulk_update(updated_prods,['description_json'],batch_size=1000)
            self.stdout.write("Successfully updated")
        except:
            raise CommandError("Error while updating description_json")
        

    def handle(self,**options):
        self.replace_text_inproduct_description(**options)


# command to use 

# python manage.py replace_product_description 37  "Bio washed" "cant wash"
