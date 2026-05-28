import graphene
from rest_framework.viewsets import ViewSetMixin,GenericViewSet
from rest_framework.mixins import ListModelMixin
from rest_framework.views import APIView
import logging
from rest_framework.response import Response
from saleor import settings
from saleor.core import models as core_models
from saleor.product import models as product_models
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.order import models as order_models
from saleor.order import FulfillmentStatus
from saleor.warehouse.models import Stock
from saleor.rest_apis.zaamo_integration.auth import token_creation , validate_auth_token
from .serializers import UpdateInventorySerializer,PostOrderDispatchSerializer, PostStatusNotificationSerializer,PostOrderCancelSerializer
from .helpers import LargeResultsSetPagination , IntergrationParser
from saleor.utilities.api_client import ApiClient

logger = logging.getLogger(__name__)

class AuthTokenGenerationViewSet(ViewSetMixin,APIView):

    def list(self,request):
        
        timestamp = TimeUtilities.get_current_date_time()
        #logger.info(f"Unicommerce Auth API request at {timestamp} with Access token : {None}")

        username = request.GET.get('username', '')
        password = request.GET.get('password', '')
        try:
            if core_models.ApiApp.objects.filter(app_id=username , api_secret_key=password).exists():

                api_app = core_models.ApiApp.objects.filter(app_id=username , api_secret_key=password).first()

                encoded_jwt = token_creation(api_app)
                data = {"status":"SUCCESS",'accessToken':encoded_jwt}
                error_dict = {'errors': []}
            
            else:
                data = {'errors':'Incorrect Username or Password'}
                
        except Exception as e:

                data = {'errors':'Incorrect Username or Password'}
        
        return Response(data, status=200)


class GetProductCountViewSet(ViewSetMixin, APIView):

    @validate_auth_token('apiKey')
    def list(self, request):
        
        apiKey = request.headers.get('apiKey')

        timestamp = TimeUtilities.get_current_date_time()
        
        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)

        #logger.info(f"Unicommerce ProductsCount API for brand_id : {brand_id} request at {timestamp} with Access token : {apiKey}")

        published_status = request.GET.get('publishedStatus', '')
        
        qs = product_models.Product.objects.filter(brand_id=brand_id)

        if published_status:
            if published_status == 'PUBLISHED':
                qs = qs.filter(is_published=True)
            elif published_status == 'UNPUBLISHED':
                qs = qs.none()

        count = qs.count()
        data = {'count': count}
        return Response(data, status=200) 

class GetProductsViewSet(ListModelMixin,GenericViewSet):

    paginate_by = 10
    pagination_class = LargeResultsSetPagination

    @validate_auth_token('apiKey')
    def list(self, request):
        result_data = {}

        apiKey = request.headers.get('apiKey')
        timestamp = TimeUtilities.get_current_date_time()
        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)
        #logger.info(f"Unicommerce Products API for brand_id : {brand_id} request at {timestamp} with Access token : {apiKey}")

        queryset = product_models.Product.objects.filter(is_published=True , brand_id=brand_id).prefetch_related('variants')

        try:
            data = self.paginate_queryset(queryset)
        except Exception as e:
            data = []
            return Response({"products": data}, status=200)
        
        data = IntergrationParser.serializer_product_data(data)

        return Response({"products": data}, status=200)

class UpdateInventoryViewSet(ViewSetMixin, APIView):

    serializer_class = UpdateInventorySerializer

    @validate_auth_token('apiKey')
    def create(self, request):
        
        apiKey = request.headers.get('apiKey')

        timestamp = TimeUtilities.get_current_date_time()
        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)
        #logger.info(f"Unicommerce UpdateInventory API for brand_id : {brand_id} request at {timestamp} with Access token : {apiKey} with Request Body : {request.body}")
        
        serializer  = UpdateInventorySerializer(data=self.request.data.get("inventoryList",None), many=True)

        if serializer.is_valid():
            failed_products = []
            for data in serializer.data:
                
                product_id = NumberUtilities.convert_string_to_number(data.get('productId',None))
                variant_id = NumberUtilities.convert_string_to_number(data.get('variantId',None))
                quantity = data.get('inventory')
                product_instance = product_models.Product.objects.filter(id=product_id).first()

                if not product_instance:
                    data = {
                        "productId": data.get('productId',""),
                        "variantId": data.get('variantId',""),
                        "message": "Unable to find Variant Id"
                    }
                    failed_products.append(data)
                    break

                variant_stock = Stock.objects.filter(product_variant_id=variant_id).first()
                
                if variant_stock:
                    variant_stock.quantity = quantity
                    variant_stock.save()
                
                else:
                    data = {
                        "productId": data.get('productId',""),
                        "variantId": data.get('variantId',""),
                        "message": "Unable to find Variant Id"
                    }
                    failed_products.append(data)

            if failed_products:
                final_response = {"status":"FAILED","failedProductList" : failed_products}
            else:
                final_response = {"status":"SUCCESS","failedProductList" : failed_products}

            return Response(final_response, status=200)
        else:
            final_response = {'error': serializer.errors}
            return Response(final_response, status=200)

class PostOrderDispatchViewSet(ViewSetMixin, APIView):

    serializer_class =PostOrderDispatchSerializer

    @validate_auth_token('apiKey')
    def create(self,request):

        apiKey = request.headers.get('apiKey')
        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)
        timestamp = TimeUtilities.get_current_date_time()
        #logger.info(f"Unicommerce PostOrderDispatch API for brand_id : {brand_id} request at {timestamp} with Access token : {apiKey} with Request Body : {request.body}")
        
        serializer = PostOrderDispatchSerializer(data = self.request.data)
        
        if serializer.is_valid():
            
            response_data = {}

            response_data["status"]="SUCCESS"
            
            order_items = request.data.get('orderItems')
            shipping_info = request.data.get('selfShipping')
            order_items_response = []

            failed = False
            success = False
            for order_lines in order_items:
                
                order_item_response_data = {
                    "orderItemId":order_lines.get('orderItemId'),
                    "errorMessage":""
                }
                order_lines_id = NumberUtilities.convert_string_to_number(order_lines.get('orderItemId'))

                fulfillment_line_id = order_models.FulfillmentLine.objects.filter(order_line_id=order_lines_id).first()
                
                if fulfillment_line_id:
                    fulfillment  = fulfillment_line_id.fulfillment
                    fulfillment_id = fulfillment_line_id.fulfillment_id
                    
                    fulfillment.status = FulfillmentStatus.SHIPPED
                    fulfillment.save()
                    order_shipping_data = {
                        "fulfillment_id":fulfillment_id,
                        "shipping_provider":shipping_info.get('deliveryPartner'),
                        "shipping_id":shipping_info.get('trackingId')
                    }
                    
                    if not order_models.ShippingFulfillment.objects.filter(fulfillment_id = fulfillment_id).exists():
                        order_shipping_instance = order_models.ShippingFulfillment.objects.create(**order_shipping_data)                
                        success = True
                else:
                    order_item_response_data["errorMessage"] = "No such kind of Order Fulfillment"
                    failed = True
                
                order_items_response.append(order_item_response_data)
            
            if success and failed:
                response_data["status"] = "PARTIAL_SUCCESS"
            
            if not success:
                response_data["status"] = "FAILED"

            response_data["orderItems"] = order_items_response

            return Response(response_data, status=200)
        
        else:
            response_data = {'error': serializer.errors}
            #logger.info(f"Unicommerce PostOrderDispatch API for brand_id : {brand_id} response : {response_data}") 
            return Response(response_data, status=200)


class PostStatusNotificationViewSet(ViewSetMixin, APIView):

    serializer_class = PostStatusNotificationSerializer

    def create_status_dict(self):

        status_dict = {}

        status_dict["CREATED"] = FulfillmentStatus.PLACED
        status_dict["LOCATION_NOT_SERVICEABLE"]  = FulfillmentStatus.INPROCESS
        status_dict["PICKING"] = FulfillmentStatus.INPROCESS
        status_dict["PICKED"] = FulfillmentStatus.SHIPPED
        status_dict["PENDING_CUSTOMIZATION"] = FulfillmentStatus.INPROCESS
        status_dict["CUSTOMIZATION_COMPLETE"] = FulfillmentStatus.INPROCESS
        status_dict["PACKED"] = FulfillmentStatus.INPROCESS
        status_dict["READY_TO_SHIP"] = FulfillmentStatus.INPROCESS
        status_dict["SPLITTED"] = FulfillmentStatus.PLACED
        status_dict["CANCELLED"] = FulfillmentStatus.CANCELLATION_INITIATED
        status_dict["MERGED"] = FulfillmentStatus.PLACED
        status_dict["MANIFESTED"] = FulfillmentStatus.SHIPPED
        status_dict["DISPATCHED"] = FulfillmentStatus.SHIPPED
        status_dict["SHIPPED"] = FulfillmentStatus.SHIPPED
        status_dict["DELIVERED"] = FulfillmentStatus.DELIVERED
        status_dict["RETURN_EXPECTED"] = FulfillmentStatus.RETURN_REQUESTED
        status_dict["RETURN_ACKNOWLEDGED"] = FulfillmentStatus.RETURN_INITIATED
        status_dict["RETURNED"] = FulfillmentStatus.RETURN_COMPLETED
        status_dict["COMPLETE"] = FulfillmentStatus.RETURN_COMPLETED
        status_dict["NOT_RECEIVED"] = FulfillmentStatus.RETURN_REQUESTED

        return status_dict

    @validate_auth_token('apiKey')
    def create(self,request,order_id):

        apiKey = request.headers.get('apiKey')

        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)

        timestamp = TimeUtilities.get_current_date_time()
        #logger.info(f"Unicommerce PostStatusNotification API for brand_id : {brand_id} request at {timestamp} with Access Token : {apiKey}\n with Request Body : {request.body}")
        

        serializer = PostStatusNotificationSerializer(data = self.request.data.get('orderItems',None),many=True)

        if serializer.is_valid():
            
            res = {
                "status":"SUCCESS",
            }
            failed = False
            success = False
            status_dict = self.create_status_dict()
            order_failed_items = []
            for order_item in request.data.get('orderItems'):
                
                order_line_id = NumberUtilities.convert_string_to_number(order_item.get('orderItemId',None))
                status =  status_dict.get(order_item.get('status'),FulfillmentStatus.PLACED)
                updated_at = order_item.get('updated')

                fulfillment_line  = order_models.FulfillmentLine.objects.filter(order_line_id = order_line_id).first()
                if fulfillment_line:
                    fullfillment_instance = fulfillment_line.fulfillment
                    fullfillment_instance.status = status
                    fullfillment_instance.save() 
                    success = True
                else:
                    failed= True
                    order_failed_data = {
                        "orderItemId":order_item.get('orderItemId'),
                        "errorMessage":"No fulfillment for updation of Notification"
                    }
                    order_failed_items.append(order_failed_data)

            if success and failed:
                res["status"] = "PARTIAL_SUCCESS"
            
            if not success:
                res["status"] = "FAILED"

            res["orderItems"] = order_failed_items


            return Response(res, status=200)
        
        else:
            res = {"error":serializer.errors}

            return Response(res,status=200)

class GetOrderStatusViewSet(ListModelMixin,GenericViewSet):

    paginate_by = 10
    pagination_class = LargeResultsSetPagination

    @validate_auth_token('apiKey')
    def list(self, request):
        
        apiKey = request.headers.get('apiKey')
        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)
        timestamp = TimeUtilities.get_current_date_time()
        #logger.info(f"Unicommerce GetOrderStatus API for brand_id : {brand_id} request at {timestamp} with Access Token : {apiKey}")

        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)

        order_ids = request.GET.get('orderIds',None)
        order_id_list = order_ids.split(',')
        order_id_list = [NumberUtilities.convert_string_to_number(order_id) for order_id in order_id_list]

        queryset = order_models.Order.objects.filter(id__in=order_id_list).select_related('billing_address','shipping_address').prefetch_related('fulfillments','lines')

        try:
            data = self.paginate_queryset(queryset)
        except Exception as e:
            data = []
            return Response({"orders": data}, status=200)
        
        data = IntergrationParser.serializer_order_data(data,brand_id)

        return Response({"orders": data}, status=200)

class PostOrderCancelViewSet(ViewSetMixin, APIView):
    
    serializer_class = PostOrderCancelSerializer

    @validate_auth_token('apiKey')
    def create(self,request):
        
        apiKey = request.headers.get('apiKey')
        api_app = core_models.ApiApp.objects.filter(token=apiKey).first()
        
        brand_id = api_app.private_metadata.get("brand_id",None)
        timestamp = TimeUtilities.get_current_date_time()
        #logger.info(f"Unicommerce PostOrderCancel API for brand_id : {brand_id} request at {timestamp} with Access Token : {apiKey}\n with Request Body : {request.body}")

        serializer = PostOrderCancelSerializer(data = self.request.data)

        if serializer.is_valid():
            response_data = {}
            response_data["status"]="SUCCESS"
            order_items = request.data.get('orderItems')
            order_items_response = []

            for order_lines in order_items:
                
                
                order_line_id = NumberUtilities.convert_string_to_number(order_lines.get('orderItemId',None))

                orderline = order_models.OrderLine.objects.filter(id=order_line_id).first()

                if orderline:

                    fulfillment_line = orderline.fulfillment_line.first()
                    fulfillment = fulfillment_line.fulfillment
                    fulfillment.status = FulfillmentStatus.CANCELLATION_INITIATED
                    fulfillment.save()
                else:
                    order_item_response_data = {
                    "orderItemId":order_lines.get('orderItemId'),
                    "errorMessage":"order Item Id not available"
                    }
                    order_items_response.append(order_item_response_data)
            
            response_data["orderItems"] = order_items_response


            return Response(response_data, status=200)
        
        else:
            response_data = {'error': serializer.errors}
            return Response(response_data, status=200)
        
class GetAddressByMobileViewSet(ListModelMixin,GenericViewSet):

    def list(self, request):

        if settings.IS_BETA:
            return Response({'error_message':"Not available on test server"}, status=400)
        
        api = ApiClient(host='https://turbo.unicommerce.co.in', path='vas/v1/addresses')
        header = { 
            "x-api-key":"zaamo-67yekz9tgyx1dj6scuop",
        }
        mobile_no = request.GET.get('mobile_no')
        api.update_headers(header)
        api.add_url_param('mobile', mobile_no)
        address_list = []
        api.get()
        api_resp = api.fetch_response()
        api_resp.pop('mobile', None) 
        api_resp_address_list = api_resp.get('address_list')

        if api_resp_address_list:

            for address in api_resp_address_list:
                address_dict = dict()
                address_dict['city'] = address.get('city')
                address_dict['state'] = address.get('state')
                if address.get('name'):
                    name_split = address.get('name').split()
                    if len(name_split)==1:
                        address_dict['firstName'] = name_split[len(name_split)-1]
                        address_dict['lastName'] = ''
                    else:
                        address_dict['firstName'] = name_split[0]
                        last_name = ''
                        for i in range(1, len(name_split)-1):
                            last_name += name_split[i]
                            last_name += ' '
                        last_name += name_split[len(name_split)-1]
                        address_dict['lastName'] = last_name
                else:
                    address_dict['firstName'] = ''
                    address_dict['lastName'] = ''
                
                address_dict['phone'] = mobile_no
                address_dict['pincode'] = address.get('pin_code')
                address_dict['address'] = f"{address.get('address_line1')} {address.get('address_line2')}"
                address_dict['email'] = ''
                address_dict['country'] = "IN"

                address_list.append(address_dict)
        
        api_resp['address_list'] = address_list
        return Response(api_resp, status=200)
