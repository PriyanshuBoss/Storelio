from django.core.exceptions import ValidationError
import graphene
from saleor.external_services.acha_india_service.acha_india_impl import AchaIndiaImpl
from saleor.external_services.acha_india_service.tasks import initiate_product_onboarding_acha_india
from saleor.graphql.core.mutations import BaseMutation
class AchaIndiaConnect(BaseMutation):
    
    class Meta:
        description = "Onboard Acha India Store"

    success = graphene.Boolean(description="Store Onboarding status")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        
        initiate_product_onboarding_acha_india.delay()

        return cls(success=True)
