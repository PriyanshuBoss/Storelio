import graphene
from saleor.graphql.api import schema
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.conf.urls import url
from django.http import HttpResponseRedirect
from django.utils.html import format_html
from django.template.response import TemplateResponse
from saleor.brand.models import Brand, BrandCollection, BrandCollectionMapping, BrandMemberState, Commission, StaffBrandMapping, BrandEmail,BrandBankAccount, BrandUpiId,BrandShippingData,BrandGrouping,BrandGroupMapping,BrandPayout, Arrear, BrandMobile
from saleor.account.models import User
import json
import csv
from django import forms
from django.forms import widgets
from django.db.models import JSONField 
from saleor.product.models import Product, SourcingRequest
from saleor.product import BarterType
from saleor.store.models import BrandSourcingRequest
from django.contrib import messages
from .states import ArrearTypeEnum
from saleor.utilities.time_utilities import TimeUtilities
from .emails import prepare_email_text_for_barter, prepare_email_text_for_too_many_orders_or_brand_is_active, send_email_brand_ledger, send_email_for_brand_status_changes, prepare_email_text_for_botd, send_mail_for_arrear_creation_or_updation, get_arrear_text_for_arrear_creation


class PrettyJSONWidget(widgets.Textarea):

    def format_value(self, value):
        try:
            value = json.dumps(json.loads(value), indent=2, sort_keys=True)
            row_lengths = [len(r) for r in value.split('\n')]
            self.attrs['rows'] = min(max(len(row_lengths) + 2, 10), 30)
            self.attrs['cols'] = min(max(max(row_lengths) + 2, 40), 120)
            return value
        except Exception as e:
            return super(PrettyJSONWidget, self).format_value(value)
   
class BrandEmailAdmin(admin.TabularInline):
    model = BrandEmail
    fields = ("brand_email","state")
    extra=0

class BrandBankAccountAdmin(admin.TabularInline):
    model = BrandBankAccount
    extra=0

class BrandUpiIdAdmin(admin.TabularInline):
    model = BrandUpiId
    extra=0

class BrandShippingDataAdmin(admin.TabularInline):
    model = BrandShippingData
    extra=0

class BrandPayoutAdmin(admin.TabularInline):
    model = BrandPayout
    extra=0

class BrandPhoneAdmin(admin.TabularInline):
    model = BrandMobile
    extra = 0

class AuthorisedUserAdmin(admin.TabularInline):
    model = StaffBrandMapping
    extra=0

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):

        field = super(AuthorisedUserAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

        if db_field.name == 'user':
            if request._obj_ is not None:
                field.queryset = field.queryset.filter(is_staff=True)  
            else:
                field.queryset = field.queryset.none()

        return field


class BooleanKeyInputForm(forms.ModelForm):
    payment_verified = forms.BooleanField(required=False)

    class Meta:
        model = Brand
        exclude = ()

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    form = BooleanKeyInputForm
    list_display = ('brand_name', 'company_name', 'brand_contact_name', 'brand_contact_number', 'image_data')
    list_filter = ('company_name',)
    fields = [
                "company_name",
                "brand_name",
                "brand_contact_name",
                "brand_contact_number",
                "address", 
                "return_address",
                "active",
                "botd",
                "metadata",
                "shipping_return_policy",
                "zaamo_creators_guidelines",
                "short_description",
                "size_fit_note",
                "prefered_payment_mode",
                "brand_source",
                "image",
                "pan_number",
                "brand_order_info",
                "private_metadata",
                "order_processing_days",
                "order_shipping_days",
                "brand_barter",
                "brand_barter_guidelines",
                "too_many_orders",
                "payment_verified",
            ]

    raw_id_fields = ("address", "return_address")

    readonly_fields = ["private_metadata"]
    search_fields = ('brand_name', )
    inlines = [AuthorisedUserAdmin,BrandEmailAdmin,BrandPhoneAdmin,BrandBankAccountAdmin, BrandUpiIdAdmin,BrandShippingDataAdmin,BrandPayoutAdmin]

    formfield_overrides = {
        JSONField: {'widget': PrettyJSONWidget}
    }

    def update_brand_managers(self, brand_id, emails):
        SourcingRequest.objects.filter(brand=brand_id).update(brand_managers=emails)
        BrandSourcingRequest.objects.filter(brand=brand_id).update(brand_managers=emails)
    
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        for formset in formsets:
            if formset.model == StaffBrandMapping and formset.has_changed():
                
                brand_id = formset.instance.id
                emails = ",".join(formset.instance.staff_brand_mappings.all().values_list('user__email', flat=True))
                
                self.update_brand_managers(brand_id, emails)


    def save_model(self, request, obj, form, change):
        if request.method == 'POST':
            if request.POST.get('activate_account'):
                activated, msg = self.activate_account(obj.id, obj.brand_contact_number)
                if activated:
                    self.message_user(request, msg)
                else:
                    self.message_user(request, msg, level=messages.ERROR)
                return HttpResponseRedirect('../')
        if change:

            if form.changed_data:

                old_obj = self.model.objects.filter(id=obj.id).first()
                old_status = old_obj.brand_barter
                old_tmo = old_obj.too_many_orders
                old_active = old_obj.active
                old_botd = old_obj.botd

                if not old_obj.brand_barter and form.cleaned_data["brand_barter"]:
                    form.cleaned_data["metadata"].update({
                        'brand_barter_active_date': TimeUtilities.get_current_date_time()
                        })

                if not old_status:
                    
                    if obj.brand_barter:
                        email_text = prepare_email_text_for_barter(obj)
                        send_email_for_brand_status_changes.delay("Brand Name - {}(Brand Barter)".format(obj.brand_name),email_text)
                        
                        var = Product.objects.filter(brand_id = old_obj.id ,brand_barter = BarterType.ACTIVE_BARTER).first()
                        if not var:
                            Product.objects.filter(brand_id = old_obj.id).update(brand_barter = BarterType.ACTIVE_BARTER)

                else:

                    if not obj.brand_barter:
                        
                        email_text = prepare_email_text_for_barter(obj)
                        send_email_for_brand_status_changes.delay("Brand Name - {}(Not Brand Barter)".format(obj.brand_name),email_text)

                if not old_botd:

                    if obj.botd:
                        email_text = prepare_email_text_for_botd(obj)
                        # send_email_for_brand_status_changes.delay("Brand Name - {}(BOTD)".format(obj.brand_name),email_text)

                else:
                    
                    if not obj.botd:
                        email_text = prepare_email_text_for_botd(obj)
                        # send_email_for_brand_status_changes.delay("Brand Name - {}(Not BOTD)".format(obj.brand_name),email_text)
                
                if not old_tmo:

                    if obj.too_many_orders:
                        email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(obj, old_obj,for_tmo_email=True)
                        send_email_for_brand_status_changes.delay("Brand Name - {}(TMO)".format(obj.brand_name),email_text)

                else:

                    if not obj.too_many_orders:
                        email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(obj, old_obj,for_tmo_email=True)
                        send_email_for_brand_status_changes.delay("Brand Name - {}(Not TMO)".format(obj.brand_name),email_text)
                    

                if not old_active:

                    if obj.active:

                        email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(obj, old_obj,for_tmo_email=False)
                        send_email_for_brand_status_changes.delay("Brand Name - {}(Active)".format(obj.brand_name),email_text)
                else:

                    if not obj.active:

                        email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(obj, old_obj,for_tmo_email=False)
                        send_email_for_brand_status_changes.delay("Brand Name - {}(In-Active)".format(obj.brand_name),email_text )

        existing_private_metadata = obj.private_metadata
        existing_private_metadata['payment_verified'] = form.cleaned_data.get('payment_verified') 
        obj.private_metadata = existing_private_metadata

        super().save_model(request, obj, form, change)

    def get_form(self, request, obj=None, **kwargs):
        # just save obj reference for future processing in Inline
        request._obj_ = obj
        form = super(BrandAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields['payment_verified'].initial = obj.private_metadata.get('payment_verified')
        else:
            form.base_fields['payment_verified'].initial = False
        
        return form
    

    def image_data(self,obj):
        
        if obj.image:
            return format_html('<img src="{0}" style="width: 85px; height:85px;" />'.format(obj.image.url))

    def get_urls(self):
        urls = super(BrandAdmin, self).get_urls()
        custom_page_urls = [
                url(r"^upload_brand_payout/", login_required(self.upload_brand_payout), name="upload_brand_payout")
                ]
        return custom_page_urls + urls

    def activate_account(self, brand_pk, brand_contact):
        brand_contact = '91' + ''.join(brand_contact.split())[-10:]
        user_pk = 0
        user = User.objects.filter(mobile_no=brand_contact).first()
        if user:
            user_pk = user.pk
        else:
            result = self.register_user(brand_contact)
            if not result.data:
                return False, "Error"
            user_pk = graphene.Node.from_global_id(result.data['userRegister']['user']['id'])[1]
        
        brand_member = BrandMemberState.objects.filter(user=user_pk, brand=brand_pk)
        if brand_member.exists():
            return True, "Brand home already active."
        else:
            brand_id = graphene.Node.to_global_id("Brand", brand_pk)
            result = self.create_brand_member(brand_contact, brand_id)
            if not result.data:
                return False, "Error"

        return True, "Brand home activated successfully."

    def register_user(self, mobile_no):
        query = """
            mutation{
                userRegister(input:{
                    mobileNo: "%s"
                    isActive: false
                }){
                    user{
                    id
                    }
                }
            }""" % (mobile_no)
        result = schema.execute(query)
        return result

    def create_brand_member(self, mobile_no, brand_id):
        query = """
            mutation{
                activateBrandAccount(input:{
                mobileNo:"%s"
                brandId:"%s"
                }){
                    user{
                    id
                    mobileNo
                    isActive
                    }
                }
            }""" % (mobile_no, brand_id)
        result = schema.execute(query)
        return result

    def upload_brand_payout(self, request):
        mandatory_columns = ('transfer id', 'utr', 'amount', 'source', 'processed on')
        if request.method == 'POST':
            csv_file = request.FILES.get('file')
            rows = csv_file.read().decode('utf-8').splitlines()
            rows[0] = ','.join(column.strip().lower() for column in rows[0].split(','))
            columns = rows[0].split(',')
            if not set(mandatory_columns).issubset(columns):
                self.message_user(request, 'One or more mandatory column missing.', level=messages.ERROR)
                return HttpResponseRedirect('./')
            
            payouts = [row for row in csv.DictReader(rows)]
            
            brand_names = set(row['transfer id'].strip() for row in payouts)
            brands = Brand.objects.filter(brand_name__in=brand_names)
            brands = {brand.brand_name: brand for brand in brands}
            
            success = 0
            fail = 0
            for row in payouts:
                try:
                    BrandPayout.objects.update_or_create(
                        brand = brands.get(row['transfer id'].strip()),
                        amount = row['amount'].strip(),
                        transaction_details = row['utr'].strip(),
                        date = row['processed on'].strip(),
                        mode_of_payment = row['source'].strip().lower()
                    )
                    success += 1
                except Exception as e:
                    fail += 1
                    self.message_user(request, str(e), level=messages.ERROR)
            if success:
                self.message_user(request, f'{success} Payouts successfully uploaded.')
                if fail == 0:
                    send_email_brand_ledger.delay(list(brand_names))

            return HttpResponseRedirect('../')

        _dict = {
            'add': True,
            'change': False,
            'has_editable_inline_admin_formsets': False,
            'has_add_permission': True,
            "has_change_permission": True, 
            "has_view_permission": True,
            'has_file_field': True,
            "has_delete_permission": False, 
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
            'show_save_and_add_another': False,
            'show_save_and_continue': False,
            'mandatory_columns': mandatory_columns,
            'media': '',
            'title': 'Upload Payouts'
        }
        context = dict(
           # Include common variables for rendering the admin template.
           self.admin_site.each_context(request),
           # Anything else you want in the context...
           opts=self.model._meta,
           app_label=self.model._meta.app_label
        )
        context.update(_dict)

        return TemplateResponse(request, "admin/brand/upload_brand_payout.html", context)


@admin.register(BrandMemberState)
class BrandMemberAdmin(admin.ModelAdmin):
    list_display = ('brand', 'state')
    list_filter = ('brand',)


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ('brand', 'commission_percentage')
    list_filter = ('brand',)

class BrandGroupMappingAdmin(admin.TabularInline):
    model = BrandGroupMapping
    fields = ('brand','brand_group_rank')
    extra=0


@admin.register(BrandGrouping)
class BrandGroupingAdmin(admin.ModelAdmin):
    inlines = [BrandGroupMappingAdmin]

class BrandCollectionMappingAdmin(admin.TabularInline):
    model = BrandCollectionMapping
    fields = ('brand_collection',)
    extra=0

@admin.register(BrandCollection)
class BrandCollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'active','brand')
    search_fields = ('name', 'brand__brand_name')
    inlines = [BrandCollectionMappingAdmin]
    
class RequiredFieldForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['brand'].required = False
        self.fields['store'].required = False
    
    def clean(self):
        arrear_type = self.cleaned_data['arrear_type']
        brand = self.cleaned_data['brand']
        store = self.cleaned_data['store']

        if arrear_type == ArrearTypeEnum.BRAND:
            if not brand:
                raise forms.ValidationError({'brand': "Brand Field is Required for Brand Arrear Type"})
            
            if store:
                self.cleaned_data['store'] = None

        if arrear_type == ArrearTypeEnum.INFLUENCER:
            if not store:
                raise forms.ValidationError({'store': "Store Field is Required for Store Arrear Type"})
            
            if brand:
                self.cleaned_data['brand'] = None
                
    class Meta:
        model = Arrear
        fields = ('brand','store',)

@admin.register(Arrear)
class ArrearAdmin(admin.ModelAdmin):
    form = RequiredFieldForm
    list_filter = ("arrear_type",)
    list_display = ("arrear_type", "brand", "store", "amount", "created_at",)
    
    fields = [
        "arrear_details",
        "amount",
        "person_of_contact",
        "arrear_type",
        "brand",
        "store"
    ]

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):

        field = super(ArrearAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

        if db_field.name == 'person_of_contact':
            field.queryset = field.queryset.filter(is_staff=True)  
            
        return field

    def save_model(self, request, obj, form, change):

        if change:

            if form.changed_data:
                old_obj = self.model.objects.filter(id=obj.id).first()

                super().save_model(request, obj, form, change)
                arrear_instance = form.cleaned_data
                arrear_instance["updated_at"] = obj.updated_at

                arrear_text = get_arrear_text_for_arrear_creation(arrear_instance, old_obj=old_obj)
                send_mail_for_arrear_creation_or_updation.delay("Arrear Updated", arrear_text)
        
        else:
            super().save_model(request, obj, form, change)
            arrear_instance = form.cleaned_data
            arrear_instance["created_at"] = obj.created_at

            arrear_text = get_arrear_text_for_arrear_creation(arrear_instance)
            send_mail_for_arrear_creation_or_updation.delay("Arrear Created", arrear_text)
