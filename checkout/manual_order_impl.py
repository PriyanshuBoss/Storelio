import json
import requests
import graphene
import time
import logging
from saleor.checkout import calculations
from saleor.payment.models import Payment
from saleor.store.models import StoreInfo
from saleor.order.models import Order
from saleor.settings import BACKEND_URL


from saleor.checkout.models import Checkout

logger = logging.getLogger(__name__)


class ManualOrderCreate():
    
    def __init__(self) -> None:
        self.GRAPHQL_URL = f'{BACKEND_URL}/graphql/'
        self.headers = {}
        self.super_token = ''
 
    def checkout_line_update(self, checkout_token, lines_list = None):

        if lines_list:
            lines = lines_list
        
        else:
            checkout_lines = Checkout.objects.filter(token=checkout_token).values_list('lines__variant_id', 'lines__quantity')
            lines = []
            for variant_id, quantity in checkout_lines:
                lines.append({
                    "quantity": quantity,
                    "variantId": graphene.Node.to_global_id('ProductVariant', variant_id),
                    "cod": True
                })

        checkout_id = graphene.Node.to_global_id('Checkout', checkout_token)
        variables = {
            "checkoutId": checkout_id,
            "lines": lines
        }
        query='''
        mutation CheckoutLinesUpdate($checkoutId: ID!, $lines: [CheckoutLineInput]!) {
        checkoutLinesUpdate(checkoutId: $checkoutId, lines: $lines) {
            checkout {
            id
            codBasePrice
            payablePrice
            totalPrice {
                net {
                amount
                __typename
                }
                __typename
            }
            subtotalPrice {
                net {
                amount
                __typename
                }
                __typename
            }
            shippingPrice {
                net {
                amount
                __typename
                }
                __typename
            }
            lines {
                id
                quantity
                totalPrice {
                net {
                    amount
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

        '''
        res = requests.post(self.GRAPHQL_URL, json={'query': query, 'variables': variables}, headers=self.headers)

        if not res.ok:
            logger.error(res.text)

    def checkout_payment_create(self, checkout_token,amount=None):
        if not amount:
            amount=0
        else:
            amount = amount

        return_url = ''
        checkout_id = graphene.Node.to_global_id('Checkout', checkout_token)
        query = """ mutation {
            checkoutPaymentCreate(
                checkoutId: "%s"
                input: {gateway: "zaamo.payments.cashfree", amount: %s, token: "cashfree1_manual_shopify", returnUrl: "%s"}
            ) {
                payment {
                id
                token
                __typename
                }
                paymentErrors {
                field
                message
                __typename
                }
                __typename
            }
            }
        """ % (checkout_id, amount, return_url)
        res = requests.post(self.GRAPHQL_URL, json={'query': query}, headers=self.headers)

        if not res.ok:
            logger.error(res.text)
    
    def get_user_auth_token(self, mobile_no):
        try:
            query = """
            mutation{
            tokenCreate(mobileNo:"%s"){
                token
            }
            }
            """%(mobile_no)
            res = requests.post(self.GRAPHQL_URL, json={'query': query})
            token = res.json()['data']['tokenCreate']['token']
            
            return token
        
        except :
            return None
    
    def update_token(self,mobile_no):
        auth_token = self.get_user_auth_token(mobile_no)
        auth_token = 'JWT '+auth_token
        self.headers.update({'Authorization': auth_token})

    def perform_mutations(self,order_details):

        try:
            
            mobile_no = order_details['phone']
            mobile_no = '91' + ''.join(mobile_no.strip()[-10:])
            token = self.get_user_auth_token(mobile_no)
            
            if not token:
                self.user_create(mobile_no)
                
            auth_token = self.get_user_auth_token(mobile_no)
            
            if not auth_token:
                return None

            store_id = StoreInfo.objects.filter(store_name='zaamo').first().id
            auth_token = 'JWT '+auth_token
            app_code = 'IS'

            self.headers = {
                'Content-Type': 'application/json',
                'Authorization': auth_token,
                'x-store-id': str(store_id),
                'x-platform-code': 'IS'
            }
            address_id,address_variable = self.create_address(order_details)
            
            self.update_token(mobile_no)
            self.delete_existing_checkout(mobile_no)
            checkout_token,lines = self.create_checkout(order_details,address_variable)
            
            try:
                checkout = Checkout.objects.filter(token=checkout_token).first()
                checkout.shipping_method_id=9
                checkout.metadata['shopify']=True
                checkout.save()
                self.delete_existing_checkout(mobile_no,checkout)

            
            except Exception as e:
                logger.exception(e)
                return None
            

            self.update_token(mobile_no)
            self.headers.update({'x-app-code':app_code})
            self.checkout_line_update(checkout_token,lines_list=lines)
            promo_added = self.checkout_add_promo_code(checkout_token,order_details)

            if not promo_added and order_details.get('discount_code'):
                logger.exception(f"checkout voucher add mutation failed : {order_details}, {checkout_token}")
                return 
            time.sleep(5)
            self.update_token(mobile_no)
            
            amount = calculations.checkout_total(
                                        checkout=checkout, lines=checkout.lines.all()
                                    ).net.amount
            
            self.checkout_payment_create(checkout_token,amount=amount)
            time.sleep(5)

            checkout_id = graphene.Node.to_global_id('Checkout', checkout_token)
            self.update_token(mobile_no)

            query = """
            mutation {
            checkoutComplete(checkoutId: "%s") {
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
            """ % (checkout_id)

            res = requests.post(self.GRAPHQL_URL, json={'query': query}, headers=self.headers)
            
            if res.ok:

                try:
                    order_id = graphene.Node.from_global_id(res.json()['data']['checkoutComplete']['order']['id'])[1]
                    order = Order.objects.filter(id=order_id).first()
                    cod_status = list(order.lines.all().values_list('cod',flat=True))

                    if not True in cod_status:
                        Payment.objects.filter(order_id=order_id).update(charge_status = 'fully_charged')

                    shopify_order_id = order_details.get('order_id')
                    order.metadata['zaamo_shopify_order_id'] = shopify_order_id
                    order.metadata['zaamo_shopify_order_price'] =  order_details.get('zaamo_shopify_order_price')
                    order.metadata['shopify'] = True
                    order.save()
                    return order

                except Exception as e:
                    logger.error(f'error {e}')
        
        except Exception as e:
            logger.error(f'ERROR in full row :: {e}')

    def user_create(self,mobile):
        
        query = """
                    mutation{
                    userRegister(input: {mobileNo: "%s",isActive:true}) {
                        user {
                        id
                        mobileNo
                        __typename
                        }
                        accountErrors {
                        message
                        __typename
                        }
                        __typename
                    }
                    }
                """ % (mobile)
        res = requests.post(self.GRAPHQL_URL, json={'query': query}, headers=self.headers)

        if not res.ok:
            logger.error(res.text)

    def create_address(self,order_details):
        
        
        query = """
                mutation SaveAddress($firstName: String!, $lastName: String!, $address: String!, $city: String!, $pincode: String!, $state: String!, $phone: String!, $email: String, $country: CountryCode!) {
                accountAddressCreate(
                    input: {firstName: $firstName, lastName: $lastName, streetAddress1: $address, city: $city, postalCode: $pincode, countryArea: $state, phone: $phone, country: $country, email: $email}
                ) {
                    accountErrors {
                    field
                    message
                    __typename
                    }
                    address {
                    id
                    __typename
                    }
                    __typename
                }
                }
                """

        variable = {
                    "city": order_details['city'],
                    "state": order_details['state'],
                    "firstName": order_details['first_name'],
                    "lastName": order_details['last_name'],
                    "phone": order_details['phone'],
                    "pincode": order_details['zip'],
                    "address": order_details['address'],
                    "email": order_details['email'],
                    "country": "IN"
                    }
        
        res = requests.post(self.GRAPHQL_URL, json={'query': query,'variables':variable}, headers=self.headers)

        if res.ok:
            address_id = res.json()['data']['accountAddressCreate']['address']['id']
        
        else:
            logger.error(res.text)
            address_id =None
        
        return address_id,variable

    def delete_existing_checkout(self,mob,checkout=None):

        if not checkout:
            checkout = Checkout.objects.filter(user_id__mobile_no=mob).first()

        if not checkout:
            return
        
        lines = checkout.lines.all().values_list('id',flat=True)
        checkout_id = graphene.Node.to_global_id('Checkout', checkout.token)

        query = """
                mutation CheckoutLineDelete($checkoutId: ID!, $lineId: ID!) {
                    checkoutLineDelete(checkoutId: $checkoutId, lineId: $lineId) {
                        checkout {
                        lines {
                            id
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

        for line_id in lines:
            line_id = graphene.Node.to_global_id('CheckoutLine', line_id)

            variable = {
                        "lineId": line_id,
                        "checkoutId": checkout_id
                        }
            res = requests.post(self.GRAPHQL_URL, json={'query': query,'variables':variable}, headers=self.headers)
            if not res.ok:
                logger.error(res.text)
                
    def create_checkout(self,order_details,address_variable):
        
        query = """
                mutation CheckoutCreate($email: String!, $lines: [CheckoutLineInput]!, $city: String, $state: String, $firstName: String, $lastName: String, $phone: String, $pincode: String, $address: String) {
                checkoutCreate(
                    input: {email: $email, lines: $lines, shippingAddress: {firstName: $firstName, lastName: $lastName, streetAddress1: $address, city: $city, postalCode: $pincode, country: IN, countryArea: $state, phone: $phone}, billingAddress: {firstName: $firstName, lastName: $lastName, streetAddress1: $address, city: $city, postalCode: $pincode, country: IN, countryArea: $state, phone: $phone}}
                ) {
                    checkout {
                    id
                    token
                    availablePaymentGateways {
                        id
                        __typename
                    }
                    availableShippingMethods {
                        id
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
        lines = []
        default_cod = order_details['cod']
        line_items = order_details['line_items']

        for row in line_items:
            
            line = {
                    "quantity": row['quantity'],
                    "variantId": graphene.Node.to_global_id('ProductVariant', row['variant_id']),
                    "cod": default_cod
                }

            lines.append(line)

        address_variable.update({'lines':lines})
        
        res = requests.post(self.GRAPHQL_URL, json={'query': query,'variables':address_variable}, headers=self.headers)

        if res.ok:
            checkout_token = res.json()['data']['checkoutCreate']['checkout']['token']

        else:
            checkout_token = None

        return checkout_token,lines

    def checkout_add_promo_code(self,checkout_id,order_details):
        
        code = order_details.get('discount_code')

        if not code:
            return False
        
        checkout_id = graphene.Node.to_global_id('Checkout', checkout_id)
        query = """
                mutation CheckoutAddPromoCode($id: ID!, $promoCode: String!) {
                checkoutAddPromoCode(checkoutId: $id, promoCode: $promoCode) {
                    checkout {
                    voucherCode
                    totalPrice {
                        gross {
                        amount
                        currency
                        __typename
                        }
                        __typename
                    }
                    payablePrice
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
        variable = {
                    "id": checkout_id,
                    "promoCode": code
                    }
        
        res = requests.post(self.GRAPHQL_URL, json={'query': query,'variables':variable}, headers=self.headers)
        
        if res.ok:
            try:
                checkout_token = res.json()['data']['checkoutAddPromoCode']['checkout']['voucherCode']
                return checkout_token
            except:
                return False

        else:
            return False

