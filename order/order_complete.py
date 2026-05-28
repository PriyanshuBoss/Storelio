import graphene
import logging
from saleor.brand.states import BrandSourceEnum
from saleor.discount import VoucherOwner
from saleor.external_services.mydukaan_service.mydukaan_impl import MyDukaanImpl
from saleor.external_services.the_souled_store_service.the_souled_store_impl import TheSouledStoreImpl
from ..external_services.style_stree_service.style_stree_impl import StyleStreeImpl
from saleor.order.models import FulfillmentLine, OrderBrandZaamoMapping
from saleor.product.models import BrandVariantZaamoMapping
from saleor.external_services.shopify_service.constants import SHOPIFY_SOURCE
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.external_services.woo_commerce_service.constants import WOOCOMMERCE_SOURCE
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from saleor.external_services.wix.constants import WIX_SOURCE
from saleor.external_services.wix.wix_impl import WixImpl
from saleor.external_services.integrations.unicommerce import Unicommerce
from collections import defaultdict
from saleor.order import FulfillmentStatus
from saleor.product.utils.bulk_upload import handle_errors
from saleor.settings import IS_BETA
from django.conf import settings
from saleor.account.models import User
from django.db.models import Subquery
from saleor.plugins.manager import PluginsManager

logger = logging.getLogger(__name__)

from saleor.order.emails import send_checkout_complete_order_mail
from saleor.utilities.string_utilities import StringUtilities

class OrderEngine():

    def place_order(self, order):
        
        order_lines = order.lines.all()

        data = self._get_order_line_lists(order_lines)

        if IS_BETA:
            return {'success': True}
        
        response = {'success': True}
        

        woo_commerce_order_dict = data['woo_commerce_order_dict']
        shopify_order_dict = data['shopify_order_dict']
        wix_order_dict = data['wix_order_dict']
        custom_order_dict = data['custom_order_dict']
        unicommerce_order_dict = data['unicommerce_order_dict']
        mydukaan_order_dict = data['mydukaan_order_dict']
        brand_mapping_for_woo_commerce = data['brand_mapping_for_woo_commerce']
        brand_mapping_for_shopify = data['brand_mapping_for_shopify']
        brand_mapping_for_wix = data['brand_mapping_for_wix']
        brand_mapping_for_custom = data['brand_mapping_for_custom']
        brand_mapping_for_unicommerce = data['brand_mapping_for_unicommerce']
        brand_mapping_for_mydukaan = data['brand_mapping_for_mydukaan']

        if woo_commerce_order_dict:

            response = self._place_order_for_woo_commerce(woo_commerce_order_dict, brand_mapping_for_woo_commerce)
        
        if shopify_order_dict:

            response = self._place_order_for_shopify(shopify_order_dict, brand_mapping_for_shopify)

        if wix_order_dict:

            response = self._place_order_for_wix(wix_order_dict, brand_mapping_for_wix)

        if custom_order_dict:

            response = self._place_order_for_custom(custom_order_dict, brand_mapping_for_custom)
        
        if unicommerce_order_dict:

            response = self._place_order_for_unicommerce(order,unicommerce_order_dict,brand_mapping_for_unicommerce)
        
        if mydukaan_order_dict:

            response = self._place_order_for_mydukaan(mydukaan_order_dict,brand_mapping_for_mydukaan)
        
        return response
        
    def create_fulfillment_order(self, order_instance, schema, warehouse_id, store_id):
        order_lines = order_instance.lines.all()
        order_id = order_instance.id
        response_list = []
        for order_line in order_lines.prefetch_related("fulfillment_line").filter(fulfillment_line__isnull=True):

            variables = {
                "order": graphene.Node.to_global_id("Order",order_id),
                "input":{
                    "fulfillmentStatus":"PLACED",
                    "lines":[{
                        "orderLineId":graphene.Node.to_global_id("OrderLine",order_line.id),
                        "stocks":[{
                            "quantity":order_line.quantity,
                            "warehouse":warehouse_id
                        }]
                    }]
                }
            }
            query = '''
            mutation createfulfillOrder($order:ID,$input:OrderFulfillInput!){
            orderFulfill(order:$order,input:$input){
                order{
                    id
                }
                fulfillments{
                    statusDisplay
                }
                orderErrors{
                    field
                    message
                    code
                }


            }
            }

            '''
            schema_context = OrderEngineHelper.create_schema_context(**{"META": {"HTTP_X_STORE_ID": store_id}})
            response = schema.execute(query, variables=variables,context_value=schema_context)
            errors = response.data["orderFulfill"]["orderErrors"]
            handle_errors(errors)
            response_list.append(response.to_dict())
        
        return response_list

    def _get_order_line_lists(self, order_lines):
        
        variant_ids_order_line_dict = dict()
        woo_commerce_order_dict = defaultdict(list)
        shopify_order_dict = defaultdict(list)
        wix_order_dict = defaultdict(list)
        custom_order_dict = defaultdict(list)
        unicommerce_order_dict = defaultdict(list)
        mydukaan_order_dict = defaultdict(list)
        brand_mapping_for_woo_commerce = defaultdict(list)
        brand_mapping_for_shopify = defaultdict(list)
        brand_mapping_for_wix = defaultdict(list)
        brand_mapping_for_custom = defaultdict(list)
        brand_mapping_for_unicommerce = defaultdict(list)
        brand_mapping_for_mydukaan = defaultdict(list)
        voucher = order_lines[0].order.voucher
        
        if voucher:
            is_voucher_owner_brand = True if voucher.owner==VoucherOwner.BRAND else False
        else:
            is_voucher_owner_brand = False

        for order_line in order_lines:
            variant_id = order_line.variant_id
            variant_ids_order_line_dict[variant_id] = order_line

        brand_variant_zaamo_mappings = BrandVariantZaamoMapping.objects.filter(variant_zaamo_id__in=variant_ids_order_line_dict.keys()).select_related('brand_zaamo')

        for brand_variant_zaamo in brand_variant_zaamo_mappings:
            
            if brand_variant_zaamo.brand_zaamo.private_metadata.get('orders_not_allowed') and is_voucher_owner_brand:
                continue

            source = brand_variant_zaamo.source
            brand_name = brand_variant_zaamo.brand_name
            brand = brand_variant_zaamo.brand_zaamo
            if brand.private_metadata.get('no_order_write',False):
                continue

            if source==BrandSourceEnum.SHOPIFY:

                shopify_order_dict[brand_name].append(variant_ids_order_line_dict[brand_variant_zaamo.variant_zaamo_id])
                brand_mapping_for_shopify[brand_name].append(brand_variant_zaamo)

            elif source==BrandSourceEnum.WOOCOMMERCE:

                woo_commerce_order_dict[brand_name].append(variant_ids_order_line_dict[brand_variant_zaamo.variant_zaamo_id])
                brand_mapping_for_woo_commerce[brand_name].append(brand_variant_zaamo)

            elif source==BrandSourceEnum.WIX:

                wix_order_dict[brand_name].append(variant_ids_order_line_dict[brand_variant_zaamo.variant_zaamo_id])
                brand_mapping_for_wix[brand_name].append(brand_variant_zaamo)
            
            elif source==BrandSourceEnum.CUSTOM:
                custom_order_dict[brand_name].append(variant_ids_order_line_dict[brand_variant_zaamo.variant_zaamo_id])
                brand_mapping_for_custom[brand_name].append(brand_variant_zaamo)
            
            elif source==BrandSourceEnum.UNICOMMERCE:
                unicommerce_order_dict[brand_name].append(variant_ids_order_line_dict[brand_variant_zaamo.variant_zaamo_id])
                brand_mapping_for_unicommerce[brand_name].append(brand_variant_zaamo)
            
            elif source==BrandSourceEnum.MYDUKAAN:
                mydukaan_order_dict[brand_name].append(variant_ids_order_line_dict[brand_variant_zaamo.variant_zaamo_id])
                brand_mapping_for_mydukaan[brand_name].append(brand_variant_zaamo)

        response = {
                "woo_commerce_order_dict":woo_commerce_order_dict,
                "shopify_order_dict":shopify_order_dict,
                "wix_order_dict":wix_order_dict,
                "custom_order_dict":custom_order_dict,
                "unicommerce_order_dict":unicommerce_order_dict,
                "mydukaan_order_dict":mydukaan_order_dict,
                "brand_mapping_for_woo_commerce":brand_mapping_for_woo_commerce,
                "brand_mapping_for_shopify":brand_mapping_for_shopify,
                "brand_mapping_for_wix":brand_mapping_for_wix,
                "brand_mapping_for_custom":brand_mapping_for_custom,
                "brand_mapping_for_unicommerce":brand_mapping_for_unicommerce,
                "brand_mapping_for_mydukaan":brand_mapping_for_mydukaan
            }

        return response
        
    def _place_order_for_woo_commerce(self, woo_commerce_order_dict,brand_mapping_for_woo_commerce):
        
        response = {'success': True}
        res_data = dict()
        woo_impl = WooCommerceImpl()
        
        for brand, order_lines in woo_commerce_order_dict.items():
            res_data = woo_impl.place_orders_util(order_lines, brand_mapping_for_woo_commerce[brand], brand)

            order = order_lines[0].order
            orderline_ids = [order_line.id for order_line in order_lines]


            if not res_data.get('success'):
                log_error = "Order failed on brand side with order id = %s" %(StringUtilities.convert_number_to_string(order.id))
                logger.exception(log_error)
                send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_failure')

            else:
                logger.info(
                    "order placed on woocommerce with orderlines as :: %s, of brand  :: %s, with brand mapping for woocommerce as :: %s with a response as :: %s ", order_lines,
                    brand, brand_mapping_for_woo_commerce[brand], res_data
                )    
                # send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_success')

        return response

    def _place_order_for_shopify(self, shopify_order_dict, brand_mapping_for_shopify):
        
        response = {'success': True}
        shopify_impl_ins = ShopifyImpl()
        res_data = dict()

        for brand, order_lines in shopify_order_dict.items():
            res_data = shopify_impl_ins.place_orders_util(order_lines, brand, brand_mapping_for_shopify[brand])  
            
            order = order_lines[0].order
            orderline_ids = [order_line.id for order_line in order_lines]

            
            if not res_data.get('success'):
                logger.exception("Order failed on brand side with order id :: %s", (StringUtilities.convert_number_to_string(order.id)))   
                send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_failure')
            
            else:
                
                logger.info(
                    "order placed on shopify with orderlines as :: %s, of brand  :: %s, with brand mapping for shopify as :: %s with a response as :: %s ", order_lines,
                    brand, brand_mapping_for_shopify[brand], res_data
                )  
                # send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_success')

        return response

    def _place_order_for_stylestree(self,order_lines,brand,brand_mapping_for_custom):
        style_stree_impl = StyleStreeImpl()
        res_data = style_stree_impl.place_orders_util(order_lines, brand, brand_mapping_for_custom[brand])  
        
        order = order_lines[0].order
        orderline_ids = [order_line.id for order_line in order_lines]

        
        if not res_data.get('success'):
            logger.exception("Order failed on brand side with order id :: %s", (StringUtilities.convert_number_to_string(order.id)))   
            send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_failure')
        
        else:
            
            logger.info(
                f"order placed on {brand} with orderlines as :: {order_lines}, of brand  :: {brand},\
                with brand mapping for shopify as :: {brand_mapping_for_custom[brand]} with a response as :: {res_data} "
            )  
            # send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_success')

    def _place_order_for_souledstore(self,order_lines,brand,brand_mapping_for_custom):
        souled_impl = TheSouledStoreImpl()
        res_data = souled_impl.place_orders_util(order_lines, brand, brand_mapping_for_custom[brand])  
        
        order = order_lines[0].order
        orderline_ids = [order_line.id for order_line in order_lines]

        
        if not res_data.get('success'):
            logger.exception("Order failed on brand side with order id :: %s", (StringUtilities.convert_number_to_string(order.id)))   
            send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data['response'], 'order_failure')
        
        else:
            
            logger.info(
                f"order placed on {brand} with orderlines as :: {order_lines}, of brand  :: {brand},\
                with brand mapping for shopify as :: {brand_mapping_for_custom[brand]} with a response as :: {res_data} "
            )  
            # send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_success')

    def _place_order_for_custom(self, custom_order_dict, brand_mapping_for_custom):
        
        response = {'success': True}

        for brand, order_lines in custom_order_dict.items():

            if brand=='stylestree':
                self._place_order_for_stylestree(order_lines,brand,brand_mapping_for_custom)

            if brand=='shoetopia':
                self._place_order_for_stylestree(order_lines,brand,brand_mapping_for_custom) # using stylestree function since shoetopia is a sub brand of stylestree
            
            if brand=='thesouledstore':
                self._place_order_for_souledstore(order_lines,brand,brand_mapping_for_custom)
        return response
        
    def _place_order_for_wix(self, wix_order_dict, brand_mapping_for_wix):
        

        wix_impl_ins = WixImpl()

        for brand, order_lines in wix_order_dict.items():
            res_data = wix_impl_ins.place_orders_util(order_lines, brand, brand_mapping_for_wix[brand])

            logger.info(
                "order placed on wix with orderlines as :: %s, of brand  :: %s, with brand mapping for wix as :: %s with a response as :: %s ", order_lines, 
                brand, brand_mapping_for_wix[brand], res_data
            )
            
            order = order_lines[0].order
            orderline_ids = [order_line.id for order_line in order_lines]

            if not res_data.get('success'):
                logger.exception("Order failed on brand side with order id :: %s", (StringUtilities.convert_number_to_string(order.id)))   
                send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_failure')
            
            else:
                
                logger.info(
                    f"order placed on {brand} with orderlines as :: {order_lines}, of brand  :: {brand},\
                    with brand mapping for shopify as :: {brand_mapping_for_wix[brand]} with a response as :: {res_data} "
                )  
                # send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_success')
                
        return res_data
    
    def _place_order_for_unicommerce(self, order ,unicommerce_order_dict,brand_mapping_for_unicommerce):

        unicommerce_impl = Unicommerce()

        all_response = unicommerce_impl._create_order_request(order,unicommerce_order_dict,brand_mapping_for_unicommerce)

        return all_response
    
    def _place_order_for_mydukaan(self, mydukaan_order_dict, brand_mapping_for_mydukaan):
        
        response = {'success': True}
        mydukaan_impl_ins = MyDukaanImpl()
        res_data = dict()

        for brand, order_lines in mydukaan_order_dict.items():
            res_data = mydukaan_impl_ins.place_orders_util(order_lines, brand, brand_mapping_for_mydukaan[brand])  
            
            order = order_lines[0].order
            orderline_ids = [order_line.id for order_line in order_lines]

            
            if not res_data.get('success'):
                logger.exception("Order failed on brand side with order id :: %s", (StringUtilities.convert_number_to_string(order.id)))   
                send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_failure')
            
            else:
                
                logger.info(
                    "order placed on shopify with orderlines as :: %s, of brand  :: %s, with brand mapping for shopify as :: %s with a response as :: %s ", order_lines,
                    brand, brand_mapping_for_mydukaan[brand], res_data
                )  
                # send_checkout_complete_order_mail.delay(order.id,orderline_ids, res_data, 'order_success')

        return response


class OrderEngineHelper:

    @staticmethod
    def create_schema_context(**extra_params):
        try:
            params = {"user": User.objects.get(email=settings.PRODUCT_IMPORT_USER_EMAIL),
             "plugins": PluginsManager(plugins=settings.PLUGINS), 'app': None}
            params.update(extra_params)
            schema_context = graphene.types.Context(**params)
        except Exception as e:
            print(e)
        
        return schema_context
