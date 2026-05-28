from saleor.notifications.models import Notification, NotifyAppUpdate,Device
from saleor.utilities.time_utilities import TimeUtilities


def resolve_my_notifications(info,  **kwargs):
    user = info.context.user

    return Notification.objects.filter(
        recipient=user, 
        expiry_timestamp__gt=TimeUtilities.get_current_date_time()
    )

def resolve_notify_app_updates(info, **kwargs):
    return  NotifyAppUpdate.objects.all()

def resolve_device(info,device_id):

    return Device.objects.filter(device_id = device_id).first()
