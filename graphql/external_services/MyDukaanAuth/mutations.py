from django.core.exceptions import ValidationError
import graphene
from saleor.external_services.mydukaan_service.mydukaan_impl import MyDukaanImpl
from saleor.external_services.mydukaan_service.tasks import initiate_product_onboarding_mydukaan
from saleor.graphql.core.mutations import BaseMutation

class MyDukaanAuth(BaseMutation):
    
    class Arguments:
        bearer_token = graphene.String(description="Bearer Token of the store")
        name = graphene.String(description="Name of store")
    
    class Meta:
        description = "Onboard Dukaan integrated brands"

    success = graphene.Boolean(description="Onboarding status")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        bearer_token = data.get('bearer_token')
        
        mydukaan_impl_inst = MyDukaanImpl()
        
        store_insert_res = mydukaan_impl_inst.insert_store_data_from_mydukaan_store(bearer_token)
        shop = store_insert_res.get('shop')
        if not shop:
            raise ValidationError(message="In-valid shop credentials")
        shop['token']=bearer_token
        
        initiate_product_onboarding_mydukaan.delay(shop)
        
        return cls(success=True)
