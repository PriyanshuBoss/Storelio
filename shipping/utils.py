from django_countries import countries
from saleor.external_services.pincode import pincode_impl
from .models import ShippingZone,Zipcode


def default_shipping_zone_exists(zone_pk=None):
    return ShippingZone.objects.exclude(pk=zone_pk).filter(default=True)


def get_countries_without_shipping_zone():
    """Return countries that are not assigned to any shipping zone."""
    covered_countries = set()
    for zone in ShippingZone.objects.all():
        covered_countries.update({c.code for c in zone.countries})
    return (country[0] for country in countries if country[0] not in covered_countries)

def get_pincode(pincode,country='IN'):

    pincode_data = Zipcode.objects.filter(pincode=pincode,country=country)
    if pincode_data:
        return pincode_data.first()
    else:
        return None
        # pincode_data = pincode_impl.location_from_pin(pincode,country)
        # if pincode_data:
        #     zipcode_instance = Zipcode.objects.create(pincode=pincode_data['pincode'],city = pincode_data.get('city') ,state = pincode_data.get('state'),country = pincode_data.get('country'),district = pincode_data.get('district'))
        #     return zipcode_instance

def get_locations(pincodes: set):
    exists = Zipcode.objects.filter(pincode__in=pincodes).values_list('pincode', flat=True)
    create_zipcodes = [pincode for pincode in pincodes if not pincode in exists]
    for zipcode in create_zipcodes:
        get_pincode(zipcode)

    zipcodes = Zipcode.objects.filter(pincode__in=pincodes).only('state', 'pincode', 'country')
    locations = dict()
    for zipcode in zipcodes:
        locations[(zipcode.pincode, zipcode.country)] = zipcode
    
    return locations
