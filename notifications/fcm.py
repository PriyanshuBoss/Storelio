from django.conf import settings
import logging
from google.oauth2.service_account import Credentials

from saleor.notifications.tasks import notify_user_sync, send_app_notification
from saleor.utilities.api_client import ApiClient
import firebase_admin
from firebase_admin import credentials
import firebase_admin.messaging as messaging


logger = logging.getLogger(__name__)

cred = credentials.Certificate(settings.FCM_CREDENTIALS_FILE)
default_app = firebase_admin.initialize_app(cred)


class FCM(object):

        
    def make_request(self, to , data=None, ios_user=None):
        

        data = {
                'id': data.get('id', ''), 'title': data.get('title', ''), 
                'body': data.get('body', ''), 'image': data.get('image', ''),
                'onclick_action': data.get('onclick_action', ''), 
                'path': data.get('path', {}).get('screen_name', ''), 
                'path_data': data.get('path', {}).get('path_data', ''),
                'expiry_timestamp': data.get('expiry_timestamp', ''),
                'gif': data.get('gif', ''), 'video_link' : data.get('video_link', '')
            }
        
        for key in data:
            if not data.get(key):
                data[key] = ""
        
        notification = {'title': data.get('title', ''), 'body': data.get('body', ''), 'image': data.get('image', '')}

        android =   {
                        "priority": "high",
                        "notification": messaging.AndroidNotification(** {
                            'title': data.get('title', ''), 'body': data.get('body', ''), 
                            'image': data.get('image', '')}
                            ),
                        "data": {'title': data.get('title', ''), 'body': data.get('body', '')}
                    }
        
        if ios_user:
            apns = {
                'payload' : messaging.APNSPayload(** {'aps': messaging.Aps(** {
                    "alert" : messaging.ApsAlert(**{
                        'title': data.get('title'),
                        'body': data.get('body'),
                        })
                    })
                })
            }

        else:
            apns = {}


        message = messaging.Message(
                token=to,
                data=data,
                notification=messaging.Notification(**notification),
                android=messaging.AndroidConfig(**android),
                apns=messaging.APNSConfig(**apns)
                )

        response = messaging.send(message)

        return response


def notify_user(fcm_id_list, title, body,  n_id=None, onclick_action=None, path=None, media=None,
                expiry_timestamp=None, ios_user=None, is_persistent=False):
    """
    :param media: media dict with details of image, video, gif etc.
    :param fcm_id:
    :param title: title to display
    :param body: Description of the message
    :param onclick_action: What action will be on the message
    :param n_id: Notification Id
    :return: Notify The User Using Asynchronous task
    """
    
    if fcm_id_list:
        if settings.DEBUG:
            notify_user_sync(
                fcm_id_list, title, body,
                onclick_action=onclick_action, path=path, expiry_timestamp=expiry_timestamp,
                ios_user=ios_user,n_id=n_id,
                media=media, is_persistent=is_persistent)
        else:
            send_app_notification.delay(
                fcm_id_list, title, body,
                onclick_action=onclick_action, path=path, expiry_timestamp=expiry_timestamp,
                ios_user=ios_user,n_id=n_id,
                media=media, is_persistent=is_persistent)
