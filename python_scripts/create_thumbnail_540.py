
import base64
from io import StringIO
from saleor.product import models
from saleor.product.templatetags.product_images import get_product_image_thumbnail
from versatileimagefield.image_warmer import VersatileImageFieldWarmer
from saleor.core.utils import build_absolute_uri
from saleor.utilities.api_client import ApiClient
from saleor.external_services.mail.mail_impl import MailImpl
import csv

def create_thumbnails(instance, size_set, image_attr=None):
    if not image_attr:
        image_attr = "image"
    image_instance = getattr(instance, image_attr)
    if image_instance.name == "":
        # There is no file, skip processing
        return
    warmer = VersatileImageFieldWarmer(
        instance_or_queryset=instance, rendition_key_set=size_set, image_attr=image_attr
    )
    print(f"Creating thumbnails for {instance.product_id}")
    num_created, failed_to_create = warmer.warm()
    if num_created:
        print(f"Created {num_created} thumbnails")
        return True
    if failed_to_create:
        print(f"Failed to generate thumbnails: {failed_to_create}")
        return False

def check_540_image(published=True):
    if published:
        images = models.ProductImage.objects.filter(product__is_published=True).order_by('id')
    
    else:
        images = models.ProductImage.objects.all().order_by('id')

    print(images.count())
    
    w = [['product_id','thumbnail_url','thumbnail_created']]
    for image in images:
        
        url = build_absolute_uri(get_product_image_thumbnail(image,540,method="thumbnail"))
        api = ApiClient(url=url)
        api.get()
        
        if api.fetch_response_code() in [200, 201]:
            continue
        create_image = create_thumbnails(image,[("product_gallery", "thumbnail__540x540"),])
        
        w.append([image.product_id,url,create_image])

    f = StringIO() 

    csv.writer(f).writerows(w)
    base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
    attachment_json = {"content": base_encoded_file, "type": "application/csv", "filename": f"image_540_thumbnail_status.csv"}

    attachments = [attachment_json]

    m = MailImpl()
    
    m.send_mail_with_attachment('brand_owner_csv',f'Hi, Please find the attached CSVs','thumbnail 540 status',attachments,'nitanshub@zaamo.co')
    m.send_mail_with_attachment('brand_owner_csv',f'Hi, Please find the attached CSVs','thumbnail 540 status',attachments,'priyanshu@zaamo.co')
    
'''
from saleor.python_scripts.create_thumbnail_540 import check_540_image
check_540_image()
'''