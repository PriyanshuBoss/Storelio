from django.db.models.fields import IPAddressField
from saleor.account.states import InfluencerState, InfluencerStatus, UserMediaType
from saleor.notifications.models import Notification
from saleor.notifications.states import DeviceType
from saleor.store.constants import CREDENTIALS_EXPIRY_SECONDS
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from typing import Union

from django.conf import settings
from django.contrib.auth.models import _user_has_perm  # type: ignore
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    Permission,
    PermissionsMixin,
)
from django.db import models
from django.db.models import JSONField  # type: ignore
from django.db.models import Q, QuerySet, Value
from django.forms.models import model_to_dict
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_countries.fields import Country, CountryField
from phonenumber_field.modelfields import PhoneNumber, PhoneNumberField
from versatileimagefield.fields import VersatileImageField

from ..core.models import BaseBankAccountModel, BaseUpId, ModelWithCreateTimestamp, ModelWithCreateUpdateTimestamp, ModelWithMetadata
from ..core.permissions import AccountPermissions, BasePermissionEnum, InfluencerPermissions, get_permissions
from ..core.utils.json_serializer import CustomJsonEncoder
from . import CustomerEvents
from .validators import validate_possible_number
from saleor.notifications import fcm
from saleor.utilities.request_utilities import PlatformTypeEnum

class PossiblePhoneNumberField(PhoneNumberField):
    """Less strict field for phone numbers written to database."""

    default_validators = [validate_possible_number]


class AddressQueryset(models.QuerySet):
    def annotate_default(self, user):
        # Set default shipping/billing address pk to None
        # if default shipping/billing address doesn't exist
        default_shipping_address_pk, default_billing_address_pk = None, None
        if user.default_shipping_address:
            default_shipping_address_pk = user.default_shipping_address.pk
        if user.default_billing_address:
            default_billing_address_pk = user.default_billing_address.pk

        return user.addresses.annotate(
            user_default_shipping_address_pk=Value(
                default_shipping_address_pk, models.IntegerField()
            ),
            user_default_billing_address_pk=Value(
                default_billing_address_pk, models.IntegerField()
            ),
        )


class Address(models.Model):
    first_name = models.CharField(max_length=256, blank=True)
    last_name = models.CharField(max_length=256, blank=True)
    company_name = models.CharField(max_length=256, blank=True)
    street_address_1 = models.CharField(max_length=256, blank=True)
    street_address_2 = models.CharField(max_length=256, blank=True)
    city = models.CharField(max_length=256, blank=True)
    city_area = models.CharField(max_length=128, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = CountryField()
    country_area = models.CharField(max_length=128, blank=True)
    phone = PossiblePhoneNumberField(blank=True, default="")
    email = models.EmailField(blank=True,null=True)
    objects = AddressQueryset.as_manager()

    class Meta:
        ordering = ("pk",)

    @property
    def full_name(self):
        return "%s %s" % (self.first_name, self.last_name)

    def __str__(self):
        if self.company_name:
            return "%s - %s" % (self.company_name, self.full_name)
        return self.full_name

    def __eq__(self, other):
        if not isinstance(other, Address):
            return False
        return self.as_data() == other.as_data()

    __hash__ = models.Model.__hash__

    def as_data(self):
        """Return the address as a dict suitable for passing as kwargs.

        Result does not contain the primary key or an associated user.
        """
        data = model_to_dict(self, exclude=["id", "user"])
        if isinstance(data["country"], Country):
            data["country"] = data["country"].code
        if isinstance(data["phone"], PhoneNumber):
            data["phone"] = data["phone"].as_e164
        return data

    def get_copy(self):
        """Return a new instance of the same address."""
        return Address.objects.create(**self.as_data())


class UserManager(BaseUserManager):
    def create_user(
        self, email, password=None, is_staff=False, is_active=True, **extra_fields
    ):
        """Create a user instance with the given email and password."""
        email = UserManager.normalize_email(email)
        # Google OAuth2 backend send unnecessary username field
        extra_fields.pop("username", None)

        user = self.model(
            email=email, is_active=is_active, is_staff=is_staff, **extra_fields
        )
        if password:
            user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        return self.create_user(
            email, password, is_staff=True, is_superuser=True, **extra_fields
        )

    def customers(self):
        return self.get_queryset().filter(
            Q(is_staff=False) | (Q(is_staff=True) & Q(orders__isnull=False))
        )

    def staff(self):
        return self.get_queryset().filter(is_staff=True)


class User(PermissionsMixin, ModelWithMetadata, AbstractBaseUser):
    email = models.EmailField(null=True,blank=True)
    mobile_no = models.TextField(unique=True)
    first_name = models.CharField(max_length=256, blank=True)
    last_name = models.CharField(max_length=256, blank=True)
    user_name = models.CharField(max_length=127, blank=True)
    addresses = models.ManyToManyField(
        Address, blank=True, related_name="user_addresses"
    )
    image_url = models.CharField(max_length=127, null=True, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    note = models.TextField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now, editable=False)
    default_shipping_address = models.ForeignKey(
        Address, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    default_billing_address = models.ForeignKey(
        Address, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    avatar = VersatileImageField(upload_to="user-avatars", blank=True, null=True)
    jwt_token_key = models.CharField(max_length=12, default=get_random_string)
    signed_up_from = models.CharField(
        max_length=32, choices=PlatformTypeEnum.CHOICES, null=True, blank=True
    )



    USERNAME_FIELD = "mobile_no"

    objects = UserManager()

    class Meta:
        ordering = ("mobile_no",)
        permissions = (
            (AccountPermissions.MANAGE_USERS.codename, "Manage customers."),
            (AccountPermissions.MANAGE_STAFF.codename, "Manage staff."),
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._effective_permissions = None

    def __str__(self) -> str:

        if self.is_staff and self.email:
            return StringUtilities.convert_number_to_string(self.email)

        return StringUtilities.convert_number_to_string(self.mobile_no)

    @property
    def effective_permissions(self) -> "QuerySet[Permission]":
        if self._effective_permissions is None:
            self._effective_permissions = get_permissions()
            if not self.is_superuser:
                self._effective_permissions = self._effective_permissions.filter(
                    Q(user=self) | Q(group__user=self)
                )
        return self._effective_permissions

    @effective_permissions.setter
    def effective_permissions(self, value: "QuerySet[Permission]"):
        self._effective_permissions = value
        # Drop cache for authentication backend
        self._effective_permissions_cache = None

    def get_full_name(self):
        if self.first_name or self.last_name:
            return ("%s %s" % (self.first_name, self.last_name)).strip()
        if self.default_billing_address:
            first_name = self.default_billing_address.first_name
            last_name = self.default_billing_address.last_name
            if first_name or last_name:
                return ("%s %s" % (first_name, last_name)).strip()
        if self.email:
            return self.email
        return ''

    def get_short_name(self):
        return self.mobile_no

    def has_perm(self, perm: Union[BasePermissionEnum, str], obj=None):  # type: ignore
        # This method is overridden to accept perm as BasePermissionEnum
        perm = perm.value if hasattr(perm, "value") else perm  # type: ignore

        # Active superusers have all permissions.
        if self.is_active and self.is_superuser and not self._effective_permissions:
            return True
        return _user_has_perm(self, perm, obj)

    @staticmethod
    def get_user_instance_by_mobile(mobile_no):

        user_filter = User.objects.filter(mobile_no=mobile_no)

        if user_filter:

            return user_filter.first()

    def get_store_member(self, store_id):
        store_member = self.store_members.filter(store=store_id).first()

        return store_member

    def has_store_access(self, store_id, perm_list):
        store_member = self.get_store_member(store_id)

        if store_member:
            return store_member.has_perms(perm_list)

        return False

    def get_authorised_stores(self,store_type=None):
        type_filter = {}
        if store_type:
            type_filter = {'store_type':store_type}
        from saleor.store.models import StoreInfo

        if self.is_superuser:

            return StoreInfo.objects.filter(**type_filter)

        if self.is_staff:

            if self.groups.filter(name="brand team"):
                
                return StoreInfo.objects.filter(**type_filter)
            else:
                
                staff_stores_ids = self.staff_store_mappings.all().values_list('store', flat=True)
                staff_stores = StoreInfo.objects.filter(id__in=staff_stores_ids).filter(**type_filter)
                
                return staff_stores

        return StoreInfo.objects.filter(id__in =[member.store.id for member in self.store_members.select_related('store').filter(**type_filter)])
            
    def get_brand_member(self):
        # assuming only one brand member per brand
        brand_member = self.brand_members.select_related('brand').first()

        return brand_member
    
    def get_authorised_brands(self):
        if self.is_superuser:
            from saleor.brand.models import Brand
            return Brand.objects.all()

        elif self.is_staff:
            
            if self.groups.filter(name="influencer team"):
                from saleor.brand.models import Brand
                return Brand.objects.all()
            
            else:
                staff_brands = self.staff_brand_mappings.select_related('brand').all()
                return [data.brand for data in staff_brands]

        return [member.brand for member in self.brand_members.select_related('brand').all()]

    def is_user_brand_part(self):

        return self.brand_members.exists()

    def is_user_influencer(self):
        
        return self.influencer.exists()

    def push_app_notification(self, data,devices=[]):
        """
        We will send the push notifications for APP.

        :param data: Data dict for app notifiation.
        :return: Notify the user with message
        """

        title = data.get('title')
        body = data.get('body')
        onclick_action = data.get('onclick_action')
        path = data.get('path', '')
        expiry_timestamp = data.get('expiry_timestamp')
        is_persistent = data.get('is_persistent')
        media = data.get('media')

        if len(devices)>0:
            fcm_android_list = list(
                self.devices.filter(
                    device_id__in=devices, is_active=True, device_type=DeviceType.ANDROID
                ).values_list(
                    'fcm_id', flat=True
                )
            )

            fcm_ios_list = list(
                self.devices.filter(
                    device_id__in=devices, is_active=True, device_type=DeviceType.IOS
                ).values_list(
                    'fcm_id', flat=True
                )
            )
        else:
            fcm_android_list = list(
                self.devices.filter(
                    is_active=True, device_type=DeviceType.ANDROID
                ).values_list(
                    'fcm_id', flat=True
                )
            )

            fcm_ios_list = list(
                self.devices.filter(
                    is_active=True, device_type=DeviceType.IOS
                ).values_list(
                    'fcm_id', flat=True
                )
            )

        data['expiry_timestamp'] = TimeUtilities.parse_date(expiry_timestamp, "%Y-%m-%d, %H:%M:%S")
        if is_persistent:
            
            notification = Notification.objects.create(
                title=title, description=body,
                onclick_action=onclick_action, recipient=self,
                expiry_timestamp=expiry_timestamp,
                path=path,
                data=data
            )
            n_id=None
            if notification:
                n_id = notification.id
        
        
        expiry_timestamp = data['expiry_timestamp']
        if fcm_android_list:
            fcm.notify_user(
                fcm_id_list=fcm_android_list, title=title, body=body,
                expiry_timestamp=expiry_timestamp,
                n_id=n_id, onclick_action=onclick_action, path=path,
                media=media, ios_user= False, is_persistent=is_persistent
            )

        if fcm_ios_list:
            fcm.notify_user(
                fcm_id_list=fcm_ios_list, title=title, body=body,
                expiry_timestamp=expiry_timestamp,
                n_id=n_id, onclick_action=onclick_action,
                media=media, ios_user=True, is_persistent=is_persistent
            )


class CustomerNote(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )
    date = models.DateTimeField(db_index=True, auto_now_add=True)
    content = models.TextField()
    is_public = models.BooleanField(default=True)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="notes", on_delete=models.CASCADE
    )

    class Meta:
        ordering = ("date",)


class CustomerEvent(models.Model):
    """Model used to store events that happened during the customer lifecycle."""

    date = models.DateTimeField(default=timezone.now, editable=False)
    type = models.CharField(
        max_length=255,
        choices=[
            (type_name.upper(), type_name) for type_name, _ in CustomerEvents.CHOICES
        ],
    )
    order = models.ForeignKey("order.Order", on_delete=models.SET_NULL, null=True)
    parameters = JSONField(blank=True, default=dict, encoder=CustomJsonEncoder)
    user = models.ForeignKey(User, related_name="events", on_delete=models.CASCADE)

    class Meta:
        ordering = ("date",)

    def __repr__(self):
        return f"{self.__class__.__name__}(type={self.type!r}, user={self.user!r})"


class StaffNotificationRecipient(models.Model):
    user = models.OneToOneField(
        User,
        related_name="staff_notification",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    staff_email = models.EmailField(unique=True, blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("staff_email",)

    def get_email(self):
        return self.user.email if self.user else self.staff_email



class Influencer(ModelWithCreateUpdateTimestamp, ModelWithMetadata):
    instagram_username = models.CharField(max_length=256, blank=True)
    instagram_user_id = models.CharField(max_length=256, blank=True)
    image_url = models.TextField(null=True, blank=True)
    state = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="influencer")
    name = models.CharField(max_length=256, blank=True)
    ig_status = models.BooleanField(default=False)
    instagram_link = models.TextField(null=True, blank=True)
    facebook_link = models.TextField(null=True, blank=True)
    youtube_link = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=InfluencerStatus.CHOICES, default=InfluencerStatus.REQUEST_RECEIVED)


    class Meta:
        ordering = ("created_at",)
        permissions = (
            (InfluencerPermissions.MANAGE_INFLUENCER.codename, "Manage Influencer."),
        )

    @staticmethod
    def create_instance(info):

        if Influencer.is_influencer_exists(info.get('user_instance')):
            return

        if info.get('instagram_user_id') and Influencer.is_instagram_user_id_exists(info.get('instagram_user_id')):
            return

        instance = Influencer()
        instance.user = info.get('user_instance')
        instance.is_verified = info.get('is_verified', False)
        instance.name = info.get('name', '')
        instance.instagram_username = info.get('instagram_username', '')
        instance.instagram_user_id= info.get('instagram_user_id', '')
        instance.state = info.get('state', 0)
        instance.image_url = info.get('image_url', '')
        instance.ig_status = info.get('ig_status', False)
        instance.instagram_link = info.get('instagram_link')
        instance.save()

        return instance

    @staticmethod
    def is_influencer_exists(user_instance):
        return Influencer.objects.filter(user=user_instance).exists()

    @staticmethod
    def is_instagram_user_id_exists(instagram_user_id):
        
        return Influencer.objects.filter(instagram_user_id=instagram_user_id).exists()

    def is_active(self):

        return self.state == InfluencerState.VERIFIED


class Credentials(ModelWithCreateUpdateTimestamp):
    token = models.TextField(null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.BooleanField(default=True)
    expires_at = models.DateTimeField(default=TimeUtilities.get_time_with_delta)

    @staticmethod
    def create_or_update_instance(info):
        
        credentials_filter =  Credentials.objects.filter(user=info.get('user_instance'))
        
        if not credentials_filter:
            instance = Credentials()
            instance.token = info.get('token')
            instance.user = info.get('user_instance')
            instance.expires_at = TimeUtilities.get_time_with_delta(time_delta=int(info.get('expires_at', CREDENTIALS_EXPIRY_SECONDS)))
            instance.save()


class InfluencerBankAccount(ModelWithCreateUpdateTimestamp, BaseBankAccountModel):
    influencer = models.ForeignKey(Influencer, on_delete=models.CASCADE, related_name= 'bank_accounts')
    class Meta:
        unique_together = ('ac_number', 'ac_ifsc_code')

class InfluencerUpiId(ModelWithCreateUpdateTimestamp, BaseUpId):

    influencer = models.ForeignKey(Influencer, on_delete=models.CASCADE, related_name= 'upi_ids')


class AccountBrand(ModelWithCreateUpdateTimestamp):
    user = models.ForeignKey(User, on_delete=models.CASCADE)


class UserMedia(ModelWithCreateUpdateTimestamp):
    
    user            = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    media_link      = models.CharField(max_length=127)
    type            = models.CharField(max_length=7, default=UserMediaType.IMAGE, choices=UserMediaType.CHOICES)
    likes_count     = models.IntegerField(default=0)
    dislikes_count  = models.IntegerField(default=0)


class UserFollowedStatus(ModelWithCreateUpdateTimestamp):
    user            = models.ForeignKey(User, on_delete=models.CASCADE, related_name='follows')
    followee        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followed')
    follow_status   = models.BooleanField(default=True)
    message_count   = models.IntegerField(default=0)

    class Meta:
        unique_together = ('user', 'followee')


class UserLikeStatus(ModelWithCreateUpdateTimestamp):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='likes')
    liked_user  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='liked_by')
    content     = models.ForeignKey(UserMedia, on_delete=models.CASCADE, related_name='liked_by')
    like_status = models.BooleanField(default=True)

    class meta:
        unique_together = ('user', 'liked_user','content')


def profile_image_upload_to(instance,filename):
    path = f'instagram_user/{filename}'

    return path

class InstagramUser(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    store = models.ForeignKey('store.StoreInfo', on_delete=models.CASCADE, related_name='store_instagram')
    ig_user_id = models.CharField(max_length=64)
    access_token = models.CharField(max_length=400)
    user_name = models.CharField(max_length=400,default='')
    user_id = models.CharField(max_length=400,default='')
    instagram = models.BooleanField(default=True)
    profile_image = models.FileField(upload_to=profile_image_upload_to,default=None, null=True)

    def delete_media_from_bucket(self, *args, **kwargs):
        # delete media file saved in storage/cloud bucket
        # only works on Media instance delete (not Post instance and not queryset)
        self.profile_image.delete()

        return super().delete(*args, **kwargs)
    
    def get_full_profile_image_url(self):
        if settings.FILE_STORAGE == 'AZURE':
            url = 'https://{}.blob.core.windows.net/{}/{}/{}'.format(
                    settings.AZURE_ACCOUNT_NAME,
                    settings.AZURE_CONTAINER,
                    settings.AZURE_LOCATION,
                    self.profile_image
                )
            return url
        
        return self.profile_image


class Post(ModelWithCreateUpdateTimestamp):
    post_id = models.CharField(max_length=30, unique=True)
    shortcode = models.CharField(max_length=11, unique=True, blank=True)
    owner = models.ForeignKey(InstagramUser, on_delete=models.SET_NULL, null=True, blank=True)
    store = models.ForeignKey('store.StoreInfo', on_delete=models.SET_NULL, null=True, blank=True)
    like_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    caption = models.TextField(blank=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    share_link = models.CharField(max_length=511, blank=True)


def media_upload_to(instance, filename):
    store_id = 0
    try:
        store_id = instance.post.store_id
    except Exception as e:
        pass

    path = f'instagram_posts/{store_id}/{filename}'

    return path

class Media(models.Model):
    IMAGE = 0
    VIDEO = 1
    MEDIA_TYPE = (
        (IMAGE, 'IMAGE'),
        (VIDEO, 'VIDEO')
    )

    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    shortcode = models.CharField(max_length=11, unique=True)
    media_type = models.SmallIntegerField(choices=MEDIA_TYPE, default=IMAGE)
    media_file = models.FileField(upload_to=media_upload_to)

    def delete(self, *args, **kwargs):
        # delete media file saved in storage/cloud bucket
        # only works on Media instance delete (not Post instance and not queryset)
        self.media_file.delete()

        return super().delete(*args, **kwargs)
    
    def get_full_media_url(media_file):
        if settings.FILE_STORAGE == 'AZURE':
            url = 'https://{}.blob.core.windows.net/{}/{}/{}'.format(
                    settings.AZURE_ACCOUNT_NAME,
                    settings.AZURE_CONTAINER,
                    settings.AZURE_LOCATION,
                    media_file
                )
            return url
        
        return media_file
    
    def get_media_type_name(media_type):
        if media_type == Media.VIDEO:
            return 'VIDEO'
        
        return 'IMAGE'

