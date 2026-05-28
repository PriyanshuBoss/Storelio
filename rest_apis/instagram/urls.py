from .view_impl import get_ig_post_comments, instagram_webhook,auth_redirect,get_ig_posts,save_share_link_of_posts,deactivate_instagram_login
from .view_impl import instagram_webhook,auth_redirect,get_instagram_login_details,get_conversations
from django.urls import path

urlpatterns = [
    path('instagram_webhook', instagram_webhook, name="instagram_webhook"),
    path('auth', auth_redirect, name="auth"),
    path('get_ig_posts', get_ig_posts, name='get_ig_posts'),
    path('save_share_link_of_posts', save_share_link_of_posts, name='save_share_link_of_posts'),
    path('get_instagram_login_details', get_instagram_login_details, name="get_instagram_login_details"),
    path('deactivate_instagram_login', deactivate_instagram_login, name="deactivate_instagram_login"),
    path('get_ig_post_comments', get_ig_post_comments, name="get_ig_post_comments"),
    path('get_conversations', get_conversations, name="get_conversations"),
]
