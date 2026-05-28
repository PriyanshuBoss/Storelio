from django.core.exceptions import ValidationError
import graphene

from saleor.graphql.utils import get_nodes
from saleor.notifications.states import TemplateType
from saleor.notifications.utils import send_notifications,send_campaign_notifications
from saleor.checkout.utils import notification_abandoned_cart_guest_user,notification_abandoned_cart_logged_in
from saleor.utilities.number_utilities import NumberUtilities
from ..core.mutations import BaseMutation
import logging
from saleor.notifications import models
from saleor.graphql.notifications.types import Device
from saleor.utilities.time_utilities import TimeUtilities
from saleor.notifications.enums import DeviceTypeEnums
from saleor.account import models as account_models
from django.conf import settings

logger = logging.getLogger(__name__)


class DeviceCreateUpdateInput(graphene.InputObjectType):
    app_version = graphene.String(description="The customer's email address.", required=False)
    fcm_id = graphene.String(description="Device id of user (fcm id)")
    model = graphene.String(description="Model of the device the app is installed on", required=False)
    manufacturer = graphene.String(description="Device manufacturer", required=False)
    os_version = graphene.String(description="OS version of the device", required=False)

    device_type = DeviceTypeEnums(description="device type like: ios, android or web")

    is_active = graphene.Boolean(description="active status of device", required=False)

    app_installed_at = graphene.types.datetime.DateTime(
        description="Datetime at which device was installed", required=False
    )
    app_uninstalled_at = graphene.types.datetime.DateTime(
        description="datetime at which app was uninstalled", required=False
    )
    app_last_launched_at = graphene.types.datetime.DateTime(
        description="app last launched at datetime ", required=False
    )
    device_id = graphene.String(description = "Device id of the user which is unique",required = True)
    user_id = graphene.Int(description = "User id",required = True)

class DeviceCreateOrUpdate(BaseMutation):
    device = graphene.Field(Device, description='device of the user')

    class Arguments:
        input = DeviceCreateUpdateInput(
            required=True, description="Fields required to create or update device for a user"
        )

    class Meta:
        description = "Create or  update device."
        return_field_name = "Device"
        
    @classmethod
    def get_guest_user_for_notification(cls, user_id):
        """returns the user to be associated with notification"""  
        user_instance = account_models.User.objects.get(email=settings.GUEST_NOTIFICATION_USER)
            
        return user_instance.id


    @classmethod
    def perform_mutation(cls, root, info, **data):
        
        data = data.get('input', {})
        device_type = data.get("device_type")
        device_id = data.get("device_id")
        user_id = data.get("user_id")
        app_last_launched_at = data.pop("is_last_launched", None)
        
        if not user_id or NumberUtilities.convert_string_to_number(user_id) in (1881,203):
            user_id = cls.get_guest_user_for_notification(user_id)
        
        if app_last_launched_at:
            data["app_last_launched_at"] = TimeUtilities.get_current_date_time()
        try:
            if models.Device.objects.filter(device_id = device_id).exists():
                device = models.Device.objects.filter(device_id = device_id).first()
            else:
                device = models.Device.objects.create(user_id = user_id , device_id = device_id)

            for key , value in data.items():
                if hasattr(device, key) and value:
                    setattr(device, key, value)
            device.save()

            
        except:
            logger.exception("Not able to create device id for user: %s with the following data: %s", user_id, data)
            device = None

        return DeviceCreateOrUpdate(device=device)

class AttachDevicewithUserInput(graphene.InputObjectType):
    user_id = graphene.ID(description = "User id which needs to be attached")
    device_id = graphene.String(description = "Device with which user needs to be attached")


class AttachDevicewithUser(BaseMutation):
    device = graphene.Field(Device, description='device of the user')
    class Arguments:
        input = AttachDevicewithUserInput(
            required = True , description = "Fields required to Attach user with device"
        )

    class Meta:
        description = "ATTACH USER WITH DEVICE ."
        return_field_name = "Device"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        
        glob_user_id = data.get('input').get('user_id')
        user_id = graphene.Node.from_global_id(glob_user_id)[1]
        device_id =  data.get('input').get('device_id')
        device_instance = models.Device.objects.filter(device_id = device_id).first()

        if device_instance:
            device_instance.user_id = user_id
            device_instance.save()

        return AttachDevicewithUser(device = device_instance)

class PushAppNotificationInput(graphene.InputObjectType):
    users = graphene.List(graphene.ID, description='list of user to whom we are sending app notification.', required=True,)
    event_code = graphene.String(description='event for which you want to send app notification.', required=True)
    context_variables = graphene.JSONString(description='Context variables for (template data, title, path)', required=False)

class PushAppNotification(BaseMutation):
    success = graphene.Boolean(description='returns true if successfully sent app notification')
    class Arguments:
            input = PushAppNotificationInput(
                required=True, description="Fields required to PUSH App Notifiation"
            )

    class Meta:
        description = "PUSH APP NOTIfICATION."
        return_field_name = "PushAppNotification"
        
    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data.get('input')

        users = get_nodes(input['users'], "User", account_models.User)

        event_code = input.get('event_code')
        
        context_variables = input.get('context_variables')
        status = send_notifications(users, type=TemplateType.EVENT_BASED, 
                        context_variables=context_variables,
                        event_code=event_code
                    )

        return PushAppNotification(success=status)

class PushCampaignNotificationInput(graphene.InputObjectType):

    event_code = graphene.String(description='event for which you want to send app notification.', required=True)
    context_variables = graphene.JSONString(description='Context variables for (template data, title, path)', required=False)


class PushCampaignNotification(BaseMutation):
    success = graphene.Boolean(description='returns true if successfully sent app notification')
    class Arguments:
            input = PushCampaignNotificationInput(
                required=True, description="Fields required to CAMPAIGN App Notifiation"
            )

    class Meta:
        description = "PUSH CAMPAIGN NOTIfICATION."
        return_field_name = "PushCampaignNotification"
        
    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data.get('input')

        event_code = input.get('event_code')

        context_variables = input.get('context_variables')
        status = send_campaign_notifications(context_variables=context_variables,type=TemplateType.CAMPAIGN_BASED,
                        event_code=event_code
                    )

        return PushCampaignNotification(success=status)

class PushAbandonedCartNotificationInput(graphene.InputObjectType):

    event_code = graphene.String(description='event for which you want to send app notification.', required=True)

class PushAbandonedCartNotification(BaseMutation):
    success = graphene.Boolean(description='returns true if successfully sent app notification')
    class Arguments:
            input = PushAbandonedCartNotificationInput(
                required=True, description="Fields required to do Abandoned Cart Notification"
            )

    class Meta:
        description = "PUSH ABANDONED CART NOTIFICATION."
        return_field_name = "PushAbandonedCartNotification"
        
    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data.get('input')

        event_code = input.get('event_code')
        status = notification_abandoned_cart_guest_user()
        status = notification_abandoned_cart_logged_in()

        return PushAbandonedCartNotification(success=status)