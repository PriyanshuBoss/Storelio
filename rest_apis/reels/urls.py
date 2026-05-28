from .view_impl import CreateReelupMediaPlaylist,ReelupUpdateandDelete, FetchReelMediaPlaylist, FetchReels, MapReelupPlaylistToMedia, ReelupStoreApi, UpdateDefaultPlaylist, UpdateOrDeleteReelupMediaPlaylist, reel_up_media_upload,fetch_products_from_shopify,tag_product_to_shopify_reelup
from django.urls import path

urlpatterns = [
    path('reel_up_media_upload', reel_up_media_upload, name="reel_up_media_upload"),
    path('reel_up_update', ReelupUpdateandDelete.as_view(), name="reel_up_update"),
    path('fetch_reels', FetchReels.as_view({'get':'list'}), name="fetch_reels"),
    path('fetch_products_from_shopify', fetch_products_from_shopify, name="fetch_products_from_shopify"),
    path('tag_product_to_shopify_reelup', tag_product_to_shopify_reelup, name="tag_product_to_shopify_reelup"),
    path('create_reel_up_media_playlist', CreateReelupMediaPlaylist.as_view(), name="create_reel_up_media_playlist"),
    path('change_reel_up_media_playlist', UpdateOrDeleteReelupMediaPlaylist.as_view(), name="change_reel_up_media_playlist"),
    path('map_reel_up_media_playlist', MapReelupPlaylistToMedia.as_view(), name="map_reel_up_media_playlist"),
    path('fetch_reel_media_playlist', FetchReelMediaPlaylist.as_view({'get':'list'}), name="fetch_reel_media_playlist"),
    path('reel_up_store', ReelupStoreApi.as_view(), name="reel_up_store"),
    path('update_default_playslist',UpdateDefaultPlaylist.as_view(), name="update_default_playslist"),
]
