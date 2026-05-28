import graphene
from saleor.warehouse import models as warehouse_models


def resolve_warehouse(info):
    
    try:
        warehouse = warehouse_models.Warehouse.objects.get(slug='zaamo-master-warehouse')
    except:
        warehouse = None

    if warehouse:

        return graphene.Node.to_global_id("Warehouse", warehouse.id)

    return None
