from django.core.exceptions import ValidationError
import graphene
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.external_services.shopify_service.tasks import initiate_product_onboarding_shopify
from saleor.graphql.core.mutations import BaseMutation

class ShopifyAuth(BaseMutation):
    
    class Arguments:
        store_access_key = graphene.String(description="access key of shopify store")
        store_access_pass = graphene.String(description="access password of shopify store")
        shop_url = graphene.String(description="shop url")
        api_version = graphene.String(description="api version")
    
    class Meta:
        description = "generates auth token for shopify store"

    success = graphene.Boolean(description="Auth token generation status")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        store_access_key = data.get('store_access_key')
        store_access_pass = data.get('store_access_pass')
        store_url = data.get('shop_url')
        api_version = data.get('api_version', 'unstable')
        
        shopify_cred_dict = {
            'store_access_key': store_access_key,
            'store_access_pass': store_access_pass,
            'store_url': store_url,
            'api_version': api_version
        }
        shopify_impl_inst = ShopifyImpl(shopify_cred_dict)
        
        auth_token = shopify_impl_inst.generate_shopify_auth_token(store_access_key, store_access_pass)
        store_insert_res = shopify_impl_inst.insert_store_data_from_shopify_store(store_access_key, store_access_pass, \
                                                                        auth_token, store_url, api_version)
        shop = store_insert_res.get('shop')
        shopify_cred_dict['store_url'] = shop.myshopify_domain
        
        if not shop:
            raise ValidationError(message="In-valid shop credentials")
        
        shopify_impl_inst.create_webhooks_for_shopify_store()
        initiate_product_onboarding_shopify.delay(shopify_cred_dict)
        
        return cls(success=True)
