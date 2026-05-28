from saleor.product.models import Product

def func():

    products = Product.objects.filter(metadata__has_key = 'steal_deal')

    for product in products:
        prod_metadata = product.metadata
        condition = prod_metadata.get('steal_deal')
        prod_metadata.pop('steal_deal')
        prod_metadata['value_deal'] = condition


    Product.objects.bulk_update(products,['metadata'])

    print('DONE')

func()

#from saleor.python_scripts import fixing_value_deal
