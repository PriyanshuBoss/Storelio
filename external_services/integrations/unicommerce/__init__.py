from .constants import UNICOMMERCE_ORDER_PLACE_URI , UNICOMMERCE_HEADER
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.api_client import ApiClient
import logging
from saleor.brand.models import Brand
from saleor.core.models import ApiApp
from saleor.order.models import OrderBrandZaamoMapping

logger = logging.getLogger(__name__)

class Unicommerce:

    def create_post_data(self,order,order_lines_dict , brand_zaamo_dict):

        shipping_address = order.shipping_address 
        billing_address = order.billing_address
        order_id = order.id
        order_created = order.created
        brand_order_data_dict = {}
        data = {
                "id": StringUtilities.convert_number_to_string(order_id) ,
                "orderDate": TimeUtilities.convert_datetime_to_string(order_created) ,
                "orderStatus": "CREATED",
                "sla": TimeUtilities.convert_datetime_to_string((TimeUtilities.add_time_in_timestamp(order_created,10))),
                "orderPrice": {
                "currency": "INR",
                "totalDiscount": 0,
                "totalShippingCharges": 0
                }
            }

        data["shippingAddress"] = {
                "addressLine1":shipping_address.street_address_1 ,
                "addressLine2": shipping_address.street_address_2 ,
                "city": shipping_address.city,
                "country":StringUtilities.convert_object_to_string(shipping_address.country),
                "email": shipping_address.email,
                "name": shipping_address.first_name,
                "phone": StringUtilities.convert_object_to_string(shipping_address.phone),
                "pincode": shipping_address.postal_code,
                "state": shipping_address.country_area
            }
        data["billingAddress"] = {
            "addressLine1":billing_address.street_address_1 ,
            "addressLine2": billing_address.street_address_2 ,
            "city": billing_address.city,
            "country": StringUtilities.convert_object_to_string(billing_address.country),
            "email": billing_address.email,
            "name": billing_address.first_name,
            "phone": StringUtilities.convert_object_to_string(billing_address.phone),
            "pincode": billing_address.postal_code,
            "state": billing_address.country_area
        }
        
        for key in order_lines_dict:
            order_lines_items = []
            
            shipping_total = 0
            order_lines_list = order_lines_dict[key]
            brand_id = None
            if len(order_lines_list)>0:
                brand_id = order_lines_list[0].brand_id

            brand_zaamo_list = brand_zaamo_dict[key]
            for ind in range(len(order_lines_list)):
                order_line = order_lines_list[ind]
                brand_zaamo = brand_zaamo_list[ind]
                shipping_price = NumberUtilities.convert_string_to_number(order_line.shipping_cost_amount)
                shipping_total+=shipping_price
                sku = ""
                variant = order_line.variant
                if variant:
                    sku = variant.sku
                order_line_data = {

                    "orderItemId": StringUtilities.convert_object_to_string(order_line.id),
                    "status": "CREATED",
                    "productId": StringUtilities.convert_number_to_string(brand_zaamo.product_zaamo_id),
                    "variantId": StringUtilities.convert_number_to_string(brand_zaamo.variant_zaamo_id),
                    "sku": sku ,
                    "title": brand_zaamo.product_name,
                    "orderItemPrice": {
                        "sellingPrice": NumberUtilities.convert_string_to_number(order_line.unit_price_net_amount),
                        "shippingCharges":  shipping_price,
                        "totalPrice":  NumberUtilities.convert_string_to_number(order_line.unit_price_gross_amount),
                        "currency": "INR"
                    },
                    "quantity": order_line.quantity,
                }

                order_lines_items.append(order_line_data)
                
            data["orderItems"] = order_lines_items
            data["orderPrice"]["totalShippingCharges"] = shipping_total
            brand_order_data_dict[brand_id] = data
        
        return brand_order_data_dict
    
    def fetch_response_order_placing(self,data,username):

        unicommerce_url = UNICOMMERCE_ORDER_PLACE_URI
        unicommerce_headers = UNICOMMERCE_HEADER

        unicommerce_headers["merchantid"]=username

        api_client = ApiClient(url=unicommerce_url)
        api_client.body = data
        api_client.headers = unicommerce_headers
        api_client.post()
        api_response = api_client.fetch_response()

        if api_response:
            return api_response
        else:
            TimeoutError("Unicommerce Order Placing down")
    
    def create_data_order_brand_zaamo_mapping(self,data,brand_id):

        order_id = data.get("id")
        orderlines = data.get("orderItems")

        for line in orderlines:
            order_line_id = line.get("orderItemId")
            product_name = line.get("title")
            order_brand_zaamo_mapping = OrderBrandZaamoMapping()
            order_brand_zaamo_mapping.order_id_brand = order_id
            order_brand_zaamo_mapping.brand_id = brand_id
            order_brand_zaamo_mapping.order_line_zaamo_id = NumberUtilities.convert_string_to_number(order_line_id)
            order_brand_zaamo_mapping.order_zaamo_id = NumberUtilities.convert_string_to_number(order_id)
            order_brand_zaamo_mapping.product_name  = product_name
            order_brand_zaamo_mapping.save()

    def _create_order_request(self,order,order_lines_dict,brand_zaamo_dict):

        brand_order_data_dict = self.create_post_data(order,order_lines_dict,brand_zaamo_dict)
        all_response = []
        for key in brand_order_data_dict:
            
            data = brand_order_data_dict[key]
            brand_id = key
            api_app = ApiApp.objects.filter(private_metadata__brand_id = brand_id).first()
            
            username = StringUtilities.convert_object_to_string(api_app.app_id)

            logger.info(f"Unicommerce order placing for brand_id {brand_id}\n request is : {data}\n")

            response = self.fetch_response_order_placing(data,username)

            if response.get('status') == "success":

                self.create_data_order_brand_zaamo_mapping(data,brand_id)

            logger.info(f"Unicommerce order placing for brand_id {brand_id}\n response is : {response}")

            all_response.append(response)

        return all_response
