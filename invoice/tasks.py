from saleor.celeryconf import app
import logging
import re
from django.db.models import Q

from saleor.invoice.helper import create_invoice_for_brands

logger = logging.getLogger(__name__)

@app.task
def create_invoice_for_brands_task(brand_id,start_date=None,end_date=None,email=''):
    '''
from saleor.invoice.tasks import create_invoice_for_brands_task
create_invoice_for_brands_task()
    '''
    try:
        create_invoice_for_brands(brand_id,start_date,end_date,email)
    except Exception as e:
        logger.exception(
        "Exception while generating pdf", e
    )
