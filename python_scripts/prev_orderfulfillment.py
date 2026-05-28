from saleor.order.order_complete import OrderEngine
from saleor.order.models import Order
from saleor.order import OrderStatus
import datetime 
from saleor.graphql.api import schema
from saleor.warehouse.availability import get_default_warehouse_id
from saleor.warehouse.models import Allocation

def prev_order_fulfillment():
    end_date = datetime.datetime.today()
    start_data = datetime.date(2022,1,4)

    warehouse_id = get_default_warehouse_id()

    unfulfilled_orders = Order.objects.filter(status=OrderStatus.UNFULFILLED,created__range=[start_data,end_date])
    order_engine_instance = OrderEngine()
    for order in unfulfilled_orders:
        try:
            print(f'creating fulfillment for order with id {order.id}')
            response_list = order_engine_instance.create_fulfillment_order(order,schema,warehouse_id,None)
        except Exception as e:
            print(order.id)
            print(e)

prev_order_fulfillment()


#COMMAND TO RUN THIS SCRIPT

# from saleor.python_scripts import prev_orderfulfillment
