from .view_impl import fetch_cashfree_payment_response,fetch_cashfree_notify_url_response
from django.urls import path

urlpatterns = [
    path('fetch_cashfree_payment_response',fetch_cashfree_payment_response, name="fetch_cashfree_payment_response" ),
    path('get_cashfree_notify_url_response',fetch_cashfree_notify_url_response,name='get_cashfree_notify_url_response')
]
