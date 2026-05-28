from django.db.models import Q

from saleor.external_services.pincode import pincode_impl
from saleor.shipping.models import Zipcode
from ..core.dataloaders import DataLoader

class ZipcodeLoader(DataLoader):
    context_key = "zipcode_by_checkout"

    async def batch_load_fn(self, keys):
        filters = Q()
        for pincode, country in keys:
            filters |= Q(pincode=pincode, country=country)
        zipcodes = Zipcode.objects.filter(filters)
        zipcodes = {(zipcode.pincode, zipcode.country): zipcode for zipcode in zipcodes}
        
        data = []
        for key in keys:
            if key in zipcodes:
                data.append(zipcodes.get(key))
            else:
                instance = None
                pincode_data = pincode_impl.location_from_pin(pincode, country)
                if pincode_data:
                    instance = Zipcode.objects.create(
                        pincode=pincode_data['pincode'], city = pincode_data.get('city'), state = pincode_data.get('state'), 
                        country = pincode_data.get('country'), district = pincode_data.get('district')
                    )
                data.append(instance)
        return data

