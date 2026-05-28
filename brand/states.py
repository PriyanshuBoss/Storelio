class PreferedPaymentModeEnum:
    BANK = 'bank account'
    UPI = 'upi id'

    CHOICES = [
        (BANK, "Bank Account"),
        (UPI, "UPI ID")
    ]

class BrandSourceEnum:
    MANUAL = 'manual'
    SHOPIFY = 'shopify'
    STAFF = 'staff'
    WOOCOMMERCE = 'woocommerce'
    WIX = 'wix'
    ACHAINDIA = 'achaindia'
    CUSTOM = 'custom'
    UNICOMMERCE = 'unicommerce'
    MYDUKAAN = 'mydukaan'

    CHOICES = [
        (MANUAL, 'manual'),
        (SHOPIFY, 'shopify'),
        (STAFF, 'staff'),
        (WOOCOMMERCE, 'woocommerce'),
        (WIX, 'wix'),
        (ACHAINDIA, 'achaindia'),
        (CUSTOM, 'custom'),
        (UNICOMMERCE,'unicommerce'),
        (MYDUKAAN,'mydukaan')
    ]

class BrandMemberStateEnum:
    OWNER = 'owner'
    STAFF = 'staff'
    INACTIVE = 'in-active'

    CHOICES = [
        (OWNER, 'owner'),
        (STAFF, 'staff'),
        (INACTIVE, 'in-active')
    ]

class BrandEmailStateEnum:
    PRIMARY = 'primary'
    SECONDARY = 'secondary'
    SUPPORT = 'support'

    CHOICES = [
        (PRIMARY,'primary'),
        (SECONDARY,'secondary'),
        (SUPPORT,'support')
    ]

class BrandMobileTypes:
    PRIMARY = 'primary'
    SECONDARY = 'secondary'
    SUPPORT = 'support'
    MARKETING = 'marketing'
    FOUNDER = 'founder'

    CHOICES = [
        (PRIMARY,'primary'),
        (SECONDARY,'secondary'),
        (SUPPORT,'support'),
        (MARKETING,'marketing'),
        (FOUNDER,'founder')
    ]

class BrandCollectionTypeEnum:
    COLLECTION = 'collection'
    CATEGORY = 'category'
    ZAAMOCATEGORY = 'zaamocategory'

    CHOICES = [
        (COLLECTION, 'collection'),
        (CATEGORY, 'category'),
        (ZAAMOCATEGORY, 'zaamocategory')
    ]

class ArrearTypeEnum:
    INFLUENCER = "Influencer"
    BRAND = "Brand"

    CHOICES = [
        (INFLUENCER, "Influencer"),
        (BRAND, "Brand")
    ]


class BrandStatusEnum:
    ACTIVE = "active"
    INACTIVE = "inactive"
    ACTIVE_ONLY_FOR_BARTER =  'active only for barter'

    CHOICES = [
        (ACTIVE, "active"),
        (INACTIVE, "inactive"),
        (ACTIVE_ONLY_FOR_BARTER, "active only for barter")
    ]

class BrandImportanceEnum:
    SUPER_IMPORTANT = 'SUPER_IMPORTANT'
    IMPORTANT = 'IMPORTANT'
    NICE_TO_HAVE_HIGH_SALES = 'NICE_TO_HAVE_HIGH_SALES'
    NICE_TO_HAVE_UNIQUE_CATALOG = 'NICE_TO_HAVE_UNIQUE_CATALOG'
    SOURCING_ONLY = 'SOURCING_ONLY'
    OTHERS = 'OTHERS'

    CHOICES = [
        (SUPER_IMPORTANT, 'SUPER_IMPORTANT'),
        (IMPORTANT, 'IMPORTANT'),
        (NICE_TO_HAVE_HIGH_SALES, 'NICE_TO_HAVE_HIGH_SALES'),
        (NICE_TO_HAVE_UNIQUE_CATALOG , 'NICE_TO_HAVE_UNIQUE_CATALOG'),
        (SOURCING_ONLY, 'SOURCING_ONLY'),
        (OTHERS, 'OTHERS'),
    ]

