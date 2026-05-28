import logging
from django.db.models import Q, F
from saleor.settings import IS_BETA
from saleor.celeryconf import app
from saleor.utilities.time_utilities import TimeUtilities
from saleor.product.models import ProductVariant
from .gm_manager import GoogleMerchant


logger = logging.getLogger(__name__)

@app.task(queue='celery_periodic')
def gm_update_catalog_products():
    
    if IS_BETA:
        return
    now = TimeUtilities.get_current_date_time()
    last_24_hour = TimeUtilities.subtract_time_from_timestamp(now, hours=24, minutes=5)
    queryset = ProductVariant.objects.filter(Q(updated_at__gt=last_24_hour) | Q(track_inventory=True, stocks__updated_at__gt=last_24_hour))\
                .filter(product__default_variant=F('id'))
    logger.info(f'gm updating products, count: {queryset.count()}')
    gm = GoogleMerchant()
    gm.update_products(queryset)

@app.task(queue='priority_queue')
def gm_update_catalog_brand_status(brand_ids: list):
    
    if IS_BETA:
        return
    
    queryset = ProductVariant.objects.filter(product__brand_id__in=brand_ids).filter(product__default_variant=F('id'))
    logger.info(f'gm catalog updating brand status, count: {queryset.count()}, brand_ids: {brand_ids}')
    gm = GoogleMerchant()
    gm.update_products(queryset)

