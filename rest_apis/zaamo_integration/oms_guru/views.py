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
from ..auth import token_creation , LargeResultsSetPagination ,validate_auth_token, validate_auth_token_without_expiry
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
from saleor.account import models as account_models
from saleor.core import models as core_models
from saleor.rest_apis.zaamo_integration.serializers import CustomUpdateInventorySerializer, UpdateInventorySerializer , AppAuthTokenGenerationSerializer, BrandImageUploadSerializer
from saleor.graphql.utils import get_nodes
logger = logging.getLogger(__name__)

class AuthAppTokenGenerationViewSet(ViewSetMixin,APIView):

    serializer_class = AppAuthTokenGenerationSerializer

    def create(self,request):
        time_stamp = TimeUtilities.get_current_date_time()
        logger.info(f"StyleStree create Auth Request received at {time_stamp}")
        serializer = AppAuthTokenGenerationSerializer(data = self.request.data)

        if serializer.is_valid():
            error_dict= {}
            result_data = {}
            data = {}
            app_id = serializer.data.get('username', '')
            secret_token = serializer.data.get('password', '')

            try:
                if core_models.ApiApp.objects.filter(app_id=app_id , api_secret_key=secret_token).exists():

                    api_app = core_models.ApiApp.objects.filter(app_id=app_id , api_secret_key=secret_token).first()

                    encoded_jwt = token_creation(api_app)
                    data = {'token':encoded_jwt,'token_expires_on':api_app.token_expires_at}
                    error_dict = {'errors': []}
                
                else:
                    error_dict = {'errors':'Incorrect App Id or Secret Token'}

            except Exception as e:

                    error_dict = {'errors':'Incorrect App Id or Secret Token'}

            result_data.update(data)
            result_data.update(error_dict)

            time_stamp = TimeUtilities.get_current_date_time()
            logger.info(f"StyleStree create Auth Response sent at {time_stamp} with data {result_data}")
            return JsonResponse(data=result_data, status=200)
        else:
            
            time_stamp = TimeUtilities.get_current_date_time()
            logger.info(f"StyleStree create Auth Response sent at {time_stamp} with bulkStockErrors: {serializer.errors}")
            return JsonResponse(data={"bulkStockErrors": serializer.errors}, status=200)


class CustomInventoryUpdateViewSet(ViewSetMixin,APIView):
    """

    Custom inventory update and create. for Oms Guru.

    """
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

    @validate_auth_token()
    def create(self, request):
        
        time_stamp = TimeUtilities.get_current_date_time()
        
        serializer  = CustomUpdateInventorySerializer(data=self.request.data, many=True)

        if serializer.is_valid():
            
            result_data = {"items": [], "has_error": False}

            for data in serializer.data:
                error_dict = {}
                stocks = [
                    {
                        "warehouse": self.get_warehouse(),
                        "quantity": data.get('in_stock'),
                    }
                ]

                brand_variant_id = data.get('variant_id', '').strip()
                brand_product_id = data.get('product_id', '').strip()
                brand_sku_id = data.get('sku_code', '').strip()


                brand_zaamo_mapping = product_models.BrandVariantZaamoMapping.objects.filter(
                    product_id_brand=brand_product_id, 
                    variant_id_brand=brand_variant_id, 
                    sku_id_brand=brand_sku_id).first()

                if brand_zaamo_mapping:

                    variables = {
                        'variantId': graphene.Node.to_global_id("ProductVariant", brand_zaamo_mapping.variant_zaamo_id),
                        'stocks': stocks
                        }
                    
                    params = {"user": account_models.User.objects.filter(email=settings.PRODUCT_IMPORT_USER_EMAIL).first(),
                        'app': None}
                    schema_context = graphene.types.Context(**params)

                    response = schema.execute(
                        self.VARIANT_STOCKS_UPDATE_MUTATIONS, 
                        variables=variables, 
                        context_value=schema_context
                        )

                    if response.data:
                        response_data = response.data
                        error = response.data["productVariantStocksUpdate"]["bulkStockErrors"]
                        item_data = {
                            'success': True,
                            'message': None,
                            'product_id': brand_product_id,
                            'variant_id': brand_variant_id,
                            'sku_code': brand_sku_id,
                            'in_stock':  data.get('in_stock')

                        }
                        errors = {'message': '', "code": '', 'success': True}

                        if error:
                            errors['code'] = error["code"]
                            errors['message'] = str(error["attributes"])
                            errors['success']=False
                    else:
                        errors = {'message': "check mapping", "code": "002", 'success': False}
                        item_data = {}
                    
                    error_dict.update(errors)
                    if errors['success']:
                        result_data['items'].append(item_data)
                    else:
                        result_data["has_error"] = True
                        result_data['items'].append(error_dict)

                else:
                    error_dict.update({
                        "success": False,
                        "message": "Given product and variant mapping does't exists", 
                        'code': "MAPPING_DOES_NOT_EXISTS",
                        'product_id': brand_product_id,
                        'variant_id': brand_variant_id,
                        'sku_code': brand_sku_id,
                        'in_stock':  data.get('in_stock')
                        })
                    result_data['items'].append(error_dict)
                    result_data["has_error"] = True

        
            time_stamp = TimeUtilities.get_current_date_time()
            
            return JsonResponse(data=result_data, status=200)
        else:
            time_stamp = TimeUtilities.get_current_date_time()
            
            return JsonResponse(data={'message': serializer.errors, 'code': "001"}, status=200)

class ProductCatalogueViewSet(ListModelMixin,GenericViewSet):

    paginate_by = 10
    pagination_class = LargeResultsSetPagination
    
    @validate_auth_token()
    def list(self,request,**kwargs):
        
        try:
            time_stamp = TimeUtilities.get_current_date_time()
            logger.info(f"StyleStree get catalogue request received at {time_stamp}")
            mappings = product_models.BrandVariantZaamoMapping.objects.filter(
                        brand_zaamo_id__in=Subquery(brand_models.Brand.objects.filter(
                        private_metadata__source_name='stylestree').values('id'))).annotate(p_brand_id=Cast('product_id_brand', output_field=IntegerField())).order_by('p_brand_id')
            product_ids = mappings.distinct('p_brand_id').values_list('p_brand_id',flat=True)
            
            try:
                data = self.paginate_queryset(product_ids)
            except Exception as e:
                return JsonResponse(data={'has_more':False,"items":[]}, status=200)
                
            queryset = (mappings.filter(product_id_brand__in=data).prefetch_related('variant_zaamo__stocks','product_zaamo__images')
                        .select_related('product_zaamo','variant_zaamo','product_zaamo__category'))
            
            items = IntegerationHelper.structure_stylestry_response(queryset)
            
            has_more = len(data)>=self.pagination_class.page_size
            result_data={'has_more':has_more,"items":items}


            time_stamp = TimeUtilities.get_current_date_time()
            return JsonResponse(data=result_data, status=200)
        except Exception as e:
            
            time_stamp = TimeUtilities.get_current_date_time()
            
            return JsonResponse(data={'message': e, 'code': "001"}, status=200)

class OmsGuruEmptyListResponse(ListModelMixin,GenericViewSet):
    
    @validate_auth_token()
    def list(self,request,**kwargs):

        return JsonResponse(data={'has_more':False,"orders":[]}, status=200)

    
    @validate_auth_token()
    def create(self,request,**kwargs):

        return JsonResponse(data={'has_more':False,"orders":[]}, status=200)


class OmsGuruEmptyListwitherrorResponse(ListModelMixin,GenericViewSet):
    
    @validate_auth_token()
    def list(self,request,**kwargs):

        return JsonResponse(data={'has_error':False,"orders":[]}, status=200)

    
    @validate_auth_token()
    def create(self,request,**kwargs):

        return JsonResponse(data={'has_error':False,"orders":[]}, status=200)

class OmsGuruEmptyResponse(ListModelMixin,GenericViewSet):
    
    @validate_auth_token()
    def list(self,request,**kwargs):

        return JsonResponse(data={}, status=200)  

    @validate_auth_token()
    def create(self,request,**kwargs):

        return JsonResponse(data={}, status=200)

class OmsGuruStringResponse(ListModelMixin,GenericViewSet):
    
    @validate_auth_token()
    def list(self,request,**kwargs):

        return Response("", status=200)  

    @validate_auth_token()
    def create(self,request,**kwargs):

        return Response("", status=200)