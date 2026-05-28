from django.core.exceptions import ValidationError
import graphene
from saleor.external_services.style_stree_service.style_stree_impl import StyleStreeImpl
from saleor.external_services.style_stree_service.tasks import initiate_product_onboarding_style_stree
from saleor.external_services.the_souled_store_service.tasks import initiate_product_onboarding_souled_store
from saleor.external_services.the_souled_store_service.the_souled_store_impl import TheSouledStoreImpl
from saleor.graphql.core.mutations import BaseMutation

class CustomBrandTypeEnum(graphene.Enum):
    STYLESTREE = "stylestree"
    SHOETOPIA = "shoetopia"
    THESOULEDSTORE = "thesouledstore"

class CustomBrandConnect(BaseMutation):
    
    class Arguments:
        store_url = graphene.String(description="store url of store", required=False)
        products_api_endpoint = graphene.String(description="product enpoint", required=False)
        order_url = graphene.String(description="order url", required=False)
        brand_type = CustomBrandTypeEnum(description="type of brand", required=False)
        brand_name = graphene.String(description="Brand name", required=False)
        api_key = graphene.String(description="api_key", required=False)
    
    class Meta:
        description = "Onboard Custom Brand"

    success = graphene.Boolean(description="Store Onboarding status")

    @classmethod
    def perform_mutation(cls, root, info, **data):

        if data.get('brand_type')==CustomBrandTypeEnum.STYLESTREE:
            inst = StyleStreeImpl()
            data['name']=data.get('brand_name')
            store_insert_res = inst.insert_store_data_from_style_stree_brand_store(data)
            initiate_product_onboarding_style_stree.delay(data)

            return cls(success=True)

        if data.get('brand_type')==CustomBrandTypeEnum.SHOETOPIA:
            inst = StyleStreeImpl()
            data['name']=data.get('brand_name')
            
            store_insert_res = inst.insert_store_data_from_style_stree_brand_store(data) #Being used for shoetopia since it is sub brand of style stree
            initiate_product_onboarding_style_stree.delay(data)

            return cls(success=True)
        
        
        if data.get('brand_type')==CustomBrandTypeEnum.THESOULEDSTORE:
            inst = TheSouledStoreImpl()
            data['name']=data.get('brand_name')
            
            store_insert_res = inst.insert_store_data_from_souled_store_store(data)
            initiate_product_onboarding_souled_store.delay(data)

            return cls(success=True)

        return cls(success=False)
