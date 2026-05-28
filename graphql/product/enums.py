import graphene

from saleor.product.states import ProductGroupingEnum

from ...product import AttributeInputType,SourcingRequestStatus, BrandCollabStatusForSouringRequest
from ..core.enums import to_enum

AttributeInputTypeEnum = to_enum(AttributeInputType)
SourcingRequestStatusTypeEnum = to_enum(SourcingRequestStatus)
BrandCollabStatusForSouringRequestEnum = to_enum(BrandCollabStatusForSouringRequest)
productgroupingenum = to_enum(ProductGroupingEnum)

class AttributeTypeEnum(graphene.Enum):
    PRODUCT = "PRODUCT"
    VARIANT = "VARIANT"


class AttributeValueType(graphene.Enum):
    COLOR = "COLOR"
    GRADIENT = "GRADIENT"
    URL = "URL"
    STRING = "STRING"


class StockAvailability(graphene.Enum):
    IN_STOCK = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class CollectionPublished(graphene.Enum):
    PUBLISHED = "published"
    HIDDEN = "hidden"


class ProductTypeConfigurable(graphene.Enum):
    CONFIGURABLE = "configurable"
    SIMPLE = "simple"


class ProductTypeEnum(graphene.Enum):
    DIGITAL = "digital"
    SHIPPABLE = "shippable"

class CollectionMediaTypeEnum(graphene.Enum):
    IMAGE = "image"
    VIDEO = "video"


class CollectionType(graphene.Enum):
    ZAAMO_CURATION = "zaamo_curation"
    BRAND_CURATION = "brand_curation"
