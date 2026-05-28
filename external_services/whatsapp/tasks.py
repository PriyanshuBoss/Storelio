from saleor.celeryconf import app
from saleor.settings import IS_BETA
from .constants import COUPONS
from .whatsapp_impl import create_trait_for_event_new_order,create_trait_for_zaamo_influencer_request,create_trait_for_zaamo_brand_interest,create_trait_for_abandoned_cart, create_trait_for_campus_influencer,create_trait_for_fulfillment_note,create_trait_for_order_refund
from saleor.checkout.models import Checkout
from saleor.order.models import Order
import logging
from saleor.utilities.time_utilities import TimeUtilities

logger = logging.getLogger(__name__)

@app.task
def order_placing_whatsapp_notification(order_id):
    success = create_trait_for_event_new_order(order_id)
    return success

@app.task
def product_sourcing_whatsapp_notification(product_sourcing_id,content):
    success = create_trait_for_zaamo_influencer_request(product_sourcing_id,content)
    return success

@app.task
def brand_sourcing_whatsapp_notification(brand_sourcing_id):
    success = create_trait_for_zaamo_brand_interest(brand_sourcing_id)
    return success

def abandonded_cart_message():
    last_24_hr = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),1)
    user_ids = Checkout.objects.filter(checkoutstore__store__slug = 'zaamo' , last_change__gte = last_24_hr, lines__isnull=False).values_list('user_id',flat=True).distinct('user_id').order_by('user_id')
    user_ids = set(user_ids)
    for coupon in COUPONS:
        exclude_users = set(Order.objects.filter(user_id__in=user_ids).filter(voucher__code=coupon.get('code')).values_list('user_id', flat=True))
        message_users = user_ids.difference(exclude_users)
        for user_id in message_users:
            success = create_trait_for_abandoned_cart(user_id, coupon)
        
        user_ids.difference_update(message_users)

@app.task
def campus_influencer_notification(user_id, store_name):
    success = create_trait_for_campus_influencer(user_id, store_name)
    return success

@app.task
def send_whatsapp_fulfillment_note(fulfillment_line_id):
    success = create_trait_for_fulfillment_note(fulfillment_line_id)
    return success

@app.task
def send_whatsapp_order_refund(data):
    success = create_trait_for_order_refund(data)
    return success

@app.task(queue='celery_periodic')
def sending_periodic_notification_abandoned_cart():
    
    if IS_BETA:
        return
        
    try:
        abandonded_cart_message()
        
    except Exception as e:
        logger.exception(f'Whatsapp Notification for Abandoned Cart failed with an error {e}')
