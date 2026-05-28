import time
from saleor.celeryconf import app
from saleor.external_services.the_souled_store_service.the_souled_store_impl import TheSouledStoreImpl
import logging
from saleor.external_services.integrations.tasks import send_post_resync_confirmation_email

from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
logger = logging.getLogger(__name__)

@app.task(queue='onboarding_queue')
def initiate_product_onboarding_souled_store(shop):
    try:
        custom_brand_impl_inst = TheSouledStoreImpl()
        
        custom_brand_impl_inst.create_brand_from_souled_store(shop)
        custom_brand_impl_inst.insert_product_data_from_souled_store_store(shop)
        if IS_BETA:
            custom_brand_impl_inst.create_product_from_souled_store(shop)
    
    except Exception as e:
        logger.exception(f"Error in custom_brand onboarding: {e}")


@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_souledstore():
    '''
    To Run in shell: 

    from saleor.external_services.the_souled_store_service.tasks import resync_price_inventory_in_mongo_souledstore
    resync_price_inventory_in_mongo_souledstore.delay()
    '''
    
    if IS_BETA:
        return
        
    try:
        start_time = StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())

        custom_impl_inst = TheSouledStoreImpl()
        fail_names, success_names = custom_impl_inst.resync_price_and_inventory()
        mail_text = f'Resync for souledstore Brands succeeded \n Success Brand :: {success_names} \n Fail Brand :: {fail_names},\n started_at :: {start_time}.'
        mail_type = 'resync_success'
        
    except Exception as e:
        mail_text = f'Resync for souledstore Brands failed with an error {e}'
        mail_type = 'resync_failure'
        logger.exception(e)
    
    finally:
        send_post_resync_confirmation_email.delay('souledstore Brand',mail_text,mail_type)

def update_souledstore_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.the_souled_store_service.tasks import update_souledstore_order_status
    update_souledstore_order_status()
    '''
    try:
        print('task started')
        custom_impl_inst = TheSouledStoreImpl()
        custom_impl_inst.update_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for souledstore failed with an error {e}')
