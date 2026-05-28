import requests
from django.core.files.uploadedfile import SimpleUploadedFile
import logging

from saleor.celeryconf import app
from saleor.external_services.google_analytics.ga_impl import GoogleAnalyticsImpl
from saleor.store.store_analytics import SavedStoreAnalytics
from saleor.utilities.selenium_utilities import LinktreeCrawl
from saleor.store.models import Linktree
from saleor.store.states import LinktreeType
from saleor.utilities.time_utilities import TimeUtilities
from saleor.settings import IS_BETA

logger = logging.getLogger(__name__)

@app.task(queue='celery_periodic')
def save_past_store_analytics():
    
    if IS_BETA:
        return
    
    SavedStoreAnalytics().handle()

@app.task(queue='priority_queue')
def crawl_linktree(store_id, linktree_link):

    # if IS_BETA:
    #     return
    logger.info(f"linktree crawl:: store_id {store_id} :: {linktree_link} :: starting...")
    rows = LinktreeCrawl.start(linktree_link)
    logger.info(f"linktree crawl:: saving data...")

    for row in rows:
        image = None
        if row.get('img_src'):
            img = requests.get(row.get('img_src'))
            if img.ok:
                content_type = img.headers.get('Content-Type', 'image/jpeg')

                image_name = f"{store_id}_{TimeUtilities.current_time_in_milliseconds()}.jpg"
                if row.get('type') == LinktreeType.LINKTREE:
                    image_name = f"linktree/profile_{store_id}.jpg"
                
                image = SimpleUploadedFile(image_name, img.content, content_type)
        
        lt, created = Linktree.objects.get_or_create(store_id=store_id, type=row.get('type'), url=row.get('link'), text=row.get('title'))
        if image:
            if not created and lt.image and not 'social_icons/' in lt.image:
                try:
                    lt.image.delete()
                except Exception as e:
                    pass
            lt.image = image
            lt.save()
    
    logger.info(f"linktree crawl:: store_id {store_id} :: {linktree_link} :: finished")

