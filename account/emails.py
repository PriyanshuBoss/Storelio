from urllib.parse import urlencode

from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from saleor.account.models import User, Influencer
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.utilities.time_utilities import TimeUtilities
from templated_email import send_templated_mail

from ..account import events as account_events
from ..celeryconf import app
from ..core.emails import get_email_context
from ..core.utils.url import prepare_url

REQUEST_EMAIL_CHANGE_TEMPLATE = "account/request_email_change"
EMAIL_CHANGED_NOTIFICATION_TEMPLATE = "account/email_changed_notification"
ACCOUNT_DELETE_TEMPLATE = "account/account_delete"
PASSWORD_RESET_TEMPLATE = "account/password_reset"


def send_user_password_reset_email_with_url(redirect_url, user):
    """Trigger sending a password reset email for the given user."""
    token = default_token_generator.make_token(user)
    _send_password_reset_email_with_url.delay(user.email, redirect_url, user.pk, token)


def send_account_confirmation_email(user, redirect_url):
    """Trigger sending an account confirmation email for the given user."""
    token = default_token_generator.make_token(user)
    _send_account_confirmation_email.delay(user.email, token, redirect_url)


@app.task
def _send_account_confirmation_email(email, token, redirect_url):
    params = urlencode({"email": email, "token": token})
    confirm_url = prepare_url(params, redirect_url)
    send_kwargs, ctx = get_email_context()
    ctx["confirm_url"] = confirm_url
    send_templated_mail(template_name = "account/confirm", recipient_list = [email],
                        context = ctx, **send_kwargs, )


@app.task
def _send_password_reset_email_with_url(recipient_email, redirect_url, user_id, token):
    params = urlencode({"email": recipient_email, "token": token})
    reset_url = prepare_url(params, redirect_url)
    # _send_password_reset_email(recipient_email, reset_url, user_id)


def _send_password_reset_email(recipient_email, reset_url, user_id):
    send_kwargs, ctx = get_email_context()
    ctx["reset_url"] = reset_url
    send_templated_mail(template_name = "account/password_reset",
                        recipient_list = [recipient_email], context = ctx,
                        **send_kwargs, )
    account_events.customer_password_reset_link_sent_event(user_id = user_id)


def send_user_change_email_url(redirect_url, user, new_email, token):
    """Trigger sending a email change email for the given user."""
    event_parameters = {"old_email": user.email, "new_email": new_email}
    # _send_request_email_change_email.delay(new_email, redirect_url, user.pk, token,
    #                                        event_parameters)


@app.task
def _send_request_email_change_email(recipient_email, redirect_url, user_id, token,
        event_parameters):
    params = urlencode({"token": token})
    redirect_url = prepare_url(params, redirect_url)
    send_kwargs, ctx = get_email_context()
    ctx["redirect_url"] = redirect_url
    send_templated_mail(template_name = REQUEST_EMAIL_CHANGE_TEMPLATE,
                        recipient_list = [recipient_email], context = ctx,
                        **send_kwargs, )
    account_events.customer_email_change_request_event(user_id = user_id,
                                                       parameters = event_parameters)


def send_user_change_email_notification(recipient_email):
    """Trigger sending a email change notification email for the given user."""
    _send_user_change_email_notification.delay(recipient_email)


@app.task
def _send_user_change_email_notification(recipient_email):
    send_kwargs, ctx = get_email_context()
    send_templated_mail(template_name = EMAIL_CHANGED_NOTIFICATION_TEMPLATE,
                        recipient_list = [recipient_email], context = ctx,
                        **send_kwargs, )


def send_account_delete_confirmation_email_with_url(redirect_url, user):
    """Trigger sending a account delete email for the given user."""
    token = default_token_generator.make_token(user)
    _send_account_delete_confirmation_email_with_url.delay(user.email, redirect_url,
                                                           token)


@app.task
def _send_account_delete_confirmation_email_with_url(recipient_email, redirect_url,
        token):
    params = urlencode({"token": token})
    delete_url = prepare_url(params, redirect_url)
    # _send_delete_confirmation_email(recipient_email, delete_url)


def _send_delete_confirmation_email(recipient_email, delete_url):
    send_kwargs, ctx = get_email_context()
    ctx["delete_url"] = delete_url
    send_templated_mail(template_name = ACCOUNT_DELETE_TEMPLATE,
                        recipient_list = [recipient_email], context = ctx,
                        **send_kwargs, )


def send_set_password_email_with_url(redirect_url, user, staff = False):
    """Trigger sending a set password email for the given customer/staff."""
    template_type = "staff" if staff else "customer"
    template = f"dashboard/{template_type}/set_password"
    token = default_token_generator.make_token(user)
    _send_set_user_password_email_with_url.delay(user.email, redirect_url, token,
                                                 template)


@app.task
def _send_set_user_password_email_with_url(recipient_email, redirect_url, token,
        template_name):
    params = urlencode({"email": recipient_email, "token": token})
    password_set_url = prepare_url(params, redirect_url)
    # _send_set_password_email(recipient_email, password_set_url, template_name)


def _send_set_password_email(recipient_email, password_set_url, template_name):
    send_kwargs, ctx = get_email_context()
    ctx["password_set_url"] = password_set_url
    send_templated_mail(template_name = template_name,
                        recipient_list = [recipient_email], context = ctx,
                        **send_kwargs, )


@app.task()
def send_mail_influencer_signup(user_id):
    params = _send_influencer_signup_context(user_id)

    if not params:
        return

    MailImpl.send_mail(**params)


def _send_influencer_signup_context(user_id):
    try:
        user_instance = User.objects.get(id = user_id)
        influencer_instance = Influencer.objects.get(user = user_id)
    
    except:
        return {}
    
    if settings.IS_BETA:
        request_url = "http://betaanalytics.zaamo.co/prod/influencer/signup"
    else:
        request_url = "http://landing.zaamo.co/prod/influencer/signup"

    subject = "ZAAMO Influencer Signup"
    mail_type = "influencer_signup"
    template_data = {
        "contact_number": user_instance.mobile_no, 
        "date": TimeUtilities.get_current_date(), 
        "timestamp": TimeUtilities.get_current_time(),
        "subject": subject,
        "request_url": request_url,
        "instagram_link": influencer_instance.instagram_link
        }
    
    return {'mail_type': mail_type, 'template_data': template_data}


@app.task()
def send_mail_brand_signup(user_id):
    params = _send_brand_signup_context(user_id)
    if not params:
        return

    MailImpl.send_mail(**params)


def _send_brand_signup_context(user_id):
    try:
        user_instance = User.objects.get(id = user_id)

    except:
        return {}

    subject = "ZAAMO Brand Signup"
    mail_type = "brand_signup"
    template_data = {
        "contact_number": user_instance.mobile_no, 
        "date": TimeUtilities.get_current_date(), 
        "timestamp": TimeUtilities.get_current_time(),
        "subject": subject
        }
    
    return {'mail_type': mail_type, 'template_data': template_data}

@app.task()
def send_mail_influencer_account_activation(influencer_mobile_no, instagram_link, user_email):
    email = MailImpl()
    mail_type = 'influencer_account_activation'
    subject = 'Influencer Account Activated'
    cc = []
    template_data = {
        "contact_number": influencer_mobile_no,
        "date": TimeUtilities.get_current_date(),
        "timestamp": TimeUtilities.get_current_time(),
        "request_url": "https://zaamo.co",
        "instagram_link": instagram_link,
        "subject": subject,
        "user_email": user_email
    }
    email.send_mail(mail_type, template_data, cc=cc)

