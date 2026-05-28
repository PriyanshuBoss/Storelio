from django.db import IntegrityError
from django.http import JsonResponse
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet,ViewSetMixin
from rest_framework.mixins import ListModelMixin
import logging
from rest_framework.response import Response
import json
import logging
from django.db.models import Q,Count
import requests
from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
from saleor.rest_apis.reels.constants import REEL_UP_CLIENT_ID, REEL_UP_CLIENT_SECRET
from saleor.rest_apis.reels.helper import fetch_brand_cred, fetch_reels_playlist_response_serializer, fetch_reels_response_serializer, get_product_from_id_graphql, model_instance_to_dict, reel_up_thumbnail_upload, save_media_info, title_search, to_int, update_shopify_image_url_info
from saleor.rest_apis.reels.serializer import PaginationClassSet, ReelupMediaPlaylistMapSerializer, ReelupMediaPlaylistSerializer, ReelupStoreSerializer, UpdateReelupMediaPlaylistSerializer
from .tasks import clean_product_data_details_task, upload_and_check_shopify_media_task
from saleor.product.models import BrandVariantZaamoMapping, ReelUpBrandCollection, ReelUpMedia, ReelUpProductMap,ReelUpMediaPlaylist,ReelUpMediaPlaylistItems,ReelupStore

logger = logging.getLogger(__name__)


def authenticate_app_with_temp_code(code,url):
    try:
        url = f"https://{url}//admin/oauth/access_token"

        payload = json.dumps({
                    "code":code,
                    "client_id":REEL_UP_CLIENT_ID,
                    "client_secret":REEL_UP_CLIENT_SECRET
                    })

        headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
                }
        logger.info(payload)
        logger.info(headers)
        api_response = requests.request("POST", url, headers=headers, data=payload)
        logger.info(api_response)
        logger.info(api_response.content)
        response = api_response.json()
        logger.info(response)
        return response.get('access_token')
    
    except Exception as e:
        logger.info(e)
        return False

def upload_media_to_shopify_store(media_url,store_name,file_title):
    try:
        already_exist = ReelUpMedia.objects.filter(zaamo_media_url=media_url,shopify_store_name=store_name).first()
        
        if already_exist:
            return {'success':False,'message': f'Media already exists with id: {already_exist.shopify_file_id} and shopify_url: {already_exist.shopify_media_url}'}
        
        url,access_pass = fetch_brand_cred(store_name)
        
        if not access_pass:
            return {'success':False,"message":"Key is incorrect or not found."}
        
        url = f"https://{url}/admin/api/2023-10/graphql.json"
        payload = json.dumps({
                    "query": "mutation fileCreate($files: [FileCreateInput!]!) { fileCreate(files: $files) { files { alt createdAt id preview { status} } } }",
                    "variables": {
                        "files": {
                        "alt": file_title or media_url,
                        "contentType": "FILE",
                        "originalSource": media_url
                        }
                    }
                    })

        headers = {
                'X-Shopify-Access-Token': access_pass,
                'Content-Type': 'application/json'
                }
        
        api_response = requests.request("POST", url, headers=headers, data=payload)
        
        response = api_response.json()
        
        if response.get('errors'):
            return {'success':False,'shopify_error_message':response.get('errors')}
        
        g_id = response['data']['fileCreate']['files'][0]['id']

        if response:
            reel_up_inst = save_media_info(media_url,store_name,g_id,'',file_title)
            reel_up_thumbnail_upload(media_url,reel_up_inst)
            if reel_up_inst:
                upload_and_check_shopify_media_task.apply_async(args=[access_pass,url,g_id,media_url,store_name,reel_up_inst.id],countdown=300)
                reel_data = fetch_reels_response_serializer([reel_up_inst])[0]
                reel_data.update({'success':True})
                return reel_data

        return {'success':False,'message':api_response.text}

    except Exception as e:
        logger.exception(e)
        return {'success':False, "message":e}

def reel_up_media_upload(request):
    try:
    
        media_url = request.GET.get('media_url')
        file_title = request.GET.get('file_title')
        shopify_store_name = request.GET.get('shopify_store_name')
        
        if media_url and shopify_store_name:
            
            response = upload_media_to_shopify_store(media_url,shopify_store_name,file_title)

            return JsonResponse(response,safe=False)

    except Exception as e:

        logger.exception(e)
        return JsonResponse({"success":False,'error_message':e})

    return JsonResponse({"success":False,'error_message':"Invalid Input"})


def playlist_update_default(playlist_type,playlist_id,shopify_store_name):
    playlist_inst = ReelUpMediaPlaylist.objects.filter(id=playlist_id).first()

    if playlist_inst:

        ReelUpMediaPlaylist.objects.filter(type=playlist_type,store_name=shopify_store_name,rank=999999).update(rank=1)

        playlist_inst.rank=999999
        playlist_inst.save()

        return model_instance_to_dict(playlist_inst)
    
    else:
        return {'success':False,'message':'playlist not found'}



class UpdateDefaultPlaylist(APIView):

    def post(self,request):
        try:
        
            playlist_type = request.data.get('type')
            playlist_id = request.data.get('playlist_id')
            shopify_store_name = request.data.get('shopify_store_name')
            
            if playlist_type and shopify_store_name:
                
                response = playlist_update_default(playlist_type,playlist_id,shopify_store_name)

                return JsonResponse(response,safe=False)

        except Exception as e:

            logger.exception(e)
            return JsonResponse({"success":False})

        return JsonResponse({"success":False})



class ReelupUpdateandDelete(APIView):

    def post(self,request):
        try:
            reelup_media_id = request.data.get('reelup_media_id')
            file_title = request.data.get('file_title')
            action = request.data.get('action','')
            status = request.data.get('status','').lower()
            zaamo_media_url = request.data.get('zaamo_media_url')

            if not status in ['active','inactive']:
                status = None

            reel = ReelUpMedia.objects.filter(id = reelup_media_id).first()

            if reel:

                if action.lower()=='delete':
                    reel.delete()

                    response = {'success':True, 'message':f'Reel delete with id :: {reelup_media_id}'}

                    return JsonResponse(response,safe=False)
                
                if file_title:
                    reel.title = file_title

                if zaamo_media_url:
                    reel.zaamo_media_url = zaamo_media_url

                if status:
                    reel.status = status
                    
                    
                reel.save()

                response = fetch_reels_response_serializer([reel])
            
            else:
                response = {'success':False, 'message':f'No reel found with id :: {reelup_media_id}'}

            return JsonResponse(response,safe=False)

        except Exception as e:
            logger.exception(e)
            return JsonResponse({"success":False})

def fetch_products_from_shopify(request):
    
    try:
    
        shopify_store_name = request.GET.get('shopify_store_name')
        search_name = request.GET.get('search_name','')
        end_cursor = request.GET.get('end_cursor')
        response = []
        
        url,access_pass = fetch_brand_cred(shopify_store_name)

        if not access_pass:
            return JsonResponse({"success":False})
        
        store_name = shopify_store_name
        
        url = f"https://{url}/admin/api/2023-10/graphql.json"
        payload = "{\"query\":\"query {\\r\\n  \\tproducts(first: 50, query:\\\"title:<search_name>\\\") {\\r\\n          pageInfo{\\r\\n              endCursor\\r\\n          }\\r\\n    \\tedges {\\r\\n      \\tnode {\\r\\n        \\tid\\r\\n        \\ttitle\\r\\n        \\thandle\\r\\n            onlineStoreUrl\\r\\n            onlineStorePreviewUrl\\r\\n             featuredImage{url}\\r\\n      \\t}\\r\\n    \\t}\\r\\n  \\t}\\r\\n}\",\"variables\":{}}"
        if search_name:
            payload = payload.replace('<search_name>',f"*{search_name}*")
        else:
            payload = payload.replace('<search_name>',"*")
        if end_cursor:
            payload = payload.replace('first: 50,',f'first: 50, after:\\\"{end_cursor}\\\"')

        headers = {
                'X-Shopify-Access-Token': access_pass,
                'Content-Type': 'application/json'
                }
        
        api_response = requests.request("POST", url, headers=headers, data=payload)
        
        api_response = api_response.json()
        
        if api_response.get('errors'):
            return JsonResponse({'success':False,'shopify_error_message':api_response.get('errors')})
        
        edges = api_response['data']['products']['edges'] or []
        current_end_cursor = api_response['data']['products']['pageInfo']['endCursor']
        
        for node_dict in edges:
            node = node_dict['node']
            g_id = node.get('id')
            product_id_brand = g_id.split('/')[-1]
            image = node.get('featuredImage')
            image_url = ''

            if image:
                image_url = image.get('url')

            response.append({
                'product_id_brand':product_id_brand,
                'product_name':node.get('title'),
                'slug':node.get('handle'),
                'shopify_store_url':node.get('onlineStoreUrl') or node.get('onlineStorePreviewUrl'),
                'image_url':image_url
                             })

        return JsonResponse({'data':response,'end_cursor':current_end_cursor})

    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False,'message':e})
    
def fetch_or_create_collection_id_from_brand(shopify_store_name):
    collection_zaamo = ReelUpBrandCollection.objects.filter(brand_name=shopify_store_name).first()
    
    if collection_zaamo:
        return collection_zaamo.brand_collection_id
    
    url,access_pass = fetch_brand_cred(shopify_store_name)

    if not access_pass:
        return JsonResponse({"success":False})
    
    store_name = shopify_store_name
    url = f"https://{url}/admin/api/2023-10/graphql.json"
    payload = json.dumps({
                "query": "mutation CollectionCreate($input: CollectionInput!) { collectionCreate(input: $input) { userErrors { field message } collection { id title descriptionHtml handle sortOrder ruleSet { appliedDisjunctively rules { column relation condition } } } } }",
                "variables": {
                    "input": {
                    "title": "Zaamo",
                    "descriptionHtml": "<b>ZAAMO</b> collection."
                    }
                }
                })
    
    
    headers = {
            'X-Shopify-Access-Token': access_pass,
            'Content-Type': 'application/json'
            }
    
    api_response = requests.request("POST", url, headers=headers, data=payload)
    
    api_response = api_response.json()

    if api_response.get('errors'):
        return None

    if api_response:
        collection_id = api_response['data']['collectionCreate']['collection']['id']
        collection_id = collection_id.split('/')[-1]
        reel_up_collection_inst = ReelUpBrandCollection()
        reel_up_collection_inst.brand_collection_id = collection_id
        reel_up_collection_inst.brand_name = store_name
        reel_up_collection_inst.save()
        return collection_id

    return None

def clean_meta_payload(g_id,value,shopify_product_id):
    return {
                    "query": "mutation updateProductMetafields($input: ProductInput!) { productUpdate(input: $input) { product { id metafields(first: 3) { edges { node { id namespace key value } } } } userErrors { message field } } }",
                    "variables": {
                        "input": {
                        "metafields": [
                            {
                            "id": g_id,
                            "value": f"{value}"
                            }
                        ],
                        "id": f"gid://shopify/Product/{shopify_product_id}"
                        }
                    }
                    }

def map_product_with_zaamo_collection_product_meta(shopify_media_ids,shopify_product_id,collection_id,shopify_store_name):
    
    
    brand_variant_mapping = BrandVariantZaamoMapping.objects.filter(product_id_brand=shopify_product_id).first()
    
    zaamo_product_id = ''
    zaamo_shopify_product_id = ''

    if brand_variant_mapping:
        zaamo_product_id = brand_variant_mapping.product_zaamo_id
        zaamo_shopify_product = brand_variant_mapping.product_zaamo.product_zaamo_shopify_mapping.first()
        zaamo_shopify_product_id = zaamo_shopify_product.product_id_brand if zaamo_shopify_product else ''
    
    
    url,access_pass = fetch_brand_cred(shopify_store_name)

    if not access_pass:
        return JsonResponse({"success":False})
    
    store_name = shopify_store_name

    variables = {"id":f"gid://shopify/Collection/{collection_id}",
                 "productIds": [
                    f"gid://shopify/Product/{shopify_product_id}"
                    ]}

    url = f"https://{url}/admin/api/2023-10/graphql.json"

    payload = json.dumps({
            "query": "mutation collectionAddProducts($id: ID!, $productIds: [ID!]!) { collectionAddProducts(id: $id, productIds: $productIds) { collection { id title productsCount products(first: 10) { nodes { id title } } } userErrors { field message } } }",
            "variables": variables
            })
    
    
    headers = {
            'X-Shopify-Access-Token': access_pass,
            'Content-Type': 'application/json'
            }
    
    api_response = requests.request("POST", url, headers=headers, data=payload)
    

    payload = json.dumps({
            "query": "query getProductMetafields($id: ID!) { product(id: $id) {  id metafields(first: 3) { edges { node { id namespace key value } } } }  }",
            "variables": {
                "id": f"gid://shopify/Product/{shopify_product_id}"
            }
            })

    
    api_response = requests.request("POST", url, headers=headers, data=payload)
    
    api_response = api_response.json()

    payload = None

    if api_response:
        meta_fields  = api_response['data']['product']['metafields']['edges']
        for meta in meta_fields:

            namespace = meta['node']['namespace']
            g_id =  meta['node']['id']

            if namespace=='reelupzaamomedia':
                payload = json.dumps(clean_meta_payload(g_id,shopify_media_ids,shopify_product_id))

            elif namespace=='zaamo_product_id':
                payload = json.dumps(clean_meta_payload(g_id,zaamo_product_id,shopify_product_id)) 

            elif namespace=='zaamo_shopify_product_id':
                payload = json.dumps(clean_meta_payload(g_id,zaamo_shopify_product_id,shopify_product_id)) 
                
    if not payload:
        payload = json.dumps({
                "query": "mutation updateProductMetafields($input: ProductInput!) { productUpdate(input: $input) { product { id metafields(first: 3) { edges { node { id namespace key value } } } } userErrors { message field } } }",
                "variables": {
                    "input": {
                    "metafields": [
                        {
                        "namespace": "reelupzaamomedia",
                        "key": "media",
                        "type": "single_line_text_field",
                        "value": f"{shopify_media_ids}"
                        },
                        {
                        "namespace": "zaamo_product_id",
                        "key": "media",
                        "type": "single_line_text_field",
                        "value": f"{zaamo_product_id}"
                        },
                        {
                        "namespace": "zaamo_shopify_product_id",
                        "key": "media",
                        "type": "single_line_text_field",
                        "value": f"{zaamo_shopify_product_id}"
                        }
                    ],
                    "id": f"gid://shopify/Product/{shopify_product_id}"
                    }
                }
                })

    
    api_response = requests.request("POST", url, headers=headers, data=payload)

    api_response = api_response.json()

    if api_response:
        product = api_response['data']['productUpdate']['product']
        if product:
            return True

    return False

def tag_product_to_shopify_reelup(request):

    try:
        
        shopify_store_name = request.GET.get('shopify_store_name')
        status = request.GET.get('status')
        
        tag_status = True if status=='active' else False

        reelup_media_ids = request.GET.get('reelup_media_ids','')
        reelup_media_ids = reelup_media_ids.replace('[','').replace(']','').split(',')

        shopify_product_id = request.GET.get('shopify_product_id')
        product_name = request.GET.get('product_name')
        slug = request.GET.get('slug')
        shopify_product_url = request.GET.get('shopify_product_url')
        response = dict()
        
        if shopify_store_name and reelup_media_ids and shopify_product_id:
            
            reel_up_media_insts = ReelUpMedia.objects.filter(id__in=reelup_media_ids)
            
            if not reel_up_media_insts:
                return JsonResponse({"success":False,'message':'reel not exist'})

            collection_id = fetch_or_create_collection_id_from_brand(shopify_store_name)

            if not collection_id:
                response = {'success':False,'message':'Collection not found in brand'}
            
            mapping_ids = []
            for reelup_media_id in reelup_media_ids:
                reel_tag, _ = ReelUpProductMap.objects.update_or_create(reel_up_media_id=reelup_media_id,shopify_product_id=shopify_product_id,
                                                          defaults={'shopify_product_slug':slug,
                                                           'shopify_product_url':shopify_product_url,
                                                           'status':'active' if tag_status else 'inactive','product_name':product_name,
                                                           'shopify_collection_id':collection_id})
                mapping_ids.append(reel_tag.id)
                
            clean_product_data_details_task.delay(shopify_product_id,shopify_store_name,mapping_ids)

            reel_up_media_insts_active = ReelUpProductMap.objects.filter(status='active',shopify_product_id=shopify_product_id).select_related('reel_up_media')
            
            shopify_media_ids = []

            for reel_up_media_inst in reel_up_media_insts_active:
                shopify_media_ids.append(to_int(reel_up_media_inst.reel_up_media.shopify_file_id))

            status = map_product_with_zaamo_collection_product_meta(shopify_media_ids,shopify_product_id,collection_id,shopify_store_name)

            if status:
                response = {'success':True}
                return JsonResponse(response)

    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False,'message':e})
    
    return JsonResponse({"success":False})

class FetchReels(ListModelMixin,GenericViewSet):

    paginate_by = 10
    pagination_class = PaginationClassSet

    def get_queryset(self,request):

        shopify_store_name = request.GET.get('shopify_store_name')
        product_id = request.GET.get('product_id')
        shopify_media_id = request.GET.get('shopify_media_id')
        reelup_media_id = request.GET.get('reelup_media_id') 
        status = request.GET.get('status','active') 
        title = request.GET.get('title') 

        if shopify_store_name:
            
            store_reels = ReelUpMedia.objects.filter(shopify_store_name=shopify_store_name).prefetch_related('media_mapping')
            
            if product_id:
                store_reels = store_reels.filter(media_mapping__shopify_product_id=product_id)

            if shopify_media_id:
                store_reels = store_reels.filter(shopify_file_id=shopify_media_id)

            if reelup_media_id:
                store_reels = store_reels.filter(id=reelup_media_id)

            if status:
                store_reels = store_reels.filter(status=status)

            if title:
                store_reels = title_search(title,store_reels,'product_ReelUpMedia')
            
            return store_reels
        
        return ReelUpMedia.objects.none()

    def list(self,request):
        try:
            response = []
            store_reels = self.get_queryset(request).order_by('-created_at')
            
            try:
                data = self.paginate_queryset(queryset=store_reels)
            except Exception as e:
                data = []
                return Response({"reels": data}, status=200)
            
            if data:
                response = fetch_reels_response_serializer(data)
            else:
                response = fetch_reels_response_serializer(store_reels)

            return Response({"reels": response}, status=200)

        except Exception as e:
            logger.exception(e)
            return Response({"success":False}, status=400)


class CreateReelupMediaPlaylist(APIView):

    serializer_class = ReelupMediaPlaylistSerializer

    def post(self,request):
        try:
            serializer  = ReelupMediaPlaylistSerializer(data=self.request.data)
            
            if serializer.is_valid():
                try:
                    created_playlist = ReelUpMediaPlaylist.objects.create(**serializer.data)
                    created_playlist_data = model_instance_to_dict(created_playlist)

                except IntegrityError as e:
                    return Response({"success":False,"message":f"Title already exists, error: {e}"}, status=400)

            else:
                return Response({"success": False,"message":serializer.errors}, status=400)
            return Response({"success": True,'data':created_playlist_data}, status=200)

        except Exception as e:
            logger.exception(e)
            return Response({"success":False,"message":e}, status=400)

class UpdateOrDeleteReelupMediaPlaylist(APIView):

    serializer_class = UpdateReelupMediaPlaylistSerializer

    def post(self,request):
        try:
            serializer  = UpdateReelupMediaPlaylistSerializer(data=self.request.data)
            
            if serializer.is_valid():
                data = dict(serializer.data)
                operation = data.pop('operation')
                playlist_id = data.pop('id')

                playlist_qs = ReelUpMediaPlaylist.objects.filter(id=playlist_id)

                if not playlist_qs:
                    return Response({"success": False,'mesage':f'No playlist found with id: {playlist_id}'}, status=404)
                
                if operation=='update':
                    try:
                        updated = ReelUpMediaPlaylist.objects.filter(id=playlist_id).update(**data)
                        
                        if updated:
                            updated_playlist = ReelUpMediaPlaylist.objects.get(id=playlist_id)
                            updated_playlist_data = model_instance_to_dict(updated_playlist)

                            return Response({"success": True,'data':updated_playlist_data}, status=200)

                        else:
                            return Response({"success": False,'message':'Update unsuccessful'}, status=200)

                    
                    except IntegrityError as e:
                        return Response({"success":False,"message":f"Title already exists, error: {e}"}, status=400)
                    
                else:
                    ReelUpMediaPlaylist.objects.filter(id=playlist_id).delete()
                    return Response({"success": True,'message':'Delete successful'}, status=200)
                
            else:
                return Response({"success": False,"message":serializer.errors}, status=400)


        except Exception as e:
            logger.exception(e)
            return Response({"success":False,"message":e}, status=400)


class MapReelupPlaylistToMedia(APIView):

    serializer_class = ReelupMediaPlaylistMapSerializer

    def post(self,request):
        try:
            serializer  = ReelupMediaPlaylistMapSerializer(data=self.request.data)
            
            if serializer.is_valid():
                operation = serializer.data.pop('operation')
                playlist_id = serializer.data.pop('playlist_id')
                media_id = serializer.data.pop('media_id')
                rank = serializer.data.pop('rank')
                playlist_qs = ReelUpMediaPlaylist.objects.filter(id=playlist_id).first()
                media_qs = ReelUpMedia.objects.filter(id=media_id).first()

                if not playlist_qs or not media_qs:
                    return Response({"success": False,'mesage':f'Playlist or Media not found with playlist_id: {playlist_id}, media_id:{media_id}'}, status=404)
                
                if operation=='add':
                    updated = ReelUpMediaPlaylistItems.objects.update_or_create(reel_up_media_playlist=playlist_qs,
                                                                                reel_up_media=media_qs,
                                                                                defaults={'rank':rank})
                    
                    if updated:
                        return Response({"success": True,'message':'Tagging successful'}, status=200)

                    else:
                        return Response({"success": False,'message':'Tagging unsuccessful'}, status=200)
                else:
                    ReelUpMediaPlaylistItems.objects.filter(reel_up_media_playlist=playlist_qs,
                                                            reel_up_media=media_qs).delete()
                    return Response({"success": True,'message':'Delete successful'}, status=200)
                    
            else:
                return Response({"success": False,"message":serializer.errors}, status=400)

        except Exception as e:
            logger.exception(e)
            return Response({"success":False,"message":e}, status=400)


class ReelupStoreApi(APIView):

    serializer_class = ReelupStoreSerializer

    def _clean_metadata(self, req_meta,cur_meta):

        for key in cur_meta.keys():

            if req_meta.get(key)!=None :
                cur_meta[key] = req_meta.get(key)
        
        return cur_meta

    def _default_meta(self):
        return {
                "added_reel": False,
                "enabled_app": False,
                "created_wigdet": False,
                "tagged_product": False,
                "customized_design": False,
                "enable_product_page_reel": False,
                "stories_width_mobile": "60",
                "playlist_width_mobile": "150",
                "stories_width_desktop": "80",
                "pop_width_mobile": "70",
                "pop_width_desktop": "100",
                "gap_between_components": "20",
                "playlist_width_desktop": "150",
                "ProductPageReel_width_mobile": "20",
                "productPageReel_width_desktop": "20",
                "playlist_gap_between_components": "20",
                "productPageReel_gap_between_components": "20",
                "reelpop_width_desktop": "130",
                "reelpop_width_mobile": "130",
                "reelpop_spacing_horizontal": "30",
                "reelpop_spacing_vertical": "40",
                "reelpop_position": "right"
                }
    
    def post(self,request):
        try:
            serializer  = ReelupStoreSerializer(data=self.request.data)

            if serializer.is_valid():
                req_metadata = dict(serializer.data)
                store_name = req_metadata.pop('store_name')
                url = req_metadata.pop('url')
                access_token = req_metadata.pop('access_token')

                # access_token = authenticate_app_with_temp_code(code,url)
                #remove authentication as it will be done via frontend

                reelup_store_inst = ReelupStore.objects.filter(store_name=store_name).first()
                
                if reelup_store_inst:
                    cur_metadata = reelup_store_inst.metadata
                    clean_meta = self._clean_metadata(req_metadata,cur_metadata)
                    reelup_store_inst.metadata = clean_meta

                    if access_token:
                        reelup_store_inst.access_pass = access_token

                    if url:
                        reelup_store_inst.url = url
                    reelup_store_inst.save()
                
                    response = {'store_name':store_name}
                    response.update(reelup_store_inst.metadata)

                    return Response({"success": True,'message':'Updated successfully',"ReelupStore": response}, status=200)
                
                else:
                    if not access_token:
                        return Response({"success": False,"message":f'Authorization unsuccessful for store:: {store_name}, url:: {url}'}, status=400)

                    default_meta = self._default_meta()
                    
                    clean_meta = self._clean_metadata(req_metadata,default_meta)
                    ReelupStore.objects.create(store_name=store_name,url=url,access_pass=access_token,metadata=clean_meta)
                    response = {'store_name':store_name}
                    response.update(clean_meta)

                    return Response({"success": True,'message':'Created successfully',"ReelupStore": response}, status=200)                    

            else:
                return Response({"success": False,"message":serializer.errors}, status=400)

        except Exception as e:
            logger.exception(e)
            return Response({"success":False,"message":e}, status=400)

    def get(self,request):
        try:
            store_name = self.request.GET.get('store_name')

            if store_name:
                
                reelup_store_inst = ReelupStore.objects.filter(store_name=store_name).first()
                response = {'store_name':store_name}
                response.update(reelup_store_inst.metadata)
                return Response({"ReelupStore": response}, status=200)
            
            else:

                return Response({"success":False,'message': 'No store name recieved.'}, status=400)

        except Exception as e:
            logger.exception(e)
            return Response({"success":False}, status=400)


class FetchReelMediaPlaylist(ListModelMixin,GenericViewSet):

    paginate_by = 10
    pagination_class = PaginationClassSet
    store_name = ''

    def get_queryset(self,request):

        store_name = request.GET.get('store_name')
        order_by = request.GET.get('order_by','rank')
        order_dir = request.GET.get('order_dir','asc')
        playlist_id = request.GET.get('playlist_id')
        title = request.GET.get('title')
        type = request.GET.get('type','').lower()
        status = request.GET.get('status','').lower()
        
        if store_name:
            self.store_name = store_name
            playlist_insts = ReelUpMediaPlaylist.objects.filter(store_name=store_name)\
                        .prefetch_related('reel_up_media_playlist_map','reel_up_media_playlist_map__reel_up_media','reel_up_media_playlist_map__reel_up_media__media_mapping')
        else:
            playlist_insts = ReelUpMediaPlaylist.objects.all()

        if title:
            playlist_insts = title_search(title,playlist_insts,'product_ReelUpMediaPlaylist')

        if type:
            playlist_insts = playlist_insts.filter(type=type)

        if status:
            playlist_insts = playlist_insts.filter(status=status)

        if playlist_id:
            playlist_insts = playlist_insts.filter(id=playlist_id)
        
        if order_by:

            if order_dir=='desc':
                order_by = f"-{order_by}"
                
            playlist_insts = playlist_insts.order_by(order_by)

        return playlist_insts

    def fetch_playlist_type_count(self,store_name=None):

        if store_name:
            playlist_insts = ReelUpMediaPlaylist.objects.filter(status='active',store_name=store_name).values('type').annotate(count = Count('type')).order_by('type')

        else:
            playlist_insts = ReelUpMediaPlaylist.objects.filter(status='active').values('type').annotate(count = Count('type')).order_by('type')

        response = {
            "active_playlist_count": 0,
            "active_pop_count": 0,
            "active_story_count": 0,
        }

        for inst in playlist_insts:
            response[f"active_{inst['type']}_count"] = inst['count']

        return response


    def list(self,request):
        try:
            
            playlist_insts = self.get_queryset(request)
            try:
                data = self.paginate_queryset(queryset=playlist_insts)
            except Exception as e:
                data = []
                return Response({"playlists": data}, status=200)
            
            if data:
                response = fetch_reels_playlist_response_serializer(data)
            else:
                response = fetch_reels_playlist_response_serializer(playlist_insts)

            playlist_count = self.fetch_playlist_type_count(self.store_name)
            
            playlist_count.update({"playlists": response})
            return Response(playlist_count, status=200)

        except Exception as e:
            logger.exception(e)
            return Response({"success":False}, status=400)
