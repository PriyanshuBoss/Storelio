from django.contrib import admin

from saleor.support.models import Meetup, SupportQueries

# Register your models here.
@admin.register(SupportQueries)
class SupportQueryAdmin(admin.ModelAdmin):
    list_display = ('email', 'message', 'resolve_status', 'store')
    list_filter = ('email', 'store')
    search_fields = ('email', 'store__store_name', 'mobile_no')


@admin.register(Meetup)
class MeetupAdmin(admin.ModelAdmin):
    list_display = ("datetime", "details")
