from saleor.celeryconf import app
import logging
from saleor.rest_apis.reels.helper import upload_and_check_shopify_media
from saleor.rest_apis.reels.helper import clean_product_data_details
logger = logging.getLogger(__name__)

@app.task(queue='priority_queue')
def upload_and_check_shopify_media_task(access_pass,url,g_id,media_url,store_name,reel_up_id):
    try:
        upload_and_check_shopify_media(access_pass,url,g_id,reel_up_id)
    except Exception as e:
        logger.exception(f"failure while uploading shopify media {e}, {access_pass},{url},{g_id},{media_url},{store_name}")


@app.task(queue='priority_queue')
def clean_product_data_details_task(shopify_product_id,shopify_store_name,mapping_ids):
    try:
        clean_product_data_details(shopify_product_id,shopify_store_name,mapping_ids)
    except Exception as e:
        logger.exception(f"failure while updating product details {e}")