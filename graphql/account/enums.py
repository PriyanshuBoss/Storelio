import graphene
from django_countries import countries

from ...account import CustomerEvents
from ...checkout import AddressType
from ...graphql.core.enums import to_enum
from ..core.utils import str_to_enum
from ...account.states import RegisterUserType, InfluencerStatus, UserMediaType

AddressTypeEnum = to_enum(AddressType, type_name="AddressTypeEnum")
CustomerEventsEnum = to_enum(CustomerEvents)
RegisterUserTypeEnum = to_enum(RegisterUserType)
InfluencerStatusEnums = to_enum(InfluencerStatus, type_name="InfluencerStatusEnum")
UserMediaTypeEnums = to_enum(UserMediaType, type_name="UserMediaTypeEnum")

CountryCodeEnum = graphene.Enum(
    "CountryCode", [(str_to_enum(country[0]), country[0]) for country in countries]
)


class StaffMemberStatus(graphene.Enum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"

class InfluencerStateEnum(graphene.Enum):
    NOT_VERIFIED = 0
    VERIFIED = 1
