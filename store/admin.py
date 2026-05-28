from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.conf.urls import url
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
import csv
from saleor.store.models import StaffStoreMapping, StoreInfo, StoreMemberState, StoreNotification, StoreTile,StorePayout, BrandSourcingRequest
from saleor.product.models import SourcingRequest
from django import forms
from .emails import send_influencer_ledger_email

class AuthorisedUsersAdmin(admin.TabularInline):
    model = StaffStoreMapping
    extra=0
    
    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):

        field = super(AuthorisedUsersAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

        if db_field.name == 'user':
            if request._obj_ is not None:
                field.queryset = field.queryset.filter(is_staff=True)  
            else:
                field.queryset = field.queryset.none()

        return field


class StorePayoutAdmin(admin.TabularInline):
    model = StorePayout
    extra=0

@admin.register(StoreMemberState)
class StoreMemberStateAdmin(admin.ModelAdmin):
    list_display = ('id', 'state', 'store')
    list_filter = ('state',)

class BooleanKeysInputForm(forms.ModelForm):

    store_barter = forms.BooleanField(required=False)
    payment_verified = forms.BooleanField(required=False)
    max_time_botd_allowed = forms.IntegerField(required=False)

    class Meta:
        model = StoreInfo
        exclude = ()

@admin.register(StoreInfo)
class StoreInfoStateAdmin(admin.ModelAdmin):
    form = BooleanKeysInputForm
    list_display = ('store_name',)
    list_filter = ('state', )
    search_fields = ('store_name', )
    list_filter = ('created_at',)
    inlines = [AuthorisedUsersAdmin,StorePayoutAdmin]
    fields = [
        'store_name',
        'store_url',
        'description',
        'state',
        'slug',
        'store_type',
        'store_category_page_level',
        'store_barter',
        'metadata',
        'private_metadata',
        'payment_verified',
        'max_time_botd_allowed'
    ]

    readonly_fields = ('metadata',)

    def get_form(self, request, obj=None, **kwargs):
        # just save obj reference for future processing in Inline
        request._obj_ = obj
        form = super(StoreInfoStateAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields['store_barter'].initial = obj.metadata.get('store_barter')
            form.base_fields['payment_verified'].initial = obj.metadata.get('payment_verified')
            form.base_fields['max_time_botd_allowed'].initial = obj.metadata.get('max_time_botd_allowed')
        
        else:
            form.base_fields['store_barter'].initial = False
            form.base_fields['payment_verified'].initial = False
            form.base_fields['max_time_botd_allowed'].initial = 2

        return form


    def update_store_managers(self, store_id, emails):
        SourcingRequest.objects.filter(store=store_id).update(influencer_managers=emails)
        BrandSourcingRequest.objects.filter(store=store_id).update(store_managers=emails)
    
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        for formset in formsets:
            if formset.model == StaffStoreMapping and formset.has_changed():
                store_id = formset.instance.id
                emails = ",".join(formset.instance.staff_store_mappings.all().values_list('user__email', flat=True))
                
                self.update_store_managers(store_id, emails)


    def get_urls(self):
        urls = super(StoreInfoStateAdmin, self).get_urls()
        custom_page_urls = [
                url(r"^upload_store_payout/", login_required(self.upload_store_payout), name="upload_store_payout")
                ]
        return custom_page_urls + urls

    def save_model(self, request, obj, form, change):
        existing_metadata = obj.metadata
        existing_metadata['store_barter'] = form.cleaned_data.get('store_barter')
        existing_metadata['payment_verified'] = form.cleaned_data.get('payment_verified')
        existing_metadata['max_time_botd_allowed'] = form.cleaned_data.get('max_time_botd_allowed')
        obj.metadata = existing_metadata 
        return super().save_model(request, obj, form, change)

    

    def upload_store_payout(self, request):
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
            
            store_names = set(row['transfer id'].strip() for row in payouts)
            stores = StoreInfo.objects.filter(store_name__in=store_names)
            stores = {store.store_name: store for store in stores}
            
            success = 0
            fail = 0
            for row in payouts:
                try:
                    StorePayout.objects.update_or_create(
                        store = stores.get(row['transfer id'].strip()),
                        amount = row['amount'].strip(),
                        transaction_details = row['utr'].strip(),
                        date = row['processed on'].strip(),
                        modeofpayment = row['source'].strip().lower()
                    )
                    success += 1
                except Exception as e:
                    fail += 1
                    self.message_user(request, str(e), level=messages.ERROR)
            if success:
                self.message_user(request, f'{success} Payouts successfully uploaded.')
                # if fail == 0:
                #     send_influencer_ledger_email.delay(list(store_names))

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

        return TemplateResponse(request, "admin/store/upload_store_payout.html", context)
    

@admin.register(StoreNotification)
class StoreNotificationAdmin(admin.ModelAdmin):
    list_display = ('text', 'route')
    list_filter = ()
    
@admin.register(StoreTile)
class StoreTileAdmin(admin.ModelAdmin):
    list_display = ('route', 'tile_type', 'start_datetime', 'end_datetime', 'image')
    list_filter = ()
