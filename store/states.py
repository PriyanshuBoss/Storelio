class StoreMemberStatesEnum:
    OWNER = 0
    MANAGER = 1

class StoreStateEnum:
    INACTIVE = 0
    ACTIVE = 1

class StoreTypeEnum:
    BRAND = 'brand'
    INFLUENCER = 'influencer'

    CHOICES = [
        (BRAND, "brand"),
        (INFLUENCER, "influencer")
    ]

class StoreTileEnum:
    INFLUENCER_HOME = 'influencer_home'
    INFLUENCER_STORE = 'influencer_store'
    INFLUENCER_HOME_STORE = 'influencer_home_store'
    INFLUENCER_HOME_APP = 'influencer_home_app'
    INFLUENCER_STORE_APP = 'influencer_store_app'
    ZS_APP = 'zs_app'
    ALL_APP = 'all_app'

    CHOICES = [
        (INFLUENCER_HOME, "influencer_home"),
        (INFLUENCER_STORE, "influencer_store"),
        (INFLUENCER_HOME_STORE, "influencer_home_store"),
        (INFLUENCER_HOME_APP,"influencer_home_app" ),
        (INFLUENCER_STORE_APP,"influencer_store_app" ),
        (ZS_APP,"zs_app"),
        (ALL_APP,"all_app")
    ]

class StoreCategoryPageLevels:
    LEVEL_1 = 'level_1'
    LEVEL_2 = 'level_2'
    LEVEL_3 = 'level_3'

    CHOICES = [
        (LEVEL_1, "level_1"),
        (LEVEL_2, "level_2"),
        (LEVEL_3, "level_3"),
    ]

class StoreStatus:

    TEST_STORE = "TEST_STORE"
    STILL_EXPLORING = "STILL_EXPLORING"
    A1_STORE_WORKING = "A1_STORE_WORKING"
    A1_STORE_ENTHU_NO_SALES_RECENTLY = "A1_STORE_ENTHU_NO_SALES_RECENTLY"
    A1_OWN_PACE = "A1_OWN_PACE"
    A2_STORE_ENTHU = "A2_STORE_ENTHU"
    A2_OWN_PACE = "A2_OWN_PACE"
    A2_SOURCING_ENTHU = "A2_SOURCING_ENTHU"
    B1_STORE_ENTHU = "B1_STORE_ENTHU"
    B1_SOURCING_ENTHU = "B1_SOURCING_ENTHU"
    INACTIVE_ON_INSTAGRAM = "INACTIVE_ON_INSTAGRAM"
    BAD_ZAAMO_EXPERIENCE = "BAD_ZAAMO_EXPERIENCE"
    UNABLE_TO_CONNECT_ON_CALL_OR_TEXT = "UNABLE_TO_CONNECT_ON_CALL_OR_TEXT"
    NOT_INTRESTED_TO_CONTINUE = "NOT_INTRESTED_TO_CONTINUE"
    A1_5K = "A1 5k"
    B1_5K = "B1 5k"
    A1_5K_ONLY_SOURCING = "A1 5K ONLY SOURCING"
    A1_15K_ONLY_SOURCING = "A1 15K ONLY SOURCING"
    A1_CELEB_ONLY_SOURCING = "A1 CELEB ONLY SOURCING"
    B1_15K_ONLY_SOURCING = "B1 15K ONLY SOURCING"
    B1_CELEB_ONLY_SOURCING = "B1 CELEB ONLY SOURCING"
    A1_ONLY_SOURCING = "A1 ONLY SOURCING"
    A2_ONLY_SOURCING = "A2 ONLY SOURCING"
    B1_ONLY_SOURCING = "B1 ONLY SOURCING"
    A2_B2_NO_MANAGE = "A2 B2 NO MANAGE"
    STYLIST = "STYLIST"
    MANAGER = "MANAGER"
    INTERNATIONAL = "INTERNATIONAL"
    CAMPUS_AMBASSADOR = "CAMPUS_AMBASSADOR"
    SOURCING_2023 = "SOURCING_2023"
    STORE_2023 = "STORE_2023"
    CAMPAIGN_2023 = "CAMPAIGN_2023"
   


    CHOICES = [
        (TEST_STORE, "TEST_STORE"),
        (STILL_EXPLORING, "STILL_EXPLORING"),
        (A1_STORE_WORKING, "A1_STORE_WORKING"),
        (A1_STORE_ENTHU_NO_SALES_RECENTLY, "A1_STORE_ENTHU_NO_SALES_RECENTLY"),
        (A1_OWN_PACE, "A1_OWN_PACE"),
        (A2_STORE_ENTHU, "A2_STORE_ENTHU"),
        (A2_OWN_PACE, "A2_OWN_PACE"),
        (A2_SOURCING_ENTHU, "A2_SOURCING_ENTHU"),
        (B1_STORE_ENTHU, "B1_STORE_ENTHU"),
        (B1_SOURCING_ENTHU, "B1_SOURCING_ENTHU"),
        (INACTIVE_ON_INSTAGRAM, "INACTIVE_ON_INSTAGRAM"),
        (BAD_ZAAMO_EXPERIENCE, "BAD_ZAAMO_EXPERIENCE"),
        (UNABLE_TO_CONNECT_ON_CALL_OR_TEXT, "UNABLE_TO_CONNECT_ON_CALL_OR_TEXT"),
        (NOT_INTRESTED_TO_CONTINUE, "NOT_INTRESTED_TO_CONTINUE"),
        (A1_5K, "A1 5k"),
        (B1_5K, "B1 5k"),
        (A1_5K_ONLY_SOURCING, "A1 5K ONLY SOURCING"),
        (A1_15K_ONLY_SOURCING, "A1 15K ONLY SOURCING"),
        (A1_CELEB_ONLY_SOURCING, "A1 CELEB ONLY SOURCING"),
        (B1_15K_ONLY_SOURCING, "B1 15K ONLY SOURCING"),
        (B1_CELEB_ONLY_SOURCING, "B1 CELEB ONLY SOURCING"),
        (A1_ONLY_SOURCING, "A1 ONLY SOURCING"),
        (A2_ONLY_SOURCING, "A2 ONLY SOURCING"),
        (B1_ONLY_SOURCING, "B1 ONLY SOURCING"),
        (A2_B2_NO_MANAGE, "A2 B2 NO MANAGE"),
        (STYLIST, "STYLIST"),
        (MANAGER, "MANAGER"),
        (INTERNATIONAL, "INTERNATIONAL"),
        (CAMPUS_AMBASSADOR, "CAMPUS_AMBASSADOR"),
        (SOURCING_2023, "SOURCING 2023"),
        (STORE_2023, "STORE 2023"),
        (CAMPAIGN_2023, "CAMPAIGN_2023")
    ]

class StoreNextActions:
    SKINCARE_BEAUTY_MAKEUP = "SKINCARE_BEAUTY_MAKEUP"
    FASHION = "FASHION"
    DANCE = "DANCE"
    MOM = "MOM"
    REVIEW_SHOPPABLE_COMMERCIAL = "REVIEW_SHOPPABLE_COMMERCIAL"
    MALE_INFLUENCERS = "MALE_INFLUENCERS"
    FITNESS_ATHLEISURE = "FITNESS_ATHLEISURE"
    PLUS_SIZE = "PLUS_SIZE"
    LIFESTYLE = "LIFESTYLE"
    FOOD_NUTRITION = "FOOD_NUTRITION"
   


    CHOICES = [
        (SKINCARE_BEAUTY_MAKEUP, "SKINCARE_BEAUTY_MAKEUP"),
        (FASHION, "FASHION"),
        (DANCE, "DANCE"),
        (MOM, "MOM"),
        (REVIEW_SHOPPABLE_COMMERCIAL, "REVIEW_SHOPPABLE_COMMERCIAL"),
        (MALE_INFLUENCERS, "MALE_INFLUENCERS"),
        (FITNESS_ATHLEISURE, "FITNESS_ATHLEISURE"),
        (PLUS_SIZE, "PLUS_SIZE"),
        (LIFESTYLE, "LIFESTYLE"),
        (FOOD_NUTRITION, "FOOD_NUTRITION"),
    ]



class StoreAppEnum:
    INFLUENCER_HOME = 'INFLUENCER_HOME'
    INFLUENCER_STORE = 'INFLUENCER_STORE'

    CHOICES = [
        (INFLUENCER_HOME, "INFLUENCER_HOME"),
        (INFLUENCER_STORE, "INFLUENCER_STORE"),
    ]

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

class StoreBrandSourcingRequestEnum:
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"

    CHOICES = [
        (REQUEST_RECEIVED , "REQUEST_RECEIVED"),
        (ACCEPT , "ACCEPT"),
        (REJECT , "REJECT")
    ]

class BrandCollabEnum:
    YES = "YES"
    NO = "NO"

    CHOICES = [
        (YES, "YES"),
        (NO, "NO")
    ]

class LinktreeType:
    HYPD        = "hypd"
    EMAIL       = "email"
    NYKAA       = "nykaa"
    TIKTOK      = "tiktok"
    MYNTRA      = "myntra"
    AMAZON      = "amazon"
    YOUTUBE     = "youtube"
    SPOTIFY     = "spotify"
    TWITTER     = "twitter"
    WISHLINK    = "wishlink"
    FACEBOOK    = "facebook"
    LINKTREE    = "linktree"
    SNAPCHAT    = "snapchat"
    WHATSAPP    = "whatsapp"
    INSTAGRAM   = "instagram"
    PINTEREST   = "pinterest"
    OTHER       = "other"

    EMAIL_ACCOUNT       = "email_account"
    TIKTOK_ACCOUNT      = "tiktok_account"
    SPOTIFY_ACCOUNT     = "spotify_account"
    YOUTUBE_ACCOUNT     = "youtube_account"
    TWITTER_ACCOUNT     = "twitter_account"
    FACEBOOK_ACCOUNT    = "facebook_account"
    SNAPCHAT_ACCOUNT    = "snapchat_account"
    WHATSAPP_ACCOUNT    = "whatsapp_account"
    INSTAGRAM_ACCOUNT   = "instagram_account"
    PINTEREST_ACCOUNT   = "pinterest_account"
    OTHER_ACCOUNT       = "other_account"

    CHOICES = [
        (HYPD, "HYPD"),
        (EMAIL, "EMAIL"),
        (NYKAA, "NYKAA"),
        (MYNTRA, "MYNTRA"),
        (TIKTOK, "TIKTOK"),
        (AMAZON, "AMAZON"),
        (YOUTUBE, "YOUTUBE"),
        (SPOTIFY, "SPOTIFY"),
        (TWITTER, "TWITTER"),
        (WISHLINK, "WISHLINK"),
        (FACEBOOK, "FACEBOOK"),
        (LINKTREE, "LINKTREE"),
        (SNAPCHAT, "SNAPCHAT"),
        (WHATSAPP, "WHATSAPP"),
        (INSTAGRAM, "INSTAGRAM"),
        (PINTEREST, "PINTEREST"),
        (OTHER, "OTHER"),
        (EMAIL_ACCOUNT, "EMAIL_ACCOUNT"),
        (TIKTOK_ACCOUNT, "TIKTOK_ACCOUNT"),
        (SPOTIFY_ACCOUNT, "SPOTIFY_ACCOUNT"),
        (YOUTUBE_ACCOUNT, "YOUTUBE_ACCOUNT"),
        (TWITTER_ACCOUNT, "TWITTER_ACCOUNT"),
        (FACEBOOK_ACCOUNT, "FACEBOOK_ACCOUNT"),
        (SNAPCHAT_ACCOUNT, "SNAPCHAT_ACCOUNT"),
        (WHATSAPP_ACCOUNT, "WHATSAPP_ACCOUNT"),
        (INSTAGRAM_ACCOUNT, "INSTAGRAM_ACCOUNT"),
        (PINTEREST_ACCOUNT, "PINTEREST_ACCOUNT"),
        (OTHER_ACCOUNT, "OTHER_ACCOUNT"),
    ]

    @staticmethod
    def get_type(link, return_account=False):
        _type = LinktreeType.OTHER
        link = link.lower()
        for type, _ in LinktreeType.CHOICES:
            if type.lower() in link:
                _type = type
        if 'pin.it' in link:
            _type = LinktreeType.PINTEREST
        elif 'mailto:' in link:
            _type = LinktreeType.EMAIL
        elif 'x.com' in link:
            _type = LinktreeType.TWITTER
        if return_account:
            _type += '_account'
        
        return _type
    