from re import T
import re
import csv
import datetime
from io import StringIO
from django.contrib import admin
import json
from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from saleor.product.models import LandingPageCategories, LandingPageSubCategories, Product, Collection, Category, ProductImage, ProductVariant, ProductGrouping, ProductTag, RejectedShopifyProduct, ZaamoShopifyProductMapping
from saleor.external_services.google_analytics.ga_helper import update_product_views
from django.conf.urls import include, url
from django.forms import formset_factory
from django.template.response import TemplateResponse
from saleor.external_services.integrations.csv import CsvIntegration
from saleor.product.forms import BulkUploadForm, ImageForm
from saleor.product.bulk_products_import import ETLDataLoader
from saleor.product.tasks import delete_product_image, save_image_with_celery
from saleor.product.templatetags.product_images import get_product_image_thumbnail
from django.utils.safestring import mark_safe
from django import forms
from django.contrib.admin import SimpleListFilter
from saleor.brand.models import Brand
from decimal import Decimal
import graphene
from saleor.graphql.utils import resolve_global_ids_to_primary_keys
from saleor.rest_apis.csv.csv_context import ExploreProductUploadCSV
from django.utils.html import format_html

class CategoryInputForm(forms.ModelForm):
    alias = forms.CharField(required=False,widget=forms.Textarea(attrs={'rows': 9, 'cols': 60}))

    class Meta:
        model = Category
        exclude = ()


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryInputForm
    list_display = ('name', )
    list_filter = ()
    readonly_fields = ('metadata',)

    def get_form(self, request, obj=None, **kwargs):
        request._obj_ = obj
        form = super(CategoryAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields['alias'].initial = obj.metadata.get('alias')
        
        else:
            form.base_fields['alias'].initial = ""

        return form

    def save_model(self, request, obj, form, change):
        existing_metadata = obj.metadata
        existing_metadata['alias'] = form.cleaned_data.get('alias') 
        obj.metadata = existing_metadata
        return super().save_model(request, obj, form, change)


class BooleanKeysInputForCollectionForm(forms.ModelForm):
    steal_deal = forms.BooleanField(required=False)
    landing = forms.BooleanField(required=False)
    share = forms.BooleanField(required=False)

    class Meta:
        model = Collection
        exclude = ()

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    form = BooleanKeysInputForCollectionForm
    list_display = ('name', 'created_at', 'store', 'user')
    ordering=('-updated_at',)
    list_filter = ('created_at',)
    readonly_fields = ('metadata',)


    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('collection_store', 
        'collection_store__store',
        'collection_store__user'
        )

    def store(self, obj):
        coll_store = obj.collection_store.all()

        if coll_store: 
            return coll_store[0].store

    def user(self, obj):
        coll_store = obj.collection_store.all()
        
        if coll_store: 
            return coll_store[0].user.mobile_no

    def get_form(self, request, obj=None, **kwargs):
        request._obj_ = obj
        form = super(CollectionAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields['steal_deal'].initial = obj.metadata.get('steal_deal')
            form.base_fields['landing'].initial = obj.metadata.get('landing')
            form.base_fields['share'].initial = obj.metadata.get('share')
        else:
            form.base_fields['steal_deal'].initial = False
            form.base_fields['landing'].initial = False
            form.base_fields['share'].initial = False

        return form

    def save_model(self, request, obj, form, change):
        existing_metadata = obj.metadata
        existing_metadata['steal_deal'] = form.cleaned_data.get('steal_deal') 
        existing_metadata['landing'] = form.cleaned_data.get('landing') 
        existing_metadata['share'] = form.cleaned_data.get('share')
        obj.metadata = existing_metadata
        return super().save_model(request, obj, form, change)



class ProductImagesInlineAdmin(admin.TabularInline):
    template = "admin/edit_inline/tabular.html"
    model = ProductImage
    fields = ('image','image_tag','delete')
    readonly_fields = ('delete','image_tag')
    can_delete = False
    form = ImageForm
    extra = 0

    def has_change_permission(self,request,obj):
        return False
    
    def image_tag(self, obj):
        html =''
        thumbnail_url = get_product_image_thumbnail(obj, 255, method="thumbnail")
        html = html+ '<img src="{url}" style="width: 120px; height:150px;" />'.format(
                        url=thumbnail_url)

        return mark_safe(html)

    image_tag.short_description = 'Preview'

    def delete(self, obj):
        return format_html('<button type="button" class="button" onclick="delete_object({})">Delete</button>', obj.id)

    delete.short_description = 'Delete'

    class Media:
        js = ('product/custom.js',)

class ProductVariantInlineAdmin(admin.TabularInline):
    template = "admin/edit_inline/tabular.html"
    model = ProductVariant
    fields = ('name', 'price_amount', 'cost_price_amount', 'inventory', 'track_inventory',)
    readonly_fields = ('inventory',)
    extra = 0
    can_delete = False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('stocks')

    def inventory(self, obj):
        return obj.get_inventory()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'available_for_purchase', 'category', 'product_thumbnail')
    list_filter = ('is_published', 'visible_in_listings', "brand__brand_name", 'category')
    readonly_fields = ("updated_at", "product_thumbnail", 'private_metadata', 'product_type', "default_variant", "is_published")
    change_list_template = "product/change_list.html"
    fields = ('product_thumbnail', 'name', 'brand', 'product_type', 'category', 'default_variant', 'minimal_variant_price_amount', 'is_published', 'publication_date', 
    'visible_in_listings', 'available_for_purchase', 'description_json', 'private_metadata','commission_percentage','has_custom_commission','brand_barter'
    )
    search_fields = ('name', 'description_json')
    inlines = [ ProductVariantInlineAdmin, ProductImagesInlineAdmin]
    actions = ['activate_visible_in_listings', 'deactivate_visible_in_listings', 'publish', 'deactivate_published']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('category', 'product_type', 'images')

    def activate_visible_in_listings(self, request, queryset):
        queryset.update(visible_in_listings=True)

    activate_visible_in_listings.short_description = u"Activate visible in listings"

    def deactivate_visible_in_listings(self, request, queryset):
        queryset.update(visible_in_listings=False)
        
    deactivate_visible_in_listings.short_description = u"Deactivate visible in listings"

    def publish(self, request, queryset):
        queryset.update(is_published=True, publication_date=datetime.date.today(), 
        available_for_purchase=datetime.date.today())
        
    publish.short_description = u"Publish products"

    def deactivate_published(self, request, queryset):
        queryset.update(is_published=False)
        
    deactivate_published.short_description = u"Remove products from published products"


    def product_thumbnail(self, obj):

        first_image = obj.images.first()
        
        if first_image:

            html=""
            
            thumbnail_url = get_product_image_thumbnail(first_image, 1080, method="thumbnail")

            html = html+ '<img src="{url}" style="width: 120px; height:150px;" />'.format(
                        url=thumbnail_url)

            return mark_safe(html)

        return "NA"
    

    def get_urls(self):
        urls = super(ProductAdmin, self).get_urls()
        custom_page_urls = [
                url(r"^bulk_upload_product/", login_required(self.bulk_upload_product), name="bulk_upload_product"),
                url(r"^explore_upload/", login_required(self.upload_explore_products), name="explore_upload"),
                url(r"^custom_image_delete/", login_required(self.custom_delete), name="custom_image_delete")
                ]
        
        return custom_page_urls + urls

    def custom_delete(self,request):
        if request.method == 'POST':
            body = json.loads(request.body.decode("utf-8"))
            id = body.get("image_id")
            delete_product_image.delay(id)
            return JsonResponse({"status": "ok"})

        return JsonResponse({"message": "Wrong Request"})
    
    def bulk_upload_product(self, request):
        opts = self.model._meta
        app_label = opts.app_label
        formset = formset_factory(BulkUploadForm)

        if request.method == 'POST':

            formset = formset_factory(BulkUploadForm)(request.POST, request.FILES)

            if formset.is_valid():

                if 'csv_file' in formset.forms[0].cleaned_data:
                    csvfile = formset.forms[0].cleaned_data['csv_file']
                    csv_integration = CsvIntegration()

                    reader = csv.DictReader(StringIO(csvfile.read().decode('utf-8')))
                    
                    reader_list = [{key.strip().lower().replace('*', '').replace('_', ' '): value.strip() for key, value in _dict.items()} for _dict in reader]

                    csv_integration.upload_products(reader_list, product_attribute_list=settings.PRODUCTS_CSV_UPLOAD['CSV_PRODUCT_ATTRIBUTE_LIST'],
                    variant_attributes_list=settings.PRODUCTS_CSV_UPLOAD['CSV_VARIANT_ATTRIBUTE_LIST'])
                    messages.success(request, 'CSV Uploaded Successfully!!,  New products and updated products will reflect in a few minutes')


        
        _dict = {
            'add': True,
            'change': False,
            'has_editable_inline_admin_formsets': False,
            'has_add_permission': True,
            "has_change_permission": True, 
            "has_view_permission": True,
            'has_file_field': True,
            "has_delete_permission": False, 
            'opts': opts,
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
            'app_label': app_label,
            'show_save_and_add_another': False,
            'show_save_and_continue': False,
            'available_csv_columns': settings.PRODUCTS_CSV_UPLOAD['CSV_COLUMNS'],
            'mandatory_csv_column': settings.PRODUCTS_CSV_UPLOAD['MANDATORY_CSV_COLUMNS'],
            'media': '',
            'title': 'Bulk Upload Products'
        }
        context = dict(
           # Include common variables for rendering the admin template.
           self.admin_site.each_context(request),
           # Anything else you want in the context...
           form=formset,
           opts= opts,
           app_label=app_label
        )
        context.update(_dict)


        return TemplateResponse(request, "product/bulk_upload_product.html", context)

    def upload_explore_products(self, request):
        mandatory_columns = ('product_id', 'state', 'media_url')
        if request.method == 'POST':
            csv_file = request.FILES.get('file')
            explore = ExploreProductUploadCSV(csv_file)
            columns = explore.get_headers()
            rows = explore.get_rows()
            if not set(mandatory_columns).issubset(columns):
                self.message_user(request, 'One or more mandatory column missing.', level=messages.ERROR)
                return HttpResponseRedirect('./')
            
            products = ExploreProductUploadCSV.upload_csv.delay(rows)
            self.message_user(request, 'csv successfully uploaded.')

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
            'title': 'Upload Explore Products'
        }
        context = dict(
           # Include common variables for rendering the admin template.
           self.admin_site.each_context(request),
           # Anything else you want in the context...
           opts=self.model._meta,
           app_label=self.model._meta.app_label
        )
        context.update(_dict)

        return TemplateResponse(request, "product/explore_upload.html", context)



class LandingPageSubcategoriesInlineAdmin(admin.TabularInline):
    template = "admin/edit_inline/tabular.html"
    model = LandingPageSubCategories
    fields = ('sub_category','sub_category_rank')
    extra = 0

@admin.register(LandingPageCategories)
class LandingPageCategoriesAdmin(admin.ModelAdmin):
    list_display = ('category', 'category_rank', 'is_visible')
    list_filter = ('category',)

    inlines = [LandingPageSubcategoriesInlineAdmin]

class StealDealFilter(SimpleListFilter):
    title = 'stealDeal' 
    parameter_name = 'stealDeal'

    def lookups(self, request, model_admin):
        return (
            (True, (True)),
            (False, (False)),   
        )

    def queryset(self, request, queryset):
        if self.value() is not None:
            if self.value() == "True":
                return queryset.filter(rule__stealDeal=True)
            elif self.value() == "False":
                return queryset.filter(rule__stealDeal=False)
        else:
            return queryset

class ProductGroupingSortingOptions:
    TAG_STRENGTH='TAG_STRENGTH'
    SELLING_FAST='SELLING_FAST'
    STEAL_DEALS_ONLY='VALUE_UPDATED_AT'
    PRICE='PRICE'
    NEWNESS='PUBLICATION_DATE' 
    HOT_SELLING='HOT_SELLING'
    TRENDING_NOW='TRENDING_NOW'
    BRAND_DISCOUNT='BRAND_DISCOUNT'
    COMMISSION='COMMISSION'
    choices=[
        (TAG_STRENGTH,'TAG_STRENGTH'),
        (SELLING_FAST,'SELLING_FAST'),
        (STEAL_DEALS_ONLY,'STEAL_DEALS_ONLY'),
        (PRICE,'PRICE'),
        (NEWNESS,'NEWNESS'), 
        (HOT_SELLING,'HOT_SELLING'),
        (TRENDING_NOW,'TRENDING_NOW'),
        (BRAND_DISCOUNT,'BRAND_DISCOUNT'),
        (COMMISSION,'COMMISSION'),
    ]

class ProductGroupingSortingDirections:
    DESC='DESC'
    ASC='ASC'
    choices=[
        (DESC, 'DESC'), 
        (ASC, 'ASC'),
    ]


class BooleanKeysInputForm(forms.ModelForm):
    share = forms.BooleanField(required=False)
    steal_deal = forms.BooleanField(required=False)
    value_deal = forms.BooleanField(required=False)
    sorting = forms.ChoiceField(choices=ProductGroupingSortingOptions.choices)
    direction = forms.ChoiceField(choices=ProductGroupingSortingDirections.choices)
    brands = forms.ModelMultipleChoiceField(queryset = Brand.objects.all(), required = False)
    categories = forms.ModelMultipleChoiceField(queryset = Category.objects.all(), required = False)
    product_tags = forms.ModelMultipleChoiceField(queryset = ProductTag.objects.all(), required = False)
    price_gtequal = forms.DecimalField(decimal_places=3, required=False)
    price_ltequal = forms.DecimalField(decimal_places=3, required=False)
    discount_gtequal = forms.DecimalField(decimal_places=3, required=False)
    discount_ltequal = forms.DecimalField(decimal_places=3, required=False)
    public_link = forms.SlugField()

    class Meta:
        model = ProductGrouping
        exclude = ()
        
@admin.register(ProductGrouping)
class ProductGroupingAdmin(admin.ModelAdmin):
    form = BooleanKeysInputForm
    list_display = ('name', 'steal_deal','public_link','image_data')
    list_filter = (StealDealFilter,)
    search_fields = ('name', )
    readonly_fields = ('rule','slug','public_link')
    exclude = ('metadata', 'private_metadata',)
    fields = (
        'name',
        'type',
        'public_link',
        'steal_deal',
        'value_deal',
        'share',
        'sorting',
        'direction',
        'brands',
        'categories',
        'product_tags',
        'price_gtequal',
        'price_ltequal',
        'discount_gtequal',
        'discount_ltequal',
        'rule',
        'slug',
        'image',
    )   

    def public_link(self, obj):
        url = "https://zaamo.co/zaamo/group/"+ obj.slug
        
        return format_html("""<a href='%s'>%s</a>""" %(url,url))
    

    def convert_to_global_ids(self, type, ids):
        global_ids = []
        for id in ids:
            global_id = graphene.Node.to_global_id(type, id)
            global_ids.append(global_id)

        return global_ids


    def image_data(self,obj):
        
        if obj.image:
            return format_html('<img src="{0}" style="width: 85px; height:85px;" />'.format(obj.image.url))
        
    def extract_from_global_ids(self, type, global_ids):
        _, primary_keys = resolve_global_ids_to_primary_keys(global_ids, type)
        return primary_keys

    def get_form(self, request, obj=None, **kwargs):
        request._obj_ = obj
        form = super(ProductGroupingAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields['share'].initial = obj.rule.get('share')
            form.base_fields['steal_deal'].initial = obj.rule.get('stealDeal')
            form.base_fields['value_deal'].initial = obj.rule.get('valueDeal')
            form.base_fields['sorting'].initial = obj.rule.get('field')
            form.base_fields['direction'].initial = obj.rule.get('direction')
            form.base_fields['brands'].initial = Brand.objects.filter(id__in=self.extract_from_global_ids("Brand", obj.rule.get('brands')))
            form.base_fields['categories'].initial = Category.objects.filter(id__in=self.extract_from_global_ids("Category", obj.rule.get('categories')))
            form.base_fields['product_tags'].initial = ProductTag.objects.filter(id__in=self.extract_from_global_ids("ProductTag", obj.rule.get('productTags')))
            form.base_fields['price_gtequal'].initial = obj.rule.get('price').get('gtequal')
            form.base_fields['price_ltequal'].initial = obj.rule.get('price').get('ltequal')
            form.base_fields['discount_gtequal'].initial = obj.rule.get('discount').get('gtequal')
            form.base_fields['discount_ltequal'].initial = obj.rule.get('discount').get('ltequal')
        else:
            form.base_fields['share'].initial = False
            form.base_fields['steal_deal'].initial = False
            form.base_fields['value_deal'].initial = False
            form.base_fields['sorting'].initial = ProductGroupingSortingOptions.TAG_STRENGTH
            form.base_fields['direction'].initial = ProductGroupingSortingDirections.DESC
            form.base_fields['brands'].initial = Brand.objects.none()
            form.base_fields['categories'].initial = Category.objects.none()
            form.base_fields['product_tags'].initial = ProductTag.objects.none()
            form.base_fields['price_gtequal'].initial = Decimal(0.0)
            form.base_fields['price_ltequal'].initial = Decimal(0.0)
            form.base_fields['discount_gtequal'].initial = Decimal(0.0)
            form.base_fields['discount_ltequal'].initial = Decimal(0.0)
        return form

    def save_model(self, request, obj, form, change):
        existing_rule = obj.rule
        existing_rule['stealDeal'] = form.cleaned_data.get('steal_deal')
        existing_rule['valueDeal'] = form.cleaned_data.get('value_deal')
        existing_rule['share'] = form.cleaned_data.get('share')
        existing_rule['field'] = form.cleaned_data.get('sorting')
        existing_rule['direction'] = form.cleaned_data.get('direction')
        existing_rule['brands'] = self.convert_to_global_ids("Brand",list(form.cleaned_data.get('brands').values_list('id', flat=True)))
        existing_rule['categories'] = self.convert_to_global_ids("Category",list(form.cleaned_data.get('categories').values_list('id', flat=True)))
        existing_rule['productTags'] = self.convert_to_global_ids("ProductTag",list(form.cleaned_data.get('product_tags').values_list('id', flat=True)))
        price_dict = {}
        price_dict['gtequal'] = float(form.cleaned_data.get('price_gtequal'))
        price_dict['ltequal'] = float(form.cleaned_data.get('price_ltequal'))
        discount_dict = {}
        discount_dict['gtequal'] = float(form.cleaned_data.get('discount_gtequal'))
        discount_dict['ltequal'] = float(form.cleaned_data.get('discount_ltequal'))
        existing_rule['price'] = price_dict
        existing_rule['discount'] = discount_dict
        obj.rule = existing_rule
        return super().save_model(request, obj, form, change)

@admin.register(RejectedShopifyProduct)
class RejectedShopifyProductAdmin(admin.ModelAdmin):
    autocomplete_fields = ('product',)
    list_display = ('product_id', 'product_name', 'brand_name', 'updated_at')
    list_filter = ('product__brand__brand_name',)
    search_fields = ('product__id', 'product__name', 'product__description_json')
    
    change_list_template = "rejectedshopifyproduct/change_list.html"

    def get_urls(self):
        urls = super(RejectedShopifyProductAdmin, self).get_urls()
        custom_page_urls = [
                url(r"^bulk_upload/", login_required(self.bulk_upload), name="bulk_upload"),
                url(r"^pdp_views_upload/", login_required(self.pdp_views_upload), name="pdp_views_upload"),
            ]
        
        return custom_page_urls + urls
    

    def bulk_upload(self, request):
        mandatory_columns = ('product_link',)
        if request.method == 'POST':
            csv_file = request.FILES.get('file')
            reader = csv.DictReader(StringIO(csv_file.read().decode('utf-8')))
            rows = [{key.strip().lower().replace(' ', '_'): value.strip() for key, value in _dict.items() if value} for _dict in reader]
            
            product_ids = list()
            slugs = {row.get('product_link').split('products/')[-1].split('/')[0] for row in rows if row.get('product_link')}
            if slugs:
                product_ids = list(Product.objects.filter(slug__in=slugs).values_list('id', flat=True))
            else:
                product_ids = {graphene.Node.from_global_id(row.get('product_id'))[1] for row in rows if row.get('product_id')}
                
            if not product_ids:
                self.message_user(request, '0 product found, One or more mandatory column missing.', level=messages.ERROR)
                return HttpResponseRedirect('./')
            
            csv_integration = CsvIntegration()
            count = csv_integration.upload_shopify_rejected(product_ids)
            self.message_user(request, f'csv uploaded successfully. {count} product(s) added.')

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
            'title': 'Upload Shopify Rejected'
        }
        context = dict(
           # Include common variables for rendering the admin template.
           self.admin_site.each_context(request),
           # Anything else you want in the context...
           opts=self.model._meta,
           app_label=self.model._meta.app_label
        )
        context.update(_dict)

        return TemplateResponse(request, "rejectedshopifyproduct/bulk_upload.html", context)
    
    def pdp_views_upload(self, request):
        mandatory_columns = ('product_id', 'pdp_views')
        if request.method == 'POST':
            csv_file = request.FILES.get('file')
            reader = csv.DictReader(StringIO(csv_file.read().decode('utf-8')))
            rows = [{key.strip().lower().replace(' ', '_'): value.strip() for key, value in _dict.items() if value} for _dict in reader]
            
            pids = [row['product_id'] for row in rows]
            brand_pids = ZaamoShopifyProductMapping.objects.filter(product_id_brand__in=pids).values_list('product_id_brand', 'product_zaamo_id')
            brand_pids = {bpid: pid for bpid, pid in brand_pids}

            store_id = 3552 # zaamo
            pdp_views = []
            for row in rows:
                pdp_view = int(row['pdp_views'])
                bpid = row['product_id']
                if not bpid in brand_pids:
                    continue
                if not pdp_view:
                    continue
                data = {
                    'views': pdp_view,
                    'store_id': store_id,
                    'product_id': int(brand_pids.get(bpid))
                }
                pdp_views.append(data)
            update_product_views(pdp_views)

            if not pids:
                self.message_user(request, '0 product found, One or more mandatory column missing.', level=messages.ERROR)
                return HttpResponseRedirect('./')
            
            count = len(pdp_views)
            self.message_user(request, f'CSV uploaded successfully. {count} pdp views added.')

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
            'title': 'Upload Shopify Rejected'
        }
        context = dict(
           # Include common variables for rendering the admin template.
           self.admin_site.each_context(request),
           # Anything else you want in the context...
           opts=self.model._meta,
           app_label=self.model._meta.app_label
        )
        context.update(_dict)

        return TemplateResponse(request, "rejectedshopifyproduct/pdp_views_upload.html", context)