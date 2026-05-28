import logging
logger = logging.getLogger(__name__)


class RequestUtilities:
    @staticmethod
    def get_store_id_from_headers(request):
        store_id = request.META.get('HTTP_X_STORE_ID')
        
        try:
            store_id = int(store_id)
            return store_id
        
        except Exception as e:
            #logger.exception(f"request failed: {str(request.body.decode())} due to wrong store_id in header {store_id}")
            return None

    @staticmethod
    def get_platfrom_type_from_headers(request):

        return request.META.get('HTTP_X_PLATFORM_CODE')
    
    @staticmethod
    def get_app_code_from_headers(request):

        return request.META.get('HTTP_X_APP_CODE','')

    @staticmethod
    def get_device_id_from_headers(request):

        return request.META.get('HTTP_X_DEVICE_ID','')

class PlatformTypeEnum:
    INFLUENCER_STORE = 'IS'
    INFLUENCER_HOME = 'IH'
    BRAND_HOME = 'BH'
    ZAAMO_STORE = 'ZS'
    TAGGING_PANNEL = 'TP'
    ANALYTICS = 'AN'

    CHOICES = [
        (INFLUENCER_STORE , "IS"),
        (INFLUENCER_HOME , "IH"),
        (BRAND_HOME , "BH"),
        (ZAAMO_STORE , "ZS"),
        (TAGGING_PANNEL , "TP"),
        (ANALYTICS , "AN")
    ]
