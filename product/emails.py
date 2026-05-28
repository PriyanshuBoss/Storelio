from saleor.product import SourcingRequestStatus
from saleor.product.templatetags.product_images import get_product_image_thumbnail
from ..celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl
from django.conf import settings


def sourcing_request_email_context(data ):
    product_slug = data['product'].slug
    product_url = settings.HOME_LINK
    product_url += '/products/'
    product_url+=product_slug
    
    mail_text = """
    A new sourcing request has been created with the following details :: {}
    Store Name :  {} {}
    Store URL : {}  {}
    Influencer Managers : {} {}
    Product Name : {} {}
    Pdp Link : {} {}
    Product MSP : {} {}
    Variant : {} {}
    Brand : {} {}
    Brand Active : {} {}
    Brand Barter : {} {}
    Brand TMO : {} {}
    Brand Barter Guidelines : {} {}
    Brand Managers : {} {}
    Status : {} {}
    Brand Collab : {} {}
    Last Updated By : {} {}
    """.format("\n", data['store'].store_name, "\n", data['store'].store_url, "\n", data['influencer_managers'],  "\n",
            data['product'].name, "\n", product_url, "\n", data['product'].msp, "\n",
            data['variant'].name, "\n", data['brand'].brand_name, "\n", data['brand_active'], "\n", data['brand_barter'], "\n", data['brand_tmo'],"\n",data['brand_barter_guidelines'], "\n" , data['brand_managers'], "\n",
            SourcingRequestStatus.REQUEST_RECIEVED, "\n", data["brand_collab"], "\n", data["user_last_updated"], "\n"
    )
    
    return mail_text


@app.task
def send_sourcing_request_email(subject, souring_request_text, mail_type="sourcing_request", cc=None):
    
    if not cc:
        cc=[]

    MailImpl.send_mail_without_template(mail_type, souring_request_text, subject, cc=cc)
