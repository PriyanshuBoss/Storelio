import graphene

from ...core.models import ModelWithMetadata
from .resolvers import (
    resolve_metadata,
    resolve_object_with_metadata_type,
    resolve_private_metadata,
)


class MetadataItem(graphene.ObjectType):
    key = graphene.String(required=True, description="Key of a metadata item.")
    value = graphene.String(required=True, description="Value of a metadata item.")


class ObjectWithMetadata(graphene.Interface):
    private_metadata = graphene.List(
        MetadataItem,
        required=True,
        description=(
            "List of private metadata items."
            "Requires proper staff permissions to access."
        ),
    )
    metadata = graphene.List(
        MetadataItem,
        required=True,
        description=(
            "List of public metadata items. Can be accessed without permissions."
        ),
    )

    # Deprecated we should remove it in #5221
    private_meta = graphene.List(
        "saleor.graphql.meta.deprecated.types.MetaStore",
        required=True,
        description="List of privately stored metadata namespaces.",
        deprecation_reason=(
            "Use the `privetaMetadata` field. This field will be removed after "
            "2020-07-31."
        ),
    )
    meta = graphene.List(
        "saleor.graphql.meta.deprecated.types.MetaStore",
        required=True,
        description="List of publicly stored metadata namespaces.",
        deprecation_reason=(
            "Use the `metadata` field. This field will be removed after 2020-07-31."
        ),
    )

    @staticmethod
    def resolve_metadata(root: ModelWithMetadata, _info):
        return resolve_metadata(root.metadata)

    @staticmethod
    def resolve_private_metadata(root: ModelWithMetadata, info):
        return resolve_private_metadata(root, info)

    @classmethod
    def resolve_type(cls, instance: ModelWithMetadata, _info):
        return resolve_object_with_metadata_type(instance)

'''
Below are Types for Product Grouping Mapping which have use static data from groupingmapping metadata to recreate product types
'''

class BrandForGrouping(graphene.ObjectType):
    id = graphene.ID(description="id of brand")
    brand_name = graphene.String(description="Name of the brand")
    commission_percentage = graphene.String(description = 'Commision Percentage on product level')



class ImageForGrouping(graphene.ObjectType):
    url = graphene.String(description="url of thumbnail")


class MoneyForGrouping(graphene.ObjectType):
    amount = graphene.Float(description="money")


class priceUndiscountedForGrouping(graphene.ObjectType):

    gross = graphene.Field(MoneyForGrouping, description="money")

    
class VariantPricingInfoForGrouping(graphene.ObjectType):

    price_undiscounted = graphene.Field(priceUndiscountedForGrouping, description="money")
class ProductVariantForGrouping(graphene.ObjectType):
    id = graphene.ID(description="url of thumbnail")
    cost_price = graphene.Field(MoneyForGrouping,description="url of thumbnail")
    pricing = graphene.Field(VariantPricingInfoForGrouping,description="url of thumbnail")



'''
Product grouping Mapping types END
'''
