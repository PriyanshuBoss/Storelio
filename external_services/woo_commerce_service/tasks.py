import time
from saleor.celeryconf import app
from saleor.external_services.integrations.tasks import send_post_resync_confirmation_email
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
import logging
from celery import group, chain
from saleor.external_services import gen_chunks
from saleor.settings import IS_BETA
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
logger = logging.getLogger(__name__)

@app.task(queue='priority_queue')
def initiate_product_onboarding_woo_commerce(shop):
    try:
        woocommerce_impl_inst = WooCommerceImpl(shop['store_url'])
        
        woocommerce_impl_inst.set_authtoken(shop['auth_token'])
        woocommerce_impl_inst.create_brand_from_WooCommerce(shop)
        woocommerce_impl_inst.insert_product_data_from_woo_commerce_store(shop['name'])
        if IS_BETA:
            woocommerce_impl_inst.create_product_from_WooCommerce(shop)
    
    except Exception as e:
        logger.exception(f"Error in Woocommerce onboarding: {e}")

@app.task(queue='onboarding_queue')
def product_create_webhook(data,url):
    try:
        woocommerce_impl_inst = WooCommerceImpl(url)
        token = woocommerce_impl_inst.get_auth_token(store_url=url)
        
        if token:
            woocommerce_impl_inst.set_authtoken(token)
            woocommerce_impl_inst.add_new_product_to_store_from_webhook(data)
    
    except Exception as e:
        logger.exception(f"Error in Woocommerce create webhook: {e}, url :: {url}")

@app.task(queue='onboarding_queue')
def product_update_webhook(data,url):
    try:
        woocommerce_impl_inst = WooCommerceImpl(url)
        token = woocommerce_impl_inst.get_auth_token(store_url=url)
        
        if token:
            woocommerce_impl_inst.set_authtoken(token)
            woocommerce_impl_inst.update_product_to_store_from_webhook(data)
    
    except Exception as e:
        logger.exception(f"Error in Woocommerce update webhook: {e}, url :: {url}")
    
@app.task(queue='onboarding_queue')
def product_delete_webhook(product_id,url):    
    try:
        woocommerce_impl_inst = WooCommerceImpl(url)
        token = woocommerce_impl_inst.get_auth_token(store_url=url)

        if token:
            woocommerce_impl_inst.set_authtoken(token)
            woocommerce_impl_inst.delete_product_from_store(product_id,url)
    
    except Exception as e:
        logger.exception(f"Error in Woocommerce delete webhook: {e}, url :: {url}")

@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_woo_commerce():
    '''
    To Run in shell: 

    from saleor.external_services.woo_commerce_service.tasks import resync_price_inventory_in_mongo_woo_commerce
    resync_price_inventory_in_mongo_woo_commerce.delay()
    '''
    
    if IS_BETA:
        return
        
    try:
        
        woocommerce_impl_inst = WooCommerceImpl()
        brand_ids = woocommerce_impl_inst.get_brand_ids_for_resync()
        resync_task = chain(resync_price_inventory_in_mongo_woo_commerce_for_chunks.si(tuple(chunked_brand_id)) for chunked_brand_id in gen_chunks(brand_ids,chunksize=20))

        return resync_task()
        
    except Exception as e:
        mail_text = f'Resync for Woo Commerce failed with an error {e}'
        mail_type = 'resync_failure'
        logger.exception(e)
        send_post_resync_confirmation_email.delay('Woo Commerce',mail_text,mail_type)


@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_woo_commerce_for_chunks(brand_ids):
    '''
    To Run in shell: 

    from saleor.external_services.woo_commerce_service.tasks import resync_price_inventory_in_mongo_woo_commerce_for_chunks
    resync_price_inventory_in_mongo_woo_commerce_for_chunks.delay()
    '''
    
    if IS_BETA:
        return
        
    try:
        
        woocommerce_impl_inst = WooCommerceImpl()
        woocommerce_impl_inst.resync_price_and_inventory(brand_ids)
        
    except Exception as e:
        mail_text = f'Resync for Woo Commerce failed with an error {e}, for brand_ids: {brand_ids}'
        mail_type = 'resync_failure'
        logger.exception(e)
        send_post_resync_confirmation_email.delay('Woo Commerce',mail_text,mail_type)


@app.task(queue='onboarding_queue')
def order_update_webhook(order_data,url):
    try:
        woocommerce_impl_inst = WooCommerceImpl(url)
        woocommerce_impl_inst.update_order_status_from_webhook(order_data,url)
    
    except Exception as e:
        logger.exception(f"Error in Woocommerce Order update webhook: {e}, url :: {url}")
    

@app.task(queue='celery_periodic')
def update_woocommerce_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.woo_commerce_service.tasks import update_woocommerce_order_status
    update_woocommerce_order_status.delay()
    '''
    if IS_BETA:
        return

    try:
        print('task started')
        woo_inst = WooCommerceImpl()
        woo_inst.update_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for WooCommerce failed with an error {e}')
