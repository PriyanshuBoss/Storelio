import logging
from django.db.models import Q
from saleor.celeryconf import app
from saleor.product.models import ProductVariant
from saleor.settings import IS_BETA, FB_CATALOG_CREDENTIALS
from saleor.utilities.time_utilities import TimeUtilities
from .instagram_shop_manager import CatalogManager

logger = logging.getLogger(__name__)

@app.task(queue='celery_periodic')
def catalog_update_product_status_and_inventory():
    
    if IS_BETA:
        return
    
    now = TimeUtilities.get_current_date_time()
    last_4_hour = TimeUtilities.subtract_time_from_timestamp(now, hours=24, minutes=5)
    queryset = ProductVariant.objects.filter(Q(updated_at__gt=last_4_hour) | Q(track_inventory=True, stocks__updated_at__gt=last_4_hour))
    logger.info(f'updating product status in catalog, count: {queryset.count()}')
    for catalog_id, access_token in FB_CATALOG_CREDENTIALS.items():
        catalog_manager = CatalogManager(catalog_id, access_token)
        catalog_manager.update_product_status(queryset)

@app.task(queue='priority_queue')
def catalog_update_brand_status(brand_ids: list):
    queryset = ProductVariant.objects.filter(product__brand_id__in=brand_ids)
    logger.info(f'catalog updating brand status, count: {queryset.count()}, brand_ids: {brand_ids}')
    for catalog_id, access_token in FB_CATALOG_CREDENTIALS.items():
        catalog_manager = CatalogManager(catalog_id, access_token)
        catalog_manager.update_product_status(queryset)
