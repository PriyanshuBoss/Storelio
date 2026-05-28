import graphene
from saleor.utilities.request_utilities import RequestUtilities
from ...core.permissions import CheckoutPermissions
from ..core.fields import BaseDjangoConnectionField, FilterInputConnectionField, PrefetchingConnectionField
from ..core.scalars import UUID
from ..decorators import permission_required
from ..payment.mutations import CheckoutPaymentCreate
from .mutations import (
    AttachCheckoutToZaamo,
    CheckoutAddPromoCode,
    CheckoutBillingAddressUpdate,
    CheckoutClearMeta,
    CheckoutClearPrivateMeta,
    CheckoutComplete,
    CheckoutCreate,
    CheckoutCustomerAttach,
    CheckoutCustomerDetach,
    CheckoutEmailUpdate,
    CheckoutLineDelete,
    CheckoutLinesAdd,
    CheckoutLinesUpdate,
    CheckoutRemovePromoCode,
    CheckoutShippingAddressUpdate,
    CheckoutShippingMethodUpdate,
    CheckoutUpdateMeta,
    CheckoutUpdatePrivateMeta,
)
from .resolvers import resolve_checkout, resolve_checkout_lines, resolve_checkouts,resolve_brand_shipping_cost, resolve_checkouts_by_user,resolve_applicable_vouchers
from .types import Checkout, CheckoutLine,BrandShippingPrice
from ..core.types.money import TaxedMoney
import logging
from saleor.graphql.discount.types import Voucher
logger = logging.getLogger(__name__)

class CheckoutQueries(graphene.ObjectType):
    checkout = graphene.Field(
        Checkout,
        description="Look up a checkout by token.",
        token=graphene.Argument(UUID, description="The checkout's token."),
    )
    # FIXME we could optimize the below field
    checkouts = BaseDjangoConnectionField(Checkout, description="List of checkouts.")
    checkout_line = graphene.Field(
        CheckoutLine,
        id=graphene.Argument(graphene.ID, description="ID of the checkout line."),
        description="Look up a checkout line by ID.",
    )
    checkouts_by_user = FilterInputConnectionField(Checkout, description="List of checkouts.",
            user_id= graphene.ID(description="ID of the User.", required=False),
            mobile_no = graphene.String(description="mobile no of user", required=False))

    checkout_lines = PrefetchingConnectionField(
        CheckoutLine, description="List of checkout lines."
    )
    brand_shipping_cost_distribution = graphene.List(BrandShippingPrice,token = graphene.Argument(UUID,description="ID of the order"),description="Individual Brand Shipping Cost List")

    available_vouchers = graphene.List(Voucher,checkout_id = graphene.Argument(graphene.ID,description="ID of the checkout",required=False),
                                            product_id = graphene.Argument(graphene.ID,description="ID of the Product",required=False)  )

    def resolve_checkout(self, info, token):
        return resolve_checkout(info, token)

    @permission_required(CheckoutPermissions.MANAGE_CHECKOUTS)
    def resolve_checkouts(self, *_args, **_kwargs):
        resolve_checkouts()
    
    def resolve_checkouts_by_user(self, info, user_id=None, mobile_no=None, *args, **kwargs):
        
        return resolve_checkouts_by_user(info, user_id, mobile_no, *args, **kwargs)


    def resolve_checkout_line(self, info, id):
        return graphene.Node.get_node_from_global_id(info, id, CheckoutLine)

    @permission_required(CheckoutPermissions.MANAGE_CHECKOUTS)
    def resolve_checkout_lines(self, *_args, **_kwargs):
        return resolve_checkout_lines()
    
    def resolve_brand_shipping_cost_distribution(self,info,token):
        brand_cost_dict,brand_instance_dict = resolve_brand_shipping_cost(token)
        brand_cost_list = []

        for brand_id in brand_cost_dict:
            shipping_price = brand_cost_dict[brand_id]
            brand = brand_instance_dict[brand_id]
            brand_cost_list.append(BrandShippingPrice(brand=brand, shipping_cost = TaxedMoney(net=shipping_price, gross=shipping_price))) 

        return brand_cost_list
    
    def resolve_available_vouchers(self,info,product_id=None,checkout_id = None):
        
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        try:
            return resolve_applicable_vouchers(info,store_id,product_id,checkout_id)
        except Exception as e:
            logger.exception(f"resolve available voucher failed with error: {e}, checkout_id: {checkout_id}, product_id: {product_id}, store_id: {store_id}")
            

class CheckoutMutations(graphene.ObjectType):

    attach_checkout_to_zaamo = AttachCheckoutToZaamo.Field()
    checkout_add_promo_code = CheckoutAddPromoCode.Field()
    checkout_billing_address_update = CheckoutBillingAddressUpdate.Field()
    checkout_complete = CheckoutComplete.Field()
    checkout_create = CheckoutCreate.Field()
    checkout_customer_attach = CheckoutCustomerAttach.Field()
    checkout_customer_detach = CheckoutCustomerDetach.Field()
    checkout_email_update = CheckoutEmailUpdate.Field()
    checkout_line_delete = CheckoutLineDelete.Field()
    checkout_lines_add = CheckoutLinesAdd.Field()
    checkout_lines_update = CheckoutLinesUpdate.Field()
    checkout_remove_promo_code = CheckoutRemovePromoCode.Field()
    checkout_payment_create = CheckoutPaymentCreate.Field()
    checkout_shipping_address_update = CheckoutShippingAddressUpdate.Field()
    checkout_shipping_method_update = CheckoutShippingMethodUpdate.Field()
    checkout_update_metadata = CheckoutUpdateMeta.Field(
        deprecation_reason=(
            "Use the `updateMetadata` mutation. This field will be removed after "
            "2020-07-31."
        )
    )
    checkout_clear_metadata = CheckoutClearMeta.Field(
        deprecation_reason=(
            "Use the `deleteMetadata` mutation. This field will be removed after "
            "2020-07-31."
        )
    )
    checkout_update_private_metadata = CheckoutUpdatePrivateMeta.Field(
        deprecation_reason=(
            "Use the `updatePrivateMetadata` mutation. This field will be removed "
            "after 2020-07-31."
        )
    )
    checkout_clear_private_metadata = CheckoutClearPrivateMeta.Field(
        deprecation_reason=(
            "Use the `deletePrivateMetadata` mutation. This field will be removed "
            "after 2020-07-31."
        )
    )
