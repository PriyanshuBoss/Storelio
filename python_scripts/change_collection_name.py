from saleor.product import models as product_models


def func():

    collections = product_models.Collection.objects.filter(is_default = True)
    collections.update(name = 'Steal Deal')

    for col in collections:
        col.collectionproduct.all().delete()


func()
print("Script ran successfully")

#command to run the script 

# from saleor.python_scripts import change_collection_name

