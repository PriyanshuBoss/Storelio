from django.core.exceptions import ValidationError
import graphene
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.woo_commerce_service.tasks import initiate_product_onboarding_woo_commerce
from saleor.graphql.core.mutations import BaseMutation
class WooCommerceConnect(BaseMutation):
    
    class Arguments:
        store_access_key = graphene.String(description="access key of woocommerce store", required=False)
        store_access_pass = graphene.String(description="access password of woocommerce store", required=False)
        shop_url = graphene.String(description="shop url", required=True)
    
    class Meta:
        description = "Onboard Woo Commerce Store"

    success = graphene.Boolean(description="Store Onboarding status")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        
        store_access_key = data.get('store_access_key')
        store_access_pass = data.get('store_access_pass')
        store_url = data.get('shop_url')
        woocommerce_cred_dict = {
            'store_access_key': store_access_key,
            'store_access_pass': store_access_pass,
            'store_url': store_url
        }

        if not store_access_key and store_access_pass:
            raise ValidationError(message="In-valid api credentials")

        woocommerce_impl_inst = WooCommerceImpl(store_url)
        
        store_insert_res = woocommerce_impl_inst.insert_store_data_from_woocommerce_store(woocommerce_cred_dict)
        shop = store_insert_res.get('shop')

        if not shop:
            raise ValidationError(message="In-valid shop credentials")

        woocommerce_impl_inst.create_webhooks_for_woo_commerce_store()

        initiate_product_onboarding_woo_commerce.delay(shop)

        return cls(success=True)
