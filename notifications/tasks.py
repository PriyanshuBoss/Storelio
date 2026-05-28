from saleor.celeryconf import app
import logging
from django.conf import settings

from saleor.utilities.string_utilities import StringUtilities

logger = logging.getLogger(__name__)

def notify_user_sync(fcm_id_list, title, body,
                    onclick_action=None, path=None, expiry_timestamp=None,
                     ios_user=None, n_id=None, media=None, is_persistent=False):

        
    
    if not fcm_id_list:
        logger.warn("FCM id not present for %s , %s" % (title, body))

    
    data = {
        'id': StringUtilities.convert_number_to_string(n_id),
        'body': body,
        'title': title,
        'onclick_action': '' if onclick_action is None else onclick_action,
        'path': {} if path is None else path,
        'expiry_timestamp':  '' if expiry_timestamp is None else expiry_timestamp,
        'is_persistent': StringUtilities.convert_number_to_string(is_persistent)
    }
    if media:
        data.update(media)

    
    
    try:
        from saleor.notifications.fcm import FCM
        fcm = FCM()
        for fcm_id in fcm_id_list:
            
            try:
                result = fcm.make_request(fcm_id, data=data, ios_user=ios_user)

            except Exception as e:
                logger.debug(e)
                pass       

    except Exception:
        logger.exception("Unable to send the notifications")
        return False
    return True



@app.task(queue='priority_queue')
def send_app_notification(fcm_id_list, title, body,
                    onclick_action=None,  path=None, expiry_timestamp=None,
                     ios_user=None, n_id=None, media=None, is_persistent=False):

    notify_user_sync(fcm_id_list, title, body,
                onclick_action=onclick_action,  path=path, expiry_timestamp=expiry_timestamp,
                ios_user=ios_user,n_id=n_id,
                media=media, is_persistent=is_persistent)

    

"""
Notification Tasks Defined  for Event Based Notifications
"""

@app.task(queue='periodic_queue')
def send_notification_coupon_expiry_24():

    from saleor.discount.tasks import notification_coupon_expiry_last_24

    return notification_coupon_expiry_last_24()

@app.task(queue='periodic_queue')
def send_notification_coupon_expiry_12():

    from saleor.discount.tasks import notification_coupon_expiry_last_12

    return notification_coupon_expiry_last_12()

@app.task(queue='periodic_queue')
def send_abandoned_cart_notification_guest_user():

    from saleor.checkout.utils import notification_abandoned_cart_guest_user
    
    return notification_abandoned_cart_guest_user()

@app.task(queue='periodic_queue')
def send_abandoned_cart_notification_logged_in():

    from saleor.checkout.utils import notification_abandoned_cart_logged_in
    
    return notification_abandoned_cart_logged_in()

@app.task(queue='priority_queue')
def send_notification_fulfillment_note(fulfillment_line):
    from saleor.order.utils import notification_fulfillment_note
    return notification_fulfillment_note(fulfillment_line)

@app.task(queue='priority_queue')
def send_notification_brand_interested_in_me(brand_source_request_ids):
    from saleor.store.store_utilities import notification_brand_interested
    return notification_brand_interested(brand_source_request_ids)
