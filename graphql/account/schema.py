from unicodedata import decomposition
import graphene

from ...core.permissions import AccountPermissions, AppPermission
from ..core.fields import FilterInputConnectionField
from ..core.types import FilterInputObjectType
from ..decorators import one_of_permissions_required, permission_required
from .bulk_mutations import CustomerBulkDelete, StaffBulkDelete, UserBulkSetActive
from .deprecated.mutations_service_account import (
    ServiceAccountClearPrivateMeta,
    ServiceAccountCreate,
    ServiceAccountDelete,
    ServiceAccountTokenCreate,
    ServiceAccountTokenDelete,
    ServiceAccountUpdate,
    ServiceAccountUpdatePrivateMeta,
)
from .deprecated.resolvers import resolve_service_accounts
from .deprecated.sorters import ServiceAccountSortingInput
from .deprecated.types import ServiceAccount, ServiceAccountFilterInput
from .enums import CountryCodeEnum
from .filters import CustomerFilter, PermissionGroupFilter, StaffUserFilter,InfluencerFilter, UserMediaFilterInput
from .mutations.account import (
    AccountAddressCreate,
    AccountAddressDelete,
    AccountAddressUpdate,
    AccountDelete,
    AccountRegister,
    AccountRequestDeletion,
    AccountSetDefaultAddress,
    AccountUpdate,
    AccountUpdateMeta,
    ActivateAccount,
    ActivateBrandAccount,
    ConfirmEmailChange,
    InfluencerBankAccountCreate,
    InfluencerInstagramAccountConnect,
    InfluencerManualAccountVerification,
    InfluencerUpdate,
    InfluencerUpiIdCreate,
    LikeUnlikeContent,
    RequestEmailChange,
    InfluencerAccountRegister,
    UserRegister,
    UserMediaCreate,
    FollowUnfollowUser
)
from .mutations.base import (
    ConfirmAccount,
    PasswordChange,
    RequestPasswordReset,
    SetPassword,
    UserClearMeta,
    UserUpdateMeta,
)
from .mutations.jwt import (
    CreateToken,
    DeactivateAllUserTokens,
    RefreshToken,
    VerifyToken,
)
from .mutations.permission_group import (
    PermissionGroupCreate,
    PermissionGroupDelete,
    PermissionGroupUpdate,
)
from .mutations.staff import (
    AddressCreate,
    AddressDelete,
    AddressSetDefault,
    AddressUpdate,
    CustomerCreate,
    CustomerDelete,
    CustomerUpdate,
    StaffCreate,
    StaffDelete,
    StaffUpdate,
    UserAvatarDelete,
    UserAvatarUpdate,
    UserClearPrivateMeta,
    UserUpdatePrivateMeta,
)
from .resolvers import (
    resolve_address,
    resolve_address_validation_rules,
    resolve_all_likes,
    resolve_content_feed,
    resolve_customers,
    resolve_permission_groups,
    resolve_staff_users,
    resolve_user,
    resolve_user_by_mobile,
    resolve_user_liked_content,
    resolve_user_followers,
    resolve_user_following,
    resolve_user_media
)

from .sorters import ContentFeedSortingInput, PermissionGroupSortingInput, UserMediaSortingInput, UserSortingInput,InfluencerSortingInput, UserFollowersSortingInput, UserFollowingSortingInput
from .types import Address, AddressValidationData, Group, User,Influencer, UserMedia, UserFollowedStatus


class CustomerFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = CustomerFilter


class PermissionGroupFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = PermissionGroupFilter


class StaffUserInput(FilterInputObjectType):
    class Meta:
        filterset_class = StaffUserFilter

class InfluencerFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = InfluencerFilter


class AccountQueries(graphene.ObjectType):
    address_validation_rules = graphene.Field(
        AddressValidationData,
        description="Returns address validation rules.",
        country_code=graphene.Argument(
            CountryCodeEnum,
            description="Two-letter ISO 3166-1 country code.",
            required=True,
        ),
        country_area=graphene.Argument(
            graphene.String, description="Designation of a region, province or state."
        ),
        city=graphene.Argument(graphene.String, description="City or a town name."),
        city_area=graphene.Argument(
            graphene.String, description="Sublocality like a district."
        ),
    )
    address = graphene.Field(
        Address,
        id=graphene.Argument(
            graphene.ID, description="ID of an address.", required=True
        ),
        description="Look up an address by ID.",
    )
    customers = FilterInputConnectionField(
        User,
        filter=CustomerFilterInput(description="Filtering options for customers."),
        sort_by=UserSortingInput(description="Sort customers."),
        description="List of the shop's customers.",
    )
    permission_groups = FilterInputConnectionField(
        Group,
        filter=PermissionGroupFilterInput(
            description="Filtering options for permission groups."
        ),
        sort_by=PermissionGroupSortingInput(description="Sort permission groups."),
        description="List of permission groups.",
    )
    permission_group = graphene.Field(
        Group,
        id=graphene.Argument(
            graphene.ID, description="ID of the group.", required=True
        ),
        description="Look up permission group by ID.",
    )
    me = graphene.Field(User, description="Return the currently authenticated user.")
    staff_users = FilterInputConnectionField(
        User,
        filter=StaffUserInput(description="Filtering options for staff users."),
        sort_by=UserSortingInput(description="Sort staff users."),
        description="List of the shop's staff users.",
    )
    service_accounts = FilterInputConnectionField(
        ServiceAccount,
        filter=ServiceAccountFilterInput(
            description="Filtering options for service accounts."
        ),
        sort_by=ServiceAccountSortingInput(description="Sort service accounts."),
        description="List of the service accounts.",
        deprecation_reason=(
            "Use the `apps` query instead. This field will be removed after 2020-07-31."
        ),
    )
    service_account = graphene.Field(
        ServiceAccount,
        id=graphene.Argument(
            graphene.ID, description="ID of the service account.", required=True
        ),
        description="Look up a service account by ID.",
        deprecation_reason=(
            "Use the `app` query instead. This field will be removed after 2020-07-31."
        ),
    )

    user = graphene.Field(
        User,
        id=graphene.Argument(graphene.ID, description="ID of the user.", required=True),
        description="Look up a user by ID.",
    )

    user_by_mobile = graphene.Field(
        User,
        mobile_no = graphene.String(description="mobile no of user", required=True),
        description="Look up a user by mobile_no"
    )

    influencers = FilterInputConnectionField(
        Influencer , 
        filter = InfluencerFilterInput(description="Filter options for influencer"),
        sort_by = InfluencerSortingInput(description="Sorting Influencer")
        ,description = "List of Influencers "
    )

    user_liked_content = FilterInputConnectionField(
        UserMedia , 
        filter = UserMediaFilterInput(description="Filter options for user_liked_content"),
        sort_by = UserMediaSortingInput(description="Sorting user_liked_content"),
        user_id=graphene.Argument(graphene.ID, description="ID of the user.")
        ,description = "List of user_liked_content "
    )

    user_media = FilterInputConnectionField(
        UserMedia , 
        filter = UserMediaFilterInput(description="Filter options for user_liked_content"),
        sort_by = UserMediaSortingInput(description="Sorting user_liked_content"),
        description = "List of user content "
    )

    all_likes = FilterInputConnectionField(
        User , 
        content_id=graphene.Argument(graphene.ID, description="ID of the content.", required=True)
        ,description = "List of user that liked mentioned content "
    )

    content_feed = FilterInputConnectionField(
        UserMedia , 
        sort_by = ContentFeedSortingInput(description="Sorting user_liked_content"),
        user_id=graphene.Argument(graphene.ID, description="ID of the user.")
        ,description = "List of user_liked_content "
    )

    user_followers = FilterInputConnectionField(
        User, description="followers of the user"
    )

    user_followers = FilterInputConnectionField(
        UserFollowedStatus, 
        sort_by=UserFollowersSortingInput(description='sorting user_followers'),
        user_id=graphene.Argument(graphene.ID, description="user id"),
        description="followers of the user"
    )

    user_following = FilterInputConnectionField(
        UserFollowedStatus, 
        sort_by=UserFollowingSortingInput(description='sorting user_following'),
        user_id=graphene.Argument(graphene.ID, description="user id"),
        description="whom the user is following"
    )

    def resolve_address_validation_rules(
        self, info, country_code, country_area=None, city=None, city_area=None
    ):
        return resolve_address_validation_rules(
            info,
            country_code,
            country_area=country_area,
            city=city,
            city_area=city_area,
        )

    @permission_required(AppPermission.MANAGE_APPS)
    def resolve_service_accounts(self, info, **kwargs):
        return resolve_service_accounts(info, **kwargs)

    @permission_required(AppPermission.MANAGE_APPS)
    def resolve_service_account(self, info, id):
        return graphene.Node.get_node_from_global_id(info, id, ServiceAccount)

    @permission_required(AccountPermissions.MANAGE_USERS)
    def resolve_customers(self, info, query=None, **kwargs):
        return resolve_customers(info, query=query, **kwargs)

    @permission_required(AccountPermissions.MANAGE_STAFF)
    def resolve_permission_groups(self, info, query=None, **kwargs):
        return resolve_permission_groups(info, query=query, **kwargs)

    @permission_required(AccountPermissions.MANAGE_STAFF)
    def resolve_permission_group(self, info, id):
        return graphene.Node.get_node_from_global_id(info, id, Group)

    def resolve_me(self, info):
        user = info.context.user
        return user if user.is_authenticated else None

    @permission_required(AccountPermissions.MANAGE_STAFF)
    def resolve_staff_users(self, info, query=None, **kwargs):
        return resolve_staff_users(info, query=query, **kwargs)

    @one_of_permissions_required(
        [AccountPermissions.MANAGE_STAFF, AccountPermissions.MANAGE_USERS]
    )
    def resolve_user(self, info, id):
        return resolve_user(info, id)

    def resolve_address(self, info, id):
        return resolve_address(info, id)

    def resolve_user_by_mobile(self, info, mobile_no):
        return resolve_user_by_mobile(info, mobile_no)

    def resolve_user_liked_content(self, info,user_id=None,**kwargs):
        return resolve_user_liked_content(info,user_id)

    def resolve_all_likes(self, info,content_id,**kwargs):
        return resolve_all_likes(info,content_id)

    def resolve_content_feed(self, info,user_id=None,**kwargs):
        return resolve_content_feed(info,user_id)
    
    def resolve_user_followers(self, info, user_id=None, **kwargs):
        return resolve_user_followers(info, user_id)
    
    def resolve_user_following(self, info, user_id=None, **kwargs):
        return resolve_user_following(info, user_id)


    def resolve_user_media(self, info,**kwargs):
        return resolve_user_media(info)
class AccountMutations(graphene.ObjectType):
    # Base mutations
    token_create = CreateToken.Field()
    token_refresh = RefreshToken.Field()
    token_verify = VerifyToken.Field()
    tokens_deactivate_all = DeactivateAllUserTokens.Field()

    #influencer Register
    influencer_account_register = InfluencerAccountRegister.Field()

    request_password_reset = RequestPasswordReset.Field()
    confirm_account = ConfirmAccount.Field()
    set_password = SetPassword.Field()
    password_change = PasswordChange.Field()
    request_email_change = RequestEmailChange.Field()
    confirm_email_change = ConfirmEmailChange.Field()

    influencer_upi_id_create = InfluencerUpiIdCreate.Field()
    influencer_bank_account_create = InfluencerBankAccountCreate.Field()

    # Account mutations
    account_address_create = AccountAddressCreate.Field()
    account_address_update = AccountAddressUpdate.Field()
    account_address_delete = AccountAddressDelete.Field()
    account_set_default_address = AccountSetDefaultAddress.Field()

    account_register = AccountRegister.Field()
    account_update = AccountUpdate.Field()
    account_request_deletion = AccountRequestDeletion.Field()
    account_delete = AccountDelete.Field()

    account_update_meta = AccountUpdateMeta.Field(
        deprecation_reason=(
            "Use the `updateMetadata` mutation. This field will be removed after "
            "2020-07-31."
        )
    )

    # Staff mutations
    address_create = AddressCreate.Field()
    address_update = AddressUpdate.Field()
    address_delete = AddressDelete.Field()
    address_set_default = AddressSetDefault.Field()

    customer_create = CustomerCreate.Field()
    customer_update = CustomerUpdate.Field()
    customer_delete = CustomerDelete.Field()
    customer_bulk_delete = CustomerBulkDelete.Field()

    staff_create = StaffCreate.Field()
    staff_update = StaffUpdate.Field()
    staff_delete = StaffDelete.Field()
    staff_bulk_delete = StaffBulkDelete.Field()

    user_avatar_update = UserAvatarUpdate.Field()
    user_avatar_delete = UserAvatarDelete.Field()
    user_bulk_set_active = UserBulkSetActive.Field()

    user_update_metadata = UserUpdateMeta.Field(
        deprecation_reason=(
            "Use the `updateMetadata` mutation. This field will be removed after "
            "2020-07-31."
        )
    )
    user_clear_metadata = UserClearMeta.Field(
        deprecation_reason=(
            "Use the `deleteMetadata` mutation. This field will be removed after "
            "2020-07-31."
        )
    )

    user_update_private_metadata = UserUpdatePrivateMeta.Field(
        deprecation_reason=(
            "Use the `updatePrivateMetadata` mutation. This field will be removed "
            "after 2020-07-31."
        )
    )
    user_clear_private_metadata = UserClearPrivateMeta.Field(
        deprecation_reason=(
            "Use the `deletePrivateMetadata` mutation. This field will be removed "
            "after 2020-07-31."
        )
    )

    service_account_create = ServiceAccountCreate.Field(
        deprecation_reason=(
            "Use the `appCreate` mutation instead. This field will be removed after "
            "2020-07-31."
        )
    )
    service_account_update = ServiceAccountUpdate.Field(
        deprecation_reason=(
            "Use the `appUpdate` mutation instead. This field will be removed after "
            "2020-07-31."
        )
    )
    service_account_delete = ServiceAccountDelete.Field(
        deprecation_reason=(
            "Use the `appDelete` mutation instead. This field will be removed after "
            "2020-07-31."
        )
    )

    service_account_update_private_metadata = ServiceAccountUpdatePrivateMeta.Field(
        deprecation_reason=(
            "Use the `updatePrivateMetadata` mutation with App instead."
            "This field will be removed after 2020-07-31."
        )
    )
    service_account_clear_private_metadata = ServiceAccountClearPrivateMeta.Field(
        deprecation_reason=(
            "Use the `deletePrivateMetadata` mutation with App instead."
            "This field will be removed after 2020-07-31."
        )
    )

    service_account_token_create = ServiceAccountTokenCreate.Field(
        deprecation_reason=(
            "Use the `appTokenCreate` mutation instead. This field will be removed "
            "after 2020-07-31."
        )
    )
    service_account_token_delete = ServiceAccountTokenDelete.Field(
        deprecation_reason=(
            "Use the `appTokenDelete` mutation instead. This field will be removed "
            "after 2020-07-31."
        )
    )

    # Permission group mutations
    permission_group_create = PermissionGroupCreate.Field()
    permission_group_update = PermissionGroupUpdate.Field()
    permission_group_delete = PermissionGroupDelete.Field()

    #influencer mutation
    influencer_instagram_account_create = InfluencerInstagramAccountConnect.Field()
    activate_account = ActivateAccount.Field()
    influencer_manual_account_verification = InfluencerManualAccountVerification.Field()
    influencer_update = InfluencerUpdate.Field()

    #user create mutation
    user_register = UserRegister.Field()
    activate_brand_account = ActivateBrandAccount.Field()

    #ootd mutations
    like_unlike_content = LikeUnlikeContent.Field()
    follow_unfollow_user = FollowUnfollowUser.Field()
    user_media_create = UserMediaCreate.Field()
