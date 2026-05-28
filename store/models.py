from saleor.core.models import ModelWithCreateTimestamp, ModelWithCreateUpdateTimestamp, SortableModel, ModelWithMetadata
from saleor.store.states import StoreCategoryPageLevels, StoreNextActions, StoreStateEnum, StoreStatus, StoreTileEnum , StoreTypeEnum, StoreBrandSourcingRequestEnum, BrandCollabEnum, LinktreeType
from saleor.utilities.time_utilities import TimeUtilities
from django.conf import settings
from django.db import models
from django.contrib.auth.models import Group, Permission
from saleor.product import models as product_models
from django.utils.translation import gettext_lazy as _
from versatileimagefield.fields import VersatileImageField, PPOIField
from django.db.models import Q
from django.db import transaction
from saleor.core import ModeofPayment
class StorePermissionMixin(models.Model):
    is_superuser = models.BooleanField(
        _('superuser status'),
        default=False,
        help_text=_(
            'Designates that this user has all permissions without '
            'explicitly assigning them.'
        ),
    )

    groups = models.ManyToManyField(
    Group,
    verbose_name=_('groups'),
    blank=True,
    help_text=_(
        'The groups this Member state belongs to. A user will get all permissions'
        'granted to each of their groups.'
    ),
    related_name="storemember_set",
    related_query_name="storemember",
    )
    member_permissions = models.ManyToManyField(
        Permission,
        verbose_name=_('store permissions'),
        blank=True,
        help_text=_('Specific permissions for this user.'),
        related_name="storemember_set",
        related_query_name="storemember",
    )
    def _get_store_member_permissions(self, store_member_obj):
        return store_member_obj.member_permissions.all()

    def _get_group_permissions(self, store_member_obj):
        user_groups_field = StoreMemberState._meta.get_field('groups')
        user_groups_query = 'group__%s' % user_groups_field.related_query_name()
        return Permission.objects.filter(**{user_groups_query: store_member_obj})
        
    def _get_permissions(self, store_member_obj, obj, from_name):
        """
        Return the permissions of `store_member_obj` from `from_name`. `from_name` can
        be either "group" or "store_member" to return permissions from
        `_get_group_permissions` or `_get_store_member_permissions` respectively.
        """
        if not self.user.is_active or obj is not None:
            return set()

        perm_cache_name = '_%s_perm_cache' % from_name
        if not hasattr(store_member_obj, perm_cache_name):
            if store_member_obj.is_superuser:
                perms = Permission.objects.all()
            else:
                perms = getattr(self, '_get_%s_permissions' % from_name)(store_member_obj)
            perms = perms.values_list('content_type__app_label', 'codename').order_by()
            setattr(store_member_obj, perm_cache_name, {"%s.%s" % (ct, name) for ct, name in perms})
        return getattr(store_member_obj, perm_cache_name)

    def get_store_member_permissions(self, obj=None):
        """
        Return a list of permission strings that this store_member_obj has directly.
        If an object is passed in, return only permissions matching this object.
        """
        return self._get_permissions(self, obj, 'store_member')

    def get_group_permissions(self, obj=None):
        return self._get_permissions(self, obj, 'group')

    def get_all_permissions(self, obj=None):

        return {
            *self.get_store_member_permissions(obj=obj),
            *self.get_group_permissions(obj=obj),
        }

    def _member_has_perm(self, perm, obj=None):

        return perm in self.get_all_permissions(obj=obj)


    def has_perm(self, perm, obj=None):
        """
        Return True if the user has the specified permission. Query all
        available auth backends, but return immediately if any backend returns
        True. Thus, a user who has permission from a single auth backend is
        assumed to have permission in general. If an object is provided, check
        permissions for that object.
        """
        # This method is overridden to accept perm as BasePermissionEnum
        perm = perm.value if hasattr(perm, "value") else perm

        # Active superusers have all permissions.
        if self.user.is_active and self.user.is_superuser:
            return True

        # Otherwise we need to check the backends.
        return self._member_has_perm(perm, obj=obj)

    def has_perms(self, perm_list, obj=None):
        """
        Return True if the user has each of the specified permissions. If
        object is passed, check if the user has all required perms for it.
        """

        return all(self.has_perm(perm, obj=obj) for perm in perm_list)

    class Meta:
        abstract = True



class StoreInfo(ModelWithCreateUpdateTimestamp, ModelWithMetadata):
    store_name = models.CharField(max_length=512, blank=True)
    store_url = models.TextField(null=True)
    description = models.JSONField(default=dict)
    state = models.IntegerField(default=StoreStateEnum.ACTIVE)
    slug = models.SlugField(max_length=512, unique=True, allow_unicode=True)
    staff_members = models.ManyToManyField("account.User", related_name= "authourised_stores", through="StaffStoreMapping",
                     through_fields=['store', 'user'])
    store_type = models.CharField(max_length=15,choices=StoreTypeEnum.CHOICES,default=StoreTypeEnum.INFLUENCER)
    store_category_page_level = models.CharField(max_length=32, 
    choices=StoreCategoryPageLevels.CHOICES, default=StoreCategoryPageLevels.LEVEL_3)
    content = models.TextField(null=True)
    
    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return self.store_name

    def get_all_collections(self, qs=None):
        collection_ids = self.collection_store.all().values_list("collection",
        flat=True).distinct()
        if qs:
            collections= qs.filter(id__in=collection_ids)
        else:
            collections = product_models.Collection.objects.filter(id__in=collection_ids)
        return collections

    def get_store_authorized_users(self):
        return [data.user for data in self.store_members.select_related("user").all()]
    
    def is_streak_live(self):
        # today_start = TimeUtilities().get_today_start()
        # yesterday_start = TimeUtilities().get_yesterdays_date()
        # day_before_yesterday_start = TimeUtilities.subtract_time_from_timestamp(yesterday_start, days=1)
        # _2day_before_yesterday_start = TimeUtilities.subtract_time_from_timestamp(yesterday_start, days=2)


        # store_yesterday_order = self.order_store.filter(created_at__gte=yesterday_start, created_at__lte=today_start).first()

        # if not store_yesterday_order:
        #     return False

        # if store_yesterday_order.streak_order:
        #     return True

        # else:

        #     store_day_before_yesterday_order = self.order_store.filter(
        #         created_at__gte=day_before_yesterday_start, 
        #         created_at__lte=yesterday_start).first()

        #     store_2day_before_yesterday_order = self.order_store.filter(
        #         created_at__gte=_2day_before_yesterday_start, 
        #         created_at__lte=day_before_yesterday_start).first()

        #     return bool(store_yesterday_order and store_day_before_yesterday_order and store_2day_before_yesterday_order)
        return False

    @staticmethod
    def create_instance(info):

        instance = StoreInfo()
        instance.description = info.get('description', dict())
        instance.store_url = info.get('store_url', '')
        instance.store_name = info.get('store_name', '')
        instance.slug = info.get('slug')
        instance.store_type = info.get('store_type',StoreTypeEnum.INFLUENCER)
        instance.save()

        return instance

    @property
    def instagram_link(self):

        member = self.store_members.first()
        influencer = member.user.influencer.first()
    
        return influencer.instagram_link
        


class StoreManagerActions(ModelWithCreateUpdateTimestamp):

    store = models.OneToOneField(StoreInfo, related_name='actions', on_delete=models.CASCADE)

    status = models.CharField(max_length=50, choices=StoreStatus.CHOICES, 
                              default=StoreStatus.STILL_EXPLORING)

    next_actions = models.CharField(max_length=50, choices=StoreNextActions.CHOICES, 
                              default=StoreNextActions.LIFESTYLE)
    

class StoreManagerComment(ModelWithCreateUpdateTimestamp):
    user = models.ForeignKey("account.User", related_name="store_comments", on_delete=models.CASCADE)
    store = models.ForeignKey(StoreInfo, related_name='comments', on_delete=models.CASCADE)
    comment  = models.TextField()

    
    class Meta:
        ordering = ("created_at",)

class StaffStoreMapping(ModelWithCreateTimestamp):
    user = models.ForeignKey("account.User", related_name="staff_store_mappings", on_delete=models.CASCADE)
    store = models.ForeignKey(StoreInfo, related_name='staff_store_mappings', on_delete=models.CASCADE)


class StoreMemberState(StorePermissionMixin, ModelWithCreateUpdateTimestamp):

    store = models.ForeignKey(StoreInfo, on_delete=models.CASCADE, related_name="store_members")
    user = models.ForeignKey("account.User", on_delete=models.CASCADE,related_name="store_members")
    state = models.IntegerField(default=0)

    class Meta:
        ordering = ("created_at",)

    @staticmethod
    def create_instance(info):

        instance = StoreMemberState()
        instance.store = info.get('store_instance')
        instance.user = info.get('user_instance')
        instance.state = info.get('state', 0)
        instance.save()
        
        # add instance to grp
        grp, _ = Group.objects.get_or_create(name=settings.STORE_MEMBERS_BASE_PERMISSION_GROUP)
        grp.storemember_set.add(instance)
        
        return instance
    
    def __str__(self) -> str:
        return self.user.get_full_name()
        
    
    class Meta:
        unique_together = [['store', 'user']]


class StoreNotification(ModelWithCreateTimestamp):

    stores = models.ManyToManyField(StoreInfo, related_name="notifications")
    text = models.TextField()
    image_url = models.TextField()
    route = models.TextField(null=True)

    class Meta:
        ordering = ("-created_at", "-id")
    

    @staticmethod
    def create_instance(info):

        instance = StoreNotification()
        instance.store = info.get('store_instance')
        instance.text = info.get('text')
        instance.image_url = info.get('image_url')
        instance.route = info.get('route')
        instance.save()

        return instance

class StoreTileQueryset(models.QuerySet):
    
    def active(self):
        current_datetime = TimeUtilities.get_current_date_time()

        return self.filter(start_datetime__lt=current_datetime, end_datetime__gte=current_datetime)

    def expired(self):
        current_datetime = TimeUtilities.get_current_date_time()

        return self.filter(end_datetime__lt=current_datetime)


class StoreTile(ModelWithCreateTimestamp):
    stores = models.ManyToManyField(StoreInfo, related_name="store_tiles")
    route = models.CharField(max_length=128, null=True)
    image = VersatileImageField(upload_to='store_tiles', blank=False)
    rank = models.IntegerField(default=0)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    
    tile_type = models.CharField(max_length=32, 
    choices=StoreTileEnum.CHOICES, default=StoreTileEnum.INFLUENCER_STORE)
    
    objects = StoreTileQueryset.as_manager()
    class Meta:
        ordering = ("rank", "-created_at")


class StoreCategoryPage(ModelWithCreateUpdateTimestamp):
    store = models.ForeignKey(StoreInfo, on_delete=models.CASCADE, related_name="store_category_page")
    brand = models.ForeignKey("brand.Brand", on_delete=models.CASCADE, related_name="store_category_page")
    category = models.ForeignKey("product.Category", on_delete=models.CASCADE, related_name="store_category_page")
    is_added = models.BooleanField(default=False, db_index=True)
    add_count = models.IntegerField(default=0)

    class Meta:
        ordering = ('-created_at',)

    @staticmethod
    @transaction.atomic()
    def create_instance(info):
        store_instance = info.get('store_instance')
        category_instance = info.get('category_instance')
        brand_instance = info.get('brand_instance')
        is_added = info.get('is_added', True)
        
        if not store_instance or not category_instance or not brand_instance:
            return
        
        page_filter = StoreCategoryPage.objects.filter(
            store=store_instance, 
            category=category_instance, 
            brand=brand_instance)

        if not page_filter:
            StoreCategoryPage(store=store_instance, 
            category=category_instance, 
            brand=brand_instance, 
            is_added=is_added,
            add_count=1).save()

        else:
            instance = page_filter[0]
            instance.is_added = True if instance.is_added else False
            instance.add_count = instance.add_count + 1
            instance.save()

class StorePayout(ModelWithCreateUpdateTimestamp):
    store = models.ForeignKey(StoreInfo , on_delete=models.CASCADE ,related_name="store_payout")
    amount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0)
    transaction_details = models.CharField(max_length=500,blank = True)
    date = models.DateTimeField(null=True, blank=True)
    modeofpayment = models.CharField(max_length = 15 ,choices=ModeofPayment.CHOICES, blank = True)


class StoreAnalytics(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    store = models.ForeignKey(StoreInfo, on_delete=models.CASCADE, related_name="store_analytics")
    total_orders = models.IntegerField(default=0)
    orderlines_count = models.IntegerField(default=0)
    wishlist_of_products = models.IntegerField(default=0)
    no_of_sourcing_requests_initiated = models.IntegerField(default=0)
    no_of_sourcing_requests_brand_fullfilled = models.IntegerField(default=0)
    number_of_products_sold = models.IntegerField(default=0)
    total_store_sales = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total_store_sales_after_discount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total_msp_sales = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    no_of_coupons_used = models.IntegerField(default=0)
    abandoned_cart_count = models.IntegerField(default=0)
    total_earnings = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total_store_payout = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    net_payout_due = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    last_payout = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    mobile_no = models.CharField(default='', max_length=20)
    last_product_added = models.CharField(default='', max_length=40)
    analytics_date = models.DateTimeField()
    last_3_order_cities = models.CharField(default='', max_length=200)


class BrandSourcingRequest(ModelWithCreateTimestamp):
    brand = models.ForeignKey("brand.Brand", on_delete=models.CASCADE, related_name="sourcing_requests")
    store = models.ForeignKey(StoreInfo, on_delete=models.CASCADE, related_name="sourcing_requests")
    terms_and_conditions = models.TextField()
    store_bucket = models.CharField(max_length=50, choices=StoreStatus.CHOICES, default=StoreStatus.STILL_EXPLORING)
    state = models.CharField(max_length=20, choices=StoreBrandSourcingRequestEnum.CHOICES, default=StoreBrandSourcingRequestEnum.REQUEST_RECEIVED)
    created_by = models.ForeignKey("account.User", on_delete=models.CASCADE)
    brand_managers = models.TextField(null=True)
    store_managers = models.TextField(null=True)
    brand_collab = models.CharField(max_length=20, choices=BrandCollabEnum.CHOICES, default=BrandCollabEnum.YES)
    campaign_name = models.TextField(null=True)
    content = models.TextField(null=True)
    notification = models.BooleanField(default=False)

class Linktree(ModelWithCreateUpdateTimestamp):
    store = models.ForeignKey(StoreInfo, on_delete=models.SET_NULL, null=True)
    type = models.CharField(max_length=31, choices=LinktreeType.CHOICES, default=LinktreeType.OTHER)
    url = models.CharField(max_length=511)
    image = VersatileImageField(upload_to="linktree", ppoi_field="ppoi", blank=True, null=True)
    ppoi = PPOIField()
    text = models.CharField(max_length=255)

    def save(self, *args, **kwargs) -> None:
        super().save(*args, **kwargs)
        if not self.image:
            if self.type in (LinktreeType.OTHER, LinktreeType.LINKTREE):
                image = f"linktree/profile_{self.store_id}.jpg"
            else:
                image = f"linktree/social_icons/{self.type}.jpg"
            img_update = Linktree.objects.filter(id=self.id).update(image=image) 

