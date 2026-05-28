from ...shipping import models
from ...shipping.utils import get_pincode
from collections import defaultdict

def resolve_shipping_zones(info):
    return models.ShippingZone.objects.all()

def resolve_data_by_postal(info,pincode,country):

    zipcode_data =  defaultdict(str)
    zipcode_instance = get_pincode(pincode,country)
        
    if zipcode_instance:
        zipcode_data['city'] = zipcode_instance.city
        zipcode_data['country'] = zipcode_instance.country
        zipcode_data['state'] = zipcode_instance.state

    return zipcode_data

