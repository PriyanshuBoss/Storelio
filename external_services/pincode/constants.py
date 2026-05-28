from django.conf import settings

PINCODE_URI = "https://pincode.p.rapidapi.com/"
PINCODE_HEADER = {
	"content-type": "application/json",
	"Content-Type": "application/json",
	"X-RapidAPI-Host": settings.PINCODE_CREDENTIALS.get('api_host'),
	"X-RapidAPI-Key": settings.PINCODE_CREDENTIALS.get('api_key')
}
PINCODE_BODY = {
    "searchBy": "pincode",
	"value": 0
}
