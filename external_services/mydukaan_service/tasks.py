import time
from saleor.celeryconf import app
from saleor.external_services.integrations.tasks import send_post_resync_confirmation_email
from saleor.external_services.mydukaan_service.mydukaan_impl import MyDukaanImpl
import logging

from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
logger = logging.getLogger(__name__)

@app.task(queue='onboarding_queue')
def initiate_product_onboarding_mydukaan(shop):
    try:
        mydukaan_impl_inst = MyDukaanImpl()
        
        mydukaan_impl_inst.set_authtoken(shop['token'])
        mydukaan_impl_inst.create_brand_from_MyDukaan(shop)
        mydukaan_impl_inst.insert_product_data_from_mydukaan_store(shop)
        if IS_BETA:
            mydukaan_impl_inst.create_product_from_MyDukaan(shop)
    
    except Exception as e:
        logger.exception(f"Error in MyDukaan onboarding: {e}")

@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_mydukaan():
    '''
    To Run in shell: 

    from saleor.external_services.mydukaan_service.tasks import resync_price_inventory_in_mongo_mydukaan
    resync_price_inventory_in_mongo_mydukaan.delay()
    '''
    
    if IS_BETA:
        return
        
    try:
        start_time = StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())
        
        mydukaan_impl_inst = MyDukaanImpl()
        fail_names, success_names = mydukaan_impl_inst.resync_price_and_inventory()
        mail_text = f'Resync for My Dukaan succeeded \n Success Brand :: {success_names} \n Fail Brand :: {fail_names},\n started_at :: {start_time}.'
        mail_type = 'resync_success'
        
    except Exception as e:
        mail_text = f'Resync for My Dukaan failed with an error {e}'
        mail_type = 'resync_failure'
        logger.exception(e)
    
    finally:
        send_post_resync_confirmation_email.delay('My Dukaan',mail_text,mail_type)

@app.task(queue='celery_periodic')
def update_mydukaan_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.mydukaan_service.tasks import update_mydukaan_order_status
    update_mydukaan_order_status.delay()
    '''
    if IS_BETA:
        return

    try:
        print('task started')
        dukaan_inst = MyDukaanImpl()
        dukaan_inst.update_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for MyDukaan failed with an error {e}')
