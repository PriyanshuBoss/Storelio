from saleor.graphql.core.dataloaders import DataLoader
from saleor.brand.models import BrandShippingData

class BrandShippingDataLoader(DataLoader):
    context_key = 'brand_shipping_by_brand_id'

    def batch_load(self, keys):
        brand_shipping = BrandShippingData.objects.filter(brand_id__in=keys)
        data = dict()
        for shipping in brand_shipping:
            if not shipping.brand_id in data:
                data[shipping.brand_id] = shipping
        return [data.get(key) for key in keys]

