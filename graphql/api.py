from saleor.graphql.analytics.schema import DashboardQueries, pdpPublishProductMutation
from saleor.graphql.store.schema import StoreMutations, StoreQueries
from graphene_federation import build_schema
from saleor.graphql.support.schema import SupportMutations, SupportQueries, EmailSendingMutations

from saleor.graphql.wishlist.schema import WishlistMutations, WishlistQueries

from .account.schema import AccountMutations, AccountQueries
from .app.schema import AppMutations, AppQueries
from .checkout.schema import CheckoutMutations, CheckoutQueries
from .core.schema import CoreQueries
from .csv.schema import CsvMutations, CsvQueries
from .discount.schema import DiscountMutations, DiscountQueries
from .giftcard.schema import GiftCardMutations, GiftCardQueries
from .invoice.schema import InvoiceMutations
from .menu.schema import MenuMutations, MenuQueries
from .meta.schema import MetaMutations
from .order.schema import OrderMutations, OrderQueries
from .page.schema import PageMutations, PageQueries
from .payment.schema import PaymentMutations, PaymentQueries
from .plugins.schema import PluginsMutations, PluginsQueries
from .product.schema import ProductMutations, ProductQueries
from .shipping.schema import ShippingMutations, ShippingQueries
from .shop.schema import ShopMutations, ShopQueries
from .translations.schema import TranslationQueries
from .warehouse.schema import StockQueries, WarehouseMutations, WarehouseQueries
from .webhook.schema import WebhookMutations, WebhookQueries
from saleor.graphql.brand.schema import BrandMutations, BrandQueries
from .external_services.schema import AchaIndiaConnectMutation, MyDukaanConnectMutation, OtpMutation, ShopifyAuthMutation, CustomBrandConnectMutation, WooCommerceConnectMutation
from .integrations.schema import IntegrationMutations
from saleor.graphql.notifications.schema import NotificationMutations, NotificationsQueries

class Query(
    AccountQueries,
    AppQueries,
    CheckoutQueries,
    CoreQueries,
    CsvQueries,
    DiscountQueries,
    PluginsQueries,
    GiftCardQueries,
    MenuQueries,
    OrderQueries,
    PageQueries,
    PaymentQueries,
    ProductQueries,
    ShippingQueries,
    ShopQueries,
    StockQueries,
    TranslationQueries,
    WarehouseQueries,
    WebhookQueries,
    BrandQueries,
    StoreQueries,
    WishlistQueries,
    SupportQueries,
    DashboardQueries,
    NotificationsQueries

):
    pass


class Mutation(
    AccountMutations,
    AppMutations,
    CheckoutMutations,
    CsvMutations,
    DiscountMutations,
    PluginsMutations,
    GiftCardMutations,
    IntegrationMutations,
    InvoiceMutations,
    MenuMutations,
    MetaMutations,
    OrderMutations,
    PageMutations,
    PaymentMutations,
    ProductMutations,
    ShippingMutations,
    ShopMutations,
    WarehouseMutations,
    WebhookMutations,
    BrandMutations,
    OtpMutation,
    StoreMutations,
    WishlistMutations,
    SupportMutations,
    NotificationMutations,
    EmailSendingMutations,
    ShopifyAuthMutation,
    WooCommerceConnectMutation,
    pdpPublishProductMutation,
    AchaIndiaConnectMutation,
    CustomBrandConnectMutation,
    MyDukaanConnectMutation
):
    pass


schema = build_schema(Query, mutation=Mutation)
