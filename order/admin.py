from django.contrib import admin
from saleor.order.models import Order, OrderLine


class OrderLineInlineAdmin(admin.TabularInline):
    template = "admin/edit_inline/tabular.html"
    model = OrderLine
    fields = ('product_name', 'variant_name', 'quantity', 'unit_price_gross_amount',)
    readonly_fields = ('product_name', 'variant_name', 'quantity', 'unit_price_gross_amount',)
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('created', 'total_gross_amount', 'shipping_price_net_amount', 'status')
    list_filter = ('created', 'status')
    inlines = [OrderLineInlineAdmin]
