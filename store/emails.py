import logging

from saleor.store.models import StoreInfo
from saleor.store.models import StoreMemberState
from saleor.brand.models import Brand
from saleor.discount.models import Voucher
from saleor.external_services.mail.mail_impl import MailImpl
from ..celeryconf import app
from saleor.utilities.time_utilities import TimeUtilities
from .states import StoreBrandSourcingRequestEnum
from saleor.rest_apis.csv.csv_context import InfluencerLedgerXLSX

logger = logging.getLogger(__name__)


@app.task()
def send_mail_request_collection(store_id,user_email, mobile_no, message):
    params = _send_request_collection_context(store_id, user_email,mobile_no, message)
    
    if params:
        MailImpl.send_mail(**params)

    # FIXME implementation for Request Collection mail to Influencer
    #       for now not useful, but uncomment these two lines and add a template and it will be funcitonal
    #
    # store = StoreMemberState.objects.filter(store__id = store_id).first()
    # if store.user.email:
    #     params = send_request_collection_influencer(store_id,store.user.email,mobile_no,message)
    #     MailImpl.send_mail(**params)



def _send_request_collection_context(store_id,user_email, mobile_no, message):
    subject = "ZAAMO Collection Request"
    mail_type = "request_collection"

    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        store = None

    if not store:
        return {}
    
    store_managers_email = []
    for data in store.staff_store_mappings.all().prefetch_related('user'):
        user = data.user
        
        if user.email:
            store_managers_email.append(user.email)

    template_data = {
        "subject":subject,
        "store_name":store.slug,
        "date": TimeUtilities.get_current_date(), 
        "timestamp": TimeUtilities.get_current_time(),
        "store_url":store.store_url,
        "request_collection_text":message
    }

    return {'mail_type': mail_type, 'template_data': template_data, "cc": store_managers_email}

def send_request_collection_influencer(store_id,user_email, mobile_no, message):
    try:
        store = StoreInfo.objects.get(id = store_id)
    except:
        store = None

    if not store:
        return {}

    subject = "ZAAMO Store Collection Request"
    mail_type = "request_collection_influencer"
    recipient_email = user_email
    template_data = {
        "subject":subject,
        "store_name":store.slug,
        "date": TimeUtilities.get_current_date(), 
        "timestamp": TimeUtilities.get_current_time(),
        "store_url":store.store_url,
        "request_collection_text":message
    }

    return {'mail_type': mail_type, 'template_data': template_data, 'recipient_email': recipient_email}

@app.task
def send_barter_feedback(brand_id, email, message):
    
    brand_managers = list(Brand.objects.filter(id=brand_id).values_list('staff_brand_mappings__user__email', flat=True))
    email = MailImpl()
    mail_type = 'barter_feedback'
    subject = 'Barter Feedback'

    email.send_mail_without_template(mail_type, message, subject, cc=brand_managers, recipient_email=email)    

@app.task
def send_email_marked_botd(brand_id, store_id):
    
    brand_managers = list(Brand.objects.filter(id=brand_id).values_list('staff_brand_mappings__user__email', flat=True))
    store_managers = list(StoreInfo.objects.filter(id=store_id).values_list('staff_store_mappings__user__email', flat=True))
    cc_emails = list(set(brand_managers + store_managers))

    brand_name = Brand.objects.get(id=brand_id).brand_name
    store_name = StoreInfo.objects.get(id=store_id).store_name
    
    start_date, end_date = Voucher.objects.filter(store=store_id, name="BOTD").values_list('start_date', 'end_date').first()
    start_date = start_date.strftime('%Y-%m-%d %H:%M:%S')
    end_date = end_date.strftime('%Y-%m-%d %H:%M:%S')

    email = MailImpl()
    cc = cc_emails
    mail_type = 'marked_botd'
    msg = f'The botd of the brand "{brand_name}" has been turned for store "{store_name}" at {start_date}. The botd will expire at {end_date}.\n'
    subject = 'BOTD turned on'

    email.send_mail_without_template(mail_type, msg, subject, cc=cc)

def brand_sourcing_request_email_context(data):
    mail_text = """
        A new brand sourcing request has been created with the following details :: {}
        Store Name :  {} {}
        Store URL : {}  {}
        Store Managers : {} {}
        Brand : {} {}
        Brand Active : {} {}
        Brand Managers : {} {}
        Status : {} {}
        Terms and Conditions : {} {}
        """.format("\n", data['store'].store_name, "\n", data['store'].store_url, "\n", data['store_managers'], "\n",
                data['brand'].brand_name, "\n", data['brand'].active, "\n", data['brand_managers'], "\n",
                StoreBrandSourcingRequestEnum.REQUEST_RECEIVED, "\n", data['terms_and_conditions'], "\n",
        )
    
    if data.get('campaign_name') is not None:
        mail_text_for_campaign_name = """
        Campaign Name : {} {}
        """.format(data['campaign_name'], "\n")

        mail_text  = mail_text + mail_text_for_campaign_name
        
    if data.get('content') is not None:
        mail_text_for_content = """
        Content : {} {}
        """.format(data['content'], "\n")
        
        mail_text  = mail_text + mail_text_for_content
    
    return mail_text


@app.task
def send_brand_sourcing_request_email(subject, souring_request_text, mail_type="brand_sourcing_request", cc=None):
    
    if not cc:
        cc=[]
    
    MailImpl.send_mail_without_template(mail_type, souring_request_text, subject, cc=cc)

@app.task
def send_influencer_ledger_email(store_names):
    store_emails = StoreMemberState.objects.filter(store__store_name__in=store_names).values_list('store__store_name', 'user__email')
    emails = {store_name: email for store_name, email in store_emails}

    influencer_payouts = InfluencerLedgerXLSX.influencer_ledger_payouts(emails)
    influencer_orders = InfluencerLedgerXLSX.influencer_ledger_orders(emails)
    
    for store_name, recipient_email in emails.items():
        if not recipient_email:
            continue
        email = MailImpl()
        sheets = {
            'Orders': influencer_orders.get(store_name, []),
            'Payouts Done': influencer_payouts.get(store_name, [])
        }
        ledger_attachment_dict = email.get_excel_attachment_dict(f'{store_name}-Ledger.xlsx', sheets)
        mail_type = "influencer_ledger_csv"
        msg = "Hi Team,\nPFA the ledger. For any queries, please reach out to us @91404 20972 or accounts@zaamo.co\n"
        subject = "Ledger"
        attachments = [ledger_attachment_dict]
        cc = ['accounts@zaamo.co']
        email.send_mail_with_attachment(mail_type, msg, subject, attachments, recipient_email, cc)
        logger.info(f"Influencer Ledger email sent to {recipient_email} with cc {cc}.")

def prepare_email_text_store_barter_changed(store, user):
    store_barter = store.metadata.get('store_barter')
    subject = 'Store Barter changed by ' + user.email
    mail_text = f"The store barter is changed to {store_barter} by user with email = {user.email} and mobile_no = {user.mobile_no} at {TimeUtilities.get_current_date_time()} for {store.store_name}"
    return subject, mail_text

@app.task
def send_email_store_barter_changed(subject, mail_text):
    mail_type = 'store_barter_changed'
    email = MailImpl()
    email.send_mail_without_template(mail_type, mail_text, subject)

