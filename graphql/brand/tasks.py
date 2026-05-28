import logging
from django.conf import settings
from saleor.celeryconf import app
from saleor.utilities.api_client import ApiClient
from saleor.brand.models import Brand
from saleor.brand.states import BrandStatusEnum
from saleor.product.models import Product
import graphene

logger = logging.getLogger(__name__)

@app.task(queue='onboarding_queue')
def explore_content_sync(brand_id: int=None, product_id: int=None):

    try:
        body = dict()
        if brand_id:
            brand_status = Brand.objects.filter(id=brand_id).values_list('status', flat=True)[0]
            body = {
                'brand_ids': [graphene.Node.to_global_id('Brand', brand_id)],
                'brand_status': 1 if brand_status == BrandStatusEnum.ACTIVE else 0
            }

        if product_id:
            is_published = Product.objects.filter(id=product_id).values_list('is_published', flat=True)[0]
            body = {
                'product_ids': [graphene.Node.to_global_id('Product', product_id)],
                'product_status': 1 if is_published == True else 0
            }
        
        if body:
            _url = settings.CONTENT_SERVICE_URL + '/streaming/api/explore/product/sync/'
            token = settings.CONTENT_SERVICE_TOKEN
            api_client = ApiClient(url=_url)
            api_client.add_header('SERVICE-TOKEN', token)
            api_client.body = body
            api_client.post(timeout=5)
            res = api_client.fetch_response()
            logger.info(f"explore_content_sync body: {body} response: {res}")

    except Exception as e:
        logger.info(f"explore_content_sync: {e}")
