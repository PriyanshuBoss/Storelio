import graphene
from saleor.graphql.support.filters import SupportQueryFilterInput
from saleor.graphql.support.mutation import  SupportQueryCreate, EmailSending, MeetupCreate, MeetupUpdate, MeetupDelete,WhatsappNotificationTriggerMutation
from saleor.graphql.support.sorter import SupportQuerySortingInput, MeetupSortingInput
from saleor.graphql.support.types import SupportQuery, Meetup
from ..core.fields import FilterInputConnectionField, PrefetchingConnectionField


class SupportQueries(graphene.ObjectType):
    support_queries = FilterInputConnectionField(
        SupportQuery,
        filter=SupportQueryFilterInput(description="Filtering options support queries"),
        sort_by=SupportQuerySortingInput(description="Sort Support Queries."),
        description="List of support queries"
    )

    meetups = FilterInputConnectionField(
        Meetup, description = "List of meetups",
        sort_by=MeetupSortingInput(description="Sort Meetups.")
    )

class SupportMutations(graphene.ObjectType):
    support_query_create = SupportQueryCreate.Field()
    meetup_create = MeetupCreate.Field()
    meetup_update = MeetupUpdate.Field()
    meetup_delete = MeetupDelete.Field()
    notification_trigger = WhatsappNotificationTriggerMutation.Field()

class EmailSendingMutations(graphene.ObjectType):
    email_sending = EmailSending.Field()
