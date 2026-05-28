from rest_framework.pagination import PageNumberPagination
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.time_utilities import TimeUtilities

class LargeResultsSetPagination(PageNumberPagination):
    pageSize = 100
    page_size_query_param = 'pageSize'
    page = 1
    page_query_param='pageNumber'


class IntergrationParser():
    
    @staticmethod
    def fetch_brand_instance(products):

        if(len(products)>0):
            first_product = products[0]
            if first_product.brand:
                brand = first_product.brand
                return brand
        
        return None


    @staticmethod
    def serializer_product_data(products):
        items = []

        brand_instance = IntergrationParser.fetch_brand_instance(products)
        commission_percentage = 0
        brand_name = ""
        if brand_instance:
            brand_name = brand_instance.brand_name
            commission = brand_instance.commission.first()
            if commission:
                commission_percentage = NumberUtilities.convert_string_to_number(commission.commission_percentage)
        
        for product in products:
            
            data = {
                "id": StringUtilities.convert_number_to_string(product.id),
                "parentTitle":product.name,
                "brand":brand_name,
                "commissionPercentage": commission_percentage,
                "created": StringUtilities.convert_number_to_string(product.publication_date)

                }
                
            variant_info = []
            product_name = product.name
            if product.variants:
                variants = product.variants.all().prefetch_related('stocks')
                for variant in variants:
                    
                    stock = variant.stocks.first()
                    stock_quantity = 0
                    if stock:
                        stock_quantity = stock.quantity

                    variant_data = {
                    "variantId": StringUtilities.convert_number_to_string(variant.id),
                    "title": product_name,
                    "sku": variant.sku,
                    "size": variant.name,
                    "live": True,
                    "itemPrice": {
                        "currency": variant.currency,
                        "mrp": variant.cost_price_amount,
                        "msp": variant.price_amount,
                    },
                    "inventory": stock_quantity,

                    }
                    variant_info.append(variant_data)
                data.update({"variants":variant_info})

            items.append(data)

        return items

    @staticmethod
    def status_mapper():

        order_status_dict={}
     
        order_status_dict["in process"] = "PROCESSING"
        order_status_dict["delivered"] = "COMPLETE"
        order_status_dict["placed"] = "CREATED"
        order_status_dict["cancellation initiated"] = "CANCELLED"
        order_status_dict["cancellation processed"] = "CANCELLED"

        order_line_status_dict={}
        order_line_status_dict["cancellation initiated"] = "CANCELLED"
        order_line_status_dict["cancellation processed"] = "CANCELLED"
        order_line_status_dict["shipped"] = "DISPATCHED"
        order_line_status_dict["delivered"] = "DELIVERED"
        order_line_status_dict["placed"] = "CREATED"
        order_line_status_dict["in process"] = "CREATED"
        order_line_status_dict["return requested"] = "RETURN_REQUESTED"
        order_line_status_dict["return initiated"] = "COURIER_RETURN"
        order_line_status_dict["return completed"] = "RETURNED"

        return order_status_dict,order_line_status_dict


    @staticmethod
    def serializer_order_data(orders,brand_id):
        items = []

        order_status_dict,order_line_status_dict = IntergrationParser.status_mapper()

        for order in orders:
            
            fulfillment_status = None
            if order.fulfillments.first():
                fulfillment_status = order.fulfillments.first().status
            shipping_address = order.shipping_address 
            billing_address = order.billing_address
            order_id = order.id
            order_created = order.created
            payment_type  = order.payments.first().payment_method_type
            data = {
                "id":order_id ,
                "orderDate": order_created ,
                "orderStatus": order_status_dict.get(fulfillment_status,""),
                "sla": TimeUtilities.add_time_in_timestamp(order_created,10),
                "paymentType":payment_type,
                "orderPrice": {"currency": "INR"},
                "thirdPartyShipping":False
            }

            order_lines_items = []
            for order_line in order.lines.filter(brand_id=brand_id).select_related('variant').prefetch_related('fulfillment_line'):
                fulfillment_line = order_line.fulfillment_line.first()
                order_line_status = ""
                if fulfillment_line:
                    order_line_status = fulfillment_line.fulfillment.status
                variant = order_line.variant
                order_line_data = {

                    "orderItemId": order_line.id,
                    "status": order_line_status_dict.get(order_line_status,""),
                    "productId": variant.product_id,
                    "variantId": variant.id,
                    "sku": order_line.product_sku,
                    "title": order_line.product_name,
                    "returnReason": "",
                    "returnDate": "",
                    "returnAWB": "",
                    "returnShippingProvider": "",
                    "orderItemPrice": {
                        "sellingPrice": order_line.unit_price_net_amount,
                        "shippingCharges": order_line.shipping_cost_amount,
                        "totalPrice": order_line.unit_price_gross_amount,
                        "currency": "INR"
                    },
                    "quantity": order_line.quantity,
                }

                order_lines_items.append(order_line_data)
            
            if(len(order_lines_items)>0):
                data["orderItems"] = order_lines_items
                items.append(data)
            data["shippingAddress"] = {
                    "addressLine1":shipping_address.street_address_1 ,
                    "addressLine2": shipping_address.street_address_2 ,
                    "city": shipping_address.city,
                    "country": StringUtilities.convert_object_to_string(shipping_address.country),
                    "email": shipping_address.email,
                    "name": shipping_address.first_name,
                    "phone": StringUtilities.convert_object_to_string(shipping_address.phone),
                    "pincode": shipping_address.postal_code,
                    "state": shipping_address.country_area
                }
            data["billingAdderss"] = {
                "addressLine1":billing_address.street_address_1 ,
                "addressLine2": billing_address.street_address_2 ,
                "city": billing_address.city,
                "country": StringUtilities.convert_object_to_string(billing_address.country),
                "email": billing_address.email,
                "name": billing_address.first_name,
                "phone":StringUtilities.convert_object_to_string(billing_address.phone),
                "pincode": billing_address.postal_code,
                "state": billing_address.country_area
            }

        return items
