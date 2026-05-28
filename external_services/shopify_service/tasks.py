
import time
from saleor.celeryconf import app
from saleor.external_services.integrations.tasks import send_post_resync_confirmation_email
from saleor.external_services import gen_chunks
from saleor.settings import IS_BETA, RESTRICT_MANAUL_SHOPIY_ORDER
from saleor.utilities.string_utilities import StringUtilities
from celery import group, chain
from saleor.utilities.time_utilities import TimeUtilities
from .shopify_impl import ShopifyImpl, ZaamoShopifyImpl
import logging
logger = logging.getLogger(__name__)

@app.task(queue='priority_queue')
def initiate_product_onboarding_shopify(store_credentials):
    try:
        shopify_impl_inst = ShopifyImpl(store_credentials)
        shop = shopify_impl_inst.get_current_shop_obj()

        shopify_impl_inst.create_brand_from_shopify(shop,store_credentials)
        shopify_impl_inst.insert_product_data_from_shopify_store(shop)
        if IS_BETA:
            shopify_impl_inst.create_products_in_shopify(shop)
    
    except Exception as e:
        logger.exception(f"Error in shopify onboarding: {e}")

@app.task(queue='onboarding_queue')
def product_create_webhook(product_id, url):
    try:
        shopify_impl = ShopifyImpl()
        shopify_impl.add_new_product_to_store_from_webhook(product_id, url)
    
    except Exception as e:
        logger.exception(f"Error in shopify create webhook: {e}, url :: {url}")

@app.task(queue='onboarding_queue')
def product_update_webhook(product_id, url):
    try:
        shopify_impl = ShopifyImpl()
        shopify_impl.update_product_from_webhook(product_id, url)
        
    except Exception as e:
        logger.exception(f"Error in shopify update webhook: {e}, url :: {url}")
    
@app.task(queue='onboarding_queue')
def product_delete_webhook(product_id, url):
    try:
        shopify_impl = ShopifyImpl()
        shopify_impl.delete_product_from_webhook_response(product_id, url)
    
    except Exception as e:
        logger.exception(f"Error in shopify delete webhook: {e}, url :: {url}")


@app.task(queue='celery_periodic')
def resync_price_inventory_failed_in_mongo_shopify():
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import resync_price_inventory_failed_in_mongo_shopify
    resync_price_inventory_failed_in_mongo_shopify.delay()
    '''
    if IS_BETA:
        return

    try:
        shopify_impl = ShopifyImpl()
        brand_ids = shopify_impl.get_brand_ids_for_resync_failed()
        
        resync_task = chain(resync_price_inventory_in_mongo_shopify_for_chunks.si(tuple(chunked_brand_id)) for chunked_brand_id in gen_chunks(brand_ids,chunksize=40))
        
        return resync_task()
        
    except Exception as e:
        mail_text = f'Resync for Shopify failed with an error {e}'
        mail_type = 'resync_failure'
        send_post_resync_confirmation_email.delay('Shopify',mail_text,mail_type)
        logger.exception(e)

@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_shopify():
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import resync_price_inventory_in_mongo_shopify
    resync_price_inventory_in_mongo_shopify.delay()
    '''
    if IS_BETA:
        return

    try:
        shopify_impl = ShopifyImpl()
        brand_ids = shopify_impl.get_brand_ids_for_resync()
        
        resync_task = group(resync_price_inventory_in_mongo_shopify_for_chunks.si(tuple(chunked_brand_id)) for chunked_brand_id in gen_chunks(brand_ids,chunksize=60))
        
        return resync_task()
        
    except Exception as e:
        mail_text = f'Resync for Shopify failed with an error {e}'
        mail_type = 'resync_failure'
        send_post_resync_confirmation_email.delay('Shopify',mail_text,mail_type)
        logger.exception(e)
        
@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_shopify_for_chunks(brand_ids):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import resync_price_inventory_in_mongo_shopify_for_chunks
    resync_price_inventory_in_mongo_shopify_for_chunks.delay(brand_ids)
    '''
    if IS_BETA:
        return
    
    try:
        shopify_impl = ShopifyImpl()
        shopify_impl.resync_price_and_inventory(brand_ids)
        
    except Exception as e:
        mail_text = f'Resync for Shopify failed with an error {e}, for brand_ids: {brand_ids}'
        mail_type = 'resync_failure'
        send_post_resync_confirmation_email.delay('Shopify',mail_text,mail_type)
        logger.exception(e)

@app.task(queue='onboarding_queue')
def order_update_webhook(order_id, url):
    try:
        shopify_impl = ShopifyImpl()
        shopify_impl.update_order_from_webhook(order_id, url)
        
    except Exception as e:
        logger.exception(f"Error in shopify order update webhook: {e}, url :: {url}")

@app.task(queue='priority_queue')
def order_create_webhook(order_id, url):
    try:
        shopify_impl = ZaamoShopifyImpl()
        shopify_impl.create_order_from_webhook(order_id)
        
    except Exception as e:
        logger.exception(f"Error in shopify order create webhook: {e}, url :: {url}")

@app.task(queue='celery_periodic')
def update_shopify_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import update_shopify_order_status
    update_shopify_order_status.delay()
    '''
    if IS_BETA:
        return

    try:
        print('task started')
        sh_inst = ShopifyImpl()
        sh_inst.update_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for Shopify failed with an error {e}')

@app.task(queue='celery_periodic')
def create_manual_order_for_zaamo():
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import create_manual_order_for_zaamo
    create_manual_order_for_zaamo.delay()
    '''
    if IS_BETA:
        return

    if RESTRICT_MANAUL_SHOPIY_ORDER:
        return

    try:
        print('task started')
        sh_inst = ZaamoShopifyImpl()
        sh_inst.manual_create_order_for_zaamo()
        
    except Exception as e:
        logger.exception(f'order status update for Shopify failed with an error {e}')


@app.task(queue='priority_queue')
def push_product_to_shopify_task(product_id,category_name):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import push_product_to_shopify_task
    push_product_to_shopify_task.delay(product,category_name)
    '''
    zaamo_shopify_inst = ZaamoShopifyImpl()
    zaamo_shopify_inst.push_product_to_shopify(product_id,category_name)


@app.task(queue='priority_queue')
def update_product_status_shopify_task(product_id_brand,status,product_zaamo_id):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import update_product_status_shopify_task
    update_product_status_shopify_task.delay(product,status)
    '''
    zaamo_shopify_inst = ZaamoShopifyImpl()
    zaamo_shopify_inst.update_product_status_shopify(product_id_brand,status,product_zaamo_id)


@app.task(queue='priority_queue')
def update_product_status_shopify_product_zaamo_task(product_id,status):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import update_product_status_shopify_product_zaamo_task
    update_product_status_shopify_product_zaamo_task.delay(product_id,status)
    '''
    zaamo_shopify_inst = ZaamoShopifyImpl()
    zaamo_shopify_inst.update_product_status_shopify_product_zaamo(product_id,status)


@app.task(queue='celery_periodic')
def resync_price_and_inventory_for_zaamo_shopify(celery=1):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import resync_price_and_inventory_for_zaamo_shopify
    resync_price_and_inventory_for_zaamo_shopify.delay()
    '''
    if IS_BETA:
        return

    try:
        t = time.time()
        print('task started')
        sh_inst = ZaamoShopifyImpl()
        product_list = sh_inst.fetch_product_list_to_resync_zaamo_shopify(celery)
        
        sh_inst.resync_price_inventory_for_zaamo_shopify(product_list)
        print(f'task Completed in {time.time()-t}')
        
    except Exception as e:
        logger.exception(f'Resync for zaamo shopify failed with error :: {e}')



@app.task(queue='priority_queue')
def resync_price_and_inventory_for_zaamo_shopify_for_step_price_update(product_id_list=list()):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import resync_price_and_inventory_for_zaamo_shopify_for_step_price_update
    resync_price_and_inventory_for_zaamo_shopify_for_step_price_update.delay()
    '''
    if IS_BETA:
        return

    try:
        print('task started')
        sh_inst = ZaamoShopifyImpl()
        sh_inst.resync_price_inventory_for_zaamo_shopify(product_id_list)
        
    except Exception as e:
        logger.exception(f'Resync for zaamo shopify failed with error :: {e}')


@app.task(queue='priority_queue')
def change_product_status_with_brand_status_task(brand_id):
    '''
    To Run in shell: 

    from saleor.external_services.shopify_service.tasks import change_product_status_with_brand_status_task
    change_product_status_with_brand_status_task.delay()
    '''
    if IS_BETA:
        return

    try:
        print('task started')
        sh_inst = ZaamoShopifyImpl()
        sh_inst.change_product_status_with_brand_status(brand_id)
        
    except Exception as e:
        logger.exception(f'change_product_status_with_brand_status_task failed with error :: {e}')
