import logging
import uuid
from typing import Dict
import json
from .cashfree_client import CashfreeClient
from . import cashfree_errors
from .constants import WEBHOOK_URL
from . import errors

from ... import TransactionKind
from ...interface import GatewayConfig, GatewayResponse, PaymentData
from .utils import  get_error_response
from saleor.utilities.string_utilities import StringUtilities
from ...models import Payment
from datetime import timedelta,datetime
from ....utilities.time_utilities import TimeUtilities
from decimal import Decimal
from ...emails import send_cashfree_client_capture_email

# The list of currencies supported by cashfree
SUPPORTED_CURRENCIES = ("INR",)

# Define what are the cashfree exceptions
CASHFREE_EXCEPTIONS = (
    cashfree_errors.BadRequestError,
    cashfree_errors.InvalidRequestError,
    cashfree_errors.ServerError,
    cashfree_errors.RateLimitError

)

# Get the logger for this file, it will allow us to log
# error responses from cashfree. FIXME implement logger and set up logging
logger = logging.getLogger(__name__)


def _generate_response(
    payment_information: PaymentData, kind: str, data: Dict
) -> GatewayResponse:
    """Generate Saleor transaction information from the payload or from passed data."""
    return GatewayResponse(
        transaction_id=data.get("id", payment_information.token),
        action_required=False,
        kind=kind,
        amount=data.get("amount", payment_information.amount),
        currency=data.get("currency", payment_information.currency),
        error=data.get("error"),
        is_success=data.get("is_success", True),
        raw_response=data,
    )


def check_payment_supported(payment_information: PaymentData):
    """Check that a given payment is supported."""
    if payment_information.currency not in SUPPORTED_CURRENCIES:
        return errors.UNSUPPORTED_CURRENCY % {"currency": payment_information.currency}


def get_error_message_from_cashfree_error(exc: BaseException):
    """Convert a Cashfree error to a user-friendly error message.

    It also logs the exception to stderr.
    """
    logger.info("error msg from cashfree-")
    logger.info(exc)
    if isinstance(exc, cashfree_errors.BadRequestError):
        return errors.INVALID_REQUEST
    else:
        return errors.SERVER_ERROR

def get_client(public_key: str, private_key: str, **_):
    """Create a Cashfree client from set-up application keys."""
    cashfree_client = CashfreeClient()
    return cashfree_client


def get_client_token(**_):
    """Generate a random client token."""
    return str(uuid.uuid4())


def capture(payment_information: PaymentData, config: GatewayConfig) -> GatewayResponse:
    """
    Check status of payment by a checkout ID, if successful returns response
    If an error from Cashfree occurs, we flag the transaction as failed and return
    a short user friendly description of the error after logging the error to stderr.
    """

    error = check_payment_supported(payment_information=payment_information)
    cashfree_client = get_client(**config.connection_params)
    payment = Payment.objects.filter(id=payment_information.payment_id).first()
    payment_exist = True if payment else False
    response_list = []
    cashfree_order_id = ""
    try:
        response = {}
        #webhook says accepted, but their system API says no transaction has been processed yet
        cashfree_webhook_api_mismatch = False
        if not payment_information.amount.compare(Decimal("0.0")):
            response.update({'is_success': True, 'checkout_id': payment.checkout_id})
        else:
            cashfree_order_id = json.loads(payment.extra_data)["order_id"]
            response = cashfree_client.get_order_details(str(cashfree_order_id),payment_exist,payment_information)
            if response['order_status']=="PAID":
                response.update({'is_success': True, 'checkout_id': payment.checkout_id})
            else:
                response.update({'is_success': False, 'checkout_id': payment.checkout_id,"cashfree_webhook_api_mismatch":"yes"})
                cashfree_webhook_api_mismatch = True
        
        subject = 'Cashfree payment captured'
        response_context = 'a response'

    except CASHFREE_EXCEPTIONS as exc:
            cashfree_order_id = ""
            error = get_error_message_from_cashfree_error(exc)
            response = get_error_response(
                payment_information.amount, error=error, id=cashfree_order_id
            ) 

            subject = 'Cashfree exception error while cashfree capture'
            response_context = f'an error :: {exc}'

    except Exception as exc:
            cashfree_order_id = ""
            error = get_error_message_from_cashfree_error(exc)
            response = get_error_response(
                payment_information.amount, error=error, id=cashfree_order_id
            ) 

            subject = 'ERROR in Cashfree payment capture'
            response_context = f'an error :: {exc}'

    if cashfree_webhook_api_mismatch:
        subject = 'ERROR: Cashfree webhook and api response mismatch'
        response_context = 'a response'        

    payment_information.token = str(cashfree_order_id)

    log_text = f"{subject} with {response_context} as :: {response}\n\n Payment Object exist :: {payment_exist},\n cashfree_order_id  :: {cashfree_order_id},\n payment order list :: {response_list}, \n payment information :: {payment_information}"
    logger.info(log_text)

    if payment_exist and payment.token=='cashfree1_manual_shopify':
        pass
    
    else:
        send_cashfree_client_capture_email.delay({'subject':subject,'body':log_text})
    
    return _generate_response(
        payment_information=payment_information,
        kind=TransactionKind.CAPTURE,
        # set this data correctly
        data=response,
    )


def refund(payment_information: PaymentData, config: GatewayConfig) -> GatewayResponse:
    """Refund a payment using the Cashfree client.

    But it first check if the given payment instance is supported
    by the gateway.

    It first retrieve a `charge` transaction to retrieve the
    payment id to refund. And return an error with a failed transaction
    if the there is no such transaction, or if an error
    from Cashfree occurs during the refund.
    """
    error = check_payment_supported(payment_information=payment_information)
    # FIXME implement this for cashfree
    response = {"is_success":False, "amount":payment_information.amount ,"error":"Couldnt refund the amount, please raise request to Support" }
    return _generate_response(
        payment_information=payment_information,
        kind=TransactionKind.REFUND,
        data=response,
    )


def process_payment(
    payment_information: PaymentData, config: GatewayConfig
) -> GatewayResponse:
    return capture(payment_information=payment_information, config=config)


# save details generated somewhere
def create_order_id(payment_information: PaymentData,
                    config: GatewayConfig) -> GatewayResponse:
    """Create payment link by a checkout ID, if successful returns response
    If an error from Cashfree occurs, we flag the transaction as failed and return
    a short user friendly description of the error after logging the error to stderr.
    """
    error = check_payment_supported(payment_information=payment_information)
    cashfree_client = get_client(**config.connection_params)
    cashfree_order_id = str(payment_information.data["cashfree_order_id"])+str(TimeUtilities.current_time_in_milliseconds())
    cashfree_notify_url = WEBHOOK_URL.NOTIFY_URL_ORDERS

    #handing new api cashfree call
    logger.info("payment_information data ",payment_information.data.get('is_new_cashfree_api'))
    print("debug")
    print(payment_information.data.get('is_new_cashfree_api'))
    logger.info(payment_information.data.get('is_new_cashfree_api'))
    
    if payment_information.data.get('is_new_cashfree_api'):
        cashfree_client.client.update_headers({'x-api-version':"2022-09-01"})

    if not error:
        try:
            order_id = ""
            if payment_information.order_id:
            
                order_id = payment_information.order_id

            customer_phone = ""
            try:
            
                customer_phone = str(payment_information.data["customer_phone"])
            except Exception as e:
                # FIXME when customer phone is not present in checkout, 
                # add store manager contact detail here
                customer_phone = "8586970063"
            
            # FIXME add order meta with notify url and implement webhook for notify_url
            data = {
                "order_id": cashfree_order_id,
                "order_amount":str(payment_information.amount),
                "order_currency":"INR",
                "customer_details": {
                    "customer_id": str(payment_information.customer_id),
                    "customer_email": str(payment_information.customer_email),   
                    "customer_phone":customer_phone 
                },
                "order_meta":{
                    "return_url": str(payment_information.data["return_url"]),
                    "notify_url":cashfree_notify_url,
                    "payment_methods":""
                },
                "order_expiry_time":TimeUtilities.parse_date_tz(1),
                "order_note":"Order Processing for Zaamo",
                "order_tags": {
                    "order_id": str(order_id),
                    "payment_id": str(payment_information.payment_id),
                    "graphql_payment_id":str(payment_information.graphql_payment_id)
                }
            }
            response = cashfree_client.create_payment_link(
                data=dict(data)
            )
        except CASHFREE_EXCEPTIONS as exc:
            error = get_error_message_from_cashfree_error(exc)
            response = get_error_response(
                payment_information.amount, error=error, id=payment_information.data["cashfree_order_id"]
            )
    else:
        response = get_error_response(
            payment_information.amount, error=error, id=payment_information.data["cashfree_order_id"]
        )
        payment_information.token = cashfree_order_id

    return _generate_response(
        payment_information=payment_information,
        kind=TransactionKind.CAPTURE,
        data=response,
    )
