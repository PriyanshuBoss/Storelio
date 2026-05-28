from graphene import relay
from saleor.graphql.core.connection import CountableDjangoObjectType
from saleor.support import models

class SupportQuery(CountableDjangoObjectType):

    class Meta:
        description = "support queries"
        model = models.SupportQueries
        interfaces = [relay.Node]
        exclude = ()

class Meetup(CountableDjangoObjectType):

    class Meta:
        description = "meetups"
        model = models.Meetup
        interfaces = [relay.Node]
        exclude = ()


class FreshDeskTickets(CountableDjangoObjectType):

    class Meta:
        description = "meetups"
        model = models.FreshDeskTickets
        interfaces = [relay.Node]
        exclude = ()

