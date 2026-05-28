from django.core.exceptions import ValidationError
import graphene
from saleor.graphql.support.types import Meetup, SupportQuery
from saleor.store.store_utilities import get_instance_for_store
from saleor.store.models import BrandSourcingRequest
from saleor.product.models import SourcingRequest
from saleor.support import models
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.support.emails import send_mail_support, _send_influencer_request_domain , _send_influencer_request_ig, send_mail_brand_support, send_mail_brand_suggestion, send_mail_brand_signup_query
from saleor.store.emails import send_barter_feedback, send_mail_request_collection
from ..core.mutations import ModelMutation
from ..core.mutations import BaseMutation
from .emails import send_mail_to_email_ids
from saleor.graphql.meta.mutations import MetadataInput
from .enums import NotificationTypeEnum
from saleor.external_services.whatsapp.tasks import product_sourcing_whatsapp_notification,brand_sourcing_whatsapp_notification

class SupportQueryCreateInput(graphene.InputObjectType):
    email = graphene.String(description="The customer's email address.")
    mobile_no = graphene.String(description="The customer's mobile no", required=False)
    message = graphene.String(description="Message of the customer")
    info = graphene.JSONString(description = "info data for support query")


class SupportQueryCreate(ModelMutation):
    class Arguments:
        input = SupportQueryCreateInput(
            required=True, description="Fields required to create support message"
        )

    class Meta:
        description = "Create a new message for support."
        model = models.SupportQueries
        return_field_name = "SupportQuery"

    @classmethod
    def clean_input(cls, info, instance, data, input_cls=None):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)

        if not store_instance:
             raise ValidationError(message="In-valid store id")
        
        cleaned_input = super().clean_input(info, instance, data, input_cls=input_cls)
        cleaned_input['store'] = store_instance

        return cleaned_input

    @classmethod
    def get_type_for_model(cls):
        return SupportQuery

    @classmethod
    def post_save_action(cls, info, instance, cleaned_input):
        store_id = instance.store_id
        email = instance.email
        mobile_no = StringUtilities.convert_number_to_string(instance.mobile_no)
        message = instance.message
        if instance.email=="requestcollection@zaamo.co":
            send_mail_request_collection.delay(store_id,email,mobile_no,message)

        elif instance.email=="instagramrequest@zaamo.co":
            _send_influencer_request_ig.delay(store_id,email,mobile_no,message)

        elif instance.email=="domainrequest@zaamo.co":
            _send_influencer_request_domain.delay(store_id,email,mobile_no,message)

        elif instance.email=="brandsupport@zaamo.co":
            send_mail_brand_support.delay(store_id,email,mobile_no,message)
        
        elif instance.email=="suggestbrand@zaamo.co":
            send_mail_brand_suggestion.delay(store_id, email, mobile_no, message)

        elif instance.email=="brands@zaamo.co":
            send_mail_brand_signup_query.delay(store_id, email, mobile_no, message)
        
        elif instance.email=="barterfeedback@zaamo.co":
            brand_id= graphene.Node.from_global_id(cleaned_input.get("info", {}).get("brand_id", ""))[1]
            send_barter_feedback.delay(brand_id, email, message)

        else:
            send_mail_support.delay(store_id,email,mobile_no,message)

        return super().post_save_action(info, instance, cleaned_input)


class EmailSendingInput(graphene.InputObjectType):
    email_ids = graphene.List(
        graphene.String,
        required=True,
        description="The list of email addresses."
    )
    message = graphene.String(required=True,description="Message to be sent")
    mail_type = graphene.String(required=True,description="Mail type")
    subject = graphene.String(required=True,description="Subject")



class EmailSending(BaseMutation):
    class Arguments:
        input = EmailSendingInput(
            required=True, description="Fields required for email send"
        )
    
    class Meta:
        description = "Email Send"
        error_type_field = "email_sending_errors"

    success = graphene.Boolean(description="status of message sent")
    
    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        email_ids = input['email_ids']
        message = input['message']
        subject = input['subject']
        mail_type = input['mail_type']
        
        if not email_ids:
            raise ValidationError(message="Provide EmailIds")

        if not message:
            raise ValidationError(message="Invalid Message Text")

        if not mail_type:
            raise ValidationError(message="Invalid Mail Type")

        if not subject:
            raise ValidationError(message="Invalid Mail Subject")
            
        send_mail_to_email_ids.delay(mail_type, message, subject, email_ids)
        
        return cls(success=True)


class MeetupCreateInput(graphene.InputObjectType):
    details = graphene.JSONString(description="meetup details", required=True)
    datetime = graphene.DateTime(description = "meetup datetime", required=True)



class MeetupCreate(BaseMutation):

    meetup = graphene.Field(Meetup, description = "Meetup details")

    class Arguments:
        input = MeetupCreateInput(
            required=True, description = "Meetup Create Input."
        )

    class Meta:
        description = "Create a new meetup."
        model = models.Meetup
        return_field_name = "Meetup"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        meetup = models.Meetup.objects.create(
            details=input['details'],
            datetime = input['datetime']
        )
        return cls(meetup=meetup)


class MeetupUpdateInput(graphene.InputObjectType):
    id = graphene.ID(description = "Meetup ID", required=True)
    details = graphene.JSONString(description="meetup details", required=False)
    datetime = graphene.DateTime(description = "meetup datetime", required=False)


class MeetupUpdate(BaseMutation):
    meetup = graphene.Field(Meetup, description = "Meetup details")

    class Arguments:
        input = MeetupUpdateInput(
            required=True, description = "Meetup Update Input."
        )

    class Meta:
        description = "Update meetup."
        model = models.Meetup
        return_field_name = "Meetup"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        meetup = graphene.Node.get_node_from_global_id(info, input['id'], Meetup)

        if not meetup:
            raise ValidationError("Invalid Meetup ID.")
        
        if input.get('details'):
            meetup.details = input.get('details')

        if input.get('datetime'):
            meetup.datetime = input.get('datetime')
        
        meetup.save()
        return cls(meetup=meetup)


class MeetupDeleteInput(graphene.InputObjectType):
    id = graphene.ID(description = "Meetup ID", required=True)


class MeetupDelete(BaseMutation):
    success = graphene.Boolean(description = "Meetup delete success")

    class Arguments:
        input = MeetupDeleteInput(
            required=True, description = "Meetup Delete Input."
        )

    class Meta:
        description = "Delete meetup."
        model = models.Meetup
        return_field_name = "Meetup"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        meetup = graphene.Node.get_node_from_global_id(info, input['id'], Meetup)
        if not meetup:
            raise ValidationError("Invalid Meetup ID.")

        models.Meetup.objects.filter(pk=meetup.id).delete()
        return cls(success=True)

class WhatsappNotificationTriggerInput(graphene.InputObjectType):
    notification_type = NotificationTypeEnum(description = "Notification Type", required=True)
    sourcing_id = graphene.ID(description = "Sourcing ID of brand or product" , required = True)
    content = graphene.String(description = "Content information for brand" , required = False)

class WhatsappNotificationTriggerMutation(BaseMutation):
    success = graphene.Boolean(description = "Notification sent successfully")

    class Arguments:
        input = WhatsappNotificationTriggerInput(description = "Brand or sourcing Request details" , required = True)

    class Meta:
        description = "Notification trigger mutation for sourcing request"

    
    @classmethod
    def perform_mutation(cls, root, info, **data):
        data = data.get('input')
        sourcing_global_id = data.get('sourcing_id')
        sourcing_type = data.get('notification_type')
        content = data.get('content','')
        sourcing_id = graphene.Node.from_global_id(sourcing_global_id)[1]
        success = False
        if sourcing_type == NotificationTypeEnum.BRAND_SOURCING:
            sourcing_request = BrandSourcingRequest.objects.filter(pk=sourcing_id).first()
            if sourcing_request.notification == False:
                success = brand_sourcing_whatsapp_notification.delay(sourcing_id)
        elif sourcing_type == NotificationTypeEnum.PRODUCT_SOURCING:
            sourcing_request = SourcingRequest.objects.filter(pk=sourcing_id).first()
            if sourcing_request.notification == False:
                success = product_sourcing_whatsapp_notification.delay(sourcing_id,content)

        return cls(success=success)