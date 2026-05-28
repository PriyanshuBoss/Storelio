import json
from django.http import JsonResponse,HttpResponse
from django.db.models import F, Subquery, OuterRef
import logging

from saleor.account.models import InstagramUser, Post, Media
from saleor.rest_apis.instagram.helper import auth_body, clean_message_response, comment_body, conversation_body, long_live_access_body, media_body, message_api_body, save_profile_image, user_details_body, validate_comment
from saleor.rest_apis.instagram.helper import auth_body, get_instagram_login_body, long_live_access_body, media_body, message_api_body, validate_comment, save_post
from saleor.store.models import StoreInfo
from saleor.utilities.api_client import ApiClient
from saleor.utilities.json_utilities import JsonUtilities
from saleor.utilities.number_utilities import NumberUtilities
logger = logging.getLogger(__name__)
import time

class InstagramBase:

    graph_url = 'https://graph.instagram.com/v20.0/'
    ig_user_id = ''
    access_token = ''
    
    def fetch_long_live_token(self,short_lived_acces_token):
        # time.sleep(1)
        body = long_live_access_body(short_lived_acces_token)
        api_client = ApiClient(host=self.graph_url,path='access_token')
        api_client.params={}
        api_client.update_url_params(body)
        api_client.get()
        response = api_client.fetch_response()

        access_token = response.get('access_token')
        
        if access_token:
            self.access_token = access_token
            return access_token
        
        return False

    def fetch_access_token(self,code,redirect_url,store_id):
        
        url = f"https://api.instagram.com/oauth/access_token"
        
        body = auth_body(code,redirect_url)
        api_client = ApiClient(url=url)
        api_client.body = body
        api_client.post(body_as_data=True)
        response = api_client.fetch_response()
        logger.info(f"fetch_access_token_response::{api_client.response.status_code}::{api_client.response.text}")

        access_token = response.get('access_token')
        self.ig_user_id = response.get('user_id')
        

        if access_token:
            long_access_token = self.fetch_long_live_token(access_token)
            
            media = self.fetch_media(long_access_token)
            user_details = self.fetch_user_details(long_access_token)

            if long_access_token:
                store = StoreInfo.objects.filter(id=store_id).first()

                if not store:
                    store = StoreInfo.objects.filter(store_name='zaamo').first()

                record = {
                    'ig_user_id' : self.ig_user_id,
                    'access_token' : long_access_token,
                    'store_id' : store.id,
                    'user_name' : user_details.get('username'),
                    'user_id' : user_details.get('user_id'),
                    'store_id' : store.id,
                    'instagram': True,
                    'metadata':user_details}
                
                new_ig_user, created = InstagramUser.objects.update_or_create(ig_user_id=self.ig_user_id,defaults=record)
                profile_image_cdn = user_details.get('profile_picture_url')

                if profile_image_cdn:
                    save_profile_image(profile_image_cdn,new_ig_user.id)
                
                if media:
                    save_post.delay(media)

                return {'access_token': long_access_token,'user_id':self.ig_user_id,'posts':media, 'metadata':new_ig_user.metadata}
        
        return {'message':'auth failed'}


    def fetch_access_token_from_user_id(self,user_id):
        user_inst = InstagramUser.objects.filter(user_id=user_id).first()
        
        if user_inst:
            return user_inst.access_token, user_inst.ig_user_id
        
        return None,None
        
    def fetch_access_token_from_ig_user_id(self,ig_user_id):
        user_inst = InstagramUser.objects.filter(ig_user_id=ig_user_id).first()
        
        if user_inst:
            return user_inst.access_token
        
        return None
        
    def fetch_media(self,access_token,post_limit=100):
        
        after = None
        response_data = []

        while True and len(response_data)<post_limit:

            body = media_body(access_token)

            if after:
                body['after']=after

            api_client = ApiClient(host=self.graph_url,path='me/media')
            api_client.update_url_params(body)
            api_client.get()
            response = api_client.fetch_response()
            data = response.get('data',[])
            response_data.extend(data)

            after = response.get('paging',{}).get('after')

            if not after:
                break
            
        if response_data:
            return response_data
        
        return {'message':'post fetch failed'}
    
    def fetch_user_details(self,access_token):
    
        body = user_details_body(access_token)
        api_client = ApiClient(host=self.graph_url,path='me')
        api_client.update_url_params(body)
        api_client.get()
        response = api_client.fetch_response()
        
        if response:
            return response
        
        return {'message':'user details fetch failed'}
            
    @staticmethod
    def get_posts(filters=None):
        posts = Post.objects.all()
        if filters:
            posts = posts.filter(**filters)

        media_type_subquery = Media.objects.filter(shortcode=OuterRef('shortcode')).values('media_type')[:1]
        media_file_subquery = Media.objects.filter(shortcode=OuterRef('shortcode')).values('media_file')[:1]

        posts = posts.annotate(ig_user_id=F('owner__ig_user_id')).annotate(media_type=Subquery(media_type_subquery)).annotate(media_url=Subquery(media_file_subquery))

        return posts
    
    
    def fetch_conversations(self,ig_user_id):

        access_token = self.fetch_access_token_from_ig_user_id(ig_user_id)
        after = None
        conversations_limit = 100
        conversations = []

        while True and len(conversations)<conversations_limit:

            body = conversation_body(access_token)

            if after:
                body['after']=after

            api_client = ApiClient(host=self.graph_url,path=f'me/conversations')
            api_client.update_url_params(body)
            api_client.get()
            response = api_client.fetch_response()
            data = response.get('data',[])
            data = clean_message_response(data)
            conversations.extend(data)

            after = response.get('paging',{}).get('after')

            if not after:
                break
            
        if conversations:
            return conversations
        
    def fetch_post_comments(self,post_id,ig_user_id):
        comments = []

        if not ig_user_id:

            post = Post.objects.filter(post_id=post_id).first()

            if post:
                ig_user_id = post.owner.ig_user_id
        
        if not ig_user_id:
            return comments
        
        access_token = self.fetch_access_token_from_ig_user_id(ig_user_id)

        after = None
        comment_limit = 100

        while True and len(comments)<comment_limit:

            body = comment_body(access_token)

            if after:
                body['after']=after

            api_client = ApiClient(host=self.graph_url,path=f'{post_id}/comments')
            api_client.update_url_params(body)
            api_client.get()
            response = api_client.fetch_response()
            data = response.get('data',[])
            comments.extend(data)

            after = response.get('paging',{}).get('after')

            if not after:
                break
            
        if comments:
            return comments



    @staticmethod
    def save_share_link(post_id, share_link):
        post = Post.objects.get(post_id=post_id)
        post.share_link = share_link
        post.save()

        return post
    
    @staticmethod
    def update_instagram_login(ig_user_id, store_id, instagram):
        if not ig_user_id and not store_id:
            return 0
        
        users = InstagramUser.objects.all()
        if ig_user_id:
            users = users.filter(ig_user_id=ig_user_id)
        if store_id:
            users = users.filter(store_id=store_id)
        
        for user in users:
            if user.instagram == instagram:
                continue
            user.instagram = instagram
            user.save()

        return users.count()


class InstagramCommenttoDM(InstagramBase):
    
    from_id = ''
    post_id = ''
    comment_id = ''
    to_id = ''
    message_url = 'https://graph.instagram.com/%s/messages'
    
    def __init__(self,data) -> None:

        self.from_id = data.get('from_id')
        self.post_id = data.get('post_id')
        self.comment_id = data.get('comment_id')
        self.to_id = data.get('to_id')
    
    
    def validate_post_get_msg(self):
        try:
            msg = Post.objects.get(post_id=self.post_id).share_link
            return msg.strip()
        except Exception as e:
            return ""
    
    def send_dm(self,user_id,msg):

        url = self.message_url % user_id
        url = f"{url}?access_token={self.access_token}"

        body = message_api_body(self.comment_id,msg)
        api_client = ApiClient(url=url)
        api_client.body = body
        api_client.post()
        response = api_client.fetch_response()
        
        if response:
            return True
        
        return False
    
        
    def check_and_send_dm(self):
        
        try:
            user_id = self.to_id
            self.access_token, self.ig_user_id = self.fetch_access_token_from_user_id(user_id)
            msg = self.validate_post_get_msg()
            is_sent = False

            if msg and self.access_token and self.ig_user_id:

                is_sent = self.send_dm(self.ig_user_id,msg)

            return is_sent
        
        except Exception as e:

            logger.exception(e)

def instagram_webhook(request):
    
    try:
        
        challenge = request.GET.get('hub.challenge')
        if challenge:
            return HttpResponse(challenge)
        
        body = json.loads(request.body.decode('utf-8'))

        entries = body.get('entry',[])
        
        for entry in entries:

            changes = entry.get('changes',[])
            to_id = entry.get('id','')

            if not to_id:
                return JsonResponse({"success":False})
            
            for change in changes:
                data = dict()

                comment_text = change.get('value',{}).get('text','')

                if validate_comment(comment_text):

                    data['from_id'] = change.get('value',{}).get('from',{}).get('id')
                    data['post_id'] = change.get('value',{}).get('media',{}).get('id')
                    data['comment_id'] = change.get('value',{}).get('id','')
                    data['comment_text'] = change.get('value',{}).get('text','')
                    data['to_id'] = to_id

                    instagram_inst = InstagramCommenttoDM(data)
                    is_sent = instagram_inst.check_and_send_dm()

                    if not is_sent:
                        logger.exception(f"message sending failed. response :: {data}")

        return JsonResponse({"success":True})

    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})


def auth_redirect(request):
    
    try:
        code = request.GET.get('code')
        redirect_url = request.GET.get('redirect_url')
        store_id = request.GET.get('store_id')
        
        instagram_inst = InstagramBase()

        response = instagram_inst.fetch_access_token(code,redirect_url,store_id)

        return JsonResponse(response)

    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})
    
def get_ig_posts(request):
    
    try:
        ig_user_id = request.GET.get('ig_user_id')
        store_id = request.GET.get('store_id')
        post_id = request.GET.get('post_id')
        page = NumberUtilities.convert_string_to_number(request.GET.get('page', 1))
        page_size = NumberUtilities.convert_string_to_number(request.GET.get('page_size', 10))

        filters = {}
        if ig_user_id:
            filters['owner__ig_user_id'] = ig_user_id
        if store_id:
            filters['store_id'] = store_id
        if post_id:
            filters['post_id'] = post_id

        posts = InstagramBase.get_posts(filters)
        posts = posts.order_by('-timestamp').values()[page_size * (page - 1): page * page_size]

        data = []
        for post in posts:
            post.pop('owner_id', None)
            post.pop('id', None)
            post['media_url'] = Media.get_full_media_url(post['media_url'])
            post['media_type'] = Media.get_media_type_name(post['media_type'])
            data.append(post)

        return JsonResponse({"data": data})

    except Exception as e:
        logger.exception(e)

        return JsonResponse({"success":False})
    

def save_share_link_of_posts(request):
    try:
        if request.method == 'POST':
            body = JsonUtilities.loads(request.body)
            share_link = body.get('share_link')
            post_id = body.get('post_id')

            if not share_link or not post_id:
                return HttpResponse('share_link and post_id required', status=400)
            
            post = InstagramBase.save_share_link(post_id, share_link)

            data = {'post_id': post.post_id, 'share_link': post.share_link, 'success': True}

            return JsonResponse(data)

    except Exception as e:
        logger.exception(e)
        
        return JsonResponse({"success":False})

def get_instagram_login_details(request):
    
    try:
        response = get_instagram_login_body()
        return JsonResponse(response)

    except Exception as e:
        logger.exception(e)
        return JsonResponse({"success":False})

def deactivate_instagram_login(request):
    try:
        if request.method == 'POST':
            body = JsonUtilities.loads(request.body)
            ig_user_id = body.get('ig_user_id')
            store_id = body.get('store_id')
            instagram = body.get('instagram')
            
            updated = InstagramBase.update_instagram_login(ig_user_id, store_id, instagram)

            data = {'update_count': updated}

            return JsonResponse(data)

    except Exception as e:
        logger.exception(e)
        
        return JsonResponse({"success":False})


def get_ig_post_comments(request):
    
    try:
        ig_user_id = request.GET.get('ig_user_id')
        post_id = request.GET.get('post_id')
        page = NumberUtilities.convert_string_to_number(request.GET.get('page', 1))
        page_size = NumberUtilities.convert_string_to_number(request.GET.get('page_size', 10))
        
        instagram_inst = InstagramBase()

        comments = instagram_inst.fetch_post_comments(post_id,ig_user_id)
        comments = comments[page_size * (page - 1): page * page_size]

        return JsonResponse({"data": comments})

    except Exception as e:
        logger.exception(e)

        return JsonResponse({"success":False})

def get_conversations(request):
    
    try:
        ig_user_id = request.GET.get('ig_user_id')
        page = NumberUtilities.convert_string_to_number(request.GET.get('page', 1))
        page_size = NumberUtilities.convert_string_to_number(request.GET.get('page_size', 10))
        
        instagram_inst = InstagramBase()

        conversations = instagram_inst.fetch_conversations(ig_user_id) or []

        conversations = conversations[page_size * (page - 1): page * page_size]

        return JsonResponse({"data": conversations})

    except Exception as e:
        logger.exception(e)

        return JsonResponse({"success":False})
