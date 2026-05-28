from ..core.types import SortInputObjectType
import graphene

class WishlistSortField(graphene.Enum):
    CREATED_AT = ["created_at"]


class WishlistSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = WishlistSortField
        type_name = "wishlist"
