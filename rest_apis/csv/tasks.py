from saleor.celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.settings import IS_BETA
import logging

from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)
from saleor.rest_apis.csv.view_impl import export_zaamo_shopify_order, send_csv_to_brand_owners, send_all_collections_dump_csv_data, send_recent_checkout_csv_data, send_structure_data_ad_on_mail
from .helper import bulk_update_product_for_step_price, bulk_update_variant_for_step_price
from .csv_context import TopProductViewsCSV

@app.task(queue='priority_queue')
def send_csv_to_brand_owners_task(user_id_list,days):
    '''
    from saleor.rest_apis.csv.tasks import send_csv_to_brand_owners_task
    send_csv_to_brand_owners_task.delay()
    '''
    try:

        # if not IS_BETA:
        #     failed_emails = send_csv_to_brand_owners(user_id_list,days)

        #     m = MailImpl()
        #     recipient_email = ['nitanshub@zaamo.co','priyanshu@zaamo.co']

        #     if failed_emails:
        #         for email in recipient_email:
        #             m.send_mail_without_template('brand_owner_csv',f"Failed Emails for csv task :: {failed_emails}",'Brand CSV Status',email)
      
            logger.info("CSV Email Task completed")
    
    except Exception as e:
        logger.exception(f"Error in brand owner csv creation: {e}")

@app.task(queue='celery_periodic')
def send_zaamo_shopify_order_csv():
    '''
    from saleor.rest_apis.csv.tasks import send_zaamo_shopify_order_csv
    send_zaamo_shopify_order_csv.delay()
    '''
    try:

        if not IS_BETA:
            export_zaamo_shopify_order({},True)
    
    except Exception as e:
        logger.exception(f"Error in brand owner csv creation: {e}")


@app.task(queue='celery_periodic')
def send_csv_to_brand_owners_periodic_task():
    '''
    from saleor.rest_apis.csv.tasks import send_csv_to_brand_owners_periodic_task
    send_csv_to_brand_owners_periodic_task.delay()
    '''
    try:

        if not IS_BETA:
            failed_emails = send_csv_to_brand_owners([],3,send_to_all_brand=True)

            m = MailImpl()
            recipient_email = ['nitanshub@zaamo.co','priyanshu@zaamo.co']

            if failed_emails:
                for email in recipient_email:
                    m.send_mail_without_template('brand_owner_csv',f"Failed Emails for csv task :: {failed_emails}",'Brand CSV Status',email)
      
            logger.info("CSV Email Task completed")
    
    except Exception as e:
        logger.exception(f"Error in brand owner csv creation: {e}")

@app.task(queue='celery_periodic')
def send_all_collections_csv_task():
    '''
    from saleor.rest_apis.csv.tasks import send_all_collections_csv_task
    send_all_collections_csv_task.delay()
    '''
    try:

        if not IS_BETA:
            send_all_collections_dump_csv_data()
    
    except Exception as e:
        logger.exception(f"Error in all collections csv creation: {e}")

@app.task(queue='celery_periodic')
def send_recent_checkout_csv_task():
    '''
    from saleor.rest_apis.csv.tasks import send_recent_checkout_csv_task
    send_recent_checkout_csv_task.delay()
    '''
    try:

        if not IS_BETA:
            send_recent_checkout_csv_data()
    
    except Exception as e:
        logger.exception(f"Error in recent checkout csv creation: {e}")
        
@app.task(queue='priority_queue')
def update_product_variant_from_step_price(product_id_list_split_price_dict_temp):

    try:
        product_id_list_split_price_dict = dict()

        for key,value in product_id_list_split_price_dict_temp.items():
            product_id_list_split_price_dict[NumberUtilities.convert_string_to_number(key)] = NumberUtilities.convert_string_to_decimal(value)
        
        product_id_list_split_price_dict_temp.clear()
        
        bulk_update_product_for_step_price(product_id_list_split_price_dict)
        bulk_update_variant_for_step_price(product_id_list_split_price_dict)
    
    except Exception as e:
        logger.exception(f"Error in Step Price updation: {e}")


@app.task(queue='celery_periodic')
def send_csv_top_products_yesterday():
    
    if IS_BETA:
        return
    
    products = TopProductViewsCSV()
    header = products.get_headers()
    rows = [header] + products.get_rows()

    mail = MailImpl()
    attachment = mail.get_csv_attachment_dict('top_product_views.csv', rows)
    attachments = [attachment]
    mail.send_mail_with_attachment('top_product_views', 'Hi,\nPFA.', 'Top Products yesterday', attachments)


@app.task(queue='priority_queue')
def send_fb_ad_data_to_mail(brand_names,brand_ids_decoded):
    try:

        send_structure_data_ad_on_mail(brand_names,brand_ids_decoded)
    
    except Exception as e:
        logger.exception(f"Error in brand ad data csv creation: {e}")