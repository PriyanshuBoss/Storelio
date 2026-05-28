from saleor.core.models import  ModelWithCreateTimestamp, ModelWithCreateUpdateTimestamp
from django.db import models
from django.utils.translation import gettext_lazy as _
from saleor.account.models import PossiblePhoneNumberField
from saleor.core.utils.json_serializer import CustomJsonEncoder

class SupportQueries(ModelWithCreateUpdateTimestamp):

    email = models.EmailField()
    mobile_no = PossiblePhoneNumberField(max_length=15, blank=True)
    message = models.TextField()
    resolve_status = models.BooleanField(default=False)
    store = models.ForeignKey('store.storeinfo', on_delete=models.CASCADE, related_name='support_queries')

    class Meta:
        ordering = ("updated_at",)


class Meetup(ModelWithCreateTimestamp):

    details = models.JSONField(blank=True, null=True, default=dict, encoder=CustomJsonEncoder)
    datetime = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class TicketTypeEnum:
    INITIATE_PURCHASE = 'initiate_purchase'
    TOP_ORDER = 'top_order'
    DELAYED_ORDER = 'delayed_order'
    CANCELLED_ORDER = 'cancelled_order'
    ORDER = 'order'
    COD_ORDER = 'cod_order'

    CHOICES = [
        (INITIATE_PURCHASE, "initiate_purchase"),
        (ORDER, "order"),
        (COD_ORDER, "cod_order"),
        (DELAYED_ORDER, "delayed_order"),
        (CANCELLED_ORDER, "cancelled_order"),
        (TOP_ORDER, "top_order")
    ]

class FreshDeskTickets(ModelWithCreateUpdateTimestamp):

    mobile_no = PossiblePhoneNumberField(max_length=15, blank=True)
    message = models.TextField()
    info = models.JSONField(blank=True, null=True, default=dict, encoder=CustomJsonEncoder)
    ticket_id = models.CharField(max_length=255, blank=True, null=True)
    ticket_type = models.CharField(max_length=64,choices=TicketTypeEnum.CHOICES,default=TicketTypeEnum.INITIATE_PURCHASE)

    class Meta:
        ordering = ("updated_at",)
