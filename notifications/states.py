
class TemplateType(object):
    CAMPAIGN_BASED = "Campaign Based"
    EVENT_BASED =  "Event Based"


    Choice = (
        (CAMPAIGN_BASED, "Campaign Based"),
        (EVENT_BASED, "Event Based"),
    )


class AppType(object):
    BRANDHOME = 1


class DeviceType(object):
    IOS = 'ios'
    ANDROID = 'android'
    WEB = 'web'

    CHOICES = (
        (IOS, "Ios"),
        (ANDROID, "Android"),
        (WEB, "Web")
    )


PRODUCT_CHOICES = (
    (AppType.BRANDHOME, "Brand Home"),
)


class NotificationPath(object):
    COUPONS = 'coupons'
    COLLECTIONS = 'collections'
    CATEGORY = 'category'
    THRIFT = 'thrift'
    TBD = 'tbd'
    EXPLORE_BRANDS = 'explore_brands'
    MY_ORDERS = 'my_orders'

    Choices = (
        (COUPONS, "Coupons"),
        (COLLECTIONS, "Collections"),
        (CATEGORY, "Category"),
        (THRIFT, "Thrift"),
        (TBD, "TBD"),
        (MY_ORDERS, "My Orders"),
        (EXPLORE_BRANDS, "Explore Brands"),
    )




class MediaType(object):
    IMAGE = 1
    DOCUMENT = 2
    VIDEO = 3
    AUDIO = 4
    NO_MEDIA = 5
    GIF = 6
    CAROUSEL = 7
    LONG_TEXT = 8

    Choices = (
        (NO_MEDIA, "No Media"),
        (IMAGE, "Image"),
        (VIDEO, "Video"),
        (GIF, "Gif"),
        (CAROUSEL, "Carousel"),
    )


class ApplicationType(object):
    
    BH = 'brand_home'
    ZS = 'zaamo_store'
    IH = 'influencer_home'

    CHOICES = (
        (BH, "brand_home"),
        (ZS, "zaamo_store"),
        (IH, "influencer_home")
    )
