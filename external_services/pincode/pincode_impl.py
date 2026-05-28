import logging  
from saleor.utilities.api_client import ApiClient
from .constants import PINCODE_URI, PINCODE_HEADER,PINCODE_BODY
logger = logging.getLogger(__name__)

def location_from_pin(pincode,country_code):

    location_data = {}
    try:
        data = fetch_pincode(pincode,country_code)
    except Exception as e:
        logger.info("Error fetching the api response :: %s", e)
        return location_data
    if data:
        first_location = data[0]
        location_data['pincode'] = pincode
        location_data['city'] = first_location.get('division')
        location_data['state'] = first_location.get('circle')
        location_data['country'] = 'IN'
        location_data['district'] = first_location.get('district')

        return location_data

def fetch_pincode(pincode , country_code):

    pincode_url = PINCODE_URI
    pincode_body = PINCODE_BODY
    pincode_body['value'] = pincode
    api_client = ApiClient(url=pincode_url)
    api_client.headers = PINCODE_HEADER
    api_client.body = pincode_body
    api_client.post()
    api_response = api_client.fetch_response()
    if api_response:
        return api_response
    else:
        TimeoutError("Wrong Pincode or Country Code")
    

