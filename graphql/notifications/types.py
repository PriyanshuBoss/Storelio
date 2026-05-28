from ..core.connection import CountableDjangoObjectType
from graphene_federation import key
from graphene import relay 


from saleor.notifications import models



@key(fields="id")
class Device(CountableDjangoObjectType):

    class Meta:
        description = "Device details"
        model = models.Device
        interfaces = [relay.Node]
        exclude = ()


@key(fields="id")
class Notifications(CountableDjangoObjectType):

    class Meta:
        description = "Notifications details"
        model = models.Notification
        interfaces = [relay.Node]

@key(fields="id")
class NotifyAppUpdate(CountableDjangoObjectType):

    class Meta:
        description = "notify app update"
        model = models.NotifyAppUpdate
        interfaces = [relay.Node]
        exclude = ()
