from saleor.account.models import User
from saleor.order.models import FulfillmentLine, Order
from saleor.store.models import BrandSourcingRequest, StoreInfo
from saleor.product.models import SourcingRequest
from saleor.brand.states import BrandMobileTypes
from saleor.checkout.models import CheckoutLine
from saleor.utilities.time_utilities import TimeUtilities
from django.db.models import Sum
from django.db.models.functions import Coalesce
import logging  
import json
import base64
from .constants import USER_TRACK_URI,USER_TRACK_HEADERS,EVENT_TRACK_URI
from saleor.utilities.api_client import ApiClient
from saleor.utilities.string_utilities import StringUtilities

logger = logging.getLogger(__name__)

def construct_body_to_add_user_whatsapp(user_id=None,mobile_no=None,tags=None):

    if user_id:
        user = User.objects.filter(id = user_id).first()

        post_data = {
        "fullPhoneNumber": user.mobile_no,
        "countryCode": "+91",
        "traits":{
            'name':user.get_full_name(),
            'email':user.email
        },
        "tags": tags
        }
    else:

        post_data = {
        "fullPhoneNumber": mobile_no,
        "countryCode": "+91",
        "tags": tags
        }

    user_track_url = USER_TRACK_URI
    user_track_body = post_data
    api_client = ApiClient(url=user_track_url)
    api_client.headers = USER_TRACK_HEADERS
    api_client.body = user_track_body
    api_client.post()
    api_response = api_client.fetch_response()
    response_code = api_client.fetch_response_code()
    if api_response:
        return api_response

def create_trait_for_event_new_order(order_id):
    order = Order.objects.filter(pk=order_id).first()
    if order:
        user = order.user
        if user:
            user_id = user.id
            construct_body_to_add_user_whatsapp(user_id = user_id,tags=['new_order'])
            address = order.shipping_address
            lines = order.get_order_items_details()
            traits = {}
            name = user.first_name
            if not name and address:
                name = address.first_name
            products_list = ''
            for line in lines:
                products_list = products_list + line.get('product_name') + ', '

            traits['user_name'] = name
            traits['products_list'] = products_list[:-2]

            event_body = {
                'traits':traits,
                'event_name':'New Order Placed'
            }
            return construct_body_to_add_event_for_user(event_body,user.mobile_no)
    else:
        raise ValueError("Order Id doesn't exist")

def create_trait_for_abandoned_cart(user_id, coupon):
    last_24_hr = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),1)
    checkout_lines = CheckoutLine.objects.filter(checkout__user_id = user_id,checkout__last_change__gte = last_24_hr,checkout__checkoutstore__store__slug = 'zaamo').annotate(total_pdp_views=Coalesce(Sum('variant__product__storeproductviews__views', distinct=True),0)).order_by('-total_pdp_views')
    if checkout_lines:
        checkout_lines = checkout_lines[:10]
        checkout = checkout_lines[0].checkout
        address = checkout.shipping_address
        user = checkout.user
        if user:
            name = user.first_name
            if not name and address:
                name = address.first_name
            mobile_num = user.mobile_no
            mobile_num = mobile_num[2:]
            encoded_num = base64.b64encode(str.encode(mobile_num)).decode("utf-8")
            if not name:
                name = checkout.email
            construct_body_to_add_user_whatsapp(user_id = user_id,tags=['abandoned_cart'])
            lines = checkout.lines.all()
            traits = {}
            products = []
            zaamo_link = encoded_num
            i=1
            first_prod = None
            for line in checkout_lines:
                variant = line.variant
                product = variant.product
                product_name = product.name
                products.append(f"{i}. {product_name}")
                i+=1
                if not first_prod:
                    first_prod = product
            
            traits['name'] = name
            traits["media_url"] = first_prod.get_product_url()
            traits["order_details"] = '\\n  '.join(products) 
            traits['discount_amount'] = coupon.get('amount')
            traits['voucher_code'] = coupon.get('code')
            traits['zaamo_link'] = zaamo_link
            event_body = {
                'traits':traits,
                'event_name':'Abondoned Cart Download'
            }
            return construct_body_to_add_event_for_user(event_body,user.mobile_no)
    else:
        logger.info("Checkout is not available")

def create_trait_for_zaamo_brand_interest(brand_sourcing_id):

    sourcing_req = BrandSourcingRequest.objects.filter(id = brand_sourcing_id).select_related('brand','store').first()
    
    if sourcing_req:
        store_instance  = sourcing_req.store
        brand = sourcing_req.brand
        brand_name = brand.brand_name
        store_name = store_instance.store_name
        store_member_state = store_instance.store_members.select_related("user").first()
        if store_member_state:
            user = store_member_state.user
            construct_body_to_add_user_whatsapp(user_id = user.id,tags=['zaamo_inf_brand_interested'])
            traits = {}

            traits['store_name'] = store_name
            traits['brand_name'] = brand_name

            event_body = {
                    'traits':traits,
                    'event_name':'Zaamo Influencer Brand Interested'
                }

            sourcing_req.notification = True
            sourcing_req.save()

            return construct_body_to_add_event_for_user(event_body,user.mobile_no)
    else:
        raise ValueError("Brand Sourcing Id doesn't exist")

def create_trait_for_zaamo_influencer_request(prod_sourcing_id,content):

    prod_sourcing_req = SourcingRequest.objects.filter(id=prod_sourcing_id).select_related('brand','store').first()
    if prod_sourcing_req:
        store_instance = prod_sourcing_req.store
        store_name = store_instance.store_name
        store_staff_member = store_instance.staff_members.first()
        inf_mobile_no = ""
        zaamo_link = "https://brands.zaamo.co/sourcing/eval/"+store_instance.slug
        sourcing_content = content
        if store_staff_member:
            inf_mobile_no = store_staff_member.mobile_no[2:]

        traits = {}
        brand = prod_sourcing_req.brand
        brand_name = brand.brand_name
        brand_mobile = brand.mobiles.filter(type=BrandMobileTypes.PRIMARY).first()

        if brand_mobile:
            brand_mobile_no = brand_mobile.mobile_no
            brand_mobile_no = brand_mobile_no[-10:]
            brand_mobile_no = '91'+brand_mobile_no
            construct_body_to_add_user_whatsapp(mobile_no=brand_mobile_no,tags=['zaamo_inf_interested'])
            traits['brand_name'] = brand_name
            traits['store_name'] = store_name
            traits['influencer_no'] = inf_mobile_no
            traits['sourcing_content'] = sourcing_content
            traits['zaamo_link'] = zaamo_link

            event_body = {
                    'traits':traits,
                    'event_name':'Zaamo Influencer Interested in Brand'
                }
            
            prod_sourcing_req.notification = True
            prod_sourcing_req.save()

            return construct_body_to_add_event_for_user(event_body,brand_mobile_no)
    else:
        raise ValueError("Product Sourcing Id doesn't exist")

def create_trait_for_campus_influencer(user_id, store_name):


    user = User.objects.filter(id=user_id).first()
    
    if user:
        construct_body_to_add_user_whatsapp(user_id=user.id,tags=['campus_influencer'])
        traits = {}
        traits['store_name'] = store_name
        event_body = {
            'traits':traits,
            'event_name':'Zaamo Campus Influencer'
        }

        return construct_body_to_add_event_for_user(event_body,user.mobile_no)

def create_trait_for_fulfillment_note(fulfillment_line_id):

    try:
        fulfillment_line = FulfillmentLine.objects.filter(id=fulfillment_line_id).first()
        
        if not fulfillment_line:
            return False

        user = fulfillment_line.order_line.order.user
        product = fulfillment_line.order_line.variant.product
        product_name = product.name
        brand_name = product.brand.brand_name
        order_note = fulfillment_line.note

        if user:
            construct_body_to_add_user_whatsapp(user_id=user.id,tags=['fulfillment_note'])
            traits = {}
            traits['product_name'] = product_name
            traits['brand_name'] = brand_name
            traits['order_note'] = order_note
            event_body = {
                'traits':traits,
                'event_name':'Zaamo Order Fulfillment Note'
            }

            return construct_body_to_add_event_for_user(event_body,user.mobile_no)
    except:
        return False

def create_trait_for_order_refund(data: dict):
    if data:
        construct_body_to_add_user_whatsapp(user_id=data['user_id'],tags=['order_refund'])
        traits = {}
        traits['order_id'] = data['order_id']
        traits['brand_name'] = data['brand_name']
        traits['cashgram_link'] = data['cashgram_link']
        traits['support_email'] = 'customersupport@zaamo.co'
        event_body = {
            'traits': traits,
            'event_name': 'order_refund'
        }

        return construct_body_to_add_event_for_user(event_body, data['user_mobile'])

def construct_body_to_add_event_for_user(event_body,mobile_no):

    post_data = {
    "fullPhoneNumber":mobile_no,
    "countryCode": "+91",
    "event": event_body.get('event_name'),
    "traits": event_body.get('traits')
    }
    logger.info(f"Requesting Whatsapp Notification data :: {post_data}")
    user_track_url = EVENT_TRACK_URI
    user_track_body = post_data
    api_client = ApiClient(url=user_track_url)
    api_client.headers = USER_TRACK_HEADERS
    api_client.body = user_track_body
    api_client.post()
    api_response = api_client.fetch_response()
    response_code = api_client.fetch_response_code()

    logger.info(f"Response of Whatsapp Notification is :: {api_response} with response code {response_code}")
    if api_response:
        if api_response.get('result') == True:
            return True
        else:
            return False


