import graphene
from saleor.graphql.core.fields import FilterInputConnectionField
from saleor.graphql.notifications.filters import NotifyAppUpdateInput
from saleor.graphql.notifications.mutations import DeviceCreateOrUpdate, PushAppNotification,AttachDevicewithUser,PushCampaignNotification,PushAbandonedCartNotification
from saleor.graphql.notifications.resolvers import resolve_my_notifications, resolve_notify_app_updates, resolve_device
from saleor.graphql.notifications.types import Notifications, NotifyAppUpdate,Device


class NotificationsQueries(graphene.ObjectType):
    my_notifications = FilterInputConnectionField(
        Notifications,
        description="List of logged in user's notifications "
    )

    notify_app_updates = FilterInputConnectionField(
        NotifyAppUpdate,
        filter=NotifyAppUpdateInput(description="Filtering options for app update."),
        description="app updates pop display"
    )

    get_device = graphene.Field(Device,
        device_id=graphene.Argument(graphene.String, description=" Device unique ID .", required=True),
        description="Look up by Device id.",
    )

    def resolve_my_notifications(self, info,  **kwargs):
        
        return resolve_my_notifications(info,  **kwargs)

    def resolve_notify_app_updates(self, info,  **kwargs):
        
        return resolve_notify_app_updates(info,  **kwargs)

    def resolve_get_device(self,info,device_id):

        return resolve_device(info,device_id)


class NotificationMutations(graphene.ObjectType):
    device_create_or_update = DeviceCreateOrUpdate.Field()
    attach_device_with_user = AttachDevicewithUser.Field()
    push_app_notifiation = PushAppNotification.Field()
    push_campaign_notification = PushCampaignNotification.Field()
    push_abandoned_cart_notification = PushAbandonedCartNotification.Field()
