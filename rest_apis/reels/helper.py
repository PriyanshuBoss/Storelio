import json
import logging
import time
import requests
from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
from saleor.graphql.product.filters import parse_phrase_for_search
from saleor.product.models import ReelUpMedia, ReelUpProductMap, ReelupStore
from django.contrib.postgres.search import SearchVector
from django.db.models import Q
from io import BytesIO
import time
from django.core.files.uploadedfile import InMemoryUploadedFile

logger = logging.getLogger(__name__)


def save_media_info(media_url,store_name,g_id,shopify_image_url,title):
    g_id = g_id.split('/')[-1]
    reel_up_media = ReelUpMedia()
    reel_up_media.shopify_file_id = g_id
    reel_up_media.shopify_media_url = shopify_image_url
    reel_up_media.zaamo_media_url = media_url
    reel_up_media.shopify_store_name = store_name
    reel_up_media.title = title
    reel_up_media.save()
    return reel_up_media

def update_shopify_image_url_info(g_id,shopify_image_url,reel_up_id):
    g_id = g_id.split('/')[-1]
    reel_up_media = ReelUpMedia.objects.filter(id=reel_up_id).first()
    reel_up_media.shopify_media_url = shopify_image_url
    reel_up_media.save()
    return reel_up_media
    
def to_int(value):
    try:
        return int(value)
    except:
        value


def upload_and_check_shopify_media(access_pass,url,g_id,reel_up_id):
    headers = {
            'X-Shopify-Access-Token': access_pass,
            'Content-Type': 'application/json'
            }
    
    query = "query { node(id: \"###\") { id ... on GenericFile { url }  } }"
    query = query.replace('###',g_id)
    payload = json.dumps({
                "query": query
                })
    
    query_response = requests.request("POST", url, headers=headers, data=payload)
    
    query_response = query_response.json()
    shopify_image_url = query_response['data']['node']['url']
    reel_ip_media = update_shopify_image_url_info(g_id,shopify_image_url,reel_up_id)
    reel_ip_media.images.all().delete()
    reel_up_thumbnail_upload(url,reel_ip_media)


def reel_up_thumbnail_upload(url,reel):

    random_string = str(int((time.time() * 1000)))
    file_name = random_string
    upload_reel_image_to_ecom(reel, url, file_name, alt='')

def upload_reel_image_to_ecom(reel, url, file_name, alt=''):
    if reel and url:
        image_data = retrieve_image(url, file_name)

        if image_data:
            image = reel.images.create(image=image_data, alt=alt)

def retrieve_image(url, file_name):
    try:
        header = {"Accept":'*/*',
                "content-type":"application/json",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36"
        }

        response = requests.get(url, headers=header)
        fobject = BytesIO(response.content)
        
        return InMemoryUploadedFile(fobject,'ImageField',
            file_name + '.png',
            'image/png',
            len(fobject.getbuffer()), None)
    except:

        return None
    

def clean_product_data_details(shopify_product_id,shopify_store_name,mapping_ids):
    product = get_product_from_id_graphql(shopify_product_id,shopify_store_name)
    images_url_list = []
    selling_price=None
    cost_price=None
    product_name = product.get('title')
    images = product.get('images')
    
    if images:
        images = images["edges"]
        for image in images:
                node = image["node"]

                if not node.get('url'):
                    continue
                
                images_url_list.append(node.get('url'))

    variants = product.get('variants')

    if variants:
        node = variants["edges"][0]["node"]
        selling_price = node.get('price')
        cost_price = node.get('compareAtPrice')
    
    meta={"product_name":product_name,
            "images":images_url_list,
            "msp":selling_price,
            "mrp":cost_price}

    ReelUpProductMap.objects.filter(id__in=mapping_ids).update(metadata=meta)

def fetch_reels_response_serializer(store_reels):
    
    response = []

    for store_reel in store_reels:
        tagged_products = store_reel.media_mapping.filter(status='active')
        tagged_products_list = []

        for tagged_product in tagged_products:
            tagged_products_list.append({
                'shopify_product_id':tagged_product.shopify_product_id,
                'product_name':tagged_product.metadata.get('product_name') or tagged_product.product_name,
                'shopify_product_slug':tagged_product.shopify_product_slug,
                'shopify_product_url': tagged_product.shopify_product_url,
                'images':tagged_product.metadata.get('images'),
                'msp':tagged_product.metadata.get('msp'),
                'mrp':tagged_product.metadata.get('mrp') 

            })
        response.append({
            'shopify_media_url':store_reel.shopify_media_url,
            'shopify_media_id':store_reel.shopify_file_id,
            'reelup_media_id':store_reel.id,
            'created_at':store_reel.created_at,
            'title':store_reel.title,
            'zaamo_media_url':store_reel.zaamo_media_url,
            'status':store_reel.status,
            'tagged_products':tagged_products_list,
            'thumbnail':store_reel.reel_image_thumbnail()
            })
    
    return response

def model_instance_to_dict(model_instance):

    data = {}
    if model_instance:
        for field in model_instance._meta.fields:
            data[field.attname] =str(getattr(model_instance, field.attname))

    return data 


def fetch_reels_playlist_response_serializer(playlists):
    
    response = []
    for playlist in playlists:
        mappings = []
        reel_mappings = playlist.reel_up_media_playlist_map.filter(reel_up_media__status='active') or []
        
        for mapping in reel_mappings:
            store_reel = mapping.reel_up_media
            media_response = fetch_reels_response_serializer([store_reel])
            mappings.extend(media_response)
        playlist_dict = model_instance_to_dict(playlist)
        playlist_dict.update({'media_objs':mappings})
        response.append(playlist_dict)
    
    return response


def title_search(phrase,model,search_table):

    search_vector = SearchVector('title')

    query = parse_phrase_for_search(phrase)

    qs =  model.annotate(vector = search_vector)

    qs = qs.extra(
            where=[
                f'''
                to_tsvector('english',concat_ws(' ',
                    {search_table}.title
                )) @@ to_tsquery('english', %s)
                '''
            ],
            params=[query],
        )
    return qs


def get_product_from_id_graphql(product_id,brand_name):

    store_url,access_pass = fetch_brand_cred(brand_name)
    payload = {"query":"query {\n  product(id: \"gid://shopify/Product/###\") {\n    legacyResourceId\n    status\n    images(first: 7) {\n      edges {\n        node {\n          id\n          url\n          altText\n          width\n          height\n        \n        }\n      }\n    }\n    title\n    variants(first: 1) {\n      edges {\n        node {\n          price\n          compareAtPrice\n        }\n      }\n    }\n    vendor\n  }\n}"}

    payload['query'] = payload['query'].replace('###',product_id)

    url = f"https://{store_url}/admin/api/2023-10/graphql.json"


    headers = {
            'X-Shopify-Access-Token': access_pass,
            'Content-Type': 'application/json'
            }
    

    api_response = requests.request("POST", url, headers=headers, json=payload)

    api_response = api_response.json()
    
    if api_response.get('data'):
        return api_response['data']['product']

    return None


    
def fetch_brand_cred(store_name):
    try:
        brand_cred = ReelupStore.objects.filter(store_name=store_name).first()

        if brand_cred and brand_cred.access_pass:
            return brand_cred.url, brand_cred.access_pass

        brand_cred = BrandCred.objects.filter(Q(brand__brand_name=store_name)|Q(brand__private_metadata__source_name=store_name)).first()
        access_pass = get_fernet_encoder().decrypt(brand_cred.access_pass.encode()).decode('utf-8')

        return brand_cred.url, access_pass
    
    except Exception as e:
        logger.exception(e)
        return None,None
    
