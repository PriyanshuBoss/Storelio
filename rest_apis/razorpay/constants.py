from django.conf import settings
from saleor.payment.gateways.cashfree.constants import AUTHORIZATION_HEADERS

from saleor.settings import BACKEND_URL



class GRAPHQL_ENDPOINT_URL(object):
    BACKEND_URL=settings.BACKEND_URL+"/graphql/"
    HEADERS = {    
        "Authorization": "",
        "x-store-id":0,
        "x-platform-code":"IS"
    }
    MUTATION_CHECKOUT_COMPLETE = """
    mutation CheckoutComplete($checkoutId: ID!) {
        checkoutComplete(checkoutId: $checkoutId) {
            order {
            id
            status
            __typename
            }
            checkoutErrors {
            field
            message
            __typename
            }
            __typename
        }
    }   
    """ 
    MUTATION_TOKEN_CREATE =  """
    mutation tokenCreatemutation ($mobile_no: String!){
        tokenCreate(mobileNo: $mobile_no){
            token
            user{
                id
                isActive
                userId
            }
        }
    }
    """
    