from rest_framework.pagination import PageNumberPagination
from rest_framework import serializers

class PaginationClassSet(PageNumberPagination):
    pageSize = 10
    page_size_query_param = 'page_size'
    page = 1
    page_query_param='page'
    
class ReelupMediaPlaylistSerializer(serializers.Serializer):
    title = serializers.CharField(required=True)
    store_name = serializers.CharField(required=True)
    rank = serializers.IntegerField(default=0)
    type = serializers.ChoiceField(['playlist','story','pop'],default='playlist')
    status = serializers.ChoiceField(['active','inactive'],default='active')

class UpdateReelupMediaPlaylistSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=True)
    title = serializers.CharField(required=False)
    store_name = serializers.CharField(required=False)
    rank = serializers.IntegerField(required=False)
    operation = serializers.ChoiceField(['update','delete'],required=True)
    type = serializers.ChoiceField(['playlist','story','pop'],required=False)
    status = serializers.ChoiceField(['active','inactive'],required=False)

    
class ReelupMediaPlaylistMapSerializer(serializers.Serializer):
    rank = serializers.IntegerField(default=0)
    playlist_id = serializers.IntegerField(required=True)
    media_id = serializers.IntegerField(required=True)
    operation = serializers.ChoiceField(['add','remove'],required=True)


class ReelupStoreSerializer(serializers.Serializer):
    store_name = serializers.CharField(required=True)
    url = serializers.CharField(required=False,default='')
    access_token = serializers.CharField(required=False,default='')
    added_reel = serializers.BooleanField(required=False)
    enabled_app = serializers.BooleanField(required=False)
    created_wigdet = serializers.BooleanField(required=False)
    tagged_product = serializers.BooleanField(required=False)
    customized_design = serializers.BooleanField(required=False)
    enable_product_page_reel = serializers.BooleanField(required=False)
    stories_width_mobile = serializers.CharField(required=False)
    playlist_width_mobile = serializers.CharField(required=False)
    stories_width_desktop = serializers.CharField(required=False)
    pop_width_mobile = serializers.CharField(required=False)
    pop_width_desktop = serializers.CharField(required=False)
    gap_between_components = serializers.CharField(required=False)
    playlist_width_desktop = serializers.CharField(required=False)
    ProductPageReel_width_mobile = serializers.CharField(required=False)
    productPageReel_width_desktop = serializers.CharField(required=False)
    playlist_gap_between_components = serializers.CharField(required=False)
    productPageReel_gap_between_components = serializers.CharField(required=False)
    reelpop_width_desktop = serializers.CharField(required=False)
    reelpop_width_mobile = serializers.CharField(required=False)
    reelpop_spacing_horizontal = serializers.CharField(required=False)
    reelpop_spacing_vertical = serializers.CharField(required=False)
    reelpop_position = serializers.CharField(required=False)
