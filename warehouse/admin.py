from django.contrib import admin
from saleor.warehouse.models import Stock


class BrandListFilter(admin.SimpleListFilter):

    title = ('brand')

    parameter_name = 'brand'

    def lookups(self, request, model_admin):
        from saleor.brand.models import Brand
        
        return Brand.objects.all().values_list('id', 'brand_name')


    def queryset(self, request, queryset):
        
        if self.value():
            return queryset.select_related('product_variant', 'product_variant__product', 'product_variant__product__brand').filter(product_variant__product__brand=self.value())

        return queryset


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('brand', 'product', 'product_variant', 'quantity')
    fields = ['product_variant', 'quantity', 'warehouse']
    readonly_fields = ['warehouse', 'product_variant']
    list_filter = (BrandListFilter,)
    search_fields = ('product',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product_variant', 'product_variant__product', 'product_variant__product__brand')

    def get_search_results(self, request, queryset, search_term):

        if not search_term:
            return queryset, False

        if search_term:
            queryset = super().get_queryset(request).select_related('product_variant', 'product_variant__product', 'product_variant__product__brand').filter(product_variant__product__name__search=search_term)
        
        return queryset, False

    def product(self, obj):
        return obj.product_variant.product

    def brand(self, obj):
        return obj.product_variant.product.brand
