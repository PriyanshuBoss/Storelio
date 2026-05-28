from saleor.external_services.messaging.messaging_manager import MessagingManager
from saleor.utilities.api_client import ApiClient
from .constants import MESSAGING_SERVICE_URL,APP_DOWNLOAD_LINK
from django.conf import settings
from ...celeryconf import app
import logging

logger = logging.getLogger(__name__)


class MessagingImpl(MessagingManager):
    
    @staticmethod
    def send_message_for_account_activation(mobile_no,username=None) -> dict:
        
        
        api_client = ApiClient(host=MESSAGING_SERVICE_URL, schema='http')
        logger.info(
            "Messaging service url for send_message_for_account_activation :: %s ",
            MESSAGING_SERVICE_URL
        )
        api_client.add_header('authkey', settings.MESSAGING_MSG91_CREDENTIALS.get('auth_key'))
        api_client.update_body({
            'sender': 'EZAAMO',
            'flow_id': settings.MESSAGING_MSG91_CREDENTIALS.get('services').get('account_activation').get('flow_id'),
            'mobiles': mobile_no,
            'username':username,
            'app_download_link':APP_DOWNLOAD_LINK,
        })
        logger.info(
            "ApiClient has been initalized for send_message_for_account_activation for mobile number :: %s having auth_key :: %s and flow_id :: %s ",
            mobile_no, 
            settings.MESSAGING_MSG91_CREDENTIALS.get('auth_key'), 
            settings.MESSAGING_MSG91_CREDENTIALS.get('services').get('account_activation').get('flow_id')
        )
        api_client.get()
        api_response = api_client.fetch_response()
        logger.info(
            "ApiResponse for send_message_for_account_activation for mobile number :: %s is :: %s ",
            mobile_no, api_response
        )
        respone_context = dict()
        
        if api_response and api_response.get('type') == 'success':
            logger.info(
                "Message has been successfully sent for send_message_for_account_activation to mobile number :: %s ",
                mobile_no
            )
            respone_context['success'] = True
        
        else:
            log_error = "Error in sending message for send_message_for_account_activation to mobile number :: %s " %(mobile_no),
            print(log_error)
            respone_context['success'] = False
            respone_context['error_message'] = 'Service down. Try again later.'
        
        return respone_context
    
    @staticmethod
    @app.task
    def send_message_to_influencer_for_coupon_creation(couponName, mobile_no_list) -> dict:
        for mobile_no in mobile_no_list:
            MessagingImpl.send_message_to_mobile_number_for_coupon_creation(couponName, mobile_no)
            
    @staticmethod
    def send_message_to_mobile_number_for_coupon_creation(couponName, mobile_no) -> dict:
        api_client = ApiClient(host=MESSAGING_SERVICE_URL, schema='http')
        logger.info(
            "Messaging service url for send_message_to_mobile_number_for_coupon_creation :: %s ",
            MESSAGING_SERVICE_URL
        )
        api_client.add_header('authkey', settings.MESSAGING_MSG91_CREDENTIALS.get('auth_key'))
        api_client.update_body({
            'sender': 'EZAAMO',
            'flow_id': settings.MESSAGING_MSG91_CREDENTIALS.get('services').get('coupon_creation').get('flow_id'),
            'mobiles': mobile_no,
            'couponName': couponName
        })
        logger.info(
            "ApiClient has been initalized for send_message_to_mobile_number_for_coupon_creation for mobile number :: %s having auth_key :: %s and flow_id :: %s with coupon name :: %s",
            mobile_no, 
            settings.MESSAGING_MSG91_CREDENTIALS.get('auth_key'), 
            settings.MESSAGING_MSG91_CREDENTIALS.get('services').get('coupon_creation').get('flow_id'),
            couponName
        )
        api_client.get()
        api_response = api_client.fetch_response()
        logger.info(
            "ApiResponse for send_message_to_mobile_number_for_coupon_creation for mobile number :: %s is :: %s ",
            mobile_no, api_response
        )
        respone_context = dict()
        if api_response and api_response.get('type') == 'success':
            logger.info(
                "Message has been successfully sent for send_message_to_mobile_number_for_coupon_creation to mobile number :: %s ",
                mobile_no
            )
            respone_context['success'] = True
        
        else:
            log_error = "Error in sending message for send_message_to_mobile_number_for_coupon_creation to mobile number :: %s " %(mobile_no),
            print(log_error)
            respone_context['success'] = False
            respone_context['error_message'] = 'Service down. Try again later.'
            
        return respone_context


    @staticmethod
    def send_message_for_order_confirmation(mobile_no, my_orders_url) -> dict:
        
        
        api_client = ApiClient(host=MESSAGING_SERVICE_URL, schema='http')
        logger.info(
            "Messaging service url for send_message_for_order_confirmation :: %s ",
            MESSAGING_SERVICE_URL
        )
        api_client.add_header('authkey', settings.MESSAGING_MSG91_CREDENTIALS.get('auth_key'))
        api_client.update_body({
            'sender': 'EZAAMO',
            'flow_id': settings.MESSAGING_MSG91_CREDENTIALS.get('services').get('order_confirmation').get('flow_id'),
            'mobiles': mobile_no,
            'my_orders_url': my_orders_url
        })
        logger.info(
            "ApiClient has been initalized for send_message_for_order_confirmation for mobile number :: %s having auth_key :: %s and flow_id :: %s ",
            mobile_no, 
            settings.MESSAGING_MSG91_CREDENTIALS.get('auth_key'), 
            settings.MESSAGING_MSG91_CREDENTIALS.get('services').get('order_confirmation').get('flow_id')
        )
        api_client.get()
        api_response = api_client.fetch_response()
        logger.info(
            "ApiResponse for send_message_for_order_confirmation for mobile number :: %s is :: %s ",
            mobile_no, api_response
        )
        respone_context = dict()
        
        if api_response and api_response.get('type') == 'success':
            logger.info(
                "Message has been successfully sent for send_message_for_order_confirmation to mobile number :: %s ",
                mobile_no
            )
            respone_context['success'] = True
        
        else:
            log_error = "Error in sending message for send_message_for_order_confirmation to mobile number :: %s " %(mobile_no),
            print(log_error)
            respone_context['success'] = False
            respone_context['error_message'] = 'Service down. Try again later.'
        
        return respone_context

