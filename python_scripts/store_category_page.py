
from saleor.product.models import CollectionStore
from saleor.store.store_utilities import save_brands_for_store_category_page
import time

def fill_store_category_page():
    all_collections = CollectionStore.objects.select_related('store', 'collection')
    
    for data in all_collections:
        store_instance = data.store
        collection_instance = data.collection
        products = collection_instance.products.select_related('brand', 'category')

        if products:
            print(collection_instance.id)
            start_time = time.time()
            save_brands_for_store_category_page(products, store_instance)
            end_time = time.time()
            print(end_time-start_time)


fill_store_category_page()
print("Script Completed-------------------->")

#from saleor.python_scripts import store_category_page