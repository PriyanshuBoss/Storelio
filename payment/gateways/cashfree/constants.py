
from django.conf import settings

class ERROR_CODE(object):
    INVALID_REQUESRT_ERROR = "INVALID_REQUEST_ERROR"
    BAD_REQUEST_ERROR = "BAD_REQUEST"
    RATE_LIMIT_ERROR = "RATE_LIMIT"
    SERVER_ERROR = "SERVER_ERROR"

class CASHFREEURL(object):
    BASE_URL = settings.CASHFREE_GATEWAY.get("CASHFREE_BASE_URL")
    ORDER_URL = "/orders"
    INVOICE_URL = "/invoices"
    PAYMENTS_URL = "/payments"
    REFUNDS_URL = "/refunds"
    SETTLEMENT_URL = "/settlements"

class HTTP_STATUS_CODE(object):
    OK = 200
    REDIRECT = 300

class AUTHORIZATION_HEADERS(object):
    headers = {
        "Accept": "application/json",
        "x-client-id": settings.CASHFREE_GATEWAY.get("CASHFREE_APP_ID"),
        "x-client-secret": settings.CASHFREE_GATEWAY.get("CASHFREE_APP_SECRET"),
        "x-api-version": settings.CASHFREE_GATEWAY.get("CASHFREE_API_VERSION"),
        "Content-Type": "application/json"
    }
class ERROR_STATUS_CODES(object):
    status = {
        409:"INVALID_REQUEST_ERROR",
        429: "RATE_LIMIT",
        400: "BAD_REQUEST",
        500:"SERVER ERROR"
    }
class WEBHOOK_URL(object):
    NOTIFY_URL_ORDERS=settings.BACKEND_URL+"/cashfree/get_cashfree_notify_url_response"

