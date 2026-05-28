import graphene
from graphene import relay
from saleor.graphql.meta.types import ObjectWithMetadata
from django.conf import settings
from ...discount import models
from django.utils import timezone
from ..core import types
from ..core.connection import CountableDjangoObjectType
from ..core.fields import PrefetchingConnectionField
from ..product.types import Category, Collection, Product
from ..brand.types import Brand
from ..translations.fields import TranslationField
from ..translations.types import SaleTranslation, VoucherTranslation
from .enums import DiscountValueTypeEnum, VoucherTypeEnum
from .resolvers import resolve_store_slug
from saleor.utilities.request_utilities import RequestUtilities
from graphene_federation import key


class Sale(CountableDjangoObjectType):
    categories = PrefetchingConnectionField(
        Category, description="List of categories this sale applies to."
    )
    collections = PrefetchingConnectionField(
        Collection, description="List of collections this sale applies to."
    )
    products = PrefetchingConnectionField(
        Product, description="List of products this sale applies to."
    )
    translation = TranslationField(SaleTranslation, type_name="sale")

    class Meta:
        description = (
            "Sales allow creating discounts for categories, collections or products "
            "and are visible to all the customers."
        )
        interfaces = [relay.Node]
        model = models.Sale
        only_fields = ["end_date", "id", "name", "start_date", "type", "value"]

    @staticmethod
    def resolve_categories(root: models.Sale, *_args, **_kwargs):
        return root.categories.all()

    @staticmethod
    def resolve_collections(root: models.Sale, info, **_kwargs):
        return root.collections.visible_to_user(info.context.user)

    @staticmethod
    def resolve_products(root: models.Sale, info, **_kwargs):
        return root.products.visible_to_user(info.context.user)


class Voucher(CountableDjangoObjectType):
    categories = PrefetchingConnectionField(
        Category, description="List of categories this voucher applies to."
    )
    brands = PrefetchingConnectionField(
        Brand, description="List of Brands this voucher applies to."
    )
    collections = PrefetchingConnectionField(
        Collection, description="List of collections this voucher applies to."
    )
    products = PrefetchingConnectionField(
        Product, description="List of products this voucher applies to."
    )
    countries = graphene.List(
        types.CountryDisplay,
        description="List of countries available for the shipping voucher.",
    )
    translation = TranslationField(VoucherTranslation, type_name="voucher")
    discount_value_type = DiscountValueTypeEnum(
        description="Determines a type of discount for voucher - value or percentage",
        required=True,
    )
    store = graphene.Field('saleor.graphql.store.types.Store', description="vouchor applicable on  store")
    user = graphene.Field('saleor.graphql.account.types.User', description="creator of vouchar")
    
    type = VoucherTypeEnum(description="Determines a type of voucher.", required=True)

    active = graphene.Boolean(description="If coupon is active or not, based on date and used")

    is_applicable = graphene.Boolean(description = "If coupon is currently applicable or not ")

    shareable_link  = graphene.String(description = "Shareable link of voucher")

    class Meta:
        description = (
            "Vouchers allow giving discounts to particular customers on categories, "
            "collections or specific products. They can be used during checkout by "
            "providing valid voucher codes."
        )
        only_fields = [
            "apply_once_per_order",
            "apply_once_per_customer",
            "code",
            "discount_value",
            "discount_value_type",
            "end_date",
            "id",
            "min_spent",
            "min_checkout_items_quantity",
            "name",
            "start_date",
            "type",
            "usage_limit",
            "used",
            "is_shipping",
            "max_discount"
        ]
        interfaces = [relay.Node, ObjectWithMetadata]
        model = models.Voucher

    @staticmethod
    def resolve_categories(root: models.Voucher, *_args, **_kwargs):
        return root.categories.all()
    
    @staticmethod
    def resolve_brands(root: models.Voucher, *_args, **_kwargs):
        return root.brands.all()
    
    def resolve_active(root: models.Voucher, *_args, **_kwargs):

        return models.Voucher.objects.active(timezone.now()).filter(id=root.id).exists()

    @staticmethod
    def resolve_collections(root: models.Voucher, info, **_kwargs):
        return root.collections.all()

    @staticmethod
    def resolve_products(root: models.Voucher, info, **_kwargs):
        return root.products.visible_to_user(info.context.user)

    @staticmethod
    def resolve_countries(root: models.Voucher, *_args, **_kwargs):
        return [
            types.CountryDisplay(code=country.code, country=country.name)
            for country in root.countries
        ]
    
    @staticmethod
    def resolve_is_applicable(root:models.Voucher , *_args,**_kwargs):
        return getattr(root, 'is_applicable', None)

    def resolve_shareable_link(root:models.Voucher,info):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store = resolve_store_slug(store_id)
        if not store:
            return None
        collection = root.collections.first()
        brand = root.brands.first()

        if collection:
            collection_slug = collection.slug
            return "{}{}/collection/{}".format(settings.ZAAMO_ENV_LINK,store.slug,collection_slug)
        if brand:
            brand_id  = brand.id
            glob_brand_id = graphene.Node.to_global_id("Brand",brand_id)
            return "{}{}/explore-brands/{}".format(settings.ZAAMO_ENV_LINK,store.slug,glob_brand_id)


@key(fields="id")
class VoucherStoreDeal(CountableDjangoObjectType):
    class Meta:
        description = "Voucher Store Deal"
        interfaces = [relay.Node]
        model = models.VoucherStoreDealMapping
