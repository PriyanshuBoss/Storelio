from ..celeryconf import app
from saleor.external_services.messaging.messaging_impl import MessagingImpl
from saleor.order.models import Order


@app.task
def send_sms_for_order_confirmation(order_id):
    try:
        order_instance = Order.objects.get(pk=order_id)
    except:
        order_instance = None

    if order_instance:
        user_mobile_number = order_instance.user.mobile_no
        store_url = "https://zaamo.co/zaamo"
        my_orders_url = f"{store_url}/account/my-orders"
    
    if user_mobile_number:
        MessagingImpl.send_message_for_order_confirmation(user_mobile_number, my_orders_url)

