from saleor.celeryconf import app
import logging
from .resolvers import create_product_from_pdp_mutation
logger = logging.getLogger(__name__)

@app.task(queue='priority_queue')
def create_product_for_pdp_mutations(data,category_id,commission,value_deal):
    try:
        create_product_from_pdp_mutation(data,category_id,commission,value_deal)
    except Exception as e:
        logger.info("Error:  %s", e)
