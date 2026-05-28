from django.conf import settings

AUTH_TOKEN_URI = "{}/payout/v1/authorize".format(settings.CASHGRAM_URI)
AUTH_TOKEN_HEADER = {
	"X-Client-Id": settings.CASHGRAM_CLIENT_ID,
    "X-Client-Secret": settings.CASHGRAM_CLIENT_SECRET,
    "cache-control": "no-cache"
}

CASHGRAM_CREATE_URI = "{}/payout/v1/createCashgram".format(settings.CASHGRAM_URI)
CASHGRAM_CREATE_HEADER = {
    "Accept": "*/*",
    "Authorization":"",
    "Content-Type": "application/json"
}

CASHGRAM_STATUS_URI = "{}/payout/v1/getCashgramStatus?cashgramId=".format(settings.CASHGRAM_URI)
CASHGRAM_STATUS_HEADER = {
    "Accept": "*/*",
    "Authorization": "",
    "Content-Type": "application/json"
}