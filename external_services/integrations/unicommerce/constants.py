from django.conf import settings

UNICOMMERCE_ORDER_PLACE_URI="https://genericproxy.unicommerce.com/uc/v1/order"
UNICOMMERCE_HEADER = {
	"content-type": "application/json",
	"clientid" : settings.UNICOMMERCE_CLIENT_ID,
	"merchantid": "",
	"securitykey": settings.UNICOMMERCE_SERVICE_KEY
}
