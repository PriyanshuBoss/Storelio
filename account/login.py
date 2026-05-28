from saleor.store.constants import CREDENTIALS_EXPIRY_SECONDS
from .constants import FETCH_FACEBOOK_USER_ID_URL, FETCH_INSTAGRAM_USER_ID_URL, FETCH_INSTAGRAM_USER_PROFILE_URL, LONG_LIVED_ACCESS_TOKEN_URL
from saleor.utilities.api_client import ApiClient
from django.conf import settings
from .models import Credentials

def generate_long_lived_access_token(access_token):
    token_url = LONG_LIVED_ACCESS_TOKEN_URL % (settings.FACEBOOK_CREDENTIALS.get('client_id'), 
    settings.FACEBOOK_CREDENTIALS.get('client_secret'), 
    access_token, settings.FACEBOOK_CREDENTIALS.get('redirect_uri'))
    
    api_client = ApiClient(url=token_url)
    api_client.get()
    response = api_client.fetch_response()

    return response

def save_long_lived_token_in_db(access_token, user_instance):

    token_response = generate_long_lived_access_token(access_token)

    if not token_response:
        return

    long_lived_token = token_response.get('access_token')
    expires_in = token_response.get('expires_in', CREDENTIALS_EXPIRY_SECONDS)


    if not long_lived_token:
        return

    Credentials.create_or_update_instance({
        'user_instance': user_instance,
        'token': long_lived_token,
        'expires_at': expires_in
    })

    return long_lived_token

def fetch_user_id_of_facebook_account(access_token):
    
    user_id_url = FETCH_FACEBOOK_USER_ID_URL % access_token

    api_client = ApiClient(url=user_id_url)
    api_client.get()
    response = api_client.fetch_response()

    if response and response.get('data') and response.get('data')[0].get('id'):
        return response.get('data')[0].get('id')

def fetch_instagram_user_id(access_token, facebook_account_id):
    
    instagram_user_id_url = FETCH_INSTAGRAM_USER_ID_URL % (facebook_account_id, access_token)

    api_client = ApiClient(url=instagram_user_id_url)
    api_client.get()
    response = api_client.fetch_response()

    if response and response.get('instagram_business_account') and response.get(
        'instagram_business_account').get('id'):
        
        return response.get('instagram_business_account').get('id')

def fetch_instagram_profile_data_from_account_id(access_token, account_id):
    
    instagram_profile_fetch_url = FETCH_INSTAGRAM_USER_PROFILE_URL % (account_id, access_token)

    api_client = ApiClient(url=instagram_profile_fetch_url)
    api_client.get()
    response = api_client.fetch_response()

    return response

def get_image_url_for_instagram(instagram_profile):
    '''
        to-do shift image url to s3 bucket
    '''
    image_url = instagram_profile.get('profile_picture_url')
    
    return image_url

def process_instagram_data_for_db(instagram_profile, user_instance):

    info_context = {
        'user_instance': user_instance,
        'name': instagram_profile.get('name'),
        'instagram_username': instagram_profile.get('username'),
        'instagram_user_id': instagram_profile.get('id'),
        'image_url': get_image_url_for_instagram(instagram_profile),
        'ig_status': True
    }

    return info_context

def fetch_instagram_profile_of_user(access_token, user_instance):

    facebook_account_id = fetch_user_id_of_facebook_account(access_token)

    if not facebook_account_id:
        return
    
    instagram_account_id = fetch_instagram_user_id(access_token, facebook_account_id)

    if not instagram_account_id:
        return
    
    instagram_profile = fetch_instagram_profile_data_from_account_id(access_token, instagram_account_id)
 
    if not instagram_profile:
        return

    info_context = process_instagram_data_for_db(instagram_profile, user_instance)
   
    return info_context