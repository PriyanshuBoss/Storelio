from django.db import models
from django.utils.text import slugify
from django.conf import settings
from django_prices.models import MoneyField
from django_countries.fields import Country, CountryField
from versatileimagefield.fields import VersatileImageField
from saleor.core.models import  BaseBankAccountModel, BaseUpId, ModelWithCreateTimestamp, ModelWithMetadata, ModelWithCreateUpdateTimestamp
from saleor.account.models import Address, PossiblePhoneNumberField
from saleor.brand.states import BrandCollectionTypeEnum, BrandMemberStateEnum, BrandMobileTypes, BrandSourceEnum, BrandStatusEnum, PreferedPaymentModeEnum, BrandEmailStateEnum, ArrearTypeEnum, BrandImportanceEnum
from saleor.core.utils import generate_unique_slug
from saleor.store import models as store_models
from datetime import date
from saleor.core import ModeofPayment
from saleor.store.models import StoreInfo
from saleor.account.models import User
# Create your models here.

def get_default_return_exchange_policy():
    return {
        'shipping_policy': "",
        'return_policy': ""
    }


class Brand(ModelWithMetadata, ModelWithCreateUpdateTimestamp):
    company_name = models.CharField(max_length=75)
    brand_name = models.CharField(max_length=75, unique=True)
    brand_contact_name = models.CharField(max_length=75)
    brand_contact_number = models.CharField(max_length=75, blank=True)
    active = models.BooleanField(default=False)
    cod = models.BooleanField(default=False)
    cod_base_price = models.FloatField(default=0.0)

    status = models.CharField(max_length=75, choices=BrandStatusEnum.CHOICES, default=BrandStatusEnum.INACTIVE)
    
    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name= 'brand_address')
    return_address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name= 'brand_return_address')

    pickup_address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name= 'brand_pickup_address', null=True,blank = True)
    shipping_return_policy = models.JSONField(default=get_default_return_exchange_policy, blank=True)

    zaamo_creators_guidelines = models.JSONField(default=dict, blank=True)

    short_description = models.CharField(max_length=300, default='', blank=True)

    size_fit_note = models.CharField(max_length=300, default='', blank=True)

    prefered_payment_mode = models.CharField(max_length=25, choices=PreferedPaymentModeEnum.CHOICES, 
                                            default=PreferedPaymentModeEnum.BANK)
    brand_source = models.CharField(max_length=25, choices=BrandSourceEnum.CHOICES, 
                                    default =BrandSourceEnum.STAFF)
    image = VersatileImageField(upload_to="brands", blank=True, null=True)
    email = models.EmailField(null=True, blank=True)

    staff_members = models.ManyToManyField("account.User", related_name= "authourised_brands", through="StaffBrandMapping",
                     through_fields=['brand', 'user'])

    botd = models.BooleanField(default=False, help_text="If marked true then this can be made Brand Of The Day")
    
    pan_number = models.CharField(
        max_length=10,
        verbose_name='PAN Number',
        default='',
        blank=True
    )

    brand_order_info = models.TextField(default='', blank=True)
    order_processing_days = models.SmallIntegerField(default=0)
    order_shipping_days = models.SmallIntegerField(default=0)
    brand_barter = models.BooleanField(default=False)
    brand_barter_guidelines = models.CharField(max_length=500 , default='',blank = True)
    too_many_orders = models.BooleanField(default=False)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    slug = models.SlugField(max_length=250, unique=True, allow_unicode=True,null=True,blank=True)
    history_notes = models.TextField(default='', blank=True)
    importance = models.CharField(max_length=63, choices=BrandImportanceEnum.CHOICES, default=BrandImportanceEnum.OTHERS)

    def __str__(self) -> str:
        return self.brand_name

    class Meta:
            ordering = ['brand_name']

    def add_brand_member(self, user_instance):
    
        state_filter = self.brand_member_states.filter(brand=self, user=user_instance, state=BrandMemberStateEnum.OWNER)
        instance = None

        if not state_filter:
            instance = BrandMemberState(user=user_instance, brand=self)
            instance.save()

        return instance
    
    def get_active_brand_members(self):
        
        users = [member.user for member in self.brand_member_states.exclude(state=BrandMemberStateEnum.INACTIVE)]

        return users

    def get_brand_email(self):

        return self.email if self.email else None

    @staticmethod
    def get_instance(brand_id):
        
        try:
            brand_instance = Brand.objects.get(id=brand_id)
        except:
            brand_instance = None
        
        return brand_instance

    @property
    def store(self):
        
        store = store_models.StoreInfo.objects.filter(slug=slugify(self.brand_name, allow_unicode=True)).first()

        return store
    
    def save(self, *args, **kwargs):
        
        if not self.slug:
            self.slug = generate_unique_slug(Brand(),self.brand_name)

        super().save(*args, **kwargs)
        

class StaffBrandMapping(ModelWithCreateTimestamp):
    user = models.ForeignKey("account.User", related_name="staff_brand_mappings", on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand, related_name='staff_brand_mappings', on_delete=models.CASCADE)

class BrandBankAccount(ModelWithCreateUpdateTimestamp, BaseBankAccountModel):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name= 'bank_accounts')

    class Meta:

        unique_together = ('ac_number', 'ac_ifsc_code')


class BrandUpiId(ModelWithCreateUpdateTimestamp, BaseUpId):

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name= 'upi_ids')


class BrandMemberState(ModelWithCreateUpdateTimestamp):

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="brand_member_states")
    user = models.ForeignKey('account.User', on_delete=models.CASCADE, related_name='brand_members')
    state = models.CharField(max_length=25, choices=BrandMemberStateEnum.CHOICES, 
                            default=BrandMemberStateEnum.OWNER)

    class Meta:
        unique_together = (("brand", "user"),)


class Commission(ModelWithCreateUpdateTimestamp):

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="commission")
    commission_percentage = models.FloatField(default=0.0)
    zaamo_commission = models.FloatField(default=2.0)

class BrandEmail(ModelWithCreateUpdateTimestamp):

    brand_id = models.ForeignKey(Brand,on_delete=models.CASCADE,related_name="brand_emails")
    brand_email = models.EmailField(blank=True)
    state = models.CharField(max_length=15,choices=BrandEmailStateEnum.CHOICES,default=BrandEmailStateEnum.SECONDARY)


class BrandMobile(ModelWithCreateUpdateTimestamp):
    user_name = models.CharField(default='', max_length=40)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="mobiles")
    mobile_no = models.CharField(default='', max_length=15)
    active = models.BooleanField(default=False)
    type = models.CharField(default=BrandMobileTypes.PRIMARY, max_length=20)


class BrandGrouping(ModelWithCreateUpdateTimestamp):

    brands = models.ManyToManyField(Brand ,through="BrandGroupMapping" ,related_name="brand_grouping" , through_fields=['brand_group','brand'])
    image = VersatileImageField(upload_to="brand/brand_grouping", blank=True, null=True)
    description = models.CharField(max_length=500,blank=True)
    group_rank = models.PositiveIntegerField(default=0)
    customize = models.BooleanField(default=False)

    class Meta:
        ordering = ('group_rank','-created_at')


class BrandGroupMapping(ModelWithCreateUpdateTimestamp):

    brand_group = models.ForeignKey(BrandGrouping,related_name="through_brand_group_mapping",on_delete=models.CASCADE )
    brand = models.ForeignKey(Brand , related_name= "through_brand_group_mapping" , on_delete=models.CASCADE )
    brand_group_rank = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('brand_group_rank', '-created_at')
        unique_together = (("brand", "brand_group"),)

'''
My Dukaan Address mapping to be used when guest order creation isn't applicable

class MyDukaanBuyerMapping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    buyer_id = models.CharField(max_length=240)
    buyer_uuid = models.CharField(max_length=240)
    name = models.CharField(max_length=240)
    brand_id = models.ForeignKey(Brand,on_delete=models.CASCADE,related_name="brand_my_dukaan"),
    email = models.CharField(max_length=100)
    mobile = models.CharField(max_length=20)
    user_id = models.CharField(max_length=20,blank=True)

class MyDukaanBuyerAddressMapping(ModelWithCreateUpdateTimestamp,ModelWithMetadata):
    address_id = models.CharField(max_length=240)
    address_uuid = models.CharField(max_length=240)
    brand_id = models.ForeignKey(Brand,on_delete=models.CASCADE,related_name="brand_my_dukaan"),
    email = models.CharField(max_length=100)
    user_id = models.CharField(max_length=20,blank=True)
    mobile = models.CharField(max_length=20)
'''
class BrandShippingData(ModelWithCreateUpdateTimestamp):

    brand = models.ForeignKey(Brand,on_delete=models.CASCADE,related_name="brand_shipping")
    home_state_pincode = models.CharField(max_length=10,blank=True)
    country = CountryField(default='IN')
    currency = models.CharField(max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,default=settings.DEFAULT_CURRENCY,)
    shipping_cost_same_state_amount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0,)
    shipping_cost_other_state_amount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0,)
    min_order_value_free_cost_amount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0,)
    shipping_cost_same_state =  MoneyField(amount_field="shipping_cost_same_state_amount", currency_field="currency")
    shipping_cost_other_state =  MoneyField(amount_field="shipping_cost_other_state_amount", currency_field="currency")
    min_order_value_free_cost =  MoneyField(amount_field="min_order_value_free_cost_amount", currency_field="currency")

class BrandPayout(ModelWithCreateUpdateTimestamp):
    brand = models.ForeignKey(Brand , on_delete=models.CASCADE ,related_name="brand_payout")
    amount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0)
    transaction_details = models.CharField(max_length=500,blank = True)
    date = models.DateTimeField(null=True, blank=True)
    mode_of_payment = models.CharField(max_length = 15 ,choices=ModeofPayment.CHOICES, blank=True)

class BrandCollection(ModelWithMetadata, ModelWithCreateUpdateTimestamp):

    brand = models.ForeignKey(Brand , on_delete=models.CASCADE ,related_name="brand_collection")
    name = models.CharField(max_length=240)
    type = models.CharField(max_length=25, choices=BrandCollectionTypeEnum.CHOICES, 
                                    default =BrandCollectionTypeEnum.COLLECTION)
    product = models.ManyToManyField("product.Product", through='BrandCollectionMapping')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ('-updated_at',)

class BrandCollectionMapping(ModelWithCreateUpdateTimestamp):

    brand_collection = models.ForeignKey(BrandCollection , on_delete=models.CASCADE ,related_name="through_brand_collection")
    product = models.ForeignKey("product.Product" , on_delete=models.CASCADE ,related_name="through_brand_collection_product")

    class Meta:
        ordering = ('-updated_at',)

class Arrear(ModelWithCreateUpdateTimestamp):

    arrear_details = models.TextField(null=True, blank=True)
    amount = models.DecimalField(max_digits=settings.DEFAULT_MAX_DIGITS,decimal_places=settings.DEFAULT_DECIMAL_PLACES,default=0)
    person_of_contact = models.ForeignKey(User, on_delete=models.CASCADE)
    arrear_type = models.CharField(max_length=50, choices=ArrearTypeEnum.CHOICES, default=ArrearTypeEnum.BRAND)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, null=True)
    store = models.ForeignKey(StoreInfo, on_delete=models.CASCADE, null=True)

class BrandCred(ModelWithMetadata,ModelWithCreateUpdateTimestamp):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    access_key = models.CharField(max_length=500)
    access_pass = models.CharField(max_length=500)
    auth_token = models.CharField(max_length=3000,null=True,blank=True)
    url = models.CharField(max_length=300)

class BrandTag(ModelWithMetadata, ModelWithCreateUpdateTimestamp):

    name = models.CharField(max_length=240)
    product = models.ManyToManyField("product.Product", through='BrandTagMapping')

    class Meta:
        ordering = ('-updated_at',)

class BrandTagMapping(ModelWithCreateUpdateTimestamp):

    brand_tag = models.ForeignKey(BrandTag , on_delete=models.CASCADE ,related_name="through_brand_tag")
    product = models.ForeignKey("product.Product" , on_delete=models.CASCADE ,related_name="through_brand_tag_product")

    class Meta:
        ordering = ('-updated_at',)

class BrandOrderCount(ModelWithCreateUpdateTimestamp):
    
    brand_name = models.CharField(max_length=500)
    product_id_brand = models.CharField(max_length=500)
    variant_id_brand = models.CharField(max_length=500,null=True)
    brand_order_count = models.IntegerField(default=0)
    brand_order_count_last_month = models.IntegerField(default=0)
    brand_order_count_last_week = models.IntegerField(default=0)

    class Meta:
        ordering = ('-updated_at',)


class BrandResyncLog(ModelWithCreateTimestamp):
    source = models.CharField(max_length=800)
    success_brands = models.TextField()
    failed_brands = models.TextField()
    start_time = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(default='', blank=True)

