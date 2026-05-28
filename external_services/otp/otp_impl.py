from saleor.utilities.api_client import ApiClient
from saleor.external_services.otp.otp_manager import OtpManager
from saleor.utilities.string_utilities import StringUtilities
import logging
from .constants import MSG91_SENDOTP_URI, MSG91_VERIFYOTP_URI
from django.conf import settings

logger = logging.getLogger(__name__)

class OtpImpl(OtpManager):

    @staticmethod
    def generate_otp(mobile_no) -> dict:
        
        otp_url = MSG91_SENDOTP_URI % (settings.OTP_MSG91_CREDENTIALS.get('auth_key'), 
        settings.OTP_MSG91_CREDENTIALS.get('template_id'), StringUtilities.convert_number_to_string(mobile_no))
        logger.info(
            "Generate Otp with otp url :: %s and template_id :: %s ", otp_url, settings.OTP_MSG91_CREDENTIALS.get('template_id')
        )
        api_client = ApiClient(url=otp_url)
        logger.info(
            "ApiClient has been initialized for Generate Otp with otp url :: %s for the mobile number :: %s ", otp_url, mobile_no
        )
        api_client.get()
        api_response = api_client.fetch_response()
        logger.info(
            "ApiResponse for Generate Otp for the mobile number :: %s is :: %s", mobile_no, api_response
        )
        respone_context = dict()
        
        if api_response and api_response.get('type') == 'success':
            logger.info(
                "OTP has been successfully sent to the mobile number :: %s ", mobile_no
            )
            respone_context['success'] = True
        
        else:
            log_error = "OTP Generation failed for the mobile number = %s " %(mobile_no)
            print(log_error)
            respone_context['success'] = False
            respone_context['error_message'] = 'Service down. Try again later.'

        return respone_context

    @staticmethod
    def verify_otp(mobile_no, otp) -> dict:
        otp_url = MSG91_VERIFYOTP_URI % (settings.OTP_MSG91_CREDENTIALS.get('auth_key'),  
        StringUtilities.convert_number_to_string(mobile_no), 
        StringUtilities.convert_number_to_string(otp))
        logger.info(
            "Verify otp with otp url :: %s for the mobile number :: %s having the otp is %s ", otp_url, mobile_no, otp
        )
        api_client = ApiClient(url=otp_url)
        logger.info(
            "ApiClient has been initialized for Verify Otp with otp url :: %s for the mobile number :: %s ", otp_url, mobile_no
        )
        api_client.get()
        api_response = api_client.fetch_response()
        logger.info(
            "ApiResponse for Verify Otp for the mobile number :: %s is :: %s", mobile_no, api_response
        )
        respone_context = dict()
        
        if api_response and api_response.get('type') == 'success':
            logger.info(
                "OTP has been successfully verified to the mobile number :: %s ", mobile_no
            )
            respone_context['success'] = True
        
        else:
            log_error = "OTP Verification failed for the mobile number = %s " %(mobile_no)
            print(log_error)
            respone_context['success'] = False
            respone_context['error_message'] = 'Service down. Try again later.'

        return respone_context
