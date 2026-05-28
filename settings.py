import ast
import os
import os.path
import sys
import warnings
from datetime import timedelta

import dj_database_url
import dj_email_url
import django_cache_url
import jaeger_client
import jaeger_client.config
import pkg_resources
import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from pytimeparse import parse
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from celery.schedules import crontab
from corsheaders.defaults import default_headers
from dotenv import load_dotenv
import json

load_dotenv()

def get_list(text):
    return [item.strip() for item in text.split(",")]


def get_bool_from_env(name, default_value):
    value = os.getenv(name)

    ans = default_value

    if value:

        if value == 'true' or value == 'True':
            ans = True
        else:
            ans = False

    return ans

def get_list_for_string_list(string_list):

    try:
        return  ast.literal_eval(string_list)

    except Exception as e:

        return []
    
def get_int_from_env(name, default_value):
    value = os.getenv(name)

    ans = default_value

    try:
        ans = int(value)
        return  ans

    except Exception as e:

        return ans




DEBUG = get_bool_from_env("DEBUG", True)

SITE_ID = 1

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

ROOT_URLCONF = "saleor.urls"

WSGI_APPLICATION = "saleor.wsgi.application"

ADMINS = (
    # ('Your Name', 'your_email@example.com'),
    ('Priyanshu', 'priyanshu@zaamo.co')
)
MANAGERS = ADMINS

_DEFAULT_CLIENT_HOSTS = "localhost,127.0.0.1"

ALLOWED_CLIENT_HOSTS = get_list_for_string_list(os.getenv("ALLOWED_CLIENT_HOSTS"))

if not ALLOWED_CLIENT_HOSTS:

    if DEBUG:
        ALLOWED_CLIENT_HOSTS = _DEFAULT_CLIENT_HOSTS

    else:
        raise ImproperlyConfigured(
            "ALLOWED_CLIENT_HOSTS environment variable must be set when DEBUG=False."
        )
    ALLOWED_CLIENT_HOSTS = get_list(ALLOWED_CLIENT_HOSTS)


INTERNAL_IPS = get_list(os.getenv("INTERNAL_IPS", "127.0.0.1"))

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.getenv('DATABASE_NAME'),
        'USER': os.getenv('DATABASE_USER'),
        'PASSWORD': os.getenv('DATABASE_PASSWORD'),
        'HOST': os.getenv('DATABASE_HOST'),
        'PORT': os.getenv('DATABASE_PORT'),
        'CONN_MAX_AGE': 200
    }
}

TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Kolkata')
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("ar", "Arabic"),
    ("az", "Azerbaijani"),
    ("bg", "Bulgarian"),
    ("bn", "Bengali"),
    ("ca", "Catalan"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("es-co", "Colombian Spanish"),
    ("et", "Estonian"),
    ("fa", "Persian"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("hy", "Armenian"),
    ("id", "Indonesian"),
    ("is", "Icelandic"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ka", "Georgian"),
    ("km", "Khmer"),
    ("ko", "Korean"),
    ("lt", "Lithuanian"),
    ("mn", "Mongolian"),
    ("my", "Burmese"),
    ("nb", "Norwegian"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("pt-br", "Brazilian Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("sq", "Albanian"),
    ("sr", "Serbian"),
    ("sv", "Swedish"),
    ("sw", "Swahili"),
    ("ta", "Tamil"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
    ("zh-hans", "Simplified Chinese"),
    ("zh-hant", "Traditional Chinese"),
]
LOCALE_PATHS = [os.path.join(PROJECT_ROOT, "locale")]
USE_I18N = os.getenv('USE_I18N', True)
USE_L10N = os.getenv('USE_L10N', True)
USE_TZ = os.getenv('USE_TZ', False)

# FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

SENDGRID_API_URL = os.getenv("SENDGRID_API_URL",'https://api.sendgrid.com/v3/mail/send')
SENDGRID_USERNAME = os.getenv("SENDGRID_USERNAME")
SENDGRID_PASSWORD = os.getenv("SENDGRID_PASSWORD")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY","")
EMAIL_URL = os.getenv("EMAIL_URL")
BACKEND_URL = os.getenv("BACKEND_URL","https://beta.zaamo.co")

if not EMAIL_URL and SENDGRID_USERNAME and SENDGRID_PASSWORD:
    EMAIL_URL = "smtp://%s:%s@smtp.sendgrid.net:587/?tls=True" % (
        SENDGRID_USERNAME,
        SENDGRID_PASSWORD,
    )

email_config = dj_email_url.parse(
    EMAIL_URL or "console://demo@example.com:console@example/"
)

EMAIL_FILE_PATH = email_config["EMAIL_FILE_PATH"]
EMAIL_HOST_USER = email_config["EMAIL_HOST_USER"]
EMAIL_HOST_PASSWORD = email_config["EMAIL_HOST_PASSWORD"]
EMAIL_HOST = email_config["EMAIL_HOST"]
EMAIL_PORT = email_config["EMAIL_PORT"]
EMAIL_BACKEND = email_config["EMAIL_BACKEND"]
EMAIL_USE_TLS = email_config["EMAIL_USE_TLS"]
EMAIL_USE_SSL = email_config["EMAIL_USE_SSL"]

# If enabled, make sure you have set proper storefront address in ALLOWED_CLIENT_HOSTS.
ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL = get_bool_from_env(
    "ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL", True
)

ENABLE_SSL = get_bool_from_env("ENABLE_SSL", False)

if ENABLE_SSL:
    SECURE_SSL_REDIRECT = not DEBUG

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)

MEDIA_ROOT = os.path.join(PROJECT_ROOT, "media")
MEDIA_URL = os.getenv("MEDIA_URL", "/media/")



STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
STATIC_URL = os.getenv("STATIC_URL", "/static/")

STATICFILES_DIRS = [
    ("images", os.path.join(PROJECT_ROOT, "saleor", "static", "images"))
]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

context_processors = [
    "django.template.context_processors.debug",
    "django.contrib.auth.context_processors.auth",
    "django.contrib.messages.context_processors.messages",
    "django.template.context_processors.request",
    "django.template.context_processors.media",
    "django.template.context_processors.static",
    "saleor.site.context_processors.site",
]

loaders = [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(PROJECT_ROOT, "templates")],
        "OPTIONS": {
            "debug": DEBUG,
            "context_processors": context_processors,
            "loaders": loaders,
            "string_if_invalid": '<< MISSING VARIABLE "%s" >>' if DEBUG else "",
        },

    }
]

# Make this unique, and don't share it with anybody.
SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY and DEBUG:
    warnings.warn("SECRET_KEY not configured, using a random temporary key.")
    SECRET_KEY = get_random_secret_key()

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "saleor.core.middleware.HealthCheckMiddleware",
    "django.middleware.common.CommonMiddleware",
    "saleor.core.middleware.request_time",
    "saleor.core.middleware.discounts",
    "saleor.core.middleware.google_analytics",
    "saleor.core.middleware.country",
    "saleor.core.middleware.currency",
    "saleor.core.middleware.site",
    "saleor.core.middleware.plugins",
    "saleor.core.middleware.jwt_refresh_token_middleware",
]

CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = list(default_headers) + [
    'x-store-id',
    'x-platform-code'
]

INSTALLED_APPS = [
    # External apps that need to go before django's
    "storages",
    # Django modules
    "django.contrib.contenttypes",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "django.contrib.auth",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.admin",
    "django.contrib.postgres",
    "rest_framework",
    "corsheaders",
    # Local apps
    "saleor.plugins",
    "saleor.account",
    "saleor.discount",
    "saleor.giftcard",
    "saleor.product",
    "saleor.checkout",
    "saleor.core",
    "saleor.csv",
    "saleor.graphql",
    "saleor.menu",
    "saleor.order",
    "saleor.invoice",
    "saleor.seo",
    "saleor.shipping",
    "saleor.site",
    "saleor.data_feeds",
    "saleor.page",
    "saleor.payment",
    "saleor.warehouse",
    "saleor.webhook",
    "saleor.wishlist",
    "saleor.app",
    "saleor.brand",
    "saleor.store",
    "saleor.notifications",
    "saleor.support",
    "saleor.external_services",
    # External apps
    "versatileimagefield",
    "django_measurement",
    "django_prices",
    "django_prices_openexchangerates",
    "django_prices_vatlayer",
    "graphene_django",
    "mptt",
    "django_countries",
    "django_filters",
    "phonenumber_field",
]



ENABLE_DEBUG_TOOLBAR = get_bool_from_env("ENABLE_DEBUG_TOOLBAR", False)

if ENABLE_DEBUG_TOOLBAR:
    # Ensure the graphiql debug toolbar is actually installed before adding it
    try:
        __import__("graphiql_debug_toolbar")
    except ImportError as exc:
        msg = (
            f"{exc} -- Install the missing dependencies by "
            f"running `pip install -r requirements_dev.txt`"
        )
        warnings.warn(msg)
    else:
        INSTALLED_APPS += ["django.forms", "debug_toolbar", "graphiql_debug_toolbar"]
        MIDDLEWARE.append("saleor.graphql.middleware.DebugToolbarMiddleware")

        DEBUG_TOOLBAR_PANELS = [
            "ddt_request_history.panels.request_history.RequestHistoryPanel",
            "debug_toolbar.panels.timer.TimerPanel",
            "debug_toolbar.panels.headers.HeadersPanel",
            "debug_toolbar.panels.request.RequestPanel",
            "debug_toolbar.panels.sql.SQLPanel",
            "debug_toolbar.panels.profiling.ProfilingPanel",
        ]
        DEBUG_TOOLBAR_CONFIG = {"RESULTS_CACHE_SIZE": 100}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "root": {"level": "INFO", "handlers": ["default"]},
    "formatters": {
        "django.server": {
            "()": "django.utils.log.ServerFormatter",
            "format": "[{server_time}] [{levelname}] {message}",
            "style": "{",
        },
        "json": {
            "()": "saleor.core.logging.JsonFormatter",
            "datefmt": "%Y-%m-%dT%H:%M:%SZ",
            "format": (
                "%(asctime)s %(levelname)s %(lineno)s %(message)s %(name)s "
                + "%(pathname)s %(process)d %(threadName)s"
            ),
        },
        "verbose": {
            "format": (
                "%(levelname)s %(name)s %(message)s [PID:%(process)d:%(threadName)s]"
            )
        },
    },
    "handlers": {
        "default": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose" if DEBUG else "json",
        },
        "django.server": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "django.server" if DEBUG else "json",
        },
        'custom_handler': {
            'level':'DEBUG',
            # 'class':'logging.StreamHandler',
            # 'stream': sys.stdout
            'class':'logging.handlers.RotatingFileHandler',
            'filename': os.getenv("CUSTOM_HANDLER_LOG_FILE_PATH", '/var/log/gunicorn/django_request.log'),
            'maxBytes': 1024 * 1024 * 10, 
            'backupCount': 5,
        },
        'saleor': {
            'level': 'INFO',
            'backupCount': 10,  # how many backup file to keep, 10 days
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.getenv("SALEOR_LOG_FILE_PATH", '/var/log/gunicorn/saleor.log'),
            'maxBytes': 1024*1024*30,  # 30MB
            "formatter": "django.server",
            
        },

    },
    "loggers": {
        "django": {
            "level": "INFO", 
            "propagate": True
        },
        "django.server": {
            "handlers": ['custom_handler', "django.server"],
            "level": "INFO",
            "propagate": False,
        },
        "saleor": {
            "handlers": ['custom_handler', "django.server", "saleor"],
            "level": "DEBUG", 
            "propagate": True
        },
        "saleor.graphql.errors.handled": {
            "handlers": ['custom_handler', "default"],
            "level": "INFO",
            "propagate": False,
        },
        "graphql.execution.utils": {"propagate": False},
    },
}

AUTH_USER_MODEL = "account.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    }
]

PRODUCT_IMPORT_USER_EMAIL = os.getenv("PRODUCT_IMPORT_USER_EMAIL", "sourcing@zaamo.co")
DEFAULT_COUNTRY = os.getenv("DEFAULT_COUNTRY", "IN")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD")
DEFAULT_DECIMAL_PLACES = 3
DEFAULT_MAX_DIGITS = 12
DEFAULT_CURRENCY_CODE_LENGTH = 3

STORE_MEMBERS_BASE_PERMISSION_GROUP = os.getenv("STORE_MEMBERS_BASE_PERMISSION_GROUP", "Full Access")

PRODUCTS_CSV_UPLOAD ={
   'CSV_COLUMNS':  get_list(os.getenv("CSV_COLUMNS", "sku,product name,brand id,pid,size,selling price,\
       quantity,mrp,category,sub category,search image url,front image url,back image url,\
        left image url,right image url,description,colour,material,hsn")),

    'MANDATORY_CSV_COLUMNS': get_list(os.getenv("MANDATORY_CSV_COLUMNS", "sku,pid,size,quantity,\
        mrp,search image url,category,sub category,brand id")),
    'CSV_PRODUCT_ATTRIBUTE_LIST': get_list(os.getenv("CSV_PRODUCT_ATTRIBUTE_LIST", "hsn,colour,material")),
    'CSV_VARIANT_ATTRIBUTE_LIST': get_list(os.getenv("CSV_VARIANT_ATTRIBUTE_LIST", "size"))
}

SIZE_LIST = get_list(os.getenv("SIZE_LIST", "NA,S,M,L,XS,XL,XXL,3XL,4XL"))

BOTD_DISCOUNT_PERCENTAGE = os.getenv("BOTD_DISCOUNT_PERCENTAGE", "25.0")

BOTD_MIN_SPENT = os.getenv("BOTD_MIN_SPENT","2000")

BOTD_MAX_DISC = os.getenv("BOTD_MAX_DISC","500")

STORE_STREAK_COMMISSION = os.getenv("STORE_STREAK_COMMISSION", "1.5")


# The default max length for the display name of the
# sender email address.
# Following the recommendation of https://tools.ietf.org/html/rfc5322#section-2.1.1
DEFAULT_MAX_EMAIL_DISPLAY_NAME_LENGTH = 78

# note: having multiple currencies is not supported yet
AVAILABLE_CURRENCIES = [DEFAULT_CURRENCY]

COUNTRIES_OVERRIDE = {"EU": "European Union"}

OPENEXCHANGERATES_API_KEY = os.getenv("OPENEXCHANGERATES_API_KEY")

GOOGLE_ANALYTICS_TRACKING_ID = os.getenv("GOOGLE_ANALYTICS_TRACKING_ID")


def get_host():
    from django.contrib.sites.models import Site

    return Site.objects.get_current().domain


PAYMENT_HOST = get_host

PAYMENT_MODEL = "order.Payment"

MAX_CHECKOUT_LINE_QUANTITY = int(os.getenv("MAX_CHECKOUT_LINE_QUANTITY", 50))

TEST_RUNNER = "saleor.tests.runner.PytestTestRunner"


PLAYGROUND_ENABLED = get_bool_from_env("PLAYGROUND_ENABLED", True)

ALLOWED_HOSTS = get_list(os.getenv("ALLOWED_HOSTS", "127.0.0.1"))



ALLOWED_GRAPHQL_ORIGINS = get_list(os.getenv("ALLOWED_GRAPHQL_ORIGINS", "*"))

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Amazon S3 configuration
# See https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_LOCATION = os.getenv("AWS_LOCATION", "")
AWS_MEDIA_BUCKET_NAME = os.getenv("AWS_MEDIA_BUCKET_NAME")
AWS_MEDIA_CUSTOM_DOMAIN = os.getenv("AWS_MEDIA_CUSTOM_DOMAIN")
AWS_QUERYSTRING_AUTH = get_bool_from_env("AWS_QUERYSTRING_AUTH", False)
AWS_QUERYSTRING_EXPIRE = get_bool_from_env("AWS_QUERYSTRING_EXPIRE", 3600)
AWS_S3_CUSTOM_DOMAIN = os.getenv("AWS_STATIC_CUSTOM_DOMAIN")
AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL", None)
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", None)
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
AWS_DEFAULT_ACL = os.getenv("AWS_DEFAULT_ACL", None)

# Google Cloud Storage configuration
GS_PROJECT_ID = os.getenv("GS_PROJECT_ID")
GS_STORAGE_BUCKET_NAME = os.getenv("GS_STORAGE_BUCKET_NAME")
GS_MEDIA_BUCKET_NAME = os.getenv("GS_MEDIA_BUCKET_NAME")
GS_AUTO_CREATE_BUCKET = get_bool_from_env("GS_AUTO_CREATE_BUCKET", False)
GS_LOCATION = os.getenv("GS_LOCATION", "media")
GS_QUERYSTRING_AUTH = get_bool_from_env("GS_QUERYSTRING_AUTH", False)
GS_CUSTOM_ENDPOINT = os.getenv("GS_CUSTOM_ENDPOINT","")

# Azure Storage configuration
# https://django-storages.readthedocs.io/en/latest/backends/azure.html
AZURE_ACCOUNT_NAME = os.getenv("AZURE_ACCOUNT_NAME")
AZURE_CONTAINER = os.getenv("AZURE_CONTAINER")
AZURE_LOCATION = os.getenv("AZURE_LOCATION")
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")


# If GOOGLE_APPLICATION_CREDENTIALS is set there is no need to load OAuth token
# See https://django-storages.readthedocs.io/en/latest/backends/gcloud.html
if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
    GS_CREDENTIALS = os.getenv("GS_CREDENTIALS")

FCM_CREDENTIALS_FILE = os.getenv("FCM_CREDENTIALS_FILE")

if AWS_STORAGE_BUCKET_NAME:
    STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
elif GS_STORAGE_BUCKET_NAME:
    STATICFILES_STORAGE = "storages.backends.gcloud.GoogleCloudStorage"
elif AZURE_CONTAINER:
    STATICFILES_STORAGE = "storages.backends.azure_storage.AzureStorage"

if AWS_MEDIA_BUCKET_NAME:
    DEFAULT_FILE_STORAGE = "saleor.core.storages.S3MediaStorage"
    THUMBNAIL_DEFAULT_STORAGE = DEFAULT_FILE_STORAGE
elif GS_MEDIA_BUCKET_NAME:
    DEFAULT_FILE_STORAGE = "saleor.core.storages.GCSMediaStorage"
    THUMBNAIL_DEFAULT_STORAGE = DEFAULT_FILE_STORAGE
elif AZURE_CONTAINER:
    DEFAULT_FILE_STORAGE = "saleor.core.storages.AzureMediaStorage"
    THUMBNAIL_DEFAULT_STORAGE = DEFAULT_FILE_STORAGE

VERSATILEIMAGEFIELD_RENDITION_KEY_SETS = {
    "products": [
        ("product_gallery", "thumbnail__540x540"),
        ("product_gallery_2x", "thumbnail__1080x1080"),
        ("product_small", "thumbnail__60x60"),
        ("product_small_2x", "thumbnail__120x120"),
        ("product_list", "thumbnail__255x255"),
        ("product_list_2x", "thumbnail__510x510"),
    ],
    "background_images": [("header_image", "thumbnail__1080x440")],
    "user_avatars": [("default", "thumbnail__445x445")],
}

VERSATILEIMAGEFIELD_SETTINGS = {
    # Images should be pre-generated on Production environment
    "create_images_on_demand": get_bool_from_env("CREATE_IMAGES_ON_DEMAND", DEBUG),
    "sized_directory_name":"__sized__"
}

PLACEHOLDER_IMAGES = {
    60: "images/placeholder60x60.png",
    120: "images/placeholder120x120.png",
    255: "images/placeholder255x255.png",
    540: "images/placeholder540x540.png",
    1080: "images/placeholder1080x1080.png",
}

DEFAULT_PLACEHOLDER = "images/placeholder255x255.png"

AUTHENTICATION_BACKENDS = [
    "saleor.core.auth_backend.JSONWebTokenBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# CELERY SETTINGS
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_URL = (
    os.getenv("CELERY_BROKER_URL", os.getenv("CLOUDAMQP_URL")) or ""
)
CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", None)
CELERY_BROKER_HEARTBEAT=0
CELERY_IMPORTS = [
    'saleor.external_services.google_analytics.tasks',
    'saleor.rest_apis.csv.tasks',
    'saleor.external_services.custom_brand_service.tasks',
    'saleor.external_services.style_stree_service.tasks',
    'saleor.external_services.wix.tasks',
    'saleor.external_services.woo_commerce_service.tasks',
    'saleor.external_services.shopify_service.tasks',
    'saleor.external_services.acha_india_service.tasks',
    'saleor.product.tasks',
    'saleor.order.tasks',
    'saleor.external_services.whatsapp.tasks',
    'saleor.store.tasks',
    'saleor.external_services.freshdesk.tasks'
]
CELERY_ACKS_LATE=True
CELERYD_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULE = {
    # 'overall-dashboard-summary-past': {
    # 'task': 'saleor.external_services.google_analytics.tasks.save_past_google_analytics',
    # 'schedule': crontab(hour=14, minute=40),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'send-zaamo-shopify-order-csv': {
    'task': 'saleor.rest_apis.csv.tasks.send_zaamo_shopify_order_csv',
    'schedule': crontab(minute=30, hour='10,18'),
    'options': {'queue' : 'celery_periodic'},
    },
    # 'resync-price-and-inventory-for-zaamo-shopify': {
    # 'task': 'saleor.external_services.shopify_service.tasks.resync_price_and_inventory_for_zaamo_shopify',
    # 'schedule': crontab(hour=16, minute=00),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'create-manual-order-for-zaamo': {
    'task': 'saleor.external_services.shopify_service.tasks.create_manual_order_for_zaamo',
    'schedule': crontab(hour='*/2', minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'yesterday-checkout-details': {
    'task': 'saleor.rest_apis.csv.tasks.send_recent_checkout_csv_task',
    'schedule': crontab(hour=10, minute=00),
    'options': {'queue' : 'celery_periodic'},
    },
    'top-products-yesterday': {
    'task': 'saleor.rest_apis.csv.tasks.send_csv_top_products_yesterday',
    'schedule': crontab(hour=21, minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'update-products-meta-ranking-attibutes': {
    'task': 'saleor.product.tasks.update_products_meta_ranking_attributes',
    'schedule': crontab(hour=16, minute=10),
    'options': {'queue' : 'celery_periodic'},
    },
    # 'store-analytics-past': {
    # 'task': 'saleor.store.tasks.save_past_store_analytics',
    # 'schedule': crontab(hour=11, minute=0),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'coupon_expire_notification_24': {
    'task': 'saleor.notifications.tasks.send_notification_coupon_expiry_24',
    'schedule': crontab(hour='*/12', minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'coupon_expire_notification_12': {
    'task': 'saleor.notifications.tasks.send_notification_coupon_expiry_12',
    'schedule': crontab(hour='*/12', minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'abandoned_cart_logged_in_user': {
    'task': 'saleor.notifications.tasks.send_abandoned_cart_notification_logged_in',
    'schedule': crontab(hour=20, minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'abanadoned_cart_guest_user': {
    'task': 'saleor.notifications.tasks.send_abandoned_cart_notification_guest_user',
    'schedule': crontab(hour=20, minute=10),
    'options': {'queue' : 'celery_periodic'},
    },
    # 'coupon_expire': {
    # 'task': 'saleor.discount.tasks.send_coupon_expire_email',
    # 'schedule': crontab(hour=10, minute=5),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    # 'overall-dashboard-summary-realtime': {
    # 'task': 'saleor.external_services.google_analytics.tasks.save_realtime_google_analytics',
    # 'schedule': crontab(minute='*/30'),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    # 'send-all-collections-csv': {
    # 'task': 'saleor.rest_apis.csv.tasks.send_all_collections_csv_task',
    # 'schedule': crontab(hour=10, minute=20),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    # 'create-freshdesk-tickets-for-initiate-purchases': {
    # 'task': 'saleor.external_services.freshdesk.tasks.create_freshdesk_tickets_for_initiate_purchases',
    # 'schedule': crontab(hour=8, minute=00),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'update-tags-in-freshdesk-tickets-task': {
    'task': 'saleor.external_services.freshdesk.tasks.update_tags_in_freshdesk_tickets_task',
    'schedule': crontab(hour=17, minute=00),
    'options': {'queue' : 'celery_periodic'},
    },
    # 'create-freshdesk-tickets-for-top-order-users': {
    # 'task': 'saleor.external_services.freshdesk.tasks.create_freshdesk_tickets_for_top_order_users',
    # 'schedule': crontab(day_of_week=1, hour=8, minute=00),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'create-freshdesk-ticket-for-delayed-orders-task': {
    'task': 'saleor.external_services.freshdesk.tasks.create_freshdesk_ticket_for_delayed_orders_task',
    'schedule': crontab(hour=9, minute=00),
    'options': {'queue' : 'celery_periodic'},
    },
    'resync-price-inventory-failed-in-mongo-shopify': {
    'task': 'saleor.external_services.shopify_service.tasks.resync_price_inventory_failed_in_mongo_shopify',
    'schedule': crontab(hour=4, minute=00),
    'options': {'queue' : 'celery_periodic'},
    },
    'resync-price-inventory-in-mongo-shopify': {
    'task': 'saleor.external_services.shopify_service.tasks.resync_price_inventory_in_mongo_shopify',
    'schedule': crontab(hour=21, minute=30),
    'options': {'queue' : 'celery_periodic'},
    },
    'resync-price-inventory-in-mongo-woocommerce': {
    'task': 'saleor.external_services.woo_commerce_service.tasks.resync_price_inventory_in_mongo_woo_commerce',
    'schedule': crontab(hour=23, minute=50),
    'options': {'queue' : 'celery_periodic'},
    },
    'resync-price-inventory-in-mongo-wix': {
    'task': 'saleor.external_services.wix.tasks.resync_price_inventory_in_mongo_wix',
    'schedule': crontab(hour=21, minute=00),
    'options': {'queue' : 'celery_periodic'},
    },
    # 'resync-price-inventory-in-mongo-custom': {
    # 'task': 'saleor.external_services.custom_brand_service.tasks.resync_price_inventory_in_mongo_custom',
    # 'schedule': crontab(hour=21, minute=30),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'update-shopify-order-status': {
    'task': 'saleor.external_services.shopify_service.tasks.update_shopify_order_status',
    'schedule': crontab(hour=18, minute=55),
    'options': {'queue' : 'celery_periodic'},
    },
    'update-woocommerce-order-status': {
    'task': 'saleor.external_services.woo_commerce_service.tasks.update_woocommerce_order_status',
    'schedule': crontab(hour=19, minute=10),
    'options': {'queue' : 'celery_periodic'},
    },
    # 'update-custom-order-status': {
    # 'task': 'saleor.external_services.custom_brand_service.tasks.update_custom_order_status',
    # 'schedule': crontab(hour=19, minute=15),
    # 'options': {'queue' : 'celery_periodic'},
    # },
    'product-grouping-mapping': {
    'task': 'saleor.product.tasks.update_mapping_for_product_grouping',
    'schedule': crontab(hour='*/12', minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'refund-orderline-status-update': {
    'task': 'saleor.order.tasks.orderline_refund_status_update',
    'schedule': crontab(hour=20, minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
    'orderline-brand-order-status-update': {
    'task': 'saleor.order.tasks.orderline_brand_order_status_update',
    'schedule': crontab(hour=9, minute=30),
    'options': {'queue' : 'celery_periodic'},
    },
    'whatsapp-notification-for-abandoned-cart':{
    'task':'saleor.external_services.whatsapp.tasks.sending_periodic_notification_abandoned_cart',
    'schedule': crontab(hour=20,minute=30),
    'options':{'queue' : 'celery_periodic'},
    },
    'catalog-product-status-inventory-update': {
    'task': 'saleor.external_services.instagram_shop.tasks.catalog_update_product_status_and_inventory',
    'schedule': crontab(hour='*/4', minute=20),
    'options': {'queue' : 'celery_periodic'},
    },
    'send-brand-owner-periodic-csv': {
    'task': 'saleor.rest_apis.csv.tasks.send_csv_to_brand_owners_periodic_task',
    'schedule': crontab(day_of_week='*/3', hour=16, minute=30),
    'options': {'queue' : 'celery_periodic'},
    },
    'send-brand-ledger-weekly': {
    'task': 'saleor.brand.emails.send_brand_ledger_weekly',
    'schedule': crontab(day_of_week='5', hour=15, minute=10),
    'options': {'queue' : 'celery_periodic'},
    },
    'send-brand-delayed-orders-weekly': {
    'task': 'saleor.brand.emails.send_brand_delayed_orders_weekly',
    'schedule': crontab(day_of_week='4', hour=15, minute=0),
    'options': {'queue' : 'celery_periodic'}, 
    }, 
    'gm-update-catalog': {
        'task': 'saleor.external_services.google_merchant.tasks.gm_update_catalog_products',
        'schedule': crontab(hour='*/4', minute=40),
        'options': {'queue': 'celery_periodic'},
    },
    'send-brand-aging-report': {
    'task': 'saleor.brand.emails.send_brand_aging_email',
    'schedule': crontab(day_of_month='1', hour=17, minute=0),
    'options': {'queue' : 'celery_periodic'},
    },
}

# Change this value if your application is running behind a proxy,
# e.g. HTTP_CF_Connecting_IP for Cloudflare or X_FORWARDED_FOR
REAL_IP_ENVIRON = os.getenv("REAL_IP_ENVIRON", "REMOTE_ADDR")

# The maximum length of a graphql query to log in tracings
OPENTRACING_MAX_QUERY_LENGTH_LOG = 2000

# Slugs for menus precreated in Django migrations
DEFAULT_MENUS = {"top_menu_name": "navbar", "bottom_menu_name": "footer"}

#  Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN, integrations=[CeleryIntegration(), DjangoIntegration()]
    )

GRAPHENE = {
    "RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST": True,
    "RELAY_CONNECTION_MAX_LIMIT": 100,
    "MIDDLEWARE": [
        "saleor.graphql.middleware.OpentracingGrapheneMiddleware",
        "saleor.graphql.middleware.JWTMiddleware",
        "saleor.graphql.middleware.app_middleware",
    ],
}

PLUGINS_MANAGER = "saleor.plugins.manager.PluginsManager"

PLUGINS = [
    "saleor.plugins.avatax.plugin.AvataxPlugin",
    "saleor.plugins.vatlayer.plugin.VatlayerPlugin",
    "saleor.plugins.webhook.plugin.WebhookPlugin",
    "saleor.payment.gateways.dummy.plugin.DummyGatewayPlugin",
    "saleor.payment.gateways.dummy_credit_card.plugin.DummyCreditCardGatewayPlugin",
    "saleor.payment.gateways.stripe.plugin.StripeGatewayPlugin",
    "saleor.payment.gateways.braintree.plugin.BraintreeGatewayPlugin",
    "saleor.payment.gateways.razorpay.plugin.RazorpayGatewayPlugin",
    "saleor.payment.gateways.adyen.plugin.AdyenGatewayPlugin",
    "saleor.payment.gateways.authorize_net.plugin.AuthorizeNetGatewayPlugin",
    "saleor.payment.gateways.cashfree.plugin.CashfreeGatewayPlugin"
]

RAZORPAY = {
    'active_status':  get_bool_from_env('ACTIVE_STATUS', False),
    'captured_webhook_secret': os.getenv('CAPTURED_WEBHOOK_SECRET', 'rzp_zaamo_webhook_secret_4821'),
}

# Plugin discovery
installed_plugins = pkg_resources.iter_entry_points("saleor.plugins")
for entry_point in installed_plugins:
    plugin_path = "{}.{}".format(entry_point.module_name, entry_point.attrs[0])
    if plugin_path not in PLUGINS:
        if entry_point.name not in INSTALLED_APPS:
            INSTALLED_APPS.append(entry_point.name)
        PLUGINS.append(plugin_path)

if (
    not DEBUG
    and ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL
    and ALLOWED_CLIENT_HOSTS == get_list(_DEFAULT_CLIENT_HOSTS)
):
    raise ImproperlyConfigured(
        "Make sure you've added storefront address to ALLOWED_CLIENT_HOSTS "
        "if ENABLE_ACCOUNT_CONFIRMATION_BY_EMAIL is enabled."
    )

# Initialize a simple and basic Jaeger Tracing integration
# for open-tracing if enabled.
#
# Refer to our guide on https://docs.saleor.io/docs/next/guides/opentracing-jaeger/.
#
# If running locally, set:
#   JAEGER_AGENT_HOST=localhost
if "JAEGER_AGENT_HOST" in os.environ:
    jaeger_client.Config(
        config={
            "sampler": {"type": "const", "param": 1},
            "local_agent": {
                "reporting_port": os.getenv(
                    "JAEGER_AGENT_PORT", jaeger_client.config.DEFAULT_REPORTING_PORT
                ),
                "reporting_host": os.getenv("JAEGER_AGENT_HOST"),
            },
            "logging": get_bool_from_env("JAEGER_LOGGING", False),
        },
        service_name="saleor",
        validate=True,
    ).initialize_tracer()


# Some cloud providers (Heroku) export REDIS_URL variable instead of CACHE_URL
REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    CACHE_URL = os.environ.setdefault("CACHE_URL", REDIS_URL)
CACHES = {"default": django_cache_url.config()}

# Default False because storefront and dashboard don't support expiration of token
JWT_EXPIRE = get_bool_from_env("JWT_EXPIRE", False)
JWT_TTL_ACCESS = timedelta(seconds=parse(os.getenv("JWT_TTL_ACCESS", "5 minutes")))
JWT_TTL_APP_ACCESS = timedelta(
    seconds=parse(os.getenv("JWT_TTL_APP_ACCESS", "5 minutes"))
)
JWT_TTL_REFRESH = timedelta(seconds=parse(os.getenv("JWT_TTL_REFRESH", "30 days")))


JWT_TTL_REQUEST_EMAIL_CHANGE = timedelta(
    seconds=parse(os.getenv("JWT_TTL_REQUEST_EMAIL_CHANGE", "1 hour")),
)

FACEBOOK_CREDENTIALS = {
    'client_id': os.getenv('FACEBOOK_CLIENT_ID'),
    'client_secret': os.getenv('FACEBOOK_CLIENT_SECRET'),
    'redirect_uri': os.getenv('FACEBOOK_REDIRECT_URI')
}

ZAAMO_ENV_LINK = os.getenv('ZAAMO_ENV_LINK','https://zaamo.co/')

CASHGRAM_CLIENT_ID = os.getenv('CASHGRAM_CLIENT_ID')

CASHGRAM_URI = os.getenv('CASHGRAM_URI')

CASHGRAM_CLIENT_SECRET = os.getenv('CASHGRAM_CLIENT_SECRET')

CASHGRAM_EXPIRY_DAYS = os.getenv('CASHGRAM_EXPIRY_DAYS','5')

PDP_PER_PAGE = os.getenv("PDP_PER_PAGE",50)

DEFAULT_STORE_URL = os.getenv('DEFAULT_STORE_URL')
BACKEND_URL = os.getenv('BACKEND_URL', 'https://beta.zaamo.co')
MAPPER_STORE_URL = os.getenv('MAPPER_STORE_URL')
ZAAMO_STORE_ID = os.getenv('ZAAMO_STORE_ID', 3552)

OTP_MSG91_CREDENTIALS = {
    'auth_key': os.getenv('OTP_AUTH_KEY'),
    'template_id': os.getenv('OTP_TEMPLATE_ID')
}

MESSAGING_MSG91_CREDENTIALS = {
    'auth_key': os.getenv('MESSAGING_AUTH_KEY', ''),
    'services': {
        'account_activation': {
            'flow_id': os.getenv('ACTIVATION_MESSAGE_FLOW_ID', '')
        },
        'coupon_creation': {
            'flow_id': os.getenv('COUPON_MESSAGE_FLOW_ID', '')
        },
        'order_confirmation': {
            'flow_id': os.getenv('ORDER_CONFIRMATION_FLOW_ID', '')
        }
    }
}

PINCODE_CREDENTIALS = {
    'api_key': os.getenv("PINCODE_API_KEY",''),
    'api_host' : os.getenv("PINCODE_API_HOST",'')
}

MONGO_CLIENT = {
    'db' : os.getenv('MONGO_DB', 'saleor'),
    'url': (os.getenv('MONGO_URL', "")+os.getenv('MONGO_PARAMS', "")) or 'mongodb://127.0.0.1:27017',
}

CASHFREE_GATEWAY = {
    'CASHFREE_APP_ID': os.getenv('CASHFREE_APP_ID'),
    'CASHFREE_APP_SECRET': os.getenv('CASHFREE_APP_SECRET'),
    'CASHFREE_API_VERSION': os.getenv('CASHFREE_API_VERSION'),
    'CASHFREE_BASE_URL': os.getenv("CASHFREE_BASE_URL")
}

FCM = {
    "FCM_API_KEY": os.getenv('FCM_API_KEY', '')
}

GOOGLE_ANALYTICS = {
    'HOME_GA_ID': os.getenv('HOME_GA_ID'),
    'STORE_GA_ID': os.getenv('STORE_GA_ID'),
    'LANDING_GA_ID': os.getenv('LANDING_GA_ID'), 
    'APP_STORE_GA_ID': os.getenv('APP_STORE_GA_ID'), 
    'APP_HOME_GA_ID': os.getenv('APP_HOME_GA_ID')       

}


HOME_LINK = os.getenv('HOME_LINK','https://home.zaamo.co')

STEAL_DEAL_LIMIT = os.getenv('STEAL_DEAL_LIMIT','25')

CONTENT_SERVICE_UPLOAD_URL = os.getenv('CONTENT_SERVICE_UPLOAD_URL', "https://betacontent.zaamo.co/engine/content/upload")

MAX_UPLOAD_SIZE = "10485760"

IS_BETA = get_bool_from_env('IS_BETA', True)

BETA_RECIPIENT_EMAIL = os.getenv('BETA_RECIPIENT_EMAIL', "priyanshu+test@zaamo.co")

WIX_GATEWAY = {
    'WIX_APP_ID': os.getenv('WIX_APP_ID'),
    'WIX_APP_SECRET': os.getenv('WIX_APP_SECRET'),
    'WIX_OAUTH_URL': os.getenv("WIX_OAUTH_URL"),
    'WIX_BASE_URL': os.getenv("WIX_BASE_URL"),
    'WIX_INSTALLER_URL': os.getenv("WIX_INSTALLER_URL"),
    'WIX_REDIRECT_URL': os.getenv("WIX_REDIRECT_URL"),
}
CRYPTOGRAPHY_KEY = os.getenv('CRYPTOGRAPHY_KEY')

CONTENT_SERVICE_URL = os.getenv('CONTENT_SERVICE_URL', "https://betacontent.zaamo.co")

CONTENT_SERVICE_TOKEN = os.getenv('CONTENT_SERVICE_TOKEN')

UNICOMMERCE_CLIENT_ID = os.getenv('UNICOMMERCE_CLIENT_ID',"")

UNICOMMERCE_SERVICE_KEY = os.getenv('UNICOMMERCE_SERVICE_KEY',"")

INTERAKT_API_KEY = os.getenv('INTERAKT_API_KEY',"")

INSTAGRAM_GRAPH_API = os.getenv('INSTAGRAM_GRAPH_API', 'https://graph.facebook.com/v15.0')

FB_CATALOG_CREDENTIALS = json.loads(os.getenv('FB_CATALOG_CREDENTIALS', '{"catalog_id": "access_token"}'))

GOOGLE_MERCHANT_ID = os.getenv('GOOGLE_MERCHANT_ID')

GOOGLE_MERCHANT_CREDENTIALS = os.getenv('GOOGLE_MERCHANT_CREDENTIALS', 'saleor/external_services/google_merchant/google_content_api.json')
GM_CATALOG_BUCKET_CREDENTIALS = os.getenv('GM_CATALOG_BUCKET_CREDENTIALS', 'saleor/external_services/google_merchant/zaamo-quanitifi.json')

GOOGLE_ANALYTICS_CREDENTIALS = os.getenv('GOOGLE_ANALYTICS_CREDENTIALS', 'saleor/external_services/google_analytics/google_analytics.json')

BRAND_ORDER_DB_USER=os.getenv('BRAND_ORDER_DB_USER')
BRAND_ORDER_DB_PASSWORD=os.getenv('BRAND_ORDER_DB_PASSWORD')
BRAND_ORDER_DB_HOST=os.getenv('BRAND_ORDER_DB_HOST')
BRAND_ORDER_DB_PORT=os.getenv('BRAND_ORDER_DB_PORT')
BRAND_ORDER_DB_NAME=os.getenv('BRAND_ORDER_DB_NAME')

FILE_STORAGE = os.getenv('FILE_STORAGE', 'AWS')
GUEST_NOTIFICATION_USER = os.getenv('GUEST_NOTIFICATION_USER', 'dummyNotification@zaamo.co')

FRESHDESK_AUTH = os.getenv('FRESHDESK_AUTH')
FRESHDESK_CHECKOUT_TICEKT_LIMIT = os.getenv('FRESHDESK_CHECKOUT_TICEKT_LIMIT',20)
FRESHDESK_ORDER_TICEKT_LIMIT = os.getenv('FRESHDESK_ORDER_TICEKT_LIMIT',100)

CHROMEDRIVER_PATH = os.getenv('CHROMEDRIVER_PATH', 'saleor/chromedriver')

RESTRICT_MANAUL_SHOPIY_ORDER = get_bool_from_env('RESTRICT_MANAUL_SHOPIY_ORDER', False)
INSTAGRAM_CLIENT_SECRET = os.getenv('INSTAGRAM_CLIENT_SECRET', 'c593beaa0a22e7d8a22f60aa8b997577')
INSTAGRAM_CLIENT_ID = os.getenv('INSTAGRAM_CLIENT_ID', '483436674317103')

