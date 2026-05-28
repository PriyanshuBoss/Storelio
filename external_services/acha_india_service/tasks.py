from saleor.celeryconf import app
from saleor.external_services.acha_india_service.acha_india_impl import AchaIndiaImpl
import logging
logger = logging.getLogger(__name__)
from saleor.settings import IS_BETA

@app.task(queue='onboarding_queue')
def initiate_product_onboarding_acha_india():
    try:
        acha_india_impl_inst = AchaIndiaImpl()

        store_insert_res = acha_india_impl_inst.insert_store_data_from_acha_india_store()
        shop = store_insert_res.get('shop')

        if not shop:
            logger.exception('Shop Info Fetching Failed for Acha India Onboarding')
            return

        acha_india_impl_inst.create_brand_from_AchaIndia(shop)
        acha_india_impl_inst.insert_product_data_from_acha_india_store(shop)

        if IS_BETA:
            acha_india_impl_inst.create_product_from_AchaIndia(shop)
    
    except Exception as e:
        logger.exception(f"Error in Acha India onboarding: {e}")
