import io
import requests

from django.conf import settings
from saleor.celeryconf import app
from saleor.account.models import InstagramUser, Post, Media
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.string_utilities import StringUtilities

TRIGGER_WORD_FOR_COMMENT = 'interested'
INSTAGRAM_CLIENT_SECRET = settings.INSTAGRAM_CLIENT_SECRET
INSTAGRAM_CLIENT_ID = settings.INSTAGRAM_CLIENT_ID

def validate_comment(comment_text):

    if comment_text.lower() == TRIGGER_WORD_FOR_COMMENT:
        return True
    
    return False

def message_api_body(comment_id,text):

    return {
        'recipient' : {
            'comment_id':comment_id
            },
        'message' : {
            'text':text
            }
            }

def auth_body(code,redirect_url):
    payload = {
            'client_id': INSTAGRAM_CLIENT_ID,
            'client_secret': INSTAGRAM_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_url,
            'code': code
            }
    
    return payload


def long_live_access_body(short_access_token):
    payload = {'grant_type': 'ig_exchange_token',
            'client_secret': INSTAGRAM_CLIENT_SECRET,
            'access_token': short_access_token
            }
    
    return payload


def media_body(access_token):
    fields = ['id','owner','shortcode','caption','like_count','comments_count','media_url','media_type','timestamp','children{id,media_url,media_type,shortcode,permalink}']
    fields = ','.join(fields)
    payload = {
        'fields': fields,
        'access_token': access_token
    }
    
    return payload

def clean_message_response(data):
    data_cleaned = []

    for item in data:
        messages = item.get('messages',{})
        
        if messages:
            last_message = messages.get('data',[{}])[0]
        
        else:
            last_message = {}

        data_cleaned.append({'id':item.get('id'),'last_message':last_message})

    return data_cleaned

def comment_body(access_token):
    fields = ['from', 'username', 'user', 'text', 'timestamp', 'like_count', 'replies']
    fields = ','.join(fields)
    payload = {
        'fields': fields,
        'access_token': access_token
    }
    
    return payload

def user_details_body(access_token):
    fields = ['id', 'username', 'user_id', 'biography', 'followers_count', 'follows_count', 'media_count', 'name', 'profile_picture_url', 'website']
    fields = ','.join(fields)
    payload = {
        'fields': fields,
        'access_token': access_token
    }
    
    return payload

def conversation_body(access_token):
    fields = ["id", "messages.limit(1){id,created_time,from,to,message,read}"]
    fields = ','.join(fields)
    payload = {
        'fields': fields,
        'access_token': access_token
    }
    
    return payload

def get_instagram_login_body():
    response = {
        'host_url': 'https://www.instagram.com/oauth/authorize',
        'enable_fb_login':0,
        'force_authentication':1,
        'client_id':INSTAGRAM_CLIENT_ID,
        'response_type':'code',
        'scope':'business_basic,business_manage_messages,business_manage_comments,business_content_publish',
        'redirect_url':'http://zaamo.co/ig'
        }
        
    return response

def save_profile_image(media_url,ig_pk):

    user_inst = InstagramUser.objects.filter(id=ig_pk).first()
    user_name = user_inst.user_name
    current_time = StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds())
    
    filename = f"{user_name}_{current_time}.'jpg'"

    with requests.get(media_url, stream=True) as r:
        fileobj = io.BytesIO(r.content)
        user_inst.profile_image.save(filename, fileobj, save=True)
        prodile_image_url = user_inst.get_full_profile_image_url()
        user_inst.refresh_from_db()
        user_inst.metadata['profile_image_url_zaamo'] = prodile_image_url
        user_inst.save()


def save_media(data, post_pk):
    for media in data:
        instance, cc = Media.objects.get_or_create(post_id=post_pk, shortcode=media['shortcode'])
        instance.media_type = Media.VIDEO if media['media_type'] == 'VIDEO' else Media.IMAGE
        instance.save()

        if not media.get('media_url'):
            continue
        
        ext = 'mp4' if media['media_type'] == 'VIDEO' else 'jpg'
        current_time = StringUtilities.convert_number_to_string(TimeUtilities.current_time_in_milliseconds())
        
        filename = f"media_{media['id']}_{current_time}.{ext}"

        with requests.get(media['media_url'], stream=True) as r:
            fileobj = io.BytesIO(r.content)
            instance.media_file.save(filename, fileobj, save=True)

def get_or_create_post(post, owner=None):
    '''
    owner: account.models.InstagramUser
    '''
    if not owner:
        owner = InstagramUser.objects.filter(ig_user_id=post['owner']['id']).only('id', 'store_id').first()

    instance, cc = Post.objects.get_or_create(post_id=post['id'], shortcode=post['shortcode'])
    instance.owner_id = owner.id
    instance.store_id = owner.store_id
    instance.timestamp = post.get('timestamp')
    instance.like_count = post.get('like_count', 0)
    instance.comments_count = post.get('comments_count', 0)
    instance.caption = post.get('caption', '')
    instance.save()

    return instance, cc

@app.task(queue='onboarding_queue')
def save_post(data):
    owner_ids = [post['owner']['id'] for post in data]
    owners = InstagramUser.objects.filter(ig_user_id__in=owner_ids).only('ig_user_id', 'id', 'store_id')
    owners = {owner.ig_user_id: owner for owner in owners}

    for post in data:
        instance, cc = get_or_create_post(post, owners.get(post['owner']['id']))

        if 'media_url' in post:
            save_media([post], instance.id)

        if "children" in post:
            save_media(post['children']['data'], instance.id)                
    

