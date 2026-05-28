import logging

from saleor.brand.models import BrandEmail, BrandEmailStateEnum, Brand, BrandStatusEnum
from saleor.order import FulfillmentStatus
from saleor.order.models import FulfillmentLine, OrderLine, OrderBrandZaamoMapping
from ..celeryconf import app
from saleor.settings import IS_BETA
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.rest_apis.csv.csv_context import BrandLedgerXLSX, BrandPaymentCsvContext, OrderCsvContext, BrandLedgerOld
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from .states import ArrearTypeEnum
from .brand_helpers import BrandAging
from saleor.graphql.analytics.resolvers import filter_delayed_orders
import graphene
from collections import defaultdict

logger = logging.getLogger(__name__)

def prepare_email_text_for_too_many_orders_or_brand_is_active(obj, old_obj ,for_tmo_email=True):

    if for_tmo_email:

        mail_text = """ The brand TOO MANY ORDERS status has been changed earlier it was {} now it is {} """.format(not obj.too_many_orders ,obj.too_many_orders)
    
    else:

        mail_text = """ The brand ACTIVE status has been changed earlier it was {} now it is {} """.format(old_obj.status, obj.status)


    return mail_text
    
def prepare_email_text_for_botd(obj):
    mail_text = """ The brand BOTD status has been changed earlier it was {} now it is {}. """.format(not obj.botd,obj.botd)

    return mail_text

def prepare_email_text_for_botd_by_brand_manager(obj):
    if obj.botd:
        botd = "on"
    else:
        botd = "off"

    if obj.updated_by:
        mail_text = """ The brand BOTD status has been changed earlier it was {} now it is {}. This was turned {} by this {}. """.format(not obj.botd,obj.botd, botd, obj.updated_by.email)
    else:
        mail_text = """ The brand BOTD status has been changed earlier it was {} now it is {}. """.format(not obj.botd,obj.botd)

    return mail_text


def prepare_email_text_for_barter(obj):
    mail_text = """ The brand Barter status has been changed earlier it was {} now it is {}. """.format(not obj.brand_barter,obj.brand_barter)

    return mail_text

@app.task
def send_email_for_brand_status_changes(subject, email_text, mail_type="brand_status_changed", cc=None):
    
    if not cc:
        cc=[]

    MailImpl.send_mail_without_template(mail_type, email_text, subject, cc=cc)


@app.task
def send_email_brand_ledger(brand_ids, test_email=None, old=False):
    primary_emails = BrandEmail.objects.filter(brand_id__in=brand_ids, state=BrandEmailStateEnum.PRIMARY)\
        .values('brand_id__brand_name', 'brand_email').distinct()
    primary_emails = {brand['brand_id__brand_name']: brand['brand_email'] for brand in primary_emails}

    all_emails_qs = BrandEmail.objects.filter(brand_id__in=brand_ids)\
        .values('brand_id__brand_name', 'brand_email').distinct()
    
    all_emails = dict()
    for brand in all_emails_qs:

        brand_name = brand['brand_id__brand_name']
        if not brand_name in all_emails:
            all_emails[brand_name] = []
        all_emails[brand_name].append(brand['brand_email'])

    if old:
        brand_orders = BrandLedgerOld.brand_ledger_orders(primary_emails)
        brand_payouts = BrandLedgerOld.brand_ledger_payouts(primary_emails)
    else:
        ledger = BrandLedgerXLSX(brand_ids)
        brand_orders = ledger.brand_ledger_orders()
        brand_payouts = ledger.brand_ledger_payouts()
    
    brand_names = set(brand_orders.keys())
    brand_names.update(brand_payouts.keys())

    for brand_name in brand_names:

        primary_email = primary_emails.get(brand_name)
        if not primary_email:
            continue
        email = MailImpl()
        sheets = {
            'Payout': brand_payouts.get(brand_name, []),
            'Orders': brand_orders.get(brand_name, [])
        }
        ledger_attachment_dict = email.get_excel_attachment_dict(f'{brand_name}-Ledger.xlsx', sheets)
        mail_type = "brand_ledger_csv"
        msg = "Hi Team,\nPFA the ledger. For any queries, please reach out to us @91404 20972 or accounts@zaamo.co\n"
        subject = "Brand Ledger"
        attachments = [ledger_attachment_dict]
        recipient_email = primary_email
        cc = ['accounts@zaamo.co'] + [cc_email for cc_email in all_emails.get(brand_name, []) if cc_email != primary_email]
        if test_email:
            recipient_email = test_email
            cc = []
        email.send_mail_with_attachment(mail_type, msg, subject, attachments, recipient_email, cc)
        logger.info(f"Brand Ledger email sent to {recipient_email} with cc {cc}.")

@app.task(queue='celery_periodic')
def send_brand_ledger_weekly():
    '''
    brand active and due_amount negative
    '''
    if IS_BETA:
        return
    
    brand_ids = []
    payment = BrandPaymentCsvContext(TimeUtilities.get_current_date_time())
    brands = Brand.objects.filter(status=BrandStatusEnum.ACTIVE)
    for brand in brands:
        due_amount = payment.get_due_amount(brand)
        if due_amount < -1000:
            brand_ids.append(brand.id)
    
    send_email_brand_ledger(brand_ids)

@app.task(queue='celery_periodic')
def send_brand_delayed_orders_weekly():
    '''
    placed/inprocess delayed orders
    '''
    if IS_BETA:
        return
    
    lines = FulfillmentLine.objects.filter(fulfillment__status__in=[FulfillmentStatus.PLACED, FulfillmentStatus.INPROCESS])
    delayed_lines = filter_delayed_orders(lines)
    if not delayed_lines:
        logger.info("Brand delayed orders - 0 delayed orders")
        return

    start_date = delayed_lines.order_by('order_line__order__created').values_list('order_line__order__created', flat=True)[0]
    end_date = TimeUtilities.get_current_date_time()
    order_csv = OrderCsvContext(start_date=start_date, end_date=end_date)

    line_ids = delayed_lines.values_list('order_line_id', flat=True)
    orderlines = OrderLine.objects.filter(id__in=line_ids).select_related('order', 'brand', 'variant', 'order__shipping_address', 'order__voucher', 'order__user')
    shopify_urls = OrderBrandZaamoMapping.objects.filter(order_line_zaamo__in=line_ids).values_list('order_line_zaamo_id', 'metadata__shopify_url')
    shopify_urls = {line_id: shopify_url for line_id, shopify_url in shopify_urls}

    brand_rows = defaultdict(list)
    header = ['Brand', 'timestamp', 'order ID', 'product name', 'status', 'brand order status', 'customer msp', 'mrp', 'platform fees', 'customer name', 'phone', 'email', 'address', 'brand order ID', 'shopify_url']
    for line in orderlines:
        row = {
            'Brand': order_csv.get_brand_name(line),
            'timestamp': line.order.created,
            'order ID': graphene.Node.to_global_id('Order', line.order_id),
            'product name': order_csv.get_product_name(line),
            'status': order_csv.get_order_status(line),
            'brand order status': order_csv.get_brand_order_status(line),
            'customer msp': order_csv.get_msp(line),
            'mrp': order_csv.get_mrp(line),
            'platform fees': order_csv.get_platform_fees(line),
            'customer name': order_csv.get_customer_name(line),
            'phone': order_csv.get_customer_phone_number(line),
            'email': order_csv.get_customer_email(line),
            'address': order_csv.get_customer_address(line),
            'brand order ID': order_csv.get_brand_order_id(line),
            'shopify_url': shopify_urls.get(line.id, ''),
        }
        brand_rows[line.brand.brand_name].append(row)

    primary_emails = BrandEmail.objects.filter(brand_id__brand_name__in=list(brand_rows.keys()), state=BrandEmailStateEnum.PRIMARY)\
        .values('brand_id__brand_name', 'brand_email').distinct()
    primary_emails = {brand['brand_id__brand_name']: brand['brand_email'] for brand in primary_emails}

    all_emails = BrandEmail.objects.filter(brand_id__brand_name__in=list(brand_rows.keys())).values('brand_id__brand_name', 'brand_email').distinct()
    all_emails = {brand['brand_id__brand_name']: brand['brand_email'] for brand in all_emails}

    for brand_name, rows in brand_rows.items():
        recipient_email = primary_emails.get(brand_name)
        if not recipient_email:
            recipient_email = all_emails.get(brand_name)
        if not recipient_email:
            logger.info(f"Brand delayed orders - email not found for brand {brand_name}")
            continue

        mail = MailImpl()
        ledger_attachment_dict = mail.get_csv_attachment_dict(f'{brand_name} - Delayed Orders.csv', rows, header)
        mail_type = "brand_ledger_csv"
        msg = f"Hi team, {len(rows)} orders are currently running delayed. PFA order details.\n"
        subject = "Delayed Orders"
        attachments = [ledger_attachment_dict]
        cc = ['delayedorder@zaamo.co']

        mail.send_mail_with_attachment(mail_type, msg, subject, attachments, recipient_email, cc)
        logger.info(f"Brand delayed orders email sent to {recipient_email} with cc {cc}.")


def get_arrear_details(arrear_instance):

    if arrear_instance.get('arrear_type') == ArrearTypeEnum.BRAND:

        arrear_details = """\n Arrear Details: %s\n Amount: %s \n Person of Contact: %s\n Arrear Type: %s\n Brand Name: %s\n Brand Active: %s\n

            """ % (
            arrear_instance.get('arrear_details'),
            StringUtilities.convert_number_to_string(arrear_instance.get('amount')),
            arrear_instance.get('person_of_contact').email,
            arrear_instance.get('arrear_type'),
            arrear_instance.get('brand').brand_name,
            arrear_instance.get('brand').active
        )

    if arrear_instance.get('arrear_type') == ArrearTypeEnum.INFLUENCER:

        arrear_details = """\n Arrear Details: %s\n Amount: %s \n Person of Contact: %s\n Arrear Type: %s\n Store Name: %s\n Store Url: %s\n

            """ % (
            arrear_instance.get('arrear_details'),
            StringUtilities.convert_number_to_string(arrear_instance.get('amount')),
            arrear_instance.get('person_of_contact').email,
            arrear_instance.get('arrear_type'),
            arrear_instance.get('store').store_name,
            arrear_instance.get('store').store_url
        )
    
    return arrear_details

def get_arrear_text_for_arrear_creation(arrear_instance, old_obj=None):
    
    if not old_obj:
        prefix = " A New Arrear has been created at %s with details as follows: \n" % (arrear_instance.get('created_at'))
        arrear_text = prefix + get_arrear_details(arrear_instance)

    else:
        prefix = " Arrear has been updated at %s with details as follows: \n" % (arrear_instance.get('updated_at'))
        arrear_text = prefix + get_arrear_details(arrear_instance)

    return arrear_text


@app.task()
def send_mail_for_arrear_creation_or_updation(subject, arrear_text, mail_type="arrear_creation", cc=None):

    if not cc:
        cc=[]

    MailImpl.send_mail_without_template(mail_type, arrear_text, subject, cc=cc)


@app.task(queue='celery_periodic')
def send_brand_aging_email():
    '''
    '''
    if IS_BETA:
        return
    
    BrandAging.send_email()
