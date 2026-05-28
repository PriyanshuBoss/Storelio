import graphene
from .mutations import BaseProductCreateUpdateMutation,VariantInventoryUpdate

class IntegrationMutations(graphene.ObjectType):
    base_product_create_update = BaseProductCreateUpdateMutation.Field()
    variant_inventory_update = VariantInventoryUpdate.Field()
