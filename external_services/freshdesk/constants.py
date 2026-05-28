from django.conf import settings

CREATE_TICKET_URI = 'https://zaamo.freshdesk.com/api/v2/tickets'
CREATE_TICKET_HEADER = {
    'Authorization':'Basic {}'.format(settings.FRESHDESK_AUTH),
    'Content-Type': 'application/json'
}
