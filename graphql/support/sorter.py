import graphene
from ..core.types import SortInputObjectType
from django.db.models import QuerySet

class SupportQuerySortField(graphene.Enum):
    UPDATED_AT  = ["updated_at"]
    CREATED_AT = ["created_at"]
    


    @property
    def description(self):
        if self.name in SupportQuerySortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort support query by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    
class SupportQuerySortingInput(SortInputObjectType):
    class Meta:
        sort_enum = SupportQuerySortField
        type_name = "SupportQuery"

class MeetupSortField(graphene.Enum):
    CREATED_AT = ["created_at"]
    


    @property
    def description(self):
        if self.name in MeetupSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort support query by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    
class MeetupSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = MeetupSortField
        type_name = "Meetup"

