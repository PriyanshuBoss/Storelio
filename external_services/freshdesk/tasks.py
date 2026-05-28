from saleor.celeryconf import app
import logging
import re
from saleor.external_services.freshdesk.freshdesk_impl import create_freshdesk_ticket_for_cancelled_orders, create_freshdesk_ticket_for_delayed_orders, create_freshdesk_ticket_for_top_order_users,create_fresh_desk_order_ticket_cod_order,create_freshdesk_ticket_for_initiate_purchases, update_tags_in_freshdesk_tickets
from saleor.settings import IS_BETA

logger = logging.getLogger(__name__)

@app.task(queue='celery_periodic')
def create_freshdesk_tickets_for_initiate_purchases():
    '''
    To run
    saleor.external_services.freshdesk.tasks import create_freshdesk_tickets_for_initiate_purchases
    create_freshdesk_tickets_for_initiate_purchases()
    '''
    if IS_BETA:
        return
    
    try:
        create_freshdesk_ticket_for_initiate_purchases()
        
    except Exception as e:
        logger.exception(f'create_freshdesk_tickets_for_initiate_purchases failed with an error {e}')


@app.task(queue='celery_periodic')
def create_freshdesk_ticket_for_delayed_orders_task():
    '''
    To run
    saleor.external_services.freshdesk.tasks import create_freshdesk_ticket_for_delayed_orders_task
    create_freshdesk_ticket_for_delayed_orders_task()
    '''
    if IS_BETA:
        return
    
    try:
        create_freshdesk_ticket_for_delayed_orders()
        
    except Exception as e:
        logger.exception(f'create_freshdesk_tickets_for_initiate_purchases failed with an error {e}')

@app.task
def create_freshdesk_ticket_for_cancelled_orders_task(fulfillment_id):
    '''
    To run
    saleor.external_services.freshdesk.tasks import create_freshdesk_ticket_for_cancelled_orders_task
    create_freshdesk_ticket_for_cancelled_orders_task()
    '''
    if IS_BETA:
        return
    
    try:
        create_freshdesk_ticket_for_cancelled_orders(fulfillment_id)
        
    except Exception as e:
        logger.exception(f'create_freshdesk_tickets_for_initiate_purchases failed with an error {e}')

@app.task(queue='celery_periodic')
def update_tags_in_freshdesk_tickets_task():
    '''
    To run
    from saleor.external_services.freshdesk.tasks import update_tags_in_freshdesk_tickets_task
    update_tags_in_freshdesk_tickets_task()
    '''
    if IS_BETA:
        return
    
    try:
        update_tags_in_freshdesk_tickets()
        
    except Exception as e:
        logger.exception(f'update_tags_in_freshdesk_tickets_task failed with an error {e}')


@app.task(queue='celery_periodic')
def create_freshdesk_tickets_for_top_order_users():
    '''
    To run
    saleor.external_services.freshdesk.tasks import create_freshdesk_tickets_for_top_order_users
    create_freshdesk_tickets_for_top_order_users()
    '''
    if IS_BETA:
        return
    
    try:
        create_freshdesk_ticket_for_top_order_users()
        
    except Exception as e:
        logger.exception(f'create_freshdesk_tickets_for_top_order_users failed with an error {e}')


@app.task
def create_fresh_desk_order_ticket_cod_order_task(order_id):
    '''
    To run
    from saleor.external_services.freshdesk.tasks import create_fresh_desk_order_ticket_cod_order_task
    create_fresh_desk_order_ticket_cod_order_task()
    '''
    if IS_BETA:
        return
    
    try:
        create_fresh_desk_order_ticket_cod_order(order_id)
        
    except Exception as e:
        logger.exception(f'create_freshdesk_tickets_for_top_order_users failed with an error {e}')

