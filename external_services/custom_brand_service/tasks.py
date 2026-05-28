
from saleor.celeryconf import app
import logging
from saleor.external_services.style_stree_service.tasks import resync_price_inventory_in_mongo_stylestree, update_stylestree_order_status
from saleor.external_services.the_souled_store_service.tasks import resync_price_inventory_in_mongo_souledstore, update_souledstore_order_status
from saleor.settings import IS_BETA
logger = logging.getLogger(__name__)

@app.task(queue='celery_periodic')
def update_custom_order_status():
    '''
    To Run in shell: 

    from saleor.external_services.custom_brand_service.tasks import update_custom_order_status
    update_custom_order_status.delay()
    '''
    if IS_BETA:
        return

    try:
        update_stylestree_order_status()
        update_souledstore_order_status()
        
    except Exception as e:
        logger.exception(f'order status update for Custom failed with an error {e}')

@app.task(queue='celery_periodic')
def resync_price_inventory_in_mongo_custom():
    
    if IS_BETA:
        return

    try:
        resync_price_inventory_in_mongo_stylestree()
        resync_price_inventory_in_mongo_souledstore()
        
    except Exception as e:
        logger.exception(f'order status update for Custom failed with an error {e}')