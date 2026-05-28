from django.core.exceptions import ValidationError
import graphene
from saleor.graphql.wishlist.resolvers import resolve_wishlist_items_from_user,fetch_wishlist_from_info,resolve_product_and_wishlist_item_mapper
from saleor.graphql.wishlist.types import Wishlist , ProductInWishlist
from saleor.store.store_utilities import get_instance_for_store
from saleor.utilities.request_utilities import RequestUtilities
from .mutations import (
    WishlistAddProductVariantMutation,
    WishlistRemoveProductVariantMutation,
    checkProductsInWishlist,
)


class WishlistQueries(graphene.ObjectType):
    wishlist = graphene.Field(Wishlist, description="Items of wishlist")
    check_existence_of_product_in_wishlist = graphene.List(ProductInWishlist , wishlist_id = graphene.ID(description="Id of wishlist",required = False),product_ids=graphene.List(graphene.ID, description="list of product ids"),description="list of product ids present in wishlist")

    def resolve_wishlist(self, info, **_kwargs):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)

        if not store_instance:
            raise ValidationError(message="Store Id In-valid")
        
        user_instance = info.context.user

        return resolve_wishlist_items_from_user(user_instance, store_instance)
        
    def resolve_check_existence_of_product_in_wishlist(self,info,wishlist_id,product_ids,**_kwargs):

        product_wishlist_mapped_dict = resolve_product_and_wishlist_item_mapper(info,wishlist_id,product_ids)

        product_in_wishlist = []

        for prod_id in product_ids:

            if product_wishlist_mapped_dict.get(prod_id):
                product_in_wishlist.append(ProductInWishlist(
                    product_id = prod_id,
                    is_present = True,
                    wishlistitem_id = product_wishlist_mapped_dict.get(prod_id)
                ))
                
            else:
                product_in_wishlist.append(ProductInWishlist(
                    product_id = prod_id,
                    is_present = False,
                    wishlistitem_id = None
                ))

        return product_in_wishlist


class WishlistMutations(graphene.ObjectType):
    # wishlist_add_product = WishlistAddProductMutation.Field()
    # wishlist_remove_product = WishlistRemoveProductMutation.Field()
    wishlist_add_variant = WishlistAddProductVariantMutation.Field()
    wishlist_remove_variant = WishlistRemoveProductVariantMutation.Field()
    check_products_in_wishlist = checkProductsInWishlist.Field()
