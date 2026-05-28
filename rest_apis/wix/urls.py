from .view_impl import order_updated_webhook, redirect_to_installer,wix_onboarding,product_created_webhook,product_updated_webhook,product_deleted_webhook
from django.urls import path

urlpatterns = [
    path('installer', redirect_to_installer, name="redirect_to_installer"),
    path('onboarding', wix_onboarding, name="wix_onboarding"),
    path('webhooks/product_created', product_created_webhook, name="product_created"),
    path('webhooks/product_updated', product_updated_webhook, name="product_updated"),
    path('webhooks/product_deleted', product_deleted_webhook, name="product_deleted"),
    path('webhooks/order_updated', order_updated_webhook, name="order_updated"),
    
]
