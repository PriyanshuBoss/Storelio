import graphene

from ..core.mutations import BaseMutation
from ..core.types.common import WishlistError
from ..product.types import Product, ProductVariant
from .resolvers import fetch_wishlist_from_info, resolve_wishlist_from_info
from .types import ProductInWishlist, Wishlist, WishlistItem
from saleor.wishlist import models

class _BaseWishlistMutation(BaseMutation):
    wishlist = graphene.List(
        WishlistItem, description="The wishlist of the current user."
    )

    class Meta:
        abstract = True

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated


class _BaseWishlistProductMutation(_BaseWishlistMutation):
    class Meta:
        abstract = True

    class Arguments:
        product_id = graphene.ID(description="The ID of the product.", required=True)


class WishlistAddProductMutation(_BaseWishlistProductMutation):
    class Meta:
        description = "Add product to the current user's wishlist."
        error_type_class = WishlistError
        error_type_field = "wishlist_errors"

    @classmethod
    def perform_mutation(cls, _root, info, product_id):  # pylint: disable=W0221
        wishlist = resolve_wishlist_from_info(info)
        product = cls.get_node_or_error(
            info, product_id, only_type=Product, field="product_id"
        )
        wishlist.add_product(product)
        wishlist_items = wishlist.items.all()
        return WishlistAddProductMutation(wishlist=wishlist_items)


class WishlistRemoveProductMutation(_BaseWishlistProductMutation):
    class Meta:
        description = "Remove product from the current user's wishlist."
        error_type_class = WishlistError
        error_type_field = "wishlist_errors"

    @classmethod
    def perform_mutation(cls, _root, info, product_id):  # pylint: disable=W0221
        wishlist = resolve_wishlist_from_info(info)
        product = cls.get_node_or_error(
            info, product_id, only_type=Product, field="product_id"
        )
        wishlist.remove_product(product)
        wishlist_items = wishlist.items.all()
        return WishlistRemoveProductMutation(wishlist=wishlist_items)


class _BaseWishlistVariantMutation(_BaseWishlistMutation):
    class Meta:
        abstract = True

    class Arguments:
        variant_id = graphene.ID(
            description="The ID of the product variant.", required=True
        )


class WishlistAddProductVariantMutation(_BaseWishlistVariantMutation):
    class Meta:
        description = "Add product variant to the current user's wishlist."
        error_type_class = WishlistError
        error_type_field = "wishlist_errors"

    @classmethod
    def perform_mutation(cls, _root, info, variant_id):  # pylint: disable=W0221
        wishlist = resolve_wishlist_from_info(info)
        variant = cls.get_node_or_error(
            info, variant_id, only_type=ProductVariant, field="variant_id"
        )
        wishlist.add_variant(variant)
        wishlist_items = wishlist.items.all()
        return WishlistAddProductVariantMutation(wishlist=wishlist_items)


class WishlistRemoveProductVariantMutation(_BaseWishlistVariantMutation):
    class Meta:
        description = "Remove product variant from the current user's wishlist."
        error_type_class = WishlistError
        error_type_field = "wishlist_errors"

    @classmethod
    def perform_mutation(cls, _root, info, variant_id):  # pylint: disable=W0221
        wishlist = resolve_wishlist_from_info(info)
        variant = cls.get_node_or_error(
            info, variant_id, only_type=ProductVariant, field="variant_id"
        )
        wishlist.remove_variant(variant)
        wishlist_items = wishlist.items.all()
        return WishlistRemoveProductVariantMutation(wishlist=wishlist_items)
   
class checkProductsInWishlist(BaseMutation):
    
    class Arguments:
        wishlist_id = graphene.ID(description="Id of wishlist", required=False)
        product_ids = graphene.Argument(graphene.List(graphene.ID), description="list of product ids")

    product_in_wishlist = graphene.List(ProductInWishlist, description="list of product ids present in wishlist")

    class Meta:
        description="check existance of products in wishlist"
        error_type_class = WishlistError
        error_type_field = "wishlist_errors"
        


    @classmethod
    def clean_input(cls, info, data):
        cleaned_input = {}
        wishlist = fetch_wishlist_from_info(info)

        if not wishlist and data.get('wishlist_id'):
            wishlist = cls.get_node_or_error(info,data.get('wishlist_id'),"id", Wishlist)
        
        cleaned_input['wishlist'] = wishlist
        product_ids = [product_instance.id for product_instance in cls.get_nodes_or_error(data.get('product_ids'),"id", Product)]
        cleaned_input['product_ids'] = product_ids

        return cleaned_input

    @classmethod
    def get_existing_products_in_wishlist(cls, cleaned_input):
        
        wishlist_items = models.WishlistItem.objects.filter(
            product__in=cleaned_input.get('product_ids', []), 
            wishlist=cleaned_input.get('wishlist', None))
        
        return {graphene.Node.to_global_id("Product", instance.product_id): graphene.Node.to_global_id("WishlistItem", instance.id)  for instance in wishlist_items}

    @classmethod
    def get_product_in_wishlist(cls, product_ids, existing_products):
        product_in_wishlist = []
        
        for product_id in product_ids:

            if existing_products.get(product_id):
                product_in_wishlist.append(ProductInWishlist(
                    product_id = product_id,
                    is_present = True,
                    wishlistitem_id = existing_products.get(product_id)
                ))

            else:
                 product_in_wishlist.append(ProductInWishlist(
                    product_id = product_id,
                    is_present = False,
                    wishlistitem_id = None
                ))

        return product_in_wishlist
    
    @classmethod
    def perform_mutation(cls, root, info, **data):

        cleaned_input = cls.clean_input(info, data)
        existing_products = cls.get_existing_products_in_wishlist(cleaned_input)
        product_in_wishlist = cls.get_product_in_wishlist(data.get('product_ids'), existing_products)
        
        return cls(product_in_wishlist=product_in_wishlist)
