from django.contrib import admin

from saleor.notifications.models import Notification, AppNotificationTemplates, MediaFiles, Device, EventRule, NotifyAppUpdate

# Register your models here.

class MediaFilesInlineAdmin(admin.TabularInline):
    template = "admin/edit_inline/tabular.html"
    model = MediaFiles
    fields = ("media_file", "click_action", "is_clickable", "media_tag")
    readonly_fields = ["media_tag"]
    extra = 1
    verbose_name = "Carousel Image"
    verbose_name_plural = "Carousel Images"

@admin.register(AppNotificationTemplates)
class AppNotificationTemplatesAdmin(admin.ModelAdmin):
    exclude = ()
    readonly_fields = ["selected_context_variables"]
    inlines = [MediaFilesInlineAdmin]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    fields = ('title', 'onclick_action', 'recipient', 'unread', 
            'description', 'expiry_timestamp', 'data')

    raw_id_fields = ("recipient", )

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    fields = (
        'user', 'is_active', 'app_version', 'model', 'manufacturer', 
        'os_version', 'device_type', 'fcm_id','device_id', 'app_installed_at', 
        'app_uninstalled_at', 'app_last_launched_at')

    raw_id_fields = ("user", )


@admin.register(EventRule)
class EventRuleAdmin(admin.ModelAdmin):
    fields = (
        'code', 'name', 'app_notification_template')

    readonly_fields = ('code',)

@admin.register(NotifyAppUpdate)
class NotifyAppUpdateAdmin(admin.ModelAdmin):
    fields = (
        'version', 'device_type', 'app_type')

