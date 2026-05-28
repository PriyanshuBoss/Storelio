from saleor.celeryconf import app
import logging
import re
from django.db.models import Q
from saleor.order.order_complete import OrderEngine
from saleor.order.models import Order
from saleor.graphql.order.mutations.fulfillments import UpdateFulfillment
from saleor.order.models import OrderLineCashgram,OrderLine
from saleor.order import RefundStatus,FulfillmentStatus
from saleor.external_services.cashgram import get_status_cashgram
from saleor.order.utils import update_brand_order_status
from saleor.product.models import SourcingRequest
from saleor.settings import IS_BETA

logger = logging.getLogger(__name__)

@app.task
def create_fulfillment_task(order_id,warehouse_id,store_id):
    order_engine_instance = OrderEngine()
    try:
        order_instance = Order.objects.filter(id=order_id).first()
        from saleor.graphql.api import schema
        all_responses = order_engine_instance.create_fulfillment_order(order_instance,schema,warehouse_id,store_id)
        save_fulfillment_status_in_orderline_metadata(order_instance)
        save_order_instance_in_sourcing_request_metadata(order_instance)
        logger.info(
        "fulfillment created for order-id %s with fulfillment response as :: %s  ", order_id, all_responses
    )
    except Exception as e:
        logger.exception(
        "Exception while creating fulfillments for order as  :: %s ", e
    )

def check_for_fulfillment_id(sourcing_request_ids, order_instance):
    sourcing_request_dict = SourcingRequest.objects.filter(
        id__in = sourcing_request_ids
    ).values('product_id', 'id')

    order_lines = order_instance.lines.all().values('fulfillment_line__fulfillment_id', 'variant__product_id')
    
    fulfillment_list = []

    for sourcing_request in sourcing_request_dict:

        for order_line in order_lines:

            if order_line.get('variant__product_id') == sourcing_request.get('product_id'):

                fulfillment_list.append(
                    {
                        'fulfillment_id' : order_line.get('fulfillment_line__fulfillment_id'),
                        'sourcing_request_id':  sourcing_request.get('id')
                    }    
                )

    return fulfillment_list

def save_order_instance_in_sourcing_request_metadata(order_instance):
    
    if order_instance.voucher is not None:
        voucher_code = order_instance.voucher.code

        if voucher_code is not None:

            if voucher_code.startswith('SZ_'):
                
                voucher_code = voucher_code.replace(" ", "")
                sourcing_request_ids = []
                for sourcing_id in voucher_code.split('_'):
                    if sourcing_id != 'SZ':
                        if not sourcing_id in sourcing_request_ids:
                            if sourcing_id.isnumeric():
                                sourcing_request_ids.append(re.sub(",","",sourcing_id))

                fulfillment_list = check_for_fulfillment_id(sourcing_request_ids, order_instance)

                for fulfillment in fulfillment_list:

                    SourcingRequest.objects.filter(id = fulfillment.get('sourcing_request_id')).update(
                        metadata = {
                            'order_id': order_instance.id,
                            'fulfillment_id': fulfillment.get('fulfillment_id')
                        }
                    )

def save_fulfillment_status_in_orderline_metadata(order_instance):
    fulfillments = order_instance.lines.all()\
        .values_list('fulfillment_line__fulfillment_id', 'fulfillment_line__fulfillment__status')

    for fulfillment_id, fulfillment_status in fulfillments:
        UpdateFulfillment.update_orderline_metadata(fulfillment_id, fulfillment_status)

def orderline_refund_func():

    orderline_cashgrams = OrderLineCashgram.objects.filter(refund_status = RefundStatus.REFUND_INITIATED)

    for orderline_cashgram in orderline_cashgrams:

        orderline = orderline_cashgram.orderline
        fulfillment_line = orderline.fulfillment_line.first()
        fulfillment = fulfillment_line.fulfillment
        orderline_id = orderline.id
        response = get_status_cashgram(orderline_id)
        if response.get('data'):
            status = response.get('data').get('cashgramStatus')
            
            if status=="FAILED" or status == "EXPIRED" :

                if status == "EXPIRED":
                    orderline_cashgram.refund_status = RefundStatus.REFUND_EXPIRED
                else:
                    orderline_cashgram.refund_status = RefundStatus.REFUND_FAILED
                orderline_cashgram.save()

            if status=="REDEEMED":
                if fulfillment.status == FulfillmentStatus.CANCELLATION_INITIATED:
                    fulfillment.status = FulfillmentStatus.CANCELLATION_PROCESSED
                
                if fulfillment.status == FulfillmentStatus.RETURN_INITIATED:
                    fulfillment.status = FulfillmentStatus.RETURN_COMPLETED

                fulfillment.save()

                orderline_cashgram.refund_status = RefundStatus.REFUND_TRANSFERRED

                orderline_cashgram.save()


@app.task(queue='celery_periodic')
def orderline_refund_status_update():

    if IS_BETA:
        return
    
    try:
        orderline_refund_func()
        
    except Exception as e:
        logger.exception(f'orderline refund status update failed with an error {e}')


@app.task(queue='celery_periodic')
def orderline_brand_order_status_update():
    '''
from saleor.order.tasks import orderline_brand_order_status_update
orderline_brand_order_status_update.delay()
    '''
    if IS_BETA:
        return
    
    try:
        orderlines = OrderLine.objects.filter(Q(metadata__status__isnull=True)|Q(metadata__status__in=['placed','inprocess']))
        update_brand_order_status(orderlines)
        
    except Exception as e:
        logger.exception(f'orderline brand order status update failed with an error {e}')


