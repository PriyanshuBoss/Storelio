from saleor.rest_apis.unicommerce_integration.views import AuthTokenGenerationViewSet,GetProductCountViewSet,GetProductsViewSet,UpdateInventoryViewSet,PostOrderDispatchViewSet,PostStatusNotificationViewSet,GetOrderStatusViewSet,PostOrderCancelViewSet, GetAddressByMobileViewSet
from django.urls import path

urlpatterns = [
    path('authToken', AuthTokenGenerationViewSet.as_view({'get':'list'}), name="authToken"),
    path('productsCount', GetProductCountViewSet.as_view({'get':'list'}), name="productsCount"),
    path('products', GetProductsViewSet.as_view({'get':'list'}), name="products"),
    path('updateInventory', UpdateInventoryViewSet.as_view({'post':'create'}), name="updateInventory"),
    path('orders/dispatch',PostOrderDispatchViewSet.as_view({'post':'create'}),name="order_dispatch"),
    path('order/<int:order_id>',PostStatusNotificationViewSet.as_view({'post':'create'}),name="status notification"),
    path('orders',GetOrderStatusViewSet.as_view({'get':'list'}),name="orders"),
    path('orders/cancel',PostOrderCancelViewSet.as_view({'post':'create'}),name="orders_cancel"),
    path('fetch/address',GetAddressByMobileViewSet.as_view({'get':'list'}),name='get_address')
]

