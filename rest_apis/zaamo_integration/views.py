from collections import defaultdict
from email.policy import default
import logging
import time
from rest_framework.response import Response
import graphene
from django.conf import settings
from django.http import JsonResponse
from saleor.core.drf import RestrictedViewSet
from saleor.graphql.order.types import OrderLine
from saleor.order import FulfillmentStatus
from saleor.order import models as order_models
from saleor.rest_apis.zaamo_integration.integeration_helper import IntegerationHelper
from .auth import token_creation , LargeResultsSetPagination ,validate_auth_token, validate_auth_token_without_expiry
from rest_framework.viewsets import ViewSetMixin,GenericViewSet
from rest_framework.mixins import ListModelMixin
from rest_framework.views import APIView
from saleor.graphql.api import schema
from saleor.utilities.time_utilities import TimeUtilities
from saleor.warehouse import models as warehouse_models
from saleor.product import models as product_models
from saleor.product.bulk_products_import import ETLDataLoader
from django.db.models.functions import Cast
from django.db.models import IntegerField
from django.db.models import Subquery
from saleor.brand import models as brand_models
from saleor.discount.models import Voucher
from saleor.account import models as account_models
from saleor.core import models as core_models
from saleor.rest_apis.zaamo_integration.serializers import CustomUpdateInventorySerializer, GroupingImageUploadSerializer, UpdateInventorySerializer , AppAuthTokenGenerationSerializer, BrandImageUploadSerializer ,VoucherImageUploadSerializer
from saleor.graphql.utils import get_nodes
from saleor.utilities.string_utilities import StringUtilities

logger = logging.getLogger(__name__)


VARIANT_STOCKS_UPDATE_MUTATIONS = """
    mutation ProductVariantStocksUpdate($variantId: ID!, $stocks: [StockInput!]!){
        productVariantStocksUpdate(variantId: $variantId, stocks: $stocks){
            productVariant{
                stocks{
                    quantity
                    quantityAllocated
                }
            }
            bulkStockErrors{
                code
                field
                message
                index
            }
        }
    }
"""


class InventoryUpdateViewSet(RestrictedViewSet):
    serializer_class = UpdateInventorySerializer

    def get_warehouse(self, slug="zaamo-master-warehouse", **kwrgs):
        try:
            warehouse = warehouse_models.Warehouse.objects.get(slug="zaamo-master-warehouse")
        except:
            warehouse = None

        if warehouse:
            warehouse_id = graphene.Node.to_global_id("Warehouse", warehouse.id)
            return warehouse_id
        return None


    def create(self, request):
        
        serializer  = UpdateInventorySerializer(data=self.request.data)

        if serializer.is_valid():
            error_dict = {}
            result_data = {}
            
            stocks = [
                {
                    "warehouse": self.get_warehouse(),
                    "quantity": serializer.data.get('quantity'),
                }
            ]

            brand_variant_id = serializer.data.get('variant_id', '').strip()
            brand_product_id = serializer.data.get('product_id', '').strip()

            brand_zaamo_mapping = product_models.BrandVariantZaamoMapping.objects.filter(
                product_id_brand=brand_product_id, variant_id_brand=brand_variant_id).first()

            if brand_zaamo_mapping:

                variables = {
                    'variantId': graphene.Node.to_global_id("ProductVariant", brand_zaamo_mapping.variant_zaamo_id),
                    'stocks': stocks
                    }
                
                params = {"user": account_models.User.objects.filter(email=settings.PRODUCT_IMPORT_USER_EMAIL).first(),
                    'app': None}
                schema_context = graphene.types.Context(**params)

                response = schema.execute(
                    VARIANT_STOCKS_UPDATE_MUTATIONS, 
                    variables=variables, 
                    context_value=schema_context
                    )

                if response.data:
                    data = response.data
                    errors = {'errors': response.data["productVariantStocksUpdate"]["bulkStockErrors"]}
                else:
                    errors = {'errors': []}
                    data = {}
                
                error_dict.update(errors)
                result_data.update(data)

            else:
                error_dict.update({
                    "bulkStockErrors": "Given product and variant mapping does't exists", 
                    'Code': "MAPPING_DOES_NOT_EXISTS"})
                result_data.update(error_dict)

            return Response({"data": result_data}, status=200)
        else:
            return Response({"bulkStockErrors": serializer.errors}, status=200)

class UploadBrandImageViewSet(ViewSetMixin,APIView):
    '''
    For uploading image in Brand
    '''
    serializer_class = BrandImageUploadSerializer

    def create(self, request):
        brand_id_values = []
        brand_id_values.append(self.request.data.get('brand_id'))

        brands = get_nodes(brand_id_values, "Brand", brand_models.Brand)
        brand = brands[0]

        brand.image = self.request.data.get('image')
        brand.save()

        return Response({'message': 'Image Uploaded Successfully'}, status=200)
    

class UploadGroupingImageViewSet(ViewSetMixin,APIView):
    '''
    For uploading image in Product Grouping
    '''
    serializer_class = GroupingImageUploadSerializer

    def create(self, request):
        try:
            brand_id_values = []
            brand_id_values.append(self.request.data.get('grouping_id'))

            productgroupings = get_nodes(brand_id_values, "ProductGrouping", product_models.ProductGrouping)
            productgrouping = productgroupings[0]

            productgrouping.image = self.request.data.get('image')
            productgrouping.save()

            return Response({'message': 'Image Uploaded Successfully'}, status=200)
        
        except Exception as e:
            return Response({'message': f'Failed with error :: {e}'}, status=400)

class UploadVoucherImageViewSet(ViewSetMixin,APIView):

    serializer_class = VoucherImageUploadSerializer

    def create(self,request):

        voucher_id_values = []
        voucher_id_values.append(self.request.data.get('voucher_id'))
        vouchers = get_nodes(voucher_id_values,"Voucher",Voucher)
        voucher = vouchers[0]

        image = self.request.data.get('image')
        voucher.metadata["mixed_coupon_image_url"] = StringUtilities.convert_object_to_string(image)
        voucher.save()

        return Response({'message': 'Image Uploaded Successfully'}, status=200)


class OrderStatusUpdate(ViewSetMixin,APIView):

    @validate_auth_token_without_expiry()
    def create(self, request):
        
        token = request.headers.get('token')
        auth_inst = core_models.ApiApp.objects.filter(token=token).first()
        brand_id = auth_inst.private_metadata.get('brand_id')

        if not brand_id:
            return Response({'message': 'No brand found with the token.','success':False},status=200)
        
        status_update = request.data.get('status_update',[])
        id_status_dict = {status_id_tuple['variant_id']:status_id_tuple['status'] for status_id_tuple in status_update}
        choices = [status[0] for status in FulfillmentStatus.CHOICES]
        
        for variant_id_brand, order_status in id_status_dict.items():

            if not order_status.lower() in choices:
                return Response({'message': f'Order Status : {order_status} is incorrect.','success':False},status=200)

            order_id_brand = request.data.get('order_id','')
            brand_mapping = product_models.BrandVariantZaamoMapping.objects.filter(variant_id_brand=variant_id_brand).first()

            if not brand_mapping:
                return Response({'message': f'Variant Id : {variant_id_brand} is incorrect.','success':False},status=200)

            order_brand_mapping = (order_models.OrderBrandZaamoMapping.objects.filter
                                    (order_id_brand=order_id_brand,brand_id=brand_id,
                                    order_line_zaamo__variant_id=brand_mapping.variant_zaamo_id
                                    ).first())
            
            if not order_brand_mapping:
                return Response({'message': 'Order id not found.','success':False},status=200)
            
            inst = order_models.FulfillmentLine.objects.filter(order_line_id=order_brand_mapping.order_line_zaamo_id).first()

            if not inst:
                return Response({'message': 'Fulfillment not found.','success':False},status=200)

            etl_loader = ETLDataLoader()
            etl_loader.update_fulfillment_status(inst.fulfillment_id,order_status)

        return Response({'message': 'Order Status updated successfully.','success':True},status=200)
