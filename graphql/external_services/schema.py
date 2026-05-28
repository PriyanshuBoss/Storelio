from saleor.graphql.external_services.AchaIndiaAuth.mutations import AchaIndiaConnect
from saleor.graphql.external_services.CustomBrandAuth.mutations import CustomBrandConnect
from saleor.graphql.external_services.MyDukaanAuth.mutations import MyDukaanAuth
from saleor.graphql.external_services.otp.mutations import GenerateOtp, VerifyOtp
from saleor.graphql.external_services.ShopifyAuth.mutations import ShopifyAuth
from saleor.graphql.external_services.WooCommerceAuth.mutations import WooCommerceConnect

import graphene

class OtpMutation(graphene.ObjectType):
   generate_otp = GenerateOtp.Field()
   verify_otp = VerifyOtp.Field()

class ShopifyAuthMutation(graphene.ObjectType):
   shopify_auth = ShopifyAuth.Field()


class WooCommerceConnectMutation(graphene.ObjectType):
   woo_commerce_connect = WooCommerceConnect.Field()

class AchaIndiaConnectMutation(graphene.ObjectType):
   acha_india_connect = AchaIndiaConnect.Field()


class CustomBrandConnectMutation(graphene.ObjectType):
   custom_brand_connect = CustomBrandConnect.Field()


class MyDukaanConnectMutation(graphene.ObjectType):
   my_dukaan_connect = MyDukaanAuth.Field()