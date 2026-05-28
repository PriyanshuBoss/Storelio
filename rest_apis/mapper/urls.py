from .view_impl import fetch_store_id_by_host, fetch_store_id_by_slug, fetch_store_id_by_user,fetch_product_id_from_brand_product_id
from django.urls import path

urlpatterns = [
    path('fetch_store_by_slug', fetch_store_id_by_slug, name="fetch_store_id_by_slug"),
    path('fetch_store_id_by_user', fetch_store_id_by_user, name="fetch_store_id_by_user"),
    path('fetch_store_by_host', fetch_store_id_by_host, name="fetch_store_id_by_host"),
    path('fetch_product_id_from_brand_product_id', fetch_product_id_from_brand_product_id, name="fetch_product_id_from_brand_product_id"),
]
