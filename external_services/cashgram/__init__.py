import logging  
from saleor.utilities.api_client import ApiClient
from django.db.models import Sum
from .constants import AUTH_TOKEN_URI , AUTH_TOKEN_HEADER , CASHGRAM_CREATE_URI,CASHGRAM_CREATE_HEADER,CASHGRAM_STATUS_URI,CASHGRAM_STATUS_HEADER
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities
from django.conf import settings
from saleor.order.models import OrderLineCashgram
import re

def get_auth_token():

    auth_token_url = AUTH_TOKEN_URI
    api_client = ApiClient(url=auth_token_url)
    api_client.headers = AUTH_TOKEN_HEADER
    api_client.post()
    api_response = api_client.fetch_response()
    token = None
    if api_response:
        status = api_response.get('status')
        if status == "SUCCESS":
            token = api_response.get('data').get('token')

    return token

def post_data_cashgram_creation(orderline):

    email = ""
    phone_num = ""
    name = ""
    amount = orderline.unit_price_net_amount * orderline.quantity
    order = orderline.order
    brand_id = orderline.brand_id
    orderlines_brand = order.lines.filter(brand_id = brand_id)
    total_shipping = orderlines_brand.aggregate(total_shipping = Sum('shipping_cost_amount'))['total_shipping']
    lines = orderlines_brand.values_list('id',flat=True)
    count_lines = lines.count()
    cancelled_lines = OrderLineCashgram.objects.filter(orderline_id__in=lines).count()
    count_lines-=1
    if count_lines == cancelled_lines:
        amount += total_shipping
    discounted_amount =  NumberUtilities.convert_string_to_decimal(orderline.metadata.get('discount_amount'))
    amount = amount - discounted_amount
    order = orderline.order
    user = order.user
    if user:
        phone_num = user.mobile_no
        phone_num = phone_num[2:]
        name = user.first_name
    if order:
        address = order.shipping_address
        name = address.first_name
        email = order.user_email
        if not name:
            name = email.split('@')[0]

        name = re.sub(r'[^a-zA-Z]','',name)    

    expiry_days = NumberUtilities.convert_string_to_number(settings.CASHGRAM_EXPIRY_DAYS)
    todays_date = TimeUtilities.add_time_in_timestamp(TimeUtilities.get_current_date(False),expiry_days)
    expiry_date = TimeUtilities.parse_date(todays_date,"%Y-%m-%d")
    data = {
        "cashgramId": StringUtilities.convert_object_to_string(orderline.id),
        "amount": StringUtilities.convert_number_to_string(amount),
        "name": name,
        "email": email,
        "phone": phone_num,
        "linkExpiry":expiry_date,
        "remarks": "sample cashgram",
        "notifyCustomer": 1
    }
    return data

def create_cashgram_and_send_link(orderline,post_data):

    token = get_auth_token()
    cashgram_create = CASHGRAM_CREATE_URI
    api_client = ApiClient(url=cashgram_create)
    CASHGRAM_CREATE_HEADER["Authorization"] = "Bearer {}".format(token)
    api_client.headers = CASHGRAM_CREATE_HEADER
    api_client.body = post_data
    api_client.post()
    api_response = api_client.fetch_response()
    if api_response:
        return api_response
    else:
        return {}



def get_status_cashgram(orderline_id):

    orderline_id = StringUtilities.convert_number_to_string(orderline_id)
    token = get_auth_token()
    cashgram_status_url = CASHGRAM_STATUS_URI+orderline_id
    CASHGRAM_STATUS_HEADER["Authorization"] = "Bearer {}".format(token)
    api_client = ApiClient(url=cashgram_status_url)
    api_client.headers = CASHGRAM_STATUS_HEADER
    api_client.get()
    api_response = api_client.fetch_response()

    return api_response



