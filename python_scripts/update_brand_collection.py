from collections import defaultdict
from saleor.brand.models import Brand, BrandCollection
from saleor.product.models import Product
from saleor.brand.states import BrandCollectionTypeEnum
from saleor.external_services.integrations import BrandCollectionCreate
from saleor.graphql.analytics.resolvers import get_brand_name_from_ob

def save_brand_collection():
    brands = Brand.objects.all()
    instance = BrandCollectionCreate()
    for brand in brands:
        try:
            
            instance.save_brand_collection_name(get_brand_name_from_ob(brand))
        except Exception as e:
            print(e)

def save_staff_brand_collection():
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

save_staff_brand_collection()       
# save_brand_collection()
