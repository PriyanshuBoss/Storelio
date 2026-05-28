import logging
import json
from typing import Union
from .constants import ERROR_CODE,CASHFREEURL,AUTHORIZATION_HEADERS,ERROR_STATUS_CODES
from .cashfree_errors import (BadRequestError,InvalidRequestError,ServerError,RateLimitError)
from saleor.utilities.api_client import ApiClient
from .cashfree_manager import CashfreeManager
logger = logging.getLogger(__name__)



class CashfreeClient(CashfreeManager):
    """Cashfree client class"""

    def __init__(self):
        """
        Initialize a Client object with Authorization Headers and base URL
        """
        self.client = ApiClient(CASHFREEURL.BASE_URL)
        headers = AUTHORIZATION_HEADERS.headers
        self.client.update_headers(headers)
    
    
    def prepare_request(self, url,data={},method="GET"):
        url = CASHFREEURL.BASE_URL+url
        self.client.update_request_url(url)
        if method=="POST":
            self.client.method = "POST"
            self.client.update_body(data)
            self.client.update_headers({'Content-Type': 'application/json'})
        return self.client

    def create_payment_link(self, data: Union[dict,list]):
        urls = CASHFREEURL.ORDER_URL
        method = "POST"
        request = self.prepare_request(url = urls,data=data,method = method)
        request.post()
        api_response = request.fetch_response()
        logger.info("payment link creation")
        logger.info(data)
        logger.info(str(request.fetch_response_code()))
        response_context = dict()
        if api_response:
            response_context['success'] = True
            return api_response
        else:   
            self.error_handler(request) 
            

        
    def get_payments_for_order(self,checkout_id, payment_exist=True, payment_information=None):
        urls = CASHFREEURL.ORDER_URL+"/"+checkout_id+CASHFREEURL.PAYMENTS_URL
        request = self.prepare_request(url = urls)
        request.get()
        api_response = request.fetch_response()
        response_context = dict()

        if not payment_information:
            payment_information = {}
            
        if api_response:
            response_context['success'] = True
            return api_response
        else:   
            
            subject = 'Cashfree API CLient request failed'
            response_context = f'an error'
            log_text = f"{subject} with {response_context} \n\n Payment Object exist :: {payment_exist} ,\n cashfree_order_id  :: {checkout_id},\n payment order list :: [], \n payment information :: {payment_information}"
            logger.info(log_text)
            from ...emails import send_cashfree_client_capture_email
            send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
            
            self.error_handler(request)

    def get_order_details(self,checkout_id, payment_exist=True, payment_information=None):
        urls = CASHFREEURL.ORDER_URL+"/"+checkout_id
        request = self.prepare_request(url = urls)
        request.get()
        api_response = request.fetch_response()
        response_context = dict()
        
        if not payment_information:
            payment_information = {}

        if api_response:
            response_context['success'] = True
            return api_response
        else:   
            
            subject = 'Cashfree API CLient request failed'
            response_context = f'an error'
            log_text = f"{subject} with {response_context} \n\n Payment Object exist :: {payment_exist} ,\n cashfree_order_id  :: {checkout_id},\n payment order list :: [], \n payment information :: {payment_information}"
            logger.info(log_text)
            from ...emails import send_cashfree_client_capture_email
            send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
            
            self.error_handler(request)

    def error_handler(self, request):
        msg = ""
        code = ""
        json_response = request.response.json()
        if request.response.status_code in ERROR_STATUS_CODES.status.keys():
            if 'message' in json_response:
                msg = json_response['message']
            if 'code' in json_response:
                code = str(json_response['code'])
        if str.upper(code) == ERROR_CODE.BAD_REQUEST_ERROR:
            raise BadRequestError(msg)
        elif str.upper(code) == ERROR_CODE.INVALID_REQUESRT_ERROR:
            raise InvalidRequestError(msg)
        elif str.upper(code) == ERROR_CODE.RATE_LIMIT_ERROR:
            raise RateLimitError(msg)
        else:
            raise ServerError(msg)
