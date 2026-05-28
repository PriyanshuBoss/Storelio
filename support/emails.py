from saleor.store.models import StoreInfo
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.utilities.time_utilities import TimeUtilities
from ..celeryconf import app


@app.task()
def send_mail_support(store_id,user_email, mobile_no, message):
    params = _send_support_context(store_id, user_email,mobile_no, message)
    MailImpl.send_mail(**params)

@app.task()
def _send_influencer_request_domain(store_id,user_email,mobile_no,message):
    params = _send_influencer_request_domain_context(store_id, user_email,mobile_no, message)
    MailImpl.send_mail(**params)

@app.task()
def _send_influencer_request_ig(store_id,user_email,mobile_no,message):
    params = _send_influencer_request_ig_context(store_id,user_email,mobile_no,message)
    MailImpl.send_mail(**params)


@app.task()
def send_mail_brand_support(store_id,user_email,mobile_no,message):
    params = _send_brand_support_context(store_id,user_email,mobile_no,message)
    MailImpl.send_mail(**params)


@app.task()
def send_mail_brand_suggestion(store_id, user_email, mobile_no, message):
    params = _send_brand_suggestion_context(store_id, user_email, mobile_no, message)
    MailImpl.send_mail(**params)

@app.task()
def send_mail_brand_signup_query(store_id, user_email, mobile_no, message):
    params = _send_brand_signup_query_context(store_id, user_email, mobile_no, message)
    MailImpl.send_mail(**params)


def _send_brand_signup_query_context(store_id, user_email, mobile_no, message):
    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        pass

    if not store:
        pass

    subject = "Brand Signup"
    mail_type = "brand_signup_query"

    template_data = {
        "subject": subject,
        "store_name": store.store_url,
        "email": user_email,
        "phone": mobile_no,
        "message": message
    }

    return {'mail_type': mail_type, 'template_data': template_data}


def _send_brand_suggestion_context(store_id, user_email, mobile_no, message):
    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        pass

    if not store:
        pass

    subject = "ZAAMO Brand Suggestion"
    mail_type = "brand_suggestion_query"

    template_data = {
        "subject":subject,
        "store_name": store.store_url, 
        "email": user_email, 
        "phone": mobile_no, 
        "message":message
    }

    return {'mail_type': mail_type, 'template_data': template_data}

def _send_brand_support_context(store_id,user_email, mobile_no, message):
    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        pass

    if not store:
        pass

    subject = "ZAAMO Brand Support"
    mail_type = "brand_support_query"

    template_data = {
        "subject":subject,
        "store_name": store.store_url, 
        "email": user_email, 
        "phone": mobile_no, 
        "message":message
    }

    return {'mail_type': mail_type, 'template_data': template_data}


def _send_support_context(store_id,user_email, mobile_no, message):
    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        pass

    if not store:
        pass

    subject = "ZAAMO Support"
    mail_type = "support_query"

    template_data = {
        "subject":subject,
        "store_name": store.store_url, 
        "email": user_email, 
        "phone": mobile_no, 
        "message":message
    }

    return {'mail_type': mail_type, 'template_data': template_data}


def _send_influencer_request_domain_context(store_id,email,mobile_no,message):
    subject = "ZAAMO Domain Request"
    mail_type = "request_domain"

    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        store = None

    if not store:
        return {}
    # FIXME add review request button here, which will take to a link
    template_data = {
        "subject":subject,
        "store_name":store.slug,
        "date": TimeUtilities.get_current_date(), 
        "timestamp": TimeUtilities.get_current_time(),
        "store_url":store.store_url,
        "request_domain_text":message
    }

    cc = list(store.staff_store_mappings.all().values_list('user__email', flat=True))
    
    return {'mail_type': mail_type, 'template_data': template_data, 'cc': cc}


def _send_influencer_request_ig_context(store_id,email,mobile_no,message):
    subject = "ZAAMO Influencer Connect"
    mail_type = "request_influencer_connect"

    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        store = None

    if not store:
        return {}

    template_data = {
        "subject":subject,
        "store_name":store.slug,
        "date": TimeUtilities.get_current_date(), 
        "timestamp": TimeUtilities.get_current_time(),
        "store_url":store.store_url,
        "influencer_connect_text":message
    }

    return {'mail_type': mail_type, 'template_data': template_data}


    