from saleor.celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl


def push_inventory_sync(json_list):
    from saleor.external_services.integrations.base import BaseProductCreate

    base_product_create = BaseProductCreate()
    return base_product_create.create_or_update_db_items(json_list)

def update_brand_collection(json_list):
    
    from saleor.external_services.integrations import BrandCollectionCreate
    brand_collection_inst = BrandCollectionCreate()
    brand_ids = set()
    
    for json_item in json_list:

        if json_item.get("brand.brand"):
            brand_ids.add(json_item.get("brand.brand"))

    for brand_id in brand_ids:
        brand_collection_inst.save_staff_brand_collection(brand_id=brand_id)
        

@app.task(queue='onboarding_queue')
def push_inventory_task(json_list):
    push_inventory_sync(json_list)

@app.task(queue='priority_queue')
def push_inventory_csv_task(json_list):
    push_inventory_sync(json_list)
    update_brand_collection(json_list)
    

@app.task
def send_post_resync_confirmation_email(source,response, mail_type):
    
    if mail_type == "resync_failure":
        subject = f"{source} Resync failed"
        recipient_list = ['priyanshu+resync_failure@zaamo.co','nitanshub+resync_failure@zaamo.co']
    else:
        subject = f"{source} Resync success"
        recipient_list = ['priyanshu+resync_success@zaamo.co','nitanshub+resync_success@zaamo.co']

    mail_text = response
    for recipient in recipient_list:
        MailImpl.send_mail_without_template(mail_type,mail_text,subject,recipient)

