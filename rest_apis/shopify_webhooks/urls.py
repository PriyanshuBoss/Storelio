from .view_impl import fulfillment_updated_webhook, order_updated_webhook, product_created_webhook, product_updated_webhook,product_deleted_webhook,zaamo_order_created_webhook
from django.urls import path

urlpatterns = [
    path('product_created', product_created_webhook, name="product_created_webhook"),
    path('product_updated', product_updated_webhook, name="product_updated_webhook"),
    path('product_deleted', product_deleted_webhook, name="product_deleted_webhook"),
    path('order_updated', order_updated_webhook, name="order_updated_webhook"),
    path('zaamo_order_created', zaamo_order_created_webhook, name="zaamo_order_created_webhook"),
    path('fulfillment_updated', fulfillment_updated_webhook, name="fulfillment_updated_webhook"),
]
