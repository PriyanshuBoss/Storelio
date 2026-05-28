import time
from saleor.celeryconf import app
from saleor.external_services.style_stree_service.style_stree_impl import StyleStreeImpl
import logging
from saleor.external_services.integrations.tasks import send_post_resync_confirmation_email

from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
logger = logging.getLogger(__name__)

@app.task(queue='onboarding_queue')
def initiate_product_onboarding_style_stree(shop):
    try:
        stylestree_brand_impl_inst = StyleStreeImpl()
        
        stylestree_brand_impl_inst.create_brand_from_style_stree_brand(shop)
        stylestree_brand_impl_inst.insert_product_data_from_style_stree_brand_store(shop)
        if IS_BETA:
            stylestree_brand_impl_inst.create_product_from_style_stree_brand(shop)
    
    except Exception as e:
        logger.exception(f"Error in stylestree_brand onboarding: {e}")


@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_stylestree():
    '''
    To Run in shell: 

    from saleor.external_services.style_stree_service.tasks import resync_price_inventory_in_mongo_stylestree
    resync_price_inventory_in_mongo_stylestree.delay()
    '''
    
    if IS_BETA:
        return
        
    try:
        start_time = StringUtilities.convert_object_to_string(TimeUtilities.get_current_date_time())

        stylestree_impl_inst = StyleStreeImpl()
        fail_names, success_names = stylestree_impl_inst.resync_price_and_inventory()
        mail_text = f'Resync for stylestree Brands succeeded \n Success Brand :: {success_names} \n Fail Brand :: {fail_names},\n started_at :: {start_time}.'
        mail_type = 'resync_success'
        
    except Exception as e:
        mail_text = f'Resync for stylestree Brands failed with an error {e}'
        mail_type = 'resync_failure'
        logger.exception(e)
    
    finally:
        send_post_resync_confirmation_email.delay('stylestree Brand',mail_text,mail_type)

def update_stylestree_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.style_stree_service.tasks import update_stylestree_order_status
    update_stylestree_order_status()
    '''
    try:
        print('task started')
        stylestree_impl_inst = StyleStreeImpl()
        stylestree_impl_inst.update_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for StyleStree failed with an error {e}')
