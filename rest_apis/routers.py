from rest_framework import routers
from saleor.rest_apis.zaamo_integration.views import  InventoryUpdateViewSet, OrderStatusUpdate, UploadBrandImageViewSet, UploadGroupingImageViewSet,UploadVoucherImageViewSet
from saleor.rest_apis.zaamo_integration.oms_guru.views import CustomInventoryUpdateViewSet, AuthAppTokenGenerationViewSet, OmsGuruEmptyListResponse, OmsGuruEmptyListwitherrorResponse, OmsGuruEmptyResponse, OmsGuruStringResponse, ProductCatalogueViewSet

class ZaamoRouter(routers.DefaultRouter):
    def __init__(self):
        super().__init__()
        self.trailing_slash = '/?'


router = ZaamoRouter()

router.register(r'zaamo_integration/update_inventory', InventoryUpdateViewSet, basename='update_inventory')
router.register(r'zaamo_integration/upload_brand_image', UploadBrandImageViewSet, basename = 'upload_brand_image')
router.register(r'zaamo_integration/upload_grouping_image', UploadGroupingImageViewSet, basename = 'upload_grouping_image')
router.register(r'zaamo_integration/order_status_update', OrderStatusUpdate, basename = 'order_status_update')
router.register(r'zaamo_integration/upload_voucher_image', UploadVoucherImageViewSet,basename='upload_voucher_image')
router.register(r'zaamo_integration/oms_guru/inventory', CustomInventoryUpdateViewSet, basename='update_inventory') 
router.register(r'zaamo_integration/oms_guru/auth', AuthAppTokenGenerationViewSet , basename = 'auth')
router.register(r'zaamo_integration/oms_guru/catalogue', ProductCatalogueViewSet , basename = 'catalogue')
router.register(r'zaamo_integration/oms_guru/order', OmsGuruEmptyResponse , basename = 'order')
router.register(r'zaamo_integration/oms_guru/orders', OmsGuruEmptyListResponse, basename='orders') 
router.register(r'zaamo_integration/oms_guru/acknowledge', OmsGuruEmptyListwitherrorResponse , basename = 'acknowledge')
router.register(r'zaamo_integration/oms_guru/pack_orders', OmsGuruEmptyListwitherrorResponse , basename = 'pack_orders')
router.register(r'zaamo_integration/oms_guru/labels', OmsGuruStringResponse, basename='labels') 
router.register(r'zaamo_integration/oms_guru/invoices', OmsGuruStringResponse , basename = 'invoices')
router.register(r'zaamo_integration/oms_guru/dispatch_orders', OmsGuruEmptyListwitherrorResponse , basename = 'dispatch_orders')
router.register(r'zaamo_integration/oms_guru/self_ship_dispatch_orders', OmsGuruEmptyListwitherrorResponse, basename='self_ship_dispatch_orders') 
router.register(r'zaamo_integration/oms_guru/update_self_ship_orders', OmsGuruEmptyListwitherrorResponse , basename = 'update_self_ship_orders')
router.register(r'zaamo_integration/oms_guru/return_orders', OmsGuruEmptyListResponse , basename = 'return_orders')
router.register(r'zaamo_integration/oms_guru/cancelled_orders', OmsGuruEmptyListResponse, basename='cancelled_orders') 
router.register(r'zaamo_integration/oms_guru/pushOrder', OmsGuruEmptyListwitherrorResponse , basename = 'pushOrder')
router.register(r'zaamo_integration/oms_guru/pushOrderStatus', OmsGuruEmptyListwitherrorResponse , basename = 'pushOrderStatus')
