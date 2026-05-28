import graphene
from saleor.graphql.brand.mutations import BrandCreate, BrandBankAccountCreate, BrandMobileDelete, BrandUpdate, BrandUpiIdCreate, DeactivateBrandAccount, BrandManagerCreate, BrandCommissionCreateUpdate, BrandEmailCreate, BrandEmailUpdate, BrandEmailDelete, BrandShippingDataCreate, BrandShippingDataUpdate, BrandShippingDataDelete
from saleor.graphql.brand.sorters import BrandCollectionOrder, BrandSortingInput , BrandPayoutSortingInput
from ..core.fields import FilterInputConnectionField
from saleor.graphql.brand.types import Brand , BrandGrouping , BrandPayout, BrandCollection, BrandTag
from saleor.graphql.brand.filters import BrandFilterInput , BrandGroupingFilterInput, BrandCollectionFilterInput, BrandTagFilterInput
from saleor.graphql.brand.resolvers import resolve_brand_collections, resolve_payout_for_brand, resolve_botd_brands, resolve_brand_from_slug

class BrandQueries(graphene.ObjectType):
    brands = FilterInputConnectionField(
        Brand,
        filter=BrandFilterInput(description="Filtering options for Brands."),
        sort_by=BrandSortingInput(description="Sort brands."),
        description="List of the Brands.",
    )

    botd_brands = FilterInputConnectionField(
        Brand,
        filter=BrandFilterInput(description="Filtering options for Botd Brands."),
        sort_by=BrandSortingInput(description="Sort Botd brands."),
        description="List of the Botd Brands.",
    )

    brand = graphene.Field(
        Brand,
        description="Look up an brand by ID.",
        id=graphene.Argument(graphene.ID, description="ID of an brand."),
        slug=graphene.Argument(graphene.String, description="slug of an brand."),
    )
    brand_groups = FilterInputConnectionField(
        BrandGrouping,
        filter=BrandGroupingFilterInput(description="Filtering options for brand_groups."),
        description = "brand groups")
    
    brand_payout = FilterInputConnectionField(
        BrandPayout,
        brand_id = graphene.Argument(graphene.ID , description = "Brand id for Brand Payout" , required = True),
        sort_by = BrandPayoutSortingInput(),
        description = "Brand Payout details"
    )

    brand_collections = FilterInputConnectionField(
        BrandCollection,
        filter = BrandCollectionFilterInput(description="Filtering options for brand collections."),
        sort_by=BrandCollectionOrder(description="Sort brand collections."),
        description = "brand collections")

    brand_tags = FilterInputConnectionField(
        BrandTag,
        filter = BrandTagFilterInput(description="Filtering options for brand tags."),
        description = "brand tags")

    def resolve_brand(self, info, **data):
        
        if data.get('slug'):
            return resolve_brand_from_slug(data.get('slug'))

        return graphene.Node.get_node_from_global_id(info, data.get('id'), Brand)

    def resolve_botd_brands(self, info, **data):
        return resolve_botd_brands(self, info, **data)

    def resolve_brand_payout(self,info,brand_id,**data):
        brand_id = graphene.Node.from_global_id(brand_id)[1]
        return resolve_payout_for_brand(brand_id)

    def resolve_brand_collections(self,info,**data):
        return resolve_brand_collections()

class BrandMutations(graphene.ObjectType):
    brand_create = BrandCreate.Field()
    brand_update = BrandUpdate.Field()
    brand_bank_account_create = BrandBankAccountCreate.Field()
    brand_upi_id_create = BrandUpiIdCreate.Field()
    deactivate_brand_account = DeactivateBrandAccount.Field()
    brand_manager_create = BrandManagerCreate.Field()
    brand_commission_create_update = BrandCommissionCreateUpdate.Field()
    brand_email_create = BrandEmailCreate.Field()
    brand_email_update = BrandEmailUpdate.Field()
    brand_email_delete = BrandEmailDelete.Field()
    brand_mobile_delete = BrandMobileDelete.Field()
    brand_shipping_data_create = BrandShippingDataCreate.Field()
    brand_shipping_data_update = BrandShippingDataUpdate.Field()
    brand_shipping_data_delete = BrandShippingDataDelete.Field()
