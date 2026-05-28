import json
from ..celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities

def update_voucher_text_for_specific_products(voucher_instance):
    voucher_text = "\n"

    if voucher_instance.get("type") == 'specific_product':

        products = voucher_instance.get("products")

        if products:
            products_text = "Products: "

            for data in products:
                products_text  = products_text + data.name + "\n"

            voucher_text = voucher_text + products_text

        collections = voucher_instance.get("collections")

        if collections:
            collections_text = "Collections: "

            for data in collections:
                collections_text  = collections_text + data.name + "\n"

            voucher_text = voucher_text + collections_text

        brands = voucher_instance.get("brands")

        if brands:
            brands_text = "Brands: "

            for data in brands:
                brands_text  = brands_text + data.brand_name + "\n"

            voucher_text = voucher_text + brands_text

        categories = voucher_instance.get("categories")
        if categories:
            categories_text = "Categories: "

            for data in categories:
                categories_text = categories_text + data.name + "\n"

            voucher_text = voucher_text + categories_text

    return voucher_text


def process_metadata(old_metadata):
    process_string = ""

    if old_metadata:
        title_val = old_metadata.get('title', '')
        conditions_val = old_metadata.get('conditions', '')
        str_list = conditions_val.split('<br/>')
        conditions_val = '\n'.join(str_list)
        process_string = title_val + "\n" + conditions_val
        
    return process_string


def get_voucher_details(voucher_instance):

    if voucher_instance.get('brand_name'):
        voucher_details = """ coupon_name: %s\n discount_value: %s!\n discount_type: %s\n coupon_type: %s\n max_discount_value: %s\n owner: %s\n brand_name: %s\n coupon_code: %s\n coupon start date: %s\n coupon end date: %s\n apply Once Per Order: %s \n metadata: %s 

            """ % (
            voucher_instance.get('name'),
            StringUtilities.convert_number_to_string(voucher_instance.get("discount_value")),
            voucher_instance.get("discount_value_type"),
            voucher_instance.get("type"),
            StringUtilities.convert_number_to_string(voucher_instance.get("max_discount_value")),
            voucher_instance.get("owner"),
            voucher_instance.get('brand_name'),
            voucher_instance.get("code"),
            voucher_instance.get("start_date"),
            voucher_instance.get("end_date"),
            voucher_instance.get("apply_once_per_order"),
            process_metadata(voucher_instance.get("metadata", ""))
        )
    else:
        voucher_details = """ coupon_name: %s\n discount_value: %s!\n discount_type: %s\n coupon_type: %s\n max_discount_value: %s\n owner: %s\n coupon_code: %s\n coupon start date: %s\n coupon end date: %s\n apply Once Per Order: %s \n metadata: %s 

            """ % (
            voucher_instance.get('name'),
            StringUtilities.convert_number_to_string(voucher_instance.get("discount_value")),
            voucher_instance.get("discount_value_type"),
            voucher_instance.get("type"),
            StringUtilities.convert_number_to_string(voucher_instance.get("max_discount_value")),
            voucher_instance.get("owner"),
            voucher_instance.get("code"),
            voucher_instance.get("start_date"),
            voucher_instance.get("end_date"),
            voucher_instance.get("apply_once_per_order"),
            process_metadata(voucher_instance.get("metadata", ""))
        )
        
    return voucher_details


def get_voucher_creation_context(voucher_instance, old_obj= None):

    if not old_obj:
        prefix = " A New Coupon has been created at %s for %s with details as follows: \n" % (voucher_instance.get("created_at"), voucher_instance.get("store").store_name)
        voucher_text = prefix + get_voucher_details(voucher_instance)  + update_voucher_text_for_specific_products(voucher_instance)

    else:
        prefix = " Coupon has been updated!, which was created on %s for %s" % (voucher_instance.get("created_at"), voucher_instance.get("store").store_name)

        old_voucher_text = get_voucher_details(old_obj) + update_voucher_text_for_specific_products(old_obj)
        new_voucher_text = get_voucher_details(voucher_instance) + update_voucher_text_for_specific_products(voucher_instance)

        voucher_text = prefix + "\n  New voucher details as follows: \n" + new_voucher_text + "\n Old voucher details were:\n" + old_voucher_text

    return voucher_text

def get_voucher_creation_context_for_brand(voucher_data,store_instance,products_instance,variant_instance_dict):

    user = voucher_data.get('user')
    metadata = voucher_data.get('metadata')


    data = {    
            "subject":"A New Barter Coupon has been Created",
            "store_name":store_instance.store_name,
            "coupon_code":voucher_data.get('code'),
            "date":TimeUtilities.get_current_date(),
            "instagram_link":store_instance.instagram_link,
            "store_link":store_instance.store_url,
            "condition":metadata.get('conditions')
    }
    product_info_list=[]
    for product in products_instance:
        product_id = product.id
        variant = variant_instance_dict.get(product_id)
         
        product_info = {
            "product_name":product.name,
            "variant":variant.name,
            "price":variant.price_amount,
            "image_url":product.product_image_thumbnail()
        }
        product_info_list.append(product_info)
    
    data["products"] = product_info_list
    return data

@app.task
def send_email_for_voucher_creation(subject, voucher_text, mail_type="voucher_created",recipient_email =None, cc=None):
    
    if not cc:
        cc=[]

    MailImpl.send_mail_without_template(mail_type, voucher_text, subject,recipient_email, cc=cc)

@app.task
def send_email_for_brand_on_voucher_creation(voucher_dict,mail_type,recipient_email=None,cc=None):
    if not cc:
        cc =[]

    MailImpl.send_mail(mail_type,voucher_dict,recipient_email,cc=cc)
