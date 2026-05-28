from saleor.discount.models import Voucher
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.product.models import BrandVariantZaamoMapping
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.store.store_utilities import get_instance_for_store
from saleor.store.models import StoreInfo
from typing import List, Optional, Tuple
import logging
from saleor.settings import IS_BETA
from saleor.external_services.freshdesk.tasks import create_fresh_desk_order_ticket_cod_order_task
import graphene
from saleor.brand.states import BrandSourceEnum
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Prefetch
from saleor.order.tasks import create_fulfillment_task
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from ...checkout import models
from ...checkout.complete_checkout import complete_checkout
from ...checkout.error_codes import CheckoutErrorCode
from ...checkout.utils import (
    add_promo_code_to_checkout,
    add_variant_to_checkout,
    change_billing_address_in_checkout,
    change_shipping_address_in_checkout,
    get_user_checkout,
    get_valid_shipping_methods_for_checkout,
    recalculate_checkout_discount,
    remove_promo_code_from_checkout,
    get_voucher_discount_for_checkoutline
)

from ...core import analytics
from ...core.exceptions import InsufficientStock, PermissionDenied, ProductNotPublished
from ...core.permissions import OrderPermissions
from ...core.transactions import transaction_with_commit_on_errors
from ...order import models as order_models
from ...payment import models as payment_models
from ...product import models as product_models
from ...warehouse.availability import check_stock_quantity, get_available_quantity,get_default_warehouse_id
from ..account.i18n import I18nMixin
from ..account.types import AddressInput
from ...account.models import Address
from ..core.mutations import BaseMutation, ModelMutation
from ..core.types.common import CheckoutError
from ..core.utils import from_global_id_strict_type
from ..meta.deprecated.mutations import ClearMetaBaseMutation, UpdateMetaBaseMutation
from ..order.types import Order
from ..product.types import ProductVariant
from ..shipping.types import ShippingMethod
from .types import Checkout, CheckoutLine
from saleor.utilities.request_utilities import RequestUtilities
from saleor.order.order_complete import OrderEngine

logger = logging.getLogger(__name__)


ERROR_DOES_NOT_SHIP = "This checkout doesn't need shipping"


def clean_shipping_method(
    checkout: models.Checkout,
    lines: List[models.CheckoutLine],
    method: Optional[models.ShippingMethod],
    discounts,
) -> bool:
    """Check if current shipping method is valid."""

    if not method:
        # no shipping method was provided, it is valid
        return True

    if not checkout.is_shipping_required():
        raise ValidationError(
            ERROR_DOES_NOT_SHIP, code=CheckoutErrorCode.SHIPPING_NOT_REQUIRED.value
        )

    if not checkout.shipping_address:
        logger.exception(f"Shipping method is updated but shipping address is not set. checkout token :: {checkout.token}")
        return True

    valid_methods = get_valid_shipping_methods_for_checkout(checkout, lines, discounts)
    return method in valid_methods


def update_checkout_shipping_method_if_invalid(
    checkout: models.Checkout, lines: List[models.CheckoutLine], discounts
):
    # remove shipping method when empty checkout
    if checkout.quantity == 0 or not checkout.is_shipping_required():
        checkout.shipping_method = None
        checkout.save(update_fields=["shipping_method", "last_change"])

    is_valid = clean_shipping_method(
        checkout=checkout,
        lines=lines,
        method=checkout.shipping_method,
        discounts=discounts,
    )

    if not checkout.shipping_method:
        checkout.shipping_method = models.ShippingMethod.objects.filter(name='TNT').first()
        checkout.save(update_fields=["shipping_method", "last_change"])
        
    if not is_valid:
        cheapest_alternative = get_valid_shipping_methods_for_checkout(
            checkout, lines, discounts
        ).first()
        checkout.shipping_method = cheapest_alternative
        checkout.save(update_fields=["shipping_method", "last_change"])

        logger.info("Updating shipping method for checkout-%s by %s",  checkout.token, cheapest_alternative)

def check_lines_quantity(variants, quantities, country):
    """Check if stock is sufficient for each line in the list of dicts."""
    for variant, quantity in zip(variants, quantities):
        if quantity < 0:

            logger.info("The quantity should be higher than zero.\
                for variant-%s", variant.id)

            raise ValidationError(
                {
                    "quantity": ValidationError(
                        "The quantity should be higher than zero.",
                        code=CheckoutErrorCode.ZERO_QUANTITY,
                    )
                }
            )
        if quantity > settings.MAX_CHECKOUT_LINE_QUANTITY:

            logger.info("Cannot add more than-%s times\
                for variant-%s", settings.MAX_CHECKOUT_LINE_QUANTITY, variant.id)

            raise ValidationError(
                {
                    "quantity": ValidationError(
                        "Cannot add more than %d times this item."
                        "" % settings.MAX_CHECKOUT_LINE_QUANTITY,
                        code=CheckoutErrorCode.QUANTITY_GREATER_THAN_LIMIT,
                    )
                }
            )
        try:
            check_stock_quantity(variant, country, quantity)
        except InsufficientStock as e:

            available_quantity = get_available_quantity(e.item, country)

            logger.exception("requested quantity is %s but available_quantity is %s, So variant-%s is out of stock", 
            quantity, available_quantity, variant.id)

            message = (
                "Could not add item "
                + "%(item_name)s. Only %(remaining)d remaining in stock."
                % {
                    "remaining": available_quantity,
                    "item_name": e.item.display_product(),
                }
            )
            raise ValidationError({"quantity": ValidationError(message, code=e.code)})

def check_brand_stock_available(variant,country_code):
    '''
    To Check stock from brand side when quantity available is less than 3
    '''
    response = True

    if IS_BETA:
        return response
    
    if not variant.track_inventory:
        return response

    brand_source = variant.product.brand.brand_source
    quantity = get_available_quantity(variant,country_code)
    
    if 0<quantity<3:

        brand_mapping = BrandVariantZaamoMapping.objects.filter(variant_zaamo=variant).first()

        if not brand_mapping:
            return response

        if brand_source==BrandSourceEnum.WOOCOMMERCE:
            woo_inst = WooCommerceImpl()
            response = woo_inst.check_variant_stock_from_brand(brand_mapping)

        if brand_source==BrandSourceEnum.SHOPIFY:
            shopify_inst = ShopifyImpl()
            response = shopify_inst.check_variant_stock_from_brand(brand_mapping)

    return response

def validate_variants_available_for_purchase(variants, country_code='IN'):

    unavailable_products = ""
    not_available_variants = []

    for variant in variants:
        product_instance = variant.product

        if not product_instance.is_available_for_purchase() or not check_brand_stock_available(variant,country_code):
            not_available_variants.append(variant.pk)
            unavailable_products += product_instance.name + ", "

    if not_available_variants:
        variant_ids = [
            graphene.Node.to_global_id("ProductVariant", pk)
            for pk in not_available_variants
        ]
        raise ValidationError(
            {
                "lines": ValidationError(
                     "%s not available for purchase" % unavailable_products,
                    code=CheckoutErrorCode.PRODUCT_UNAVAILABLE_FOR_PURCHASE,
                    params={"variants": variant_ids},
                )
            }
        )


class CheckoutLineInput(graphene.InputObjectType):
    quantity = graphene.Int(required=True, description="The number of items purchased.")
    variant_id = graphene.ID(required=True, description="ID of the product variant.")
    cod = graphene.Boolean(required=False, description="ID of the product variant.")


class CheckoutCreateInput(graphene.InputObjectType):
    lines = graphene.List(
        CheckoutLineInput,
        description=(
            "A list of checkout lines, each containing information about "
            "an item in the checkout."
        ),
        required=True,
    )
    email = graphene.String(description="The customer's email address.")
    shipping_address = AddressInput(
        description=(
            "The mailing address to where the checkout will be shipped. "
            "Note: the address will be ignored if the checkout "
            "doesn't contain shippable items."
        )
    )
    billing_address = AddressInput(description="Billing address of the customer.") #currently not being used
    shipping_address_id = graphene.ID(required=False,desciption="Old saved address Id of the customer")
    billing_address_id = graphene.ID(required=False,desciption="Old saved address Id of the customer")  # currently not being used 


class CheckoutCreate(ModelMutation, I18nMixin):
    created = graphene.Field(
        graphene.Boolean,
        description=(
            "Whether the checkout was created or the current active one was returned. "
            "Refer to checkoutLinesAdd and checkoutLinesUpdate to merge a cart "
            "with an active checkout."
        ),
    )

    class Arguments:
        input = CheckoutCreateInput(
            required=True, description="Fields required to create checkout."
        )

    class Meta:
        description = "Create a new checkout."
        model = models.Checkout
        return_field_name = "checkout"
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def process_checkout_lines(
        cls, lines, country
    ) -> Tuple[List[product_models.ProductVariant], List[int]]:
        variant_ids = [line.get("variant_id") for line in lines]
        variants = cls.get_nodes_or_error(
            variant_ids,
            "variant_id",
            ProductVariant,
            qs=product_models.ProductVariant.objects.prefetch_related(
                "product__product_type"
            ),
        )
        quantities = [line.get("quantity") for line in lines]
        cod = [line.get("cod", False) for line in lines]

        validate_variants_available_for_purchase(variants, country_code=country)
        check_lines_quantity(variants, quantities, country)

        return variants, quantities, cod

    @classmethod
    def retrieve_shipping_address(cls, user, data: dict) -> Optional[models.Address]:

        if user.is_authenticated:

            if data.get("shipping_address_id"):
                shipping_address_id = graphene.Node.from_global_id(data.get("shipping_address_id"))[1]

                if Address.objects.filter(pk=shipping_address_id).exists():
                    address_instance = Address.objects.get(pk=shipping_address_id)

                    return address_instance

        if data.get("shipping_address") is not None:
            instance = cls.validate_address(data["shipping_address"])
            instance.email = data.get("email")
            instance.save()

            return instance

        return None

    @classmethod
    def retrieve_billing_address(cls, user, data: dict) -> Optional[models.Address]:  #this function is currently not being used 
        if user.is_authenticated:                                                      # we are taking billing address same as shipping address
            
            if data.get("billing_address_id"):
                billing_address_id = graphene.Node.from_global_id(data.get("billing_address_id"))[1]

                if Address.objects.filter(pk=billing_address_id).exists():
                    address_instance = Address.objects.get(pk=billing_address_id)

                    return address_instance

            elif data.get("shipping_address_id"):
                shipping_address_id = graphene.Node.from_global_id(data.get("shipping_address_id"))[1]

                if Address.objects.filter(pk=shipping_address_id).exists():
                    address_instance = Address.objects.get(pk=shipping_address_id)

                    return address_instance

        if data.get("billing_address") is not None:
            instance = cls.validate_address(data["billing_address"])
            instance.email = data.get("email")
            instance.save()

            return instance

        elif data.get("shipping_address") is not None:
            instance = cls.validate_address(data["shipping_address"])
            instance.email = data.get("email")
            instance.save()

            return instance

        return None

    @classmethod
    def clean_input(cls, info, instance: models.Checkout, data, input_cls=None):
        cleaned_input = super().clean_input(info, instance, data)
        logger.info(
            "From clean_input :: cleaned input from super class is :: %s ", cleaned_input
        )
        user = info.context.user
        country = info.context.country.code
        logger.info(
            "From clean_input :: user :: %s and country :: %s ", user, country
        )
        # set country to one from shipping address
        shipping_address = cleaned_input.get("shipping_address")
        if shipping_address and shipping_address.country:
            if shipping_address.country != country:
                country = shipping_address.country
        cleaned_input["country"] = country
        logger.info(
            "From clean_input :: cleaned input after setting country to shipping address :: %s ", cleaned_input
        )
        # Resolve and process the lines, retrieving the variants and quantities
        lines = data.pop("lines", None)
        if lines:
            (
                cleaned_input["variants"],
                cleaned_input["quantities"],
                cleaned_input["cod"],
            ) = cls.process_checkout_lines(lines, country)

        cleaned_input["shipping_address"] = cls.retrieve_shipping_address(user, data)
        cleaned_input["billing_address"] = cleaned_input["shipping_address"]
        logger.info(
            "From clean_input :: cleaned input after setting shipping address :: %s ", cleaned_input
        )
        # cleaned_input["billing_address"] = cls.retrieve_billing_address(user, data) removing this function not generating extra address for  billing

        # Use authenticated user's email as default email
        if user.is_authenticated:
            email = data.pop("email", None)
            cleaned_input["email"] = email or cleaned_input["shipping_address"].email or user.email

        return cleaned_input

    @classmethod
    def save_addresses(cls, instance: models.Checkout, cleaned_input: dict):
        shipping_address = cleaned_input.get("shipping_address")
        billing_address = cleaned_input.get("billing_address")

        updated_fields = ["last_change"]
        
        if shipping_address and instance.is_shipping_required():
            # shipping_address.save()
            instance.shipping_address = shipping_address
            updated_fields.append("shipping_address")            
        if billing_address:
            # billing_address.save()
            instance.billing_address = billing_address
            updated_fields.append("billing_address")            

        # Note django will simply return if the list is empty
        instance.save(update_fields=updated_fields)
        logger.info(
            "From save_addresses :: address has been saved to instance "
        )
    
    @classmethod
    def save_checkout_store(cls, instance: models.Checkout, store_instance: models.CheckoutStore):
        
        if not cls.check_checkout_store(instance, store_instance):
            models.CheckoutStore.create_instance({
                'token': instance,
                'store_instance': store_instance
            })

    @classmethod
    def check_checkout_store(cls, instance: models.Checkout, store_instance: models.CheckoutStore):
        
        return models.CheckoutStore.objects.filter(token=instance, store=store_instance).exists()
    
    @classmethod
    @transaction.atomic()
    def save(cls, info, instance: models.Checkout, cleaned_input):
        # Create the checkout object
        instance.platform_code = RequestUtilities.get_platfrom_type_from_headers(info.context)
        instance.app_code = RequestUtilities.get_app_code_from_headers(info.context)
        instance.mobile_device_id = RequestUtilities.get_device_id_from_headers(info.context)
        instance.save()
        logger.info(
            "From save :: checkout instance has been saved "
        )
        country = cleaned_input["country"]
        instance.set_country(country, commit=True)
        logger.info(
            "From save :: country has been set to the saved instance "
        )
        # Retrieve the lines to create
        variants = cleaned_input.get("variants")
        quantities = cleaned_input.get("quantities")
        cod_status = cleaned_input.get("cod")
        # Create the checkout lines
        if variants and quantities:
            for variant, quantity, cod in zip(variants, quantities, cod_status):
                try:
                    add_variant_to_checkout(instance, variant, quantity=quantity, cod=cod)
                except InsufficientStock as exc:
                    raise ValidationError(
                        f"Insufficient product stock: {exc.item}", code=exc.code
                    )
                except ProductNotPublished as exc:
                    raise ValidationError(
                        "Can't create checkout with unpublished product.",
                        code=exc.code,
                    )
            info.context.plugins.checkout_quantity_changed(instance)
        # Save provided addresses and associate them to the checkout
        cls.save_addresses(instance, cleaned_input)
    
    @classmethod
    def validate_if_user_store_owner(cls, store_instance, user):
        store_members = store_instance.store_members.select_related("user").all()
        if user in [member.user for member in store_members]:
            raise ValidationError(message='Kindly create order on Influencer home,\
                 You are store owner you can not create order on your store')

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        logger.info(
            "Data for which CheckoutCreate Mutation will be performed is :: %s ", data
        )
        user = info.context.user
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        platform_type = RequestUtilities.get_platfrom_type_from_headers(info.context)

        store_instance = get_instance_for_store(store_id)
        logger.info(
            "Store Instance :: %s for the store_id :: %s ", store_instance, store_id
        )
        if not store_instance:
            raise ValidationError(message='store id not sent in headers')

        if platform_type == PlatformTypeEnum.INFLUENCER_STORE:
            cls.validate_if_user_store_owner(store_instance, user)

        if user.is_authenticated:
            checkout, _ = get_user_checkout(user,store_instance)

            if checkout is not None and cls.check_checkout_store(checkout, store_instance):
                # If user has an active checkout, return it without any
                # modifications.
                logger.info(
                    "user :: %s has an active checkout :: %s ", user, checkout
                )
                return CheckoutCreate(checkout=checkout, created=False)

            checkout = models.Checkout(user=user)
            logger.info(
                "checkout for the user :: %s is %s ", user, checkout.token
            )
        else:
            checkout = models.Checkout()

        cleaned_input = cls.clean_input(info, checkout, data.get("input"))
        logger.info(
            "Cleaned input :: %s for the checkout :: %s ",cleaned_input, checkout
        )
        checkout = cls.construct_instance(checkout, cleaned_input)
        logger.info(
            "Constructed instance for the cleaned input is :: %s ",checkout
        )
        cls.clean_instance(info, checkout)
        logger.info(
            "Cleaned instance for the constructed instance is :: %s ",checkout
        )
        cls.save(info, checkout, cleaned_input)
        logger.info(
            f"checkout instance has been saved with checkout token :: {checkout.token}"
        )
        cls.save_checkout_store(checkout, store_instance)
        logger.info(
            f"checkout store instance has been saved checkout token :: {checkout.token}"
        )
        cls._save_m2m(info, checkout, cleaned_input)
        info.context.plugins.checkout_created(checkout)
        logger.info(
            f"Finally Stored checkout date with token :: {checkout.token}, platform_type :: {platform_type}, app_code :: {checkout.app_code}, store_id :: {store_id}"
        )
        return CheckoutCreate(checkout=checkout, created=True)


class CheckoutLinesAdd(BaseMutation):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(description="The ID of the checkout.", required=True)
        lines = graphene.List(
            CheckoutLineInput,
            required=True,
            description=(
                "A list of checkout lines, each containing information about "
                "an item in the checkout."
            ),
        )

    class Meta:
        description = "Adds a checkout line to the existing checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, lines, replace=False):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )
        logger.info("CheckoutLinesUpdate : adding new checkout line for checkout :: %s with data as :: %s", checkout.token, lines)
        variant_ids = [line.get("variant_id") for line in lines]
        variants = cls.get_nodes_or_error(variant_ids, "variant_id", ProductVariant)
        quantities = [line.get("quantity") for line in lines]
        cod_status = [line.get("cod", False) for line in lines]
        logger.info("Updating checkout-%s with data as ::: %s", checkout.token, lines)
        check_lines_quantity(variants, quantities, checkout.get_country())
        logger.info("checkout lines quantity validated")
        
        if True in cod_status and checkout.voucher_code:
            raise ValidationError(
                        f"Cash on Delivery not applicable with applied voucher."
                    )
        
        validate_variants_available_for_purchase(variants, country_code=checkout.get_country())
        logger.info("variants are available for purchase ")
        if variants and quantities:
            for variant, quantity, cod in zip(variants, quantities, cod_status):
                try:
                    add_variant_to_checkout(
                        checkout, variant, cod, quantity, replace=replace
                    )
                except InsufficientStock as exc:

                    logger.exception("Can not add variant-%s to checkout-%s as stock is not available \
                        for this variant", variant.id, checkout.token)

                    raise ValidationError(
                        f"Insufficient product stock: {exc.item}", code=exc.code
                    )
                except ProductNotPublished as exc:
                    raise ValidationError(
                        "Can't add unpublished product.", code=exc.code,
                    )
            info.context.plugins.checkout_quantity_changed(checkout)

        lines = list(checkout)

        update_checkout_shipping_method_if_invalid(
            checkout, lines, info.context.discounts
        )
        recalculate_checkout_discount(checkout, lines, info.context.discounts)
        info.context.plugins.checkout_updated(checkout)
        return CheckoutLinesAdd(checkout=checkout)


class CheckoutLinesUpdate(CheckoutLinesAdd):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Meta:
        description = "Updates checkout line in the existing checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def perform_mutation(cls, root, info, checkout_id, lines):
        logger.info("Updating checkout-%s",  checkout_id)
        return super().perform_mutation(root, info, checkout_id, lines, replace=True)


class CheckoutLineDelete(BaseMutation):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(description="The ID of the checkout.", required=True)
        line_id = graphene.ID(description="ID of the checkout line to delete.")

    class Meta:
        description = "Deletes a CheckoutLine."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, line_id):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )
        line = cls.get_node_or_error(
            info, line_id, only_type=CheckoutLine, field="line_id"
        )

        if line and line in checkout.lines.all():
            logger.info("Checkout Line with variant-%s, deleted from checkout-%s", line.variant_id, checkout.token)
            line.delete()
            info.context.plugins.checkout_quantity_changed(checkout)

        lines = list(checkout)

        update_checkout_shipping_method_if_invalid(
            checkout, lines, info.context.discounts
        )
        recalculate_checkout_discount(checkout, lines, info.context.discounts)

        info.context.plugins.checkout_updated(checkout)
        return CheckoutLineDelete(checkout=checkout)


class CheckoutCustomerAttach(BaseMutation):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(required=True, description="ID of the checkout.")
        customer_id = graphene.ID(
            required=False,
            description=(
                "[Deprecated] The ID of the customer. To identify a customer you "
                "should authenticate with JWT. This field will be removed after "
                "2020-07-31."
            ),
        )
        email_id = graphene.String(required = False, description = "email id of the user for checkout")

    class Meta:
        description = "Sets the customer as the owner of the checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, customer_id=None,email_id=None):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )

        # Check if provided customer_id matches with the authenticated user and raise
        # error if it doesn't. This part can be removed when `customer_id` field is
        # removed.
        if customer_id:
            current_user_id = graphene.Node.to_global_id("User", info.context.user.id)
            if current_user_id != customer_id:
                raise PermissionDenied()

        checkout.user = info.context.user
        checkout_email = checkout.email
        
        if email_id:
            checkout.email = email_id
        else:
            checkout.email = checkout_email
        
        checkout.save(update_fields=["user", "last_change", "email"])

        info.context.plugins.checkout_updated(checkout)
        return CheckoutCustomerAttach(checkout=checkout)


class CheckoutCustomerDetach(BaseMutation):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.", required=True)

    class Meta:
        description = "Removes the user assigned as the owner of the checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )

        # Raise error if the current user doesn't own the checkout of the given ID.
        if checkout.user and checkout.user != info.context.user:
            raise PermissionDenied()

        checkout.user = None
        checkout.save(update_fields=["user", "last_change"])

        info.context.plugins.checkout_updated(checkout)
        return CheckoutCustomerDetach(checkout=checkout)


class CheckoutShippingAddressUpdate(BaseMutation, I18nMixin):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(required=True, description="ID of the checkout.")
        shipping_address = AddressInput(
            required=False,
            description="The mailing address to where the checkout will be shipped.",
        )
        address_id = graphene.ID(required = False , description="ID of the address")

    class Meta:
        description = "Update shipping address in the existing checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def process_checkout_lines(cls, lines, country) -> None:
        variant_ids = [line.variant.id for line in lines]
        variants = list(
            product_models.ProductVariant.objects.filter(
                id__in=variant_ids
            ).prefetch_related("product__product_type")
        )
        quantities = [line.quantity for line in lines]

        check_lines_quantity(variants, quantities, country)

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id,**data):
        pk = from_global_id_strict_type(checkout_id, Checkout, field="checkout_id")
        try:
            checkout = models.Checkout.objects.prefetch_related(
                "lines__variant__product__product_type"
            ).get(pk=pk)
            logger.info('CheckoutShippingAddressUpdate : updating shipping address for checkout_id :: %s and with data as :: %s', pk, data)

        except ObjectDoesNotExist:
            raise ValidationError(
                {
                    "checkout_id": ValidationError(
                        f"Couldn't resolve to a node: {checkout_id}",
                        code=CheckoutErrorCode.NOT_FOUND,
                    )
                }
            )

        if not checkout.is_shipping_required():
            raise ValidationError(
                {
                    "shipping_address": ValidationError(
                        ERROR_DOES_NOT_SHIP,
                        code=CheckoutErrorCode.SHIPPING_NOT_REQUIRED,
                    )
                }
            )

        try:
            address_id = data.get('address_id')
            address_id = graphene.Node.from_global_id(address_id)[1]
            shipping_address = Address.objects.filter(pk = address_id).first()
        except Exception as e:
            shipping_address = data.get('shipping_address')
            shipping_address = cls.validate_address(
            shipping_address, instance=checkout.shipping_address, info=info)

        lines = list(checkout)

        country = info.context.country.code
        # set country to one from shipping address
        if shipping_address and shipping_address.country:
            if shipping_address.country != country:
                country = shipping_address.country
        checkout.set_country(country, commit=True)

        # Resolve and process the lines, validating variants quantities
        # if lines:
        #     cls.process_checkout_lines(lines, country)

        
        with transaction.atomic():
            
            shipping_address.save()
            change_shipping_address_in_checkout(checkout, shipping_address)

            update_checkout_shipping_method_if_invalid(
            checkout, lines, info.context.discounts
            )
            
            user_instance = info.context.user
           
            if user_instance and user_instance.is_authenticated:

                if checkout.user is None:
                    checkout.user = user_instance
                checkout.email = shipping_address.email
                checkout.save()

        recalculate_checkout_discount(checkout, lines, info.context.discounts)

        info.context.plugins.checkout_updated(checkout)
        return CheckoutShippingAddressUpdate(checkout=checkout)


class CheckoutBillingAddressUpdate(CheckoutShippingAddressUpdate):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(required=True, description="ID of the checkout.")
        billing_address = AddressInput(
            required=False, description="The billing address of the checkout."
        )
        address_id = graphene.ID(required = False , description="ID of the address")

    class Meta:
        description = "Update billing address in the existing checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id,**data):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )
        try:
            address_id = data.get('address_id')
            address_id = graphene.Node.from_global_id(address_id)[1]
            billing_address = Address.objects.filter(pk=address_id).first()
        except Exception as e:
            billing_address = data.get('billing_address')
            billing_address = cls.validate_address(
                billing_address, instance=checkout.billing_address, info=info)
        with transaction.atomic():
            billing_address.save()
            change_billing_address_in_checkout(checkout, billing_address)
            info.context.plugins.checkout_updated(checkout)
        return CheckoutBillingAddressUpdate(checkout=checkout)


class CheckoutEmailUpdate(BaseMutation):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.")
        email = graphene.String(required=True, description="email.")

    class Meta:
        description = "Updates email address in the existing checkout object."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, email):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )

        checkout.email = email
        cls.clean_instance(info, checkout)
        checkout.save(update_fields=["email", "last_change"])
        info.context.plugins.checkout_updated(checkout)
        return CheckoutEmailUpdate(checkout=checkout)


class CheckoutShippingMethodUpdate(BaseMutation):
    checkout = graphene.Field(Checkout, description="An updated checkout.")

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.")
        shipping_method_id = graphene.ID(required=True, description="Shipping method.")

    class Meta:
        description = "Updates the shipping address of the checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, shipping_method_id):
        pk = from_global_id_strict_type(
            checkout_id, only_type=Checkout, field="checkout_id"
        )

        try:
            checkout = models.Checkout.objects.prefetch_related(
                "lines__variant__product__collections",
                "lines__variant__product__product_type",
            ).get(pk=pk)
        except ObjectDoesNotExist:
            raise ValidationError(
                {
                    "checkout_id": ValidationError(
                        f"Couldn't resolve to a node: {checkout_id}",
                        code=CheckoutErrorCode.NOT_FOUND,
                    )
                }
            )
        logger.info(f"CheckoutShippingMethodUpdate : with checkout token :: {checkout.token}, shipping_method :: {shipping_method_id}")

        if not checkout.is_shipping_required():
            raise ValidationError(
                {
                    "shipping_method": ValidationError(
                        ERROR_DOES_NOT_SHIP,
                        code=CheckoutErrorCode.SHIPPING_NOT_REQUIRED,
                    )
                }
            )

        shipping_method = cls.get_node_or_error(
            info,
            shipping_method_id,
            only_type=ShippingMethod,
            field="shipping_method_id",
        )

        lines = list(checkout)
        shipping_method_is_valid = clean_shipping_method(
            checkout=checkout,
            lines=lines,
            method=shipping_method,
            discounts=info.context.discounts,
        )

        if not shipping_method_is_valid:
            raise ValidationError(
                {
                    "shipping_method": ValidationError(
                        "This shipping method is not applicable.",
                        code=CheckoutErrorCode.SHIPPING_METHOD_NOT_APPLICABLE,
                    )
                }
            )

        checkout.shipping_method = shipping_method
        checkout.save(update_fields=["shipping_method", "last_change"])
        recalculate_checkout_discount(checkout, lines, info.context.discounts)
        info.context.plugins.checkout_updated(checkout)
        logger.info(f"Checkout shipping method update with checkout token :: {checkout.token}, shipping_method :: {checkout.shipping_method_id}")
        return CheckoutShippingMethodUpdate(checkout=checkout)


class CheckoutComplete(BaseMutation):
    order = graphene.Field(Order, description="Placed order.")
    confirmation_needed = graphene.Boolean(
        required=True,
        default_value=False,
        description=(
            "Set to true if payment needs to be confirmed"
            " before checkout is complete."
        ),
    )
    confirmation_data = graphene.JSONString(
        required=False,
        description=(
            "Confirmation data used to process additional authorization steps."
        ),
    )

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.", required=True)
        store_source = graphene.Boolean(
            default_value=False,
            description=(
                "Determines whether to store the payment source for future usage."
            ),
        )
        redirect_url = graphene.String(
            required=False,
            description=(
                "URL of a view where users should be redirected to "
                "see the order details. URL in RFC 1808 format."
            ),
        )
        payment_data = graphene.JSONString(
            required=False,
            description=(
                "Client-side generated data required to finalize the payment."
            ),
        )

    class Meta:
        description = (
            "Completes the checkout. As a result a new order is created and "
            "a payment charge is made. This action requires a successful "
            "payment before it can be performed. "
            "In case additional confirmation step as 3D secure is required "
            "confirmationNeeded flag will be set to True and no order created "
            "until payment is confirmed with second call of this mutation."
        )
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def update_app_code_in_order(cls,order,app_code):
        if not order.app_code:
            order.app_code=app_code
            order.save()

    @classmethod
    def map_order_with_store(cls, order_instance, store_instance, is_streak_order):
        
        if not order_instance:
            raise ValidationError(message="Order not created")

        order_models.OrderStore.create_instance({
            'order_instance': order_instance,
            'store_instance': store_instance,
            "streak_order": is_streak_order
        })

        logger.info(
            "order_id %s mapped with store-id :: %s  ", order_instance.id, store_instance.id
        )
    
    def is_streak_order(store):
        return store.is_streak_live()
               
    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, store_source, **data):
        logger.info(f'complete checkout started for :: {checkout_id}, with data :: {data}')
        tracking_code = analytics.get_client_id(info.context)
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        app_code = RequestUtilities.get_app_code_from_headers(info.context)
        platform_code = RequestUtilities.get_platfrom_type_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        
        if not store_instance:
            raise ValidationError(message="Invalid store id")

        is_streak_order = cls.is_streak_order(store_instance)

        if is_streak_order and platform_code=='IS':
            is_streak_order = True
        else:
            is_streak_order = False
            
        with transaction_with_commit_on_errors():
            try:
                checkout = cls.get_node_or_error(
                    info,
                    checkout_id,
                    only_type=Checkout,
                    field="checkout_id",
                    qs=models.Checkout.objects.select_for_update(of=("self",))
                    .prefetch_related(
                        "gift_cards",
                        "lines__variant__product",
                        Prefetch(
                            "payments",
                            queryset=payment_models.Payment.objects.prefetch_related(
                                "order__lines"
                            ),
                        ),
                    )
                    .select_related("shipping_method__shipping_zone"),
                )
            except ValidationError as e:
                checkout_token = from_global_id_strict_type(
                    checkout_id, Checkout, field="checkout_id"
                )

                order = order_models.Order.objects.get_by_checkout_token(checkout_token)
                
                if order:
                    # The order is already created. We return it as a success
                    # checkoutComplete response. Order is anonymized for not logged in
                    # user
                    

                    cls.map_order_with_store(order, store_instance, is_streak_order)

                    return CheckoutComplete(
                        order=order, confirmation_needed=False, confirmation_data={}
                    )
                logger.info("Exception raised in CheckoutComplete ::%s", e)
                
                raise e

            order, action_required, action_data = complete_checkout(
                checkout=checkout,
                payment_data=data.get("payment_data", {}),
                store_source=store_source,
                discounts=info.context.discounts,
                user=info.context.user,
                tracking_code=tracking_code,
                redirect_url=data.get("redirect_url"),
                streak_order = is_streak_order,
            )
            cls.update_app_code_in_order(order,app_code)
            cls.map_order_with_store(order, store_instance, is_streak_order)
        
        logger.info(f'CheckotComplete mutation completed for token :: {checkout.token}, with order id :: {order.id}')

        order_engine_instance = OrderEngine()
        warehouse_id = get_default_warehouse_id()
        create_fulfillment_task.delay(order.id,warehouse_id,store_id)
        # If gateway returns information that additional steps are required we need
        # to inform the frontend and pass all required data
        
        try:
            logger.info("Order engine started for order_id ::%s", order.id)
            response = order_engine_instance.place_order(order)
            logger.info("Response generated from order engine :: %s", response)
        
        except Exception as e:
            logger.info("Engine Exception raised for order:: %s", order.id)
            logger.info(e)

    
        create_fresh_desk_order_ticket_cod_order_task.delay(order.id)

        return CheckoutComplete(
            order=order,
            confirmation_needed=action_required,
            confirmation_data=action_data,
        )


class CheckoutAddPromoCode(BaseMutation):
    checkout = graphene.Field(
        Checkout, description="The checkout with the added gift card or voucher."
    )

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.", required=True)
        promo_code = graphene.String(
            description="Gift card code or voucher code.", required=True
        )

    class Meta:
        description = "Adds a gift card or a voucher to a checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"
    
    @classmethod
    def preprocess_promo_code(cls,promo_code):

        remove_space = promo_code.replace(" ","")
        return remove_space
    
    @classmethod
    def update_checkoutline_discounts(cls, lines, voucher):
        for line in lines:
            line_discount =  get_voucher_discount_for_checkoutline(line, voucher)
            line.data.update({'discount_amount': float(line_discount.amount)})
            line.save()

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, promo_code):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        app_code = RequestUtilities.get_app_code_from_headers(info.context)
        lines = list(checkout)
        platform_code = RequestUtilities.get_platfrom_type_from_headers(info.context)
        promo_code = cls.preprocess_promo_code(promo_code)

        logger.info(f"CheckoutAddPromoCode started with voucher code :: {promo_code}, checkout token : {checkout.token}, app_code :: {app_code}, platform_type :: {platform_code}, store_id :: {store_id}")

        add_promo_code_to_checkout(checkout, lines, promo_code, info.context.discounts, store_id,platform_code,app_code)
        
        voucher = Voucher.objects.filter(code=checkout.voucher_code).first()
        if checkout.voucher_code and voucher:
            cls.update_checkoutline_discounts(lines, voucher)

        #info.context.plugins.checkout_updated(checkout)
        return CheckoutAddPromoCode(checkout=checkout)


class CheckoutRemovePromoCode(BaseMutation):
    checkout = graphene.Field(
        Checkout, description="The checkout with the removed gift card or voucher."
    )

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.", required=True)
        promo_code = graphene.String(
            description="Gift card code or voucher code.", required=True
        )

    class Meta:
        description = "Remove a gift card or a voucher from a checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def update_checkoutline_discounts(cls, lines):
        for line in lines:
            line.data.update({'discount_amount': 0})
            line.save()

    @classmethod
    def perform_mutation(cls, _root, info, checkout_id, promo_code):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        logger.info(f"CheckoutRemovePromoCode : checkout token :: {checkout.token}, promo code :: {promo_code}")
        remove_promo_code_from_checkout(checkout, promo_code, store_id)
        lines = list(checkout)
        cls.update_checkoutline_discounts(lines)
        info.context.plugins.checkout_updated(checkout)
        return CheckoutRemovePromoCode(checkout=checkout)


class CheckoutUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates metadata for checkout."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        model = models.Checkout
        public = True
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"


class CheckoutUpdatePrivateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates private metadata for checkout."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        model = models.Checkout
        public = False
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"


class CheckoutClearMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clear metadata for checkout."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        model = models.Checkout
        public = True
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"


class CheckoutClearPrivateMeta(ClearMetaBaseMutation):
    class Meta:
        description = "Clear private metadata for checkout."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        model = models.Checkout
        public = False
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

class AttachCheckoutToZaamo(BaseMutation):

    success = graphene.Boolean(description="The checkout with the removed gift card or voucher.")

    class Arguments:
        checkout_id = graphene.ID(description="Checkout ID.", required=True)

    class Meta:
        description = "Add a zaamo store to checkout."
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    
    @classmethod
    def perform_mutation(cls, _root, info, checkout_id):
        checkout = cls.get_node_or_error(
            info, checkout_id, only_type=Checkout, field="checkout_id"
        )
        success=False
        try:
            success=True
            checkout_store = models.CheckoutStore.objects.filter(token_id = checkout.token).first()
            store = StoreInfo.objects.filter(slug='zaamo').first()
            checkout_store.store = store
            checkout_store.save()
        except Exception as e:
            logger.info(e)

        return AttachCheckoutToZaamo(success=success)
