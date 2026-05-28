from .views import fetch_razorpay_payment_response, payment_captured_webhook
from django.urls import path

urlpatterns = [
    path('fetch_razorpay_payment_response',fetch_razorpay_payment_response, name="fetch_razorpay_payment_response" ),
    path('payment_captured_webhook',payment_captured_webhook,name='payment_captured_webhook')
]
