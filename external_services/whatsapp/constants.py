from django.conf import settings

USER_TRACK_URI = 'https://api.interakt.ai/v1/public/track/users/'
USER_TRACK_HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': 'Basic {}'.format(settings.INTERAKT_API_KEY)
}
EVENT_TRACK_URI = 'https://api.interakt.ai/v1/public/track/events/'

COUPONS = (
    {
        'code': 'APP500',
        'amount': '₹500'
    },
    {
        'code': 'ZAAMO30',
        'amount': '30%'
    },
    {
        'code': 'ZAAMO10',
        'amount': '10%'
    },
    {
        'code': 'APP250',
        'amount': '₹250'
    }
)
