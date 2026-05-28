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
    MUTATION_USER_REGISTER =  """
    mutation UserCreate($mobileNo: String!, $registerType: RegisterUserTypeEnum) {
  userRegister(
    input: { mobileNo: $mobileNo, isActive: true, registerType: $registerType }
  ) {
    user {
      id
      isActive
      __typename
    }
  }
}

    """
    CASHFREE_SECRET_KEY = settings.CASHFREE_GATEWAY.get("CASHFREE_APP_SECRET")
    MUTATION_CHECKOUT_ADD_PROMO_CODE = """
    mutation CheckoutAddPromoCode($id: ID!, $promoCode: String!) {
  checkoutAddPromoCode(checkoutId: $id, promoCode: $promoCode) {
    checkout {
      totalPrice {
        gross {
          amount
          currency
          __typename
        }
        __typename
      }
      discount {
        amount
        __typename
      }
      subtotalPrice {
        gross {
          amount
          currency
          __typename
        }
        __typename
      }
      shippingPrice {
        gross {
          amount
          currency
          __typename
        }
        __typename
      }
      lines {
        quantity
        variant {
          id
          name
          pricing {
            onSale
            priceUndiscounted {
              gross {
                amount
                __typename
              }
              __typename
            }
            price {
              gross {
                amount
                __typename
              }
              __typename
            }
            __typename
          }
          __typename
        }
        __typename
      }
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
    """
    sample webhook response from cashfree
    
    {'orderId': ['7d401cd8-0fac-4d45-989a-405a2d7df8a11648195670572'],
    'orderAmount': ['1199.00'],
    'referenceId': ['1411836'], 
    'txStatus': ['SUCCESS'],
    'paymentMode': ['NET_BANKING'], 
    'txMsg': ['Transaction pending'], 
    'txTime': ['2022-03-25 13:38:37'], 
    'signature': ['bW1X6HhSs+94jqpn1fncbrbEbrzzd0THz4ARLIx+u5o=']}
    """
