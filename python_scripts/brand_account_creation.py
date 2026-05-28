from saleor.brand import models as brand_models
from saleor.account import models as user_models
from saleor.graphql.api import schema
from saleor.product.utils.bulk_upload import handle_errors
import graphene
import re


def register_user(ph_num):
            

    variables = {
        "input":{
            "mobileNo":ph_num,
            "isActive": "true"
        }
    }
    query = '''
    mutation UserRegister($input:UserRegisterInput!){
    userRegister(input:$input)
        {
        user{
            id
            isActive
        }
        accountErrors{
        message
        field
        }
        }
        }
        '''
    response = schema.execute(query, variables=variables)
    errors = response.data["userRegister"]["accountErrors"]
    handle_errors(errors)
    
    return response


def activate_brand_account(ph_num , global_brand_id):


    variables = {
        "input":{
        "mobileNo":ph_num,
        "brandId":global_brand_id
        }
    }
    query = '''
    mutation BrandActivateAccount($input:ActivateBrandAccountInput!){
    activateBrandAccount(input:$input){
    
    user{
        id
        mobileNo
        isActive
    }

        }
        }
        '''
    response = schema.execute(query, variables=variables)
    return response


def script_register_activate():
    brands = brand_models.Brand.objects.all()

    for brand in brands:
        phone_number = brand.brand_contact_number
        phone_number_list = phone_number.split(" ")
        phone_number_temp = ''.join(phone_number_list)
        phone_numbers = phone_number_temp.split(",")
        phone_numbera = phone_numbers[0]
        phone_number = phone_numbera[-10:]
        
        if not phone_number:
            #print("phone_number",brand.brand_contact_number,"brand_id",brand.id)
            continue
        else:
            phone_number  = "91"+phone_number
        
        if not user_models.User.objects.filter(mobile_no = phone_number).exists():
            register_user(phone_number)

        if not brand.brand_member_states.filter(user__mobile_no = phone_number).exists():
            global_brand_id = graphene.Node.to_global_id("Brand",brand.id)
            activate_brand_account(phone_number,global_brand_id)

    print("Script completed")


script_register_activate()

#command to run 

# from saleor.python_scripts import brand_account_creation