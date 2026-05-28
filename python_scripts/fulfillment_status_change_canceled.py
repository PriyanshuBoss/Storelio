from saleor.order import models
from saleor.order import FulfillmentStatus

def func():

   fulfillments = models.Fulfillment.objects.filter(status='canceled')

   for fulfillment in fulfillments:
       fulfillment.status = FulfillmentStatus.CANCELLATION_INITIATED
       fulfillment.save()



func()
print("Script completed")

#COMMAND TO RUN THIS SCRIPT

# from saleor.python_scripts import fulfillment_status_change_canceled
