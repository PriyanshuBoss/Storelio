from saleor.external_services.google_analytics.ga_helper import get_product_views
from saleor.product.models import StoreProductViews, Product, store_models
from saleor.utilities.number_utilities import NumberUtilities


def run():
    product_views = [{
            "product_id": NumberUtilities.convert_string_to_number(doc["_id"]["product_id"]),
            "store_id": NumberUtilities.convert_string_to_number(doc["_id"]["store_id"]),
            "views": doc["views"]
        } for doc in get_product_views()]

    print('product views updating... ', len(product_views))
    
    store_ids = set(view['store_id'] for view in product_views)
    product_ids = set(view['product_id'] for view in product_views)
    
    stores = set(store_models.StoreInfo.objects.filter(pk__in=store_ids).values_list('pk', flat=True))
    products = set(Product.objects.filter(pk__in=product_ids).values_list('pk', flat=True))
    
    for views in product_views:
        if views['product_id'] in products and views['store_id'] in stores:
            product, created = StoreProductViews.objects.get_or_create(product_id=views['product_id'], store_id=views['store_id'])
            product.views = views['views']
            product.save()

    print('done')

