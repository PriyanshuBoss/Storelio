from typing import TYPE_CHECKING

import graphene
from django.core.exceptions import ValidationError
from saleor.store.store_utilities import get_instance_for_store

from saleor.utilities.request_utilities import RequestUtilities

from ...wishlist.models import Wishlist,WishlistItem

from django.db import transaction

if TYPE_CHECKING:
    # pylint: disable=unused-import
    from django.db.models.query import QuerySet
    from graphene.types import ResolveInfo
    from ...account.models import User
    from ...wishlist.models import WishlistItem



def fetch_wishlist_from_info(info):
    user = info.context.user
    
    if not user.is_authenticated:
        return None

    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    store_instance = get_instance_for_store(store_id)

    if not store_instance:
        raise ValidationError(message='store id not sent in headers')
    
    wishlist_filter = Wishlist.objects.filter(user=user, store=store_instance)

    if wishlist_filter:
        return wishlist_filter[0]
    
    return None


def check_existance_of_user_and_store(user: "User", store_instance):
    wishlist = Wishlist.objects.select_for_update().filter(user=user, store=store_instance)
    
    with transaction.atomic():
        
        if wishlist:
            return wishlist.first()
        else:
            wishlist = Wishlist.objects.create(
                user = user,
                store = store_instance
            )
            return wishlist


def resolve_wishlist_from_user(user: "User", store_instance) -> Wishlist:
    """Return wishlist of the logged in user."""
    if not user.is_authenticated:
        return None
    
    wishlist = check_existance_of_user_and_store(user, store_instance)
    
    return wishlist


def resolve_wishlist_from_info(info: "ResolveInfo") -> Wishlist:
    """Return wishlist of the logged in user."""
    user = info.context.user
    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    store_instance = get_instance_for_store(store_id)

    if not store_instance:
        raise ValidationError(message='store id not sent in headers')
    
    return resolve_wishlist_from_user(user, store_instance)


def resolve_wishlist_items_from_user(user: "User", store_instance) -> "QuerySet[WishlistItem]":
    """Return wishlist items of the logged in user."""
    wishlist = resolve_wishlist_from_user(user, store_instance)
    
    return wishlist

def resolve_product_and_wishlist_item_mapper(info,wishlist_id,product_ids):

    wishlist = fetch_wishlist_from_info(info)

    if not wishlist and wishlist_id:
        local_wishlist_id = graphene.Node.from_global_id(wishlist_id)[1]
        wishlist = Wishlist.objects.filter(pk=local_wishlist_id).first()

    valid_prod_ids =[graphene.Node.from_global_id(product_id)[1] for product_id in product_ids]

    wishlist_items = WishlistItem.objects.filter(
        product__in=valid_prod_ids, 
        wishlist=wishlist)

    return {graphene.Node.to_global_id("Product", instance.product_id): graphene.Node.to_global_id("WishlistItem", instance.id)  for instance in wishlist_items}
