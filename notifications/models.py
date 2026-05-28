from functools import partial
import json
import re
from django.utils.safestring import mark_safe
from django.db import models
from django.dispatch import receiver
from django.utils.translation import ugettext_lazy as _
from saleor.core.models import ModelWithCreateUpdateTimestamp
from django.conf import settings
from django.db.models import JSONField 
from django.db.models.signals import post_save
from django.core.exceptions import ValidationError
from markdown.extensions.toc import slugify
from jinja2 import Template as JinjaTemplate, Environment, meta

from saleor.notifications.states import ApplicationType, DeviceType, MediaType, NotificationPath, TemplateType
from saleor.notifications.utils import media_file_extension_validator, media_file_path
from saleor.utilities.time_utilities import TimeUtilities

# Create your models here.


class Device(ModelWithCreateUpdateTimestamp):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='devices', on_delete=models.CASCADE)
    app_version = models.CharField(max_length=80, null=True, blank=True,
     help_text=_("Installed App Vesion On Mobile"))

    # Device identification fields
    model = models.CharField(max_length=80, blank=True, null=True, help_text=_("Device Model Number"))
    manufacturer = models.CharField(max_length=255, null=True, blank=True, help_text=_("Device Manufacturer"))
    os_version = models.CharField(max_length=30, blank=True, null=True, help_text=_("Device OS Version"))
    device_type = models.CharField(
        choices=DeviceType.CHOICES, help_text=_("Different Type Of device type like Ios, Android, Web etc."), max_length=30
    )
    device_id = models.CharField(max_length=500,blank=True, null=True)
    fcm_id = models.TextField(default='', help_text=_("fcm Id."))
    is_active = models.BooleanField(default=True, help_text=_("Inactive devices will not be sent notifications"))

    # App related bookkeeping variables
    app_installed_at = models.DateTimeField(null=True, blank=True, help_text=_("App Installation Time"))
    app_uninstalled_at = models.DateTimeField(null=True, blank=True, help_text=_("App Uninstall Time"))
    app_last_launched_at = models.DateTimeField(null=True, blank=True, help_text=_("App Launch Time"))

    
    def __str__(self):
        return "%s" % self.id


class Notification(ModelWithCreateUpdateTimestamp):

  
    # on tap land on a screen or website
    title = models.TextField(help_text='Title of Message')
    onclick_action = models.TextField(null=True, blank=True, help_text='on tap land on a screen or website')

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, blank=False, related_name='notifications', on_delete=models.CASCADE)
    unread = models.BooleanField(default=True, blank=False)

    description = models.TextField(blank=True, null=True, help_text='Display Message')

    path =  models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Path for specific screen",
    )
    # It will represent the expiry datetime of the notification
    expiry_timestamp = models.DateTimeField(null=True, blank=True, help_text='expiry datetime of the notification')

    data = JSONField(blank=True, null=True)

    class Meta:
        ordering = ('-created_at', '-expiry_timestamp')
        app_label = 'notifications'

    def __str__(self):
        return "%s" % self.title

    def mark_as_read(self):
        if self.unread:
            self.unread = False
            self.save()

    def mark_as_unread(self):
        if not self.unread:
            self.unread = True
            self.save()


class AppNotificationTemplates(ModelWithCreateUpdateTimestamp):
    """
    App Notification Templates

    """

    name = models.CharField("Template Name", max_length=200)
    code = models.SlugField(max_length=200)

    message_type = models.IntegerField(
        choices=MediaType.Choices, null=False, blank=False, default=MediaType.NO_MEDIA
    )

    thumbnail = models.FileField(
        "thumbnail",
        upload_to=partial(
            media_file_path, media_folder_name="app_notifications_files/thumbnail/"
        ),
        max_length=1280,
        blank=True,
        null=True,
        validators=[
            partial(
                media_file_extension_validator,
                valid_extensions_file=("jpg", "jpeg", "png"),
            )
        ],
        help_text="Valid formats - IMAGE : ( png / jpg / jpeg)",
    )

    media_file = models.FileField(
        "Media File",
        upload_to=partial(media_file_path, media_folder_name="app_notifications_files"),
        max_length=1280,
        blank=True,
        null=True,
        validators=[
            partial(
                media_file_extension_validator,
                valid_extensions_file=(
                    "jpg",
                    "jpeg",
                    "png",
                    "mp4",
                    "avi",
                    "mov",
                    "gif",
                ),
            )
        ],
        help_text="Valid formats - IMAGE : ( png / jpg / jpeg), VIDEO : ( mp4 / avi / mov), GIF : (gif)",
    )

    description = models.CharField(
        "Template Description",
        max_length=300,
    )

    is_persistent = models.BooleanField(
        "Is Persistent",
        default=False,
        help_text="If True, Notification would stay persistent in Mobile App till Expiry Timestamp.",
    )

    expiry_timestamp = models.DateTimeField(
        "Persistent Notification Expiry Date",
        null=True,
        blank=True,
        help_text="Date after persistent notification will be removed from User App",
    )

    expiry_days = models.IntegerField(
        "Persistent Notification Expiry Days",
        null=True,
        blank=True,
        help_text="No. of Days after persistent notification will be removed from User App",
    )

    onclick_action = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="on tap land on a screen or website",
    )

    path =  models.CharField(
        max_length=255,
        choices=NotificationPath.Choices,
        null=True,
        blank=True,
        help_text="Path for specific screen",
    )

    title = models.CharField(
        "Title",
        help_text="Title of your Notification template",
        max_length=255,
    )

    body = models.TextField(
        "Body",
        help_text="Define the text content of your template",
        null=True,
        blank=True,
    )

    selected_context_variables = JSONField(default=dict)

    template_type = models.CharField(
        choices=TemplateType.Choice,
        null=False,
        blank=False,
        default=TemplateType.EVENT_BASED,
        max_length=30
    )

    def __str__(self):
        return "%s" % self.name

    class Meta:
        ordering = ("-id",)
        verbose_name = "App Notification Template"
        verbose_name_plural = "App Notification Templates"

    def clean(self):

        if self.expiry_days or self.expiry_timestamp:

            if self.expiry_days and self.expiry_timestamp:
                raise ValidationError(
                    'You can choose only one option from "Persistent Notification Expiry Date" and "Persistent Notification Expiry Days"'
                )

            

            if self.expiry_timestamp and (
                self.expiry_timestamp.date() < TimeUtilities.get_current_date(parse=False)
            ):
                raise ValidationError(
                    '"Persistent Notification Expiry Date" can not be smaller then today date. '
                )

            self.is_persistent = True

        if self.message_type == MediaType.NO_MEDIA and not self.body:
            raise ValidationError('In case of NO Media "body" can not be empty')

        if self.message_type in [MediaType.VIDEO, MediaType.GIF] and not (
            self.media_file and self.thumbnail
        ):
            raise ValidationError("Select both 'Media file and Thumbnail'")

        if self.message_type == MediaType.IMAGE and not self.media_file:
            raise ValidationError("Select Media file")
        if self.message_type == MediaType.IMAGE:
            media_file_extension_validator(self.media_file, ("jpg", "jpeg", "png"))
        elif self.message_type == MediaType.GIF:
            media_file_extension_validator(self.media_file, ("gif",))
        elif self.message_type == MediaType.VIDEO:
            media_file_extension_validator(self.media_file, ("mp4", "avi", "mov"))
        
        try:
            env = Environment()
            parsed_content = env.parse(self.body)
            context_variables = list(meta.find_undeclared_variables(parsed_content))
        except:
            context_variables = []
        
        self.selected_context_variables = context_variables



    def media_url(self):
        if self.media_file:
            media_url = self.media_file.url
        else:
            media_url = ''

        return media_url

    def thumbnail_url(self):
        if self.thumbnail:
            thumbnail_url = self.thumbnail.url
        else:
            thumbnail_url = ''

        return thumbnail_url

    def thumbnail_tag(self):
        if self.thumbnail.url:
            return mark_safe(
                '<embed src="{url}" style="width: 400px; height:400px;" />'.format(
                    url=self.thumbnail.url,
                )
            )
        else:
            return "No Media Found"

    def media_tag(self):
        if self.media_file.url:
            return mark_safe(
                '<embed src="{url}" style="width: 400px; height:400px;" />'.format(
                    url=self.media_file.url,
                )
            )
        else:
            return "No Media Found"

    def get_app_notification_data(self, context_variables = {}):


        if self.is_persistent:

            if self.expiry_days:
                expiry_time_obj = TimeUtilities.add_time_in_timestamp(TimeUtilities.get_current_date_time(), days=self.expiry_days)
                expiry_time = expiry_time_obj
            elif self.expiry_timestamp:
                expiry_time = self.expiry_timestamp
            else:
                expiry_time = None
        else:
            expiry_time = None
    
        title = JinjaTemplate(self.title).render(context_variables)

        body = JinjaTemplate(self.body).render(context_variables)

        onclick_action = JinjaTemplate(self.onclick_action).render(context_variables)

        data = {
            "name": self.name,
            "title": title, 
            "onclick_action": onclick_action,
            "expiry_timestamp": expiry_time,
            "is_persistent": self.is_persistent,
            "path": {"screen_name": self.path,
                     "path_data": json.dumps(context_variables.get('path_data', {}))
                    },
            "media": {
                "is_video": False,
                "video_link": "",
                "image": "",
                "carousel": [],
                "gif": "",
            },
            
            "body": body,
        }

        if self.message_type == MediaType.NO_MEDIA:
            return data

        if self.message_type == MediaType.IMAGE:
            if context_variables.get("media","")=="":
                data["media"]["image"] = self.media_url()
            else:
                data["media"]["image"] = context_variables.get("media","")

        if self.message_type == MediaType.VIDEO:
            data["media"]["image"] = self.thumbnail_url()
            data["media"]["is_video"] = True
            data["media"]["video_link"] = self.media_url()

        if self.message_type == MediaType.GIF:
            data["media"]["image"] = self.thumbnail_url()
            data["media"]["gif"] = self.media_url()

        if self.message_type == MediaType.CAROUSEL:
            images = self.media_files.all().order_by("id")
            carousel_list = []
            for image in images:
                image_dict = {
                    "image": image.media_url(),
                    "click_action": image.click_action,
                    "is_clickable": image.is_clickable,
                }
                carousel_list.append(image_dict)
            data["media"]["image"] = images.first().media_url()
            data["media"]["carousel"] = carousel_list


        return data

# method for updating
@receiver(post_save, sender=AppNotificationTemplates)
def update_app_code(sender, instance, **kwargs):

    if settings.DEBUG:
        prefix = "AT" + "D"
    else:
        prefix = "AT" + "P"

    self_object = instance

    if (
        not self_object.code
        or self_object.code
        and not re.match(r"[A-Z]+[D,P][0-9]+", self_object.code)
    ):

        self_object_code = prefix + str(self_object.pk)

        sender.objects.filter(id=instance.id).update(code=self_object_code)


class MediaFiles(ModelWithCreateUpdateTimestamp):
    app_notification_template = models.ForeignKey(
        AppNotificationTemplates,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="media_files",
    )

    media_type = models.IntegerField(
        "Media Type",
        choices=MediaType.Choices,
        blank=False,
        null=False,
        default=MediaType.IMAGE,
    )

    media_file = models.FileField(
        "Media File",
        upload_to=partial(
            media_file_path,
            file_type_identifier="media_type",
            media_folder_name="app_notifications_files",
        ),
        max_length=1280,
        blank=False,
        null=False,
        validators=[
            partial(
                media_file_extension_validator,
                valid_extensions_file=("jpg", "jpeg", "png"),
            )
        ],
        help_text="Valid formats - IMAGE : ( png / jpg / jpeg)",
    )

    click_action = models.URLField(max_length=200, null=True, blank=True)

    is_clickable = models.BooleanField(default=False)

    def media_tag(self):
        if self.media_file.url:
            return mark_safe(
                '<embed src="{url}" style="width: 250px; height:250px;" />'.format(
                    url=self.media_file.url,
                )
            )
        else:
            return "No Media Found"

    def media_url(self):
        if self.media_file:
            media_url = self.media_file.url
        else:
            media_url = None

        return media_url


class EventRule(ModelWithCreateUpdateTimestamp):
    code = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200, unique=True)
    app_notification_template = models.ForeignKey(
        AppNotificationTemplates, 
        on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return "%s" % self.code

    def save(self, *args, **kwargs):
        self.code = "EV_" + slugify(self.name, "_")

        super(EventRule, self).save(*args, **kwargs)

class NotifyAppUpdate(ModelWithCreateUpdateTimestamp):
    version = models.CharField(max_length=16)
    device_type = models.CharField(
        choices=DeviceType.CHOICES, help_text=_("Different Type Of device type like Ios, Android, Web etc."), max_length=30
    )
    app_type =  models.CharField(
        choices=ApplicationType.CHOICES, help_text=_("Different Type Of device type ZS BH"), max_length=30
    )
    force_update = models.BooleanField(default=False)
