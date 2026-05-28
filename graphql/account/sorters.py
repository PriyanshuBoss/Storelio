import graphene
from django.db.models import Count, QuerySet

from ..core.types import SortInputObjectType


class UserSortField(graphene.Enum):
    FIRST_NAME = ["first_name", "last_name", "pk"]
    LAST_NAME = ["last_name", "first_name", "pk"]
    EMAIL = ["email"]
    ORDER_COUNT = ["order_count", "email"]

    @property
    def description(self):
        if self.name in UserSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort users by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    @staticmethod
    def qs_with_order_count(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(order_count=Count("orders__id"))

class InfluencerSortField(graphene.Enum):
    UPDATED_AT = ["updated_at","pk"]

    @property
    def description(self):
        if self.name in InfluencerSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort users by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)


class UserMediaSortField(graphene.Enum):
    UPDATED_AT = ["updated_at","pk"]
    LIKE_COUNT = ["likes_count","pk"]
    DISLIKE_COUNT = ["dislikes_count","pk"]

    @property
    def description(self):
        if self.name in UserMediaSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort users by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)
    

class ContentFeedSortField(graphene.Enum):
    SORT_ORDER = ["sort_value","random","updated_at"]

    @property
    def description(self):
        if self.name in ContentFeedSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort users by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)
    
class UserFollowersSortField(graphene.Enum):
    UPDATED_AT = ["updated_at", "pk"]
    CREATED_AT = ["created_at", "pk"]
    MESSAGE_COUNT = ["message_count", "pk"]

    @property
    def description(self):
        if self.name in UserFollowersSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort users by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)
    
class UserFollowingSortField(graphene.Enum):
    UPDATED_AT = ["updated_at", "pk"]
    CREATED_AT = ["created_at", "pk"]
    MESSAGE_COUNT = ["message_count", "pk"]

    @property
    def description(self):
        if self.name in UserFollowingSortField.__enum__._member_names_:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort users by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    
class UserSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = UserSortField
        type_name = "users"


class PermissionGroupSortField(graphene.Enum):
    NAME = ["name"]

    @property
    def description(self):
        # pylint: disable=no-member
        if self in [PermissionGroupSortField.NAME]:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort permission group accounts by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)


class PermissionGroupSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = PermissionGroupSortField
        type_name = "permission group"

class InfluencerSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = InfluencerSortField
        type_name = "Influencers"

class UserMediaSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = UserMediaSortField
        type_name = "UserMedia"

class ContentFeedSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = ContentFeedSortField
        type_name = "UserMedia"

class UserFollowersSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = UserFollowersSortField
        type_name = "UserFollowedStatus"

class UserFollowingSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = UserFollowingSortField
        type_name = "UserFollowedStatus"
