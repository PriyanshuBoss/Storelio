import graphene

from saleor.graphql.product.types.products import Product

from ...wishlist import models
from ..core.connection import CountableDjangoObjectType
from .sorters import WishlistSortingInput
from saleor.graphql.core.fields import FilterInputConnectionField

class WishlistItem(CountableDjangoObjectType):
    product = graphene.Field(Product , description = "Wishlist Item Products")
    class Meta:
        only_fields = ["id", "wishlist", "product", "variants"]
        description = "Wishlist item."
        interfaces = [graphene.relay.Node]
        model = models.WishlistItem
        filter_fields = ["id", "product"]
    
    def resolve_product(root,_info):
        prod = root.product
        if prod.is_published:
            return prod
        else:
            return

class Wishlist(CountableDjangoObjectType):
    items = FilterInputConnectionField(
        WishlistItem,
        sort_by = WishlistSortingInput(description = "sort wishlist Items"),
        description = "Wishlist Items"
    )

    class Meta:
        only_fields = ["id", "created_at"]
        description = "Wishlist item."
        interfaces = [graphene.relay.Node]
        model = models.Wishlist
        filter_fields = ["id"]

    def resolve_items(root: models.Wishlist, _info, *args, **kwargs):
        return root.items.filter(product__is_published=True)

class ProductInWishlist(graphene.ObjectType):
    product_id = graphene.ID(description="id of product")
    is_present = graphene.Boolean(description="Is project present in wishlist")
    wishlistitem_id = graphene.ID(description="id of wishlist item")
   
    class Meta:
        description = "Represents existance check in wishlist"
