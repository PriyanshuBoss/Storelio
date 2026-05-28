import time
from saleor.celeryconf import app
from saleor.external_services.integrations.tasks import send_post_resync_confirmation_email
from saleor.external_services.wix.wix_impl import WixImpl
import logging
from celery import group, chain
from saleor.external_services import gen_chunks
from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
logger = logging.getLogger(__name__)

@app.task(queue='onboarding_queue')
def initiate_product_onboarding_wix(store_data):
    try:
        wix_impl_inst = WixImpl()
        wix_impl_inst.set_instance_id(store_data.get('instance_id'))
        
        wix_impl_inst.set_refresh_token(store_data.get('refresh_token'))
        wix_impl_inst.create_brand_from_wix(store_data)
        wix_impl_inst.insert_product_data_from_wix_store(store_data.get('store_name'))

        if IS_BETA:
            wix_impl_inst.create_product_from_Wix(store_data)
    
    except Exception as e:
        logger.exception(f"Error in Wix onboarding: {e}")
        
@app.task(queue='onboarding_queue')
def product_created_webhook(product_data,instance_id):
    try:
        wix_impl_inst = WixImpl()
        wix_impl_inst.set_instance_id(instance_id)
        wix_impl_inst.add_new_product_from_webhook(product_data)
    
    except Exception as e:
        logger.exception(f"Error in Wix create webhook: {e}")


@app.task(queue='onboarding_queue')
def product_deleted_webhook(product_data,instance_id):
    try:
        wix_impl_inst = WixImpl()
        wix_impl_inst.set_instance_id(instance_id)
        wix_impl_inst.delete_product_from_webhook(product_data)
    
    except Exception as e:
        logger.exception(f"Error in wix delete webhook: {e}")

@app.task(queue='onboarding_queue')
def product_updated_webhook(product_data,instance_id):
    try:
        wix_impl_inst = WixImpl()
        wix_impl_inst.set_instance_id(instance_id)
        wix_impl_inst.update_product_from_webhook(product_data)
    
    except Exception as e:
        logger.exception(f"Error in wix update webhook: {e}")

@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_wix():
    '''
    To Run in shell: 

    from saleor.external_services.wix.tasks import resync_price_inventory_in_mongo_wix
    resync_price_inventory_in_mongo_wix.delay()
    '''
    
    if IS_BETA:
        return
        
    try:
        
        wix_impl = WixImpl()
        brand_ids = wix_impl.get_brand_ids_for_resync()
        resync_task = group(resync_price_inventory_in_mongo_wix_for_chunks.si(tuple(chunked_brand_id)) for chunked_brand_id in gen_chunks(brand_ids,chunksize=50))

        return resync_task()
        
    except Exception as e:
        mail_text = f'Resync for wix failed with an error {e}'
        mail_type = 'resync_failure'
        send_post_resync_confirmation_email.delay('Wix',mail_text,mail_type)
        logger.exception(e)

@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_wix_for_chunks(brand_ids):
    '''
    To Run in shell: 

    from saleor.external_services.wix.tasks import resync_price_inventory_in_mongo_wix_for_chunks
    resync_price_inventory_in_mongo_wix_for_chunks.delay()
    '''
    
    if IS_BETA:
        return
        
    try:

        wix_impl = WixImpl()

        wix_impl.resync_price_and_inventory(brand_ids)
        
    except Exception as e:
        mail_text = f'Resync for wix failed with an error {e}, for brand_ids: {brand_ids}'
        mail_type = 'resync_failure'
        logger.exception(e)
        send_post_resync_confirmation_email.delay('wix',mail_text,mail_type)


@app.task(queue='onboarding_queue')
def order_updated_webhook(order_data,instance_id):
    try:
        wix_impl_inst = WixImpl()
        wix_impl_inst.set_instance_id(instance_id)
        wix_impl_inst.update_order_status_from_webhook(order_data)
    
    except Exception as e:
        logger.exception(f"Error in wix delete webhook: {e}")

@app.task(queue='onboarding_queue')
def update_wix_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.wix.tasks import update_wix_order_status
    update_wix_order_status.delay()
    '''
    if IS_BETA:
        return

    try:
        print('task started')
        woo_inst = WixImpl()
        woo_inst.update_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for wix failed with an error {e}')
