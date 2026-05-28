from django.conf import settings
from django.core.exceptions import ValidationError
from saleor.notifications import fcm
import logging
from saleor.notifications.states import MediaType, TemplateType,DeviceType
from saleor.utilities.time_utilities import TimeUtilities

def media_file_path(
    instance,
    filename,
    file_type_choices_dict=None,
    file_type_identifier="message_type",
    media_folder_name="app_notifications_files",
):
    """
    Provide a file path that will help prevent files being overwritten
    """
    today = TimeUtilities().get_today_start()
    if file_type_choices_dict:
        media_type_mapping = file_type_choices_dict
    else:
        media_type_mapping = {x[0]: (x[1]).lower() for x in MediaType.Choices}
    media_type = media_type_mapping.get(getattr(instance, file_type_identifier))

    path = "%s/%s/%s/%s/" % (media_folder_name, media_type, today.year, today.month)

    return path + filename


def media_file_extension_validator(value, valid_extensions_file=tuple()):
    if not valid_extensions_file:
        valid_extensions_file = ("jpg", "jpeg", "png", "mp4", "avi", "mov", "pdf")
    if value:
        file_name = value.name
        file_extension = file_name.split(".")[-1].lower()
        if file_extension in valid_extensions_file:
            if value.size > int(settings.MAX_UPLOAD_SIZE):
                raise ValidationError("Please keep the file size under 10 MB")
        else:
            raise ValidationError(
                "Valid File formats - {}".format(str(valid_extensions_file))
            )
    else:
        return True


def send_campaign_notifications(context_variables=None,type = TemplateType.CAMPAIGN_BASED,event_code=None):
    
    from saleor.notifications.models import EventRule
    from saleor.account.models import User
    try:
        rule = EventRule.objects.get(code = event_code)
    except:
        return False
    
    if not context_variables:
        context_variables = {}
    inf_users = User.objects.filter(store_members__isnull=False).exclude(staff_store_mappings__isnull=False).distinct()
    users = User.objects.filter(is_active=True).exclude(id__in=inf_users)
    app_notification_data = rule.app_notification_template.get_app_notification_data(
        context_variables = context_variables)
    push_app_notification_to_all_users(users, app_notification_data)
    
    return True

def send_notifications(users, context_variables=None, type=TemplateType.EVENT_BASED, event_code=None):
    """
        will send the push notifications for list of users.

        :param type: if the notification is event based or campaign based.
        :param event_code: event code if type is event based.
        :param context_variables is dictionary of dictionaries per user with key as user primery key
        and values as dictionary of context values for that user.

        :return: Notify the users with message

    """

    from saleor.notifications.models import EventRule
    if not context_variables:
        context_variables = {}
    
    if type ==  TemplateType.EVENT_BASED:
        try:
            rule = EventRule.objects.get(code=event_code)
        except:
            return False
    
    for user in users:
        app_notification_data = rule.app_notification_template.get_app_notification_data(
            context_variables = context_variables.get(user.id, {}) or context_variables.get(str(user.id), {}))
        user.push_app_notification(app_notification_data)
        
    return True


def send_notification_to_device(users,devices=[], context_variables=None, type=TemplateType.EVENT_BASED, event_code=None):
    """
        will send the push notifications for list of users.

        :param type: if the notification is event based or campaign based.
        :param event_code: event code if type is event based.
        :param context_variables is dictionary of dictionaries per user with key as user primery key
        and values as dictionary of context values for that user.

        :return: Notify the users with message

    """
    # add implementation for notification to specific device
    from saleor.notifications.models import EventRule
    if not context_variables:
        context_variables = {}
    
    if type ==  TemplateType.EVENT_BASED:
        try:
            rule = EventRule.objects.get(code=event_code)
        except:
            return False
    

    for user in users:
        app_notification_data = rule.app_notification_template.get_app_notification_data(
            context_variables = context_variables.get(user.id, {}) or context_variables.get(str(user.id), {}))
        user.push_app_notification(app_notification_data,devices=devices)

        
    return True



def push_app_notification_to_all_users(users, data):
        """
        We will send the push notifications for APP.

        :param data: Data dict for app notifiation.
        :return: Notify the user with message
        """

        title = data.get('title')
        body = data.get('body')
        onclick_action = data.get('onclick_action')
        path = data.get('path', '')
        expiry_timestamp = data.get('expiry_timestamp')
        is_persistent = data.get('is_persistent')
        media = data.get('media')

        fcm_android_list = []
        fcm_ios_list = []

        for user in users:
            user_android_fcm_list = list(user.devices.filter(
                is_active=True, device_type=DeviceType.ANDROID
            ).values_list('fcm_id', flat=True))

            fcm_android_list.extend(user_android_fcm_list)

            user_ios_fcm_list = list(user.devices.filter(
                is_active=True, device_type=DeviceType.IOS).values_list('fcm_id', flat=True))
            
            fcm_ios_list.extend(user_ios_fcm_list)
        
        data['expiry_timestamp'] = TimeUtilities.parse_date(expiry_timestamp, "%Y-%m-%d, %H:%M:%S")
        
        expiry_timestamp = data['expiry_timestamp']

        print(fcm_android_list)
        print(fcm_ios_list)
        if fcm_android_list:
            fcm.notify_user(
                fcm_id_list=fcm_android_list, title=title, body=body,
                expiry_timestamp=expiry_timestamp, onclick_action=onclick_action, path=path,
                media=media, ios_user= False, is_persistent=is_persistent
            )

        if fcm_ios_list:
            fcm.notify_user(
                fcm_id_list=fcm_ios_list, title=title, body=body,
                expiry_timestamp=expiry_timestamp, onclick_action=onclick_action,
                media=media, ios_user=True, is_persistent=is_persistent
            )