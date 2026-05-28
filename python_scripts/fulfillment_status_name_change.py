from saleor.order import models
from saleor.order import FulfillmentStatus

def func():

   fulfillments = models.Fulfillment.objects.filter(status='received')

   for fulfillment in fulfillments:
       fulfillment.status = FulfillmentStatus.PLACED
       fulfillment.save()



func()
print("Script completed")

#COMMAND TO RUN THIS SCRIPT

# from saleor.python_scripts import fulfillment_status_name_change
