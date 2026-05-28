import graphene

from ...core.permissions import ShippingPermissions
from ..core.fields import PrefetchingConnectionField
from ..decorators import permission_required
from ..translations.mutations import ShippingPriceTranslate
from .bulk_mutations import ShippingPriceBulkDelete, ShippingZoneBulkDelete
from .mutations import (
    ShippingPriceCreate,
    ShippingPriceDelete,
    ShippingPriceUpdate,
    ShippingZoneCreate,
    ShippingZoneDelete,
    ShippingZoneUpdate,
)
from .resolvers import resolve_shipping_zones,resolve_data_by_postal
from .types import ShippingZone,ZipcodeData
from saleor.graphql.account.enums import CountryCodeEnum 


class ShippingQueries(graphene.ObjectType):
    shipping_zone = graphene.Field(
        ShippingZone,
        id=graphene.Argument(
            graphene.ID, description="ID of the shipping zone.", required=True
        ),
        description="Look up a shipping zone by ID.",
    )
    shipping_zones = PrefetchingConnectionField(
        ShippingZone, description="List of the shop's shipping zones."
    )

    data_by_pincode = graphene.Field(ZipcodeData,pincode = graphene.Argument(graphene.String, description="Pincode for data retrieval",required = True),
                        country = CountryCodeEnum(description="Country for data retrieval",required = False))

    data_by_pincodes = graphene.List(ZipcodeData , pincodes = graphene.Argument(graphene.List(graphene.String) , description = "List of string of pincodes"))

    @permission_required(ShippingPermissions.MANAGE_SHIPPING)
    def resolve_shipping_zone(self, info, id):
        return graphene.Node.get_node_from_global_id(info, id, ShippingZone)

    @permission_required(ShippingPermissions.MANAGE_SHIPPING)
    def resolve_shipping_zones(self, info, **_kwargs):
        return resolve_shipping_zones(info)

    def resolve_data_by_pincode(self,info,pincode,country='IN'):
        zipcode_data = resolve_data_by_postal(info,pincode,country)
        return ZipcodeData(city = zipcode_data.get('city'),state = zipcode_data.get('state'),country = zipcode_data.get('country'),error = zipcode_data.get('error'))
    
    def resolve_data_by_pincodes(self,info,pincodes=[]):
        zipcodes = []
        country = 'IN'
        for pincode in pincodes:
            zipcode_data = resolve_data_by_postal(info,pincode,country)
            zipcodes.append(ZipcodeData(city = zipcode_data.get('city'),state = zipcode_data.get('state'),country = zipcode_data.get('country'),error = zipcode_data.get('error')))
        
        return zipcodes

class ShippingMutations(graphene.ObjectType):
    shipping_price_create = ShippingPriceCreate.Field()
    shipping_price_delete = ShippingPriceDelete.Field()
    shipping_price_bulk_delete = ShippingPriceBulkDelete.Field()
    shipping_price_update = ShippingPriceUpdate.Field()
    shipping_price_translate = ShippingPriceTranslate.Field()

    shipping_zone_create = ShippingZoneCreate.Field()
    shipping_zone_delete = ShippingZoneDelete.Field()
    shipping_zone_bulk_delete = ShippingZoneBulkDelete.Field()
    shipping_zone_update = ShippingZoneUpdate.Field()
