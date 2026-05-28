from re import L
import logging
import traceback
from saleor.account.emails import send_mail_influencer_signup, send_mail_influencer_account_activation
from saleor.account.states import InfluencerState, InfluencerStatus
from saleor.brand import models as brand_models
from saleor.discount import VoucherType
from saleor.discount.models import Voucher, VoucherStoreDealMapping
from saleor.external_services.messaging.messaging_impl import MessagingImpl
from saleor.utilities.api_client import ApiClient
from saleor.utilities.request_utilities import PlatformTypeEnum
from saleor.store.store_utilities import create_default_collection_store, get_default_zaamo_store,setup_store_for_brand, setup_store_for_influencer, setup_store_member_state_for_user
from saleor.core.permissions import InfluencerPermissions, get_permissions
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import F
import graphene
import jwt
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from saleor.account.login import save_long_lived_token_in_db, fetch_instagram_profile_of_user
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.time_utilities import TimeUtilities
from ....account import emails, events as account_events, models, utils
from ....account.error_codes import AccountErrorCode
from ....checkout import AddressType
from ....core.jwt import create_token, jwt_decode
from ....core.utils.url import validate_storefront_url
from ....settings import JWT_TTL_REQUEST_EMAIL_CHANGE
from ...account.enums import AddressTypeEnum, InfluencerStatusEnums
from ...account.types import Address, AddressInput, Influencer, User, UserLikeStatus, UserMedia, UserFollowedStatus
from ...core.mutations import BaseMutation, ModelDeleteMutation, ModelMutation, StoreBaseMutation
from ...core.types.common import AccountError, BaseBankAccountInput, BaseUpiIdInput
from ...meta.deprecated.mutations import UpdateMetaBaseMutation
from ...meta.deprecated.types import MetaInput
from ..enums import RegisterUserTypeEnum, RegisterUserType, UserMediaTypeEnums
from saleor.account import models as user_models
from saleor.account.emails import send_mail_brand_signup
from saleor.store.models import StoreInfo, StaffStoreMapping, StoreMemberState
from saleor.store.states import StoreStatus, StoreCategoryPageLevels, StoreTypeEnum
from django.utils.text import slugify
from saleor.graphql.utils import get_nodes
from ..i18n import I18nMixin
from saleor.graphql.meta.mutations import MetadataInput
from saleor.external_services.whatsapp.tasks import campus_influencer_notification
from .base import (

INVALID_TOKEN,
BaseAddressDelete,
BaseAddressUpdate,
BaseCustomerCreate,
)

logger = logging.getLogger(__name__)

class AccountRegisterInput(graphene.InputObjectType):
    email = graphene.String(description = "The email address of the user.",
                            required = True)
    password = graphene.String(description = "Password.", required = True)
    redirect_url = graphene.String(description = (
        "Base of frontend URL that will be needed to create confirmation URL."),
        required = False, )


class AccountRegister(ModelMutation):
    class Arguments:
        input = AccountRegisterInput(description = "Fields required to create a user.",
                                     required = True)

    requires_confirmation = graphene.Boolean(
        description = "Informs whether users need to confirm their email address.")

    class Meta:
        description = "Register a new user."
        exclude = ["password"]
        model = models.User
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def mutate(cls, root, info, **data):
        response = super().mutate(root, info, **data)
        response.requires_confirmation = settings.ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL
        return response

    @classmethod
    def clean_input(cls, info, instance, data, input_cls = None):
        if not settings.ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL:
            return super().clean_input(info, instance, data, input_cls = None)
        elif not data.get("redirect_url"):
            raise ValidationError({
                "redirect_url": ValidationError("This field is required.",
                                                code = AccountErrorCode.REQUIRED)})

        try:
            validate_storefront_url(data["redirect_url"])
        except ValidationError as error:
            raise ValidationError({"redirect_url": ValidationError(error.message,
                                                                   code = AccountErrorCode.INVALID)})

        password = data["password"]
        try:
            password_validation.validate_password(password, instance)
        except ValidationError as error:
            raise ValidationError({"password": error})

        return super().clean_input(info, instance, data, input_cls = None)

    @classmethod
    def save(cls, info, user, cleaned_input):
        password = cleaned_input["password"]
        user.set_password(password)
        if settings.ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL:
            user.is_active = False
            user.save()
            # emails.send_account_confirmation_email(user, cleaned_input["redirect_url"])
        else:
            user.save()
        account_events.customer_account_created_event(user = user)
        info.context.plugins.customer_created(customer = user)


class AccountInput(graphene.InputObjectType):
    first_name = graphene.String(description = "Given name.")
    last_name = graphene.String(description = "Family name.")
    default_billing_address = AddressInput(
        description = "Billing address of the customer.")
    default_shipping_address = AddressInput(
        description = "Shipping address of the customer.")
    user_name = graphene.String(description = "User Name")
    image_url = graphene.String(description = "image url")


class AccountUpdate(BaseCustomerCreate):
    class Arguments:
        input = AccountInput(
            description = "Fields required to update the account of the logged-in user.",
            required = True, )

    class Meta:
        description = "Updates the account of the logged-in user."
        exclude = ["password"]
        model = models.User
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def validate_user_name(cls,user_name,user_id):
        already_exist = models.User.objects.filter(user_name=user_name).exists()

        if already_exist:
            
            raise ValidationError({"message": ValidationError('User Name already exists.',
                                                                   code = AccountErrorCode.INVALID)})

    @classmethod
    def perform_mutation(cls, root, info, **data):
        user = info.context.user
        data["id"] = graphene.Node.to_global_id("User", user.id)
        
        if data['input'].get('user_name'):
            cls.validate_user_name(data['input'].get('user_name'),user.id)
            
        return super().perform_mutation(root, info, **data)


class AccountRequestDeletion(BaseMutation):
    class Arguments:
        redirect_url = graphene.String(required = True, description = (
            "URL of a view where users should be redirected to "
            "delete their account. URL in RFC 1808 format."), )

    class Meta:
        description = (
            "Sends an email with the account removal link for the logged-in user.")
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, root, info, **data):
        user = info.context.user
        redirect_url = data["redirect_url"]
        try:
            validate_storefront_url(redirect_url)
        except ValidationError as error:
            raise ValidationError({"redirect_url": error},
                                  code = AccountErrorCode.INVALID)
        emails.send_account_delete_confirmation_email_with_url(redirect_url, user)
        return AccountRequestDeletion()


class AccountDelete(ModelDeleteMutation):
    class Arguments:
        token = graphene.String(
            description = ("A one-time token required to remove account. "
                           "Sent by email using AccountRequestDeletion mutation."),
            required = True, )

    class Meta:
        description = "Remove user account."
        model = models.User
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def clean_instance(cls, info, instance):
        super().clean_instance(info, instance)
        if instance.is_staff:
            raise ValidationError("Cannot delete a staff account.",
                                  code = AccountErrorCode.DELETE_STAFF_ACCOUNT, )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        user = info.context.user
        cls.clean_instance(info, user)

        token = data.pop("token")
        if not default_token_generator.check_token(user, token):
            raise ValidationError({"token": ValidationError(INVALID_TOKEN,
                                                            code = AccountErrorCode.INVALID)})

        db_id = user.id

        user.delete()
        # After the instance is deleted, set its ID to the original database's
        # ID so that the success response contains ID of the deleted object.
        user.id = db_id
        return cls.success_response(user)


class AccountAddressCreate(ModelMutation, I18nMixin):
    user = graphene.Field(User,
                          description = "A user instance for which the address was created.")

    class Arguments:
        input = AddressInput(description = "Fields required to create address.",
                             required = True)
        type = AddressTypeEnum(required = False, description = (
            "A type of address. If provided, the new address will be "
            "automatically assigned as the customer's default address "
            "of that type."), )

    class Meta:
        description = "Create a new address for the customer."
        model = models.Address
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, root, info, **data):
        address_type = data.get("type", None)
        user = info.context.user
        cleaned_input = cls.clean_input(info = info, instance = Address(),
                                        data = data.get("input"))
        address = cls.validate_address(cleaned_input)
        cls.clean_instance(info, address)
        cls.save(info, address, cleaned_input)
        cls._save_m2m(info, address, cleaned_input)
        if address_type:
            utils.change_user_default_address(user, address, address_type)
        return AccountAddressCreate(user = user, address = address)

    @classmethod
    def save(cls, info, instance, cleaned_input):
        super().save(info, instance, cleaned_input)
        user = info.context.user
        instance.user_addresses.add(user)


class AccountAddressUpdate(BaseAddressUpdate):
    class Meta:
        description = "Updates an address of the logged-in user."
        model = models.Address
        error_type_class = AccountError
        error_type_field = "account_errors"


class AccountAddressDelete(BaseAddressDelete):
    class Meta:
        description = "Delete an address of the logged-in user."
        model = models.Address
        error_type_class = AccountError
        error_type_field = "account_errors"


class AccountSetDefaultAddress(BaseMutation):
    user = graphene.Field(User, description = "An updated user instance.")

    class Arguments:
        id = graphene.ID(required = True,
                         description = "ID of the address to set as default.")
        type = AddressTypeEnum(required = True, description = "The type of address.")

    class Meta:
        description = "Sets a default address for the authenticated user."
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        address = cls.get_node_or_error(info, data.get("id"), Address)
        user = info.context.user

        if not user.addresses.filter(pk = address.pk).exists():
            raise ValidationError({
                "id": ValidationError("The address doesn't belong to that user.",
                                      code = AccountErrorCode.INVALID, )})

        if data.get("type") == AddressTypeEnum.BILLING.value:
            address_type = AddressType.BILLING
        else:
            address_type = AddressType.SHIPPING

        utils.change_user_default_address(user, address, address_type)
        return cls(user = user)


class AccountUpdateMeta(UpdateMetaBaseMutation):
    class Meta:
        description = "Updates metadata of the logged-in user."
        model = models.User
        public = True
        error_type_class = AccountError
        error_type_field = "account_errors"

    class Arguments:
        input = MetaInput(
            description = "Fields required to update new or stored metadata item.",
            required = True, )

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def get_instance(cls, info, **data):
        return info.context.user


class RequestEmailChange(BaseMutation):
    user = graphene.Field(User, description = "A user instance.")

    class Arguments:
        password = graphene.String(required = True, description = "User password.")
        new_email = graphene.String(required = True, description = "New user email.")
        redirect_url = graphene.String(required = True, description = (
            "URL of a view where users should be redirected to "
            "update the email address. URL in RFC 1808 format."), )

    class Meta:
        description = "Request email change of the logged in user."
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        user = info.context.user
        password = data["password"]
        new_email = data["new_email"]
        redirect_url = data["redirect_url"]

        if not user.check_password(password):
            raise ValidationError({"password": ValidationError("Password isn't valid.",
                                                               code = AccountErrorCode.INVALID_CREDENTIALS, )})
        if models.User.objects.filter(email = new_email).exists():
            raise ValidationError({
                "new_email": ValidationError("Email is used by other user.",
                                             code = AccountErrorCode.UNIQUE)})
        try:
            validate_storefront_url(redirect_url)
        except ValidationError as error:
            raise ValidationError({"redirect_url": error},
                                  code = AccountErrorCode.INVALID)
        token_payload = {"old_email": user.email, "new_email": new_email,
                         "user_pk": user.pk, }
        token = create_token(token_payload, JWT_TTL_REQUEST_EMAIL_CHANGE)
        emails.send_user_change_email_url(redirect_url, user, new_email, token)
        return RequestEmailChange(user = user)


class ConfirmEmailChange(BaseMutation):
    user = graphene.Field(User, description = "A user instance with a new email.")

    class Arguments:
        token = graphene.String(
            description = "A one-time token required to change the email.",
            required = True)

    class Meta:
        description = "Confirm the email change of the logged-in user."
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def get_token_payload(cls, token):
        try:
            payload = jwt_decode(token)
        except jwt.PyJWTError:
            raise ValidationError({"token": ValidationError("Invalid or expired token.",
                                                            code = AccountErrorCode.JWT_INVALID_TOKEN, )})
        return payload

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        user = info.context.user
        token = data["token"]

        payload = cls.get_token_payload(token)
        new_email = payload["new_email"]
        old_email = payload["old_email"]

        if models.User.objects.filter(email = new_email).exists():
            raise ValidationError({
                "new_email": ValidationError("Email is used by other user.",
                                             code = AccountErrorCode.UNIQUE)})

        user.email = new_email
        user.save(update_fields = ["email"])
        emails.send_user_change_email_notification(old_email)
        event_parameters = {"old_email": old_email, "new_email": new_email}

        account_events.customer_email_changed_event(user = user,
                                                    parameters = event_parameters)
        return ConfirmEmailChange(user = user)


class InfluencerAccountRegisterInput(graphene.InputObjectType):
    mobile_no = graphene.String(description = "mobile_no.", required = True)


class InfluencerAccountRegister(ModelMutation):
    class Arguments:
        input = InfluencerAccountRegisterInput(
            description = "Fields required to register a influencer.", required = True)

    class Meta:
        description = "Register a new influencer."
        exclude = ["password", "email"]
        model = models.User
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def mutate(cls, root, info, **data):
        response = super().mutate(root, info, **data)

        return response

    @classmethod
    def save(cls, info, user, cleaned_input):
        user.is_active = True
        user.signed_up_from = RequestUtilities.get_platfrom_type_from_headers(info.context)
        user.save()


class InfluencerInstagramAccountConnectInput(graphene.InputObjectType):
    access_token = graphene.String(description = "short lived access token",
                                   required = True)
    mobile_no = graphene.String(description = "mobile_no of influencer",
                                required = True)


class InfluencerInstagramAccountConnect(BaseMutation):
    class Arguments:
        input = InfluencerInstagramAccountConnectInput(
            description = "input for instagram connect")

    class Meta:
        description = "connect influencer data"
        error_type_class = AccountError
        error_type_field = "account_errors"

    user = graphene.Field(User)

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, _root, info, **data):

        access_token = data.get('input').get('access_token')
        user_instance = models.User.get_user_instance_by_mobile(
            data.get('input').get('mobile_no'))

        if not user_instance:
            raise ValidationError(message = "In-valid mobile number")

        if models.Influencer.is_influencer_exists(user_instance):
            raise ValidationError(message = "user already registered")

        access_token = save_long_lived_token_in_db(access_token, user_instance)

        if not access_token:
            raise ValidationError(message = "Invalid token")

        instagram_profile = fetch_instagram_profile_of_user(access_token, user_instance)

        if instagram_profile:
            models.Influencer.create_instance(instagram_profile)

        else:
            raise ValidationError(message = "In-valid response from instagram")

        return cls(user = user_instance)


class InfluencerManualAccountVerification(BaseMutation):
    class Arguments:
        mobile_no = graphene.String(description = "mobile_no of influencer")
        instagram_link = graphene.String(description = "instagram link of influencer")
        instagram_username = graphene.String(description = "instagram user name of influencer")

    class Meta:
        description = "manual account verification"
        error_type_class = AccountError
        error_type_field = "account_errors"

    user = graphene.Field(User, description = "user data")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        user_instance = models.User.get_user_instance_by_mobile(data.get('mobile_no'))

        if not user_instance:
            raise ValidationError(message = "In-valid mobile number")

        influencer_filter = models.Influencer.objects.filter(user = user_instance)

        if not influencer_filter:
            models.Influencer.create_instance({
                'user_instance': user_instance,
                'instagram_link': data.get('instagram_link'),
                'instagram_username':data.get('instagram_username',''),
            
            })
            #send_mail_influencer_signup.delay(user_instance.id)

        return cls(user = user_instance)


class InfluencerUpdateInput(graphene.InputObjectType):
    name = graphene.String(description = "name of the influencer", required = False)
    email = graphene.String(description = "email of the influencer", required = False)
    instagram_link = graphene.String(description = "instagram link of influencer")
    facebook_link = graphene.String(description = "facebook link of influencer")
    youtube_link = graphene.String(description = "youtube link of influencer")
    image_url = graphene.String(description="image of influencer")
    id = graphene.ID(description="Influencer ID")
    metadata = graphene.List(MetadataInput, description="stores the metadata of influencer")
    status = InfluencerStatusEnums(description="status of influencer")



class InfluencerUpdate(StoreBaseMutation):
    class Arguments:
        input = InfluencerUpdateInput(description = "influencer update details")

    class Meta:
        description = "update influencer data"
        error_type_class = AccountError
        error_type_field = "account_errors"
        permissions = (InfluencerPermissions.MANAGE_INFLUENCER,)

    user = graphene.Field(User, description = "user data")

    @classmethod
    def check_permissions(cls, context, permissions=None):
        influencer_filter = models.Influencer.objects.filter(user = context.user)

        user_instance = context.user
        platform_code = RequestUtilities.get_platfrom_type_from_headers(context)

        if platform_code == PlatformTypeEnum.ANALYTICS and (user_instance.is_superuser or user_instance.is_staff):
            return True
        
        
        #influencer store has not been created
        if influencer_filter and influencer_filter[0].state == InfluencerState.NOT_VERIFIED:
            return True

        store_id = RequestUtilities.get_store_id_from_headers(context)
        permissions = permissions or cls._meta.permissions
        return context.user.has_store_access(store_id, permissions) and super().check_permissions(context, permissions=permissions)


    @classmethod
    def clean_input_for_influencer_update(cls, data):
        verification_dict = dict()
        input_data = data.get('input', {})

        if input_data.get('name'):
            verification_dict['name'] = input_data.get('name')

        if input_data.get('instagram_link'):
            verification_dict['instagram_link'] = input_data.get('instagram_link')

        if input_data.get('facebook_link'):
            verification_dict['facebook_link'] = input_data.get('facebook_link')

        if input_data.get('youtube_link'):
            verification_dict['youtube_link'] = input_data.get('youtube_link')

        if input_data.get('image_url'):
            verification_dict['image_url'] = input_data.get('image_url')

        if input_data.get('status'):
            verification_dict['status'] = input_data.get('status')


        return verification_dict

    @classmethod
    def process_metadata(cls, input_data, user_instance):

        influencer_existing_metadata = models.Influencer.objects.filter(user = user_instance).first()
        
        metadata_dict = influencer_existing_metadata.metadata

        for field in input_data:
            if(metadata_dict.get(field.key)):
                metadata_dict[field.key] = field.value
            else:
                metadata_dict[field.key] = field.value

        return metadata_dict

    @classmethod
    def perform_mutation(cls, root, info, **data):

        user_instance = info.context.user
        email = data.get('input').get('email')

        if email:
            user_instance.email = email
            user_instance.save()

        verification_dict = cls.clean_input_for_influencer_update(data)

        if data.get('input').get('metadata'):
            verification_dict['metadata'] = cls.process_metadata(data.get('input').get('metadata'), user_instance)

        models.Influencer.objects.filter(user = user_instance).update(
            **verification_dict)

        if data.get('input').get('id'):
            influencer_ids = []
            influencer_ids.append(data.get('input').get('id'))
            influencers = get_nodes(influencer_ids,"Influencer", models.Influencer)
            influencer = influencers[0]
            user_instance = influencer.user

            if data.get('input').get('metadata'):
                verification_dict['metadata'] = cls.process_metadata(data.get('input').get('metadata'), user_instance)
            
            models.Influencer.objects.filter(pk = influencer.id).update(
                **verification_dict
            )

        return cls(user = user_instance)


class ActivateAccountInput(graphene.InputObjectType):
    mobile_no = graphene.String(description = "mobile_no of influencer",
                                required = True)
    name = graphene.String(description = "name of instagram user", required = False)
    instagram_user_id = graphene.String(description = "user name of instagram",
                                        required = False)
    instagram_username = graphene.String(description = "user name of instagram",
                                         required = False)
    image_url = graphene.String(description = "image url of instagram",
                                required = False)
    store_barter = graphene.Boolean(description = "store barter of influencer store",
                                required = False)
    store_manager_email = graphene.String(description = "store manager email of influencer store",
                                required = False)


class ActivateAccount(BaseMutation):
    class Arguments:
        input = ActivateAccountInput(description = "id of account to be activated")

    class Meta:
        description = "activated user account"
        error_type_class = AccountError
        error_type_field = "account_errors"

    user = graphene.Field(User)

    @classmethod
    def clean_input_for_manual_verification_for_influencer(cls, data):
        verification_dict = dict()
        input_data = data.get('input', {})

        if input_data.get('name'):
            verification_dict['name'] = input_data.get('name')

        if input_data.get('instagram_user_id'):
            verification_dict['instagram_user_id'] = input_data.get('instagram_user_id')

        if input_data.get('instagram_username'):
            verification_dict['instagram_username'] = input_data.get(
                'instagram_username')
            verification_dict['instagram_link'] = "https://instagram.com/" + input_data.get(
                'instagram_username')

        if input_data.get('image_url'):
            verification_dict['image_url'] = input_data.get('image_url')

        verification_dict['state'] = InfluencerState.VERIFIED
        verification_dict['status'] = InfluencerStatus.ONBOARDED
        # verification_dict['updated_at'] = TimeUtilities.current_time_in_milliseconds()

        return verification_dict

    @classmethod
    def create_staff_store_mapping_for_store(cls, store_instance, store_manager_email):
        user_filter = user_models.User.objects.filter(email=store_manager_email)
        
        if user_filter:
            user_instance = user_filter.first()
            StaffStoreMapping.objects.create(
                user = user_instance,
                store = store_instance
            )
            store_member = store_instance.store_members.first()
            if store_member:
                campus_influencer_notification.delay(store_member.user_id,store_instance.store_name)

    @classmethod
    def create_group(cls, name, permissions, users):
        group, _ = Group.objects.get_or_create(name = name)
        group.permissions.add(*permissions)
        group.user_set.add(*users)

        return group
    
    
    @classmethod
    def create_deal_vouchermapping_for_store(cls,store):
        
        default_store = get_default_zaamo_store()
        default_store_id = default_store.id
        todays_date = TimeUtilities.get_current_date_time()

        mixed_vouchers = Voucher.objects.filter(type = VoucherType.SPECIFIC_BRAND_PRODUCTS , store_id = default_store_id).active(todays_date).values_list('id',flat=True)
        
        if not store.store_type==StoreTypeEnum.INFLUENCER:
            return
        voucher_mapping = []

        pre_existing_mapping = VoucherStoreDealMapping.objects.filter(voucher_id__in=mixed_vouchers, store=store.id).values_list('voucher_id',flat=True)

        for voucher_id in mixed_vouchers:

            
            if not voucher_id in pre_existing_mapping:

                voucher_store_deal = VoucherStoreDealMapping(
                    voucher_id=voucher_id, 
                    store_id=store.id
                )
                voucher_mapping.append(voucher_store_deal)
        

        VoucherStoreDealMapping.objects.bulk_create(voucher_mapping)

    @classmethod
    def get_sheeko_influencer_info_url(cls, influencer_instance):
        url, username = '', ''
        instagram_link = influencer_instance.instagram_link
        instagram_username = influencer_instance.instagram_username
        if instagram_link:
            username = instagram_link.split('instagram.com/')[-1].split('?')[0].split('/')[0].split('@')[-1].strip().lower()
        if instagram_username:
            username = username or instagram_username.split('@')[-1].strip().lower()
        if username:
            url = 'https://www.sheeko.in/support/creators/dashboard?name=' + username
        return url 

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, _root, info, **data):
        logged_user = info.context.user
        user_instance = models.User.get_user_instance_by_mobile(
            data.get('input').get('mobile_no'))
        user_instance.is_active = True
        user_instance.save()

        verification_dict = cls.clean_input_for_manual_verification_for_influencer(data)
        influencer_filter = models.Influencer.objects.filter(
            user = user_instance)

        if influencer_filter and influencer_filter.first().state != InfluencerState.VERIFIED:
            influencer_filter.update(**verification_dict)
            influencer_instance = influencer_filter.first()
            store_instance = setup_store_for_influencer(user_instance,
                                                        influencer_instance)
            if data.get('input').get('store_barter') is not None:
                store_instance.metadata["store_barter"] = data.get('input').get('store_barter')
            else:
                store_instance.metadata["store_barter"] = True

            store_instance.metadata["sheeko_influencer_info"] = cls.get_sheeko_influencer_info_url(influencer_instance)
            store_instance.save()
            if data.get('input').get('store_manager_email'):
                cls.create_staff_store_mapping_for_store(store_instance, data.get('input').get('store_manager_email'))
            
            if data.get('input').get('store_barter') is not None and data.get('input').get('store_manager_email'):
                store_instance.actions.status = StoreStatus.CAMPUS_AMBASSADOR
                store_instance.store_category_page_level = StoreCategoryPageLevels.LEVEL_3
                store_instance.save()
                store_instance.actions.save()
            
            create_default_collection_store(store_instance, user_instance)
            cls.create_group("Full Access", get_permissions(), [user_instance])
            MessagingImpl.send_message_for_account_activation(user_instance.mobile_no,store_instance.store_name)
            if logged_user.email is not None:
                send_mail_influencer_account_activation.delay(user_instance.mobile_no, influencer_instance.instagram_link, logged_user.email)

            try:
                cls.send_account_to_content_processing(store_instance.id, influencer_instance)
            except Exception as e:
                logger.info("send_account_to_content_processing:\n%s", traceback.format_exc())

            cls.create_deal_vouchermapping_for_store(store_instance)
        return cls(user = user_instance)


    @staticmethod
    def send_account_to_content_processing(store_id, influencer_instance):
        """
        saves instagram account in content processing service for fetching user's instagram content
        """
        def extract_username(link: str) -> str:
            username = ''
            if link and isinstance(link, str):
                username = link.split('instagram.com/')[-1].split('?')[0].split('/')[0].split('@')[-1]
                username = username.lower().strip()
            
            return username

        username = extract_username(influencer_instance.instagram_username) or extract_username(influencer_instance.instagram_link)
        if not username:
            return False

        zaamo_id = graphene.Node.to_global_id('Store', store_id)
        user_type = 'INFLUENCER'
        user_id = influencer_instance.instagram_user_id
        
        data = {
            'username': username,
            'zaamo_id': zaamo_id,
            'user_type': user_type,
        }
        if user_id:
            data['user_id'] = user_id
        
        URL = settings.CONTENT_SERVICE_URL + '/engine/user/details'
        header = {'Content-Type': 'application/json'}
        body = data
        
        api_client = ApiClient(url=URL)
        api_client.update_headers(header)
        api_client.update_body(body)
        api_client.post()

        return api_client.response.ok


class UserRegisterInput(graphene.InputObjectType):
    mobile_no = graphene.String(description = "mobile_no.", required = True)
    is_active = graphene.Boolean(description = "active status of user", required = True)
    register_type = RegisterUserTypeEnum(
        required=False, 
        description=(
            "Register User Type"
        ),
    )

class UserRegister(ModelMutation):
    class Arguments:
        input = UserRegisterInput(description = "Fields required to register a user.",
                                  required = True)

    class Meta:
        description = "Register a new user."
        exclude = ["password", "email"]
        model = models.User
        error_type_class = AccountError
        error_type_field = "account_errors"
    
    @classmethod
    def create_account_brand(cls, root, info, user_detail):
        account_brand_user_created = user_models.AccountBrand.objects.create(
            user = user_detail
        )
        return account_brand_user_created

    @classmethod
    def perform_mutation(cls, root, info, **data):
        response = super().perform_mutation(root, info, **data)
        input = data['input']
        register_type = input.get('register_type', '')
        
        if register_type == RegisterUserType.BRAND:
            user_details = user_models.User.objects.filter(mobile_no=input['mobile_no'])
            if user_details:
                account_brand_user_created = cls.create_account_brand(root, info, user_details[0])
                send_mail_brand_signup.delay(account_brand_user_created.user_id)

        return response

    @classmethod
    def save(cls, info, user, cleaned_input):
        user.signed_up_from = RequestUtilities.get_platfrom_type_from_headers(info.context)
        user.save()


class ActivateBrandAccountInput(graphene.InputObjectType):
    mobile_no = graphene.String(description = "mobile_no of influencer",
                                required = True)
    brand_id = graphene.ID(description = "id of brand", required = True)


class ActivateBrandAccount(BaseMutation):
    class Arguments:
        input = ActivateBrandAccountInput(description = "id of account to be activated")

    class Meta:
        description = "activated brand user account"
        error_type_class = AccountError
        error_type_field = "account_errors"

    user = graphene.Field(User)

    @classmethod
    def create_group(cls, name, permissions, users):
        group, _ = Group.objects.get_or_create(name = name)
        group.permissions.add(*permissions)
        group.user_set.add(*users)

        return group

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, _root, info, **data):
        user_instance = models.User.get_user_instance_by_mobile(
            data.get('input').get('mobile_no'))
        user_instance.is_active = True
        user_instance.save()

        brand_node = graphene.Node.from_global_id(data.get('input').get('brand_id'))
        brand_id = brand_node[1]
        brand_instance = brand_models.Brand.get_instance(brand_id)

        if not brand_instance:
            raise ValidationError(message = "In-valid brand id")

        slug = slugify(brand_instance.brand_name , allow_unicode = True)
        store_filter = StoreInfo.objects.filter(slug = slug)
        
        if not store_filter:            
            store_instance = setup_store_for_brand(user_instance, brand_instance)
            try:
                create_default_collection_store(store_instance, user_instance,slug=True)
            except Exception as e:
                raise ValidationError("Collection Already Exists")
        else:
            store_instance = store_filter[0]
            setup_store_member_state_for_user(user_instance, store_instance)

        cls.create_group("Full Access", get_permissions(), [user_instance])
        brand_instance.add_brand_member(user_instance)
        brand_instance.mobiles.filter(mobile_no=user_instance.mobile_no).update(active=True)

        return cls(user = user_instance)

class InfluencerBankAccountInput(BaseBankAccountInput):
    influencer = graphene.ID(
        description="ID of the influencer that Bank Account belongs to.",
        name="influencer",
        required=True,
    )
    

class InfluencerUpiIdInput(BaseUpiIdInput):
    influencer = graphene.ID(
        description="ID of the influencer that UPI ID belongs to.",
        name="influencer",
        required=True,
    )


class InfluencerBankAccountCreate(ModelMutation):
    class Arguments:
        input = InfluencerBankAccountInput(
            required=True, description="Fields required to create Influencer's BankAccount."
        )

    class Meta:
        description = "Create a new BankAccount."
        model = models.InfluencerBankAccount
        return_field_name = "InfluencerBankAccount"
        error_type_field = "InfluencerAccount_errors"


class InfluencerUpiIdCreate(ModelMutation):
    class Arguments:
        input = InfluencerUpiIdInput(
            required=True, description="Fields required to create Influencer's UPI ID."
        )

    class Meta:
        description = "Create a new Influencer's UPI ID."
        model = models.InfluencerUpiId
        return_field_name = "InfluencerUpiId"
        error_type_field = "InfluencerUpiId_errors"


class LikeUnlikeContentInput(graphene.InputObjectType):
    user_id = graphene.ID(description = "id of user from like request", required = True)
    liked_user_id = graphene.ID(description = "id of user for like request", required = True)
    like_status = graphene.Boolean(description = "like status of request")
    content_id     = graphene.ID(description = "id of user for like request", required = True)

class LikeUnlikeContent(ModelMutation):
    class Arguments:
        input = LikeUnlikeContentInput(
            required=True, description="Fields required to update like and unlike ."
        )

    class Meta:
        description = "Add and Update like/dislike in UserLikeStatus table."
        model = models.UserLikeStatus
        return_field_name = "UserLikeStatus"
        error_type_field = "UserLikeStatus_errors"

    user_like_status = graphene.Field(UserLikeStatus)

    @classmethod
    def store_and_increment_like_counts(cls,info,data):
        
        content = cls.get_node_or_error(info, data['input'].get("content_id"),only_type= UserMedia)
        user_id = graphene.Node.from_global_id(data['input'].get('user_id'))[1]
        liked_user_id = graphene.Node.from_global_id(data['input'].get('liked_user_id'))[1]
        like_status = data['input'].get('like_status',True)

        instance = models.UserLikeStatus.objects.filter(user_id=user_id,liked_user_id=liked_user_id,content_id = content.id).first()
        
        if instance:

            if like_status!=instance.like_status:
                instance.like_status=like_status
            
                if like_status==True:
                    content.likes_count+=1
                    content.dislikes_count-=1
                else:
                    content.likes_count-=1
                    content.dislikes_count+=1

                instance.save()
                content.save()
        else:
            instance = models.UserLikeStatus.objects.create(user_id=user_id,
                                                             liked_user_id=liked_user_id,
                                                             like_status=like_status,
                                                             content_id=content.id)
            
            if like_status==True:
                content.likes_count+=1
            else:
                content.dislikes_count+=1
            content.save()

        return instance

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        instance = cls.store_and_increment_like_counts(info,data)
            
        return cls(user_like_status=instance)

class FollowUnfollowUser(BaseMutation):
    
    class Arguments:
        user = graphene.ID(description='ID of User, who follows', required=True)
        followee = graphene.ID(description='ID of User, being followed', required=True)
        follow_status = graphene.Boolean(description='is following or not')

    class Meta:
        description = "Create or Update User follow status"

    UserFollowedStatus = graphene.Field(UserFollowedStatus)

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, root, info, **data):
        user_id = graphene.Node.from_global_id(data.get('user'))[1]
        followee_id = graphene.Node.from_global_id(data.get('followee'))[1]
        follow_status = data.get('follow_status', True)
        
        instance, is_created = models.UserFollowedStatus.objects.get_or_create(user_id=user_id, followee_id=followee_id)
        if instance.follow_status != follow_status:
            instance.follow_status = follow_status
            instance.save()
        if follow_status == True:
            models.UserFollowedStatus.objects.filter(id=instance.id).update(message_count=F('message_count') + 1)
        
        return FollowUnfollowUser(UserFollowedStatus=instance)

class UserMediaInput(graphene.InputObjectType):
    user_id = graphene.ID(description = "id of user from like request", required = True)
    media_link = graphene.String(description = "media link", required = True)
    type = UserMediaTypeEnums(description="type of user media ")

class UserMediaCreate(ModelMutation):
    class Arguments:
        input = UserMediaInput(
            required=True, description="user media field"
        )

    class Meta:
        description = "Create user media content"
        model = models.UserMedia
        return_field_name = "UserMedia"
        error_type_field = "UserMedia_errors"

    user_media = graphene.Field(UserMedia)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        
        try:
            cleaned_input = cls.clean_input(info = info, instance = UserMedia(),
                                                    data = data.get("input"))
            instance=models.UserMedia()
            instance.user=cleaned_input.get('user_id')
            instance.media_link=cleaned_input.get('media_link')
            instance.type=cleaned_input.get('type')
            instance.save()
            
            return cls(user_media=instance)
        
        except Exception as error:
            raise ValidationError({"message": ValidationError(error.message,
                                                                   code = AccountErrorCode.INVALID)})
            
