from django.contrib import admin
from saleor.discount.emails import send_email_for_voucher_creation

from saleor.discount.models import Voucher
from django.db.models import Q
from saleor.account.models import User
from django.forms.models import model_to_dict
from saleor.discount.emails import get_voucher_creation_context
from saleor.external_services.messaging.messaging_impl import MessagingImpl
from saleor.discount import VoucherOwner, VoucherType
from django import forms

class MetadataForm(forms.ModelForm):
    
    voucher_title = forms.CharField(required=False)
    voucher_conditions = forms.CharField(required=False)

    def save(self, commit=True):
        return super(MetadataForm, self).save(commit=commit)

    class Meta:
        model = Voucher
        exclude = ()

@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    form = MetadataForm
    list_display = ('name','code', 'discount_value_type', 'discount_value', "store", 'user', 'brand_names')
    list_filter = ('name','store')
    fields = [
        'type', 
        'name', 
        'code', 
        'start_date', 
        'end_date', 
        'discount_value_type', 
        'discount_value',
        'is_shipping',
        'products',
        'collections',
        'categories',
        'brands',
        'min_spent_amount',
        'min_checkout_items_quantity',
        'apply_once_per_order',
        'apply_once_per_customer',
        'usage_limit',
        'max_discount_value',
        'voucher_title',
        'voucher_conditions',
        'metadata',
        'private_metadata',
        'owner',
        'store',
        'user'
        ]

    raw_id_fields = ('products','collections', 'categories', 'brands')
    readonly_fields = ('metadata',)

    def get_form(self, request, obj=None, **kwargs):
        form = super(VoucherAdmin, self).get_form(request, obj, **kwargs)
        form.base_fields['voucher_conditions'].widget.attrs['style'] = 'width: 80em;'
        if obj is not None:
            form.base_fields['voucher_title'].initial = obj.metadata.get('title')
            form.base_fields['voucher_conditions'].initial = obj.metadata.get('conditions')
        else:
            form.base_fields['voucher_title'].initial = ""
            form.base_fields['voucher_conditions'].initial = ""
        
        return form

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
        'user',
        'store'
        ).prefetch_related('brands')
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))

        return super(VoucherAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

    def brand_names(self, obj):

        brands_filter = obj.brands.all()
        brand_names = ""

        for brand_instance in brands_filter:
            brand_names += brand_instance.brand_name +", "

        return brand_names

    def save_model(self, request, obj, form, change):

        obj.name = obj.name.upper()
        obj.code = obj.code.upper()
        obj.metadata = {
            'title': form.cleaned_data.get('voucher_title'), 
            'conditions': form.cleaned_data.get('voucher_conditions'),
            'Zaamo_discount':obj.metadata.get('Zaamo_discount',""),
            'Brand_discount':obj.metadata.get('Brand_discount',""),
            'only_free_shipping':obj.metadata.get('only_free_shipping',False)
        }

        if change:

            if form.changed_data:
                
                old_obj = self.model.objects.filter(id=obj.id).first()
                
                super().save_model(request, obj, form, change)

                old_obj=model_to_dict(old_obj)
                old_obj["store"] = obj.store
                old_obj["created_at"] = obj.created_at
                form.cleaned_data["created_at"] = obj.created_at
                form.cleaned_data["metadata"] = obj.metadata
                voucher_text = get_voucher_creation_context(form.cleaned_data, old_obj=old_obj)
                
                if obj.user and obj.user.email:
                    cc=[obj.user.email]
                else:
                    cc=[]
                send_email_for_voucher_creation.delay(obj.code, voucher_text, cc=cc)
                    
        else:
            super().save_model(request, obj, form, change)
            voucher_instance=form.cleaned_data
            voucher_instance["store"] = obj.store
            voucher_instance["created_at"] = obj.created_at
            voucher_name = voucher_instance['name']
            voucher_instance["metadata"] = obj.metadata
            user_mobile_number_list = []
            for user in voucher_instance['store'].store_members.filter(store_id=voucher_instance['store'].id):
                try:
                    user_mobile_number = User.objects.get(pk=user.user_id).mobile_no
                except User.DoesNotExist:
                    user_mobile_number = None
                
                if user_mobile_number:
                    user_mobile_number_list.append(user_mobile_number)
            
            if obj.user and obj.user.email:
                cc=[obj.user.email]
            else:
                cc=[]
            
            if voucher_instance.get('owner') == VoucherOwner.BRAND:
                
                if voucher_instance.get('type')== VoucherType.SPECIFIC_PRODUCT:
                    
                    voucher_products = voucher_instance['products'] 
                    if voucher_products:
                        brand_manager_emails = list(voucher_products[0].brand.staff_brand_mappings.all().values_list('user__email', flat=True))
                        voucher_instance['brand_name'] = voucher_products[0].brand.brand_name
                        cc.extend(brand_manager_emails)

            voucher_text=get_voucher_creation_context(voucher_instance)
            
            send_email_for_voucher_creation.delay(obj.code, voucher_text, cc=cc)
            
            MessagingImpl.send_message_to_influencer_for_coupon_creation.delay(voucher_name, user_mobile_number_list)
