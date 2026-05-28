from django.conf import settings
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.contrib.staticfiles.views import serve
from django.views.decorators.csrf import csrf_exempt

from .data_feeds.urls import urlpatterns as feed_urls
from saleor.rest_apis.mapper.urls import urlpatterns as mapper_urls
from saleor.rest_apis.wix.urls import urlpatterns as wix_urls
from saleor.rest_apis.cashfree.urls import urlpatterns as cashfree_urls
from saleor.rest_apis.razorpay.urls import urlpatterns as razorpay_urls
from saleor.rest_apis.woocommerce_webhooks.urls import urlpatterns as woocommerce_webhooks_urls
from saleor.rest_apis.instagram.urls import urlpatterns as instagram_urls
from saleor.rest_apis.shopify_webhooks.urls import urlpatterns as shopify_webhooks_urls
from saleor.rest_apis.csv.urls import urlpatterns as csv_urls
from saleor.rest_apis.reels.urls import urlpatterns as reels_urls
from saleor.rest_apis.insights.urls import urlpatterns as insights_urls
from saleor.rest_apis.unicommerce_integration.urls import urlpatterns as unicommerce_urls
from .graphql.api import schema
from .graphql.views import GraphQLView
from .plugins.views import handle_plugin_webhook
from .product.views import digital_product
from django.contrib import admin
from django.contrib.sites.models import Site
from django_prices_vatlayer.models import VAT
from django_prices_openexchangerates.models import ConversionRate
from saleor.rest_apis.routers import router

admin.site.site_header = admin.site.site_title = "Zaamo Administration"
admin.site.unregister(Site)
admin.site.unregister(VAT)
admin.site.unregister(ConversionRate)

urlpatterns = [
    url(r"^graphql/", csrf_exempt(GraphQLView.as_view(schema=schema)), name="api"),
    url(r"^feeds/", include((feed_urls, "data_feeds"), namespace="data_feeds")),
    url(
        r"^digital-download/(?P<token>[0-9A-Za-z_\-]+)/$",
        digital_product,
        name="digital-product",
    ),
    url(
        r"plugins/(?P<plugin_id>[.0-9A-Za-z_\-]+)/",
        handle_plugin_webhook,
        name="plugins",
    ),
    url(r"admin/", admin.site.urls),
    url(r"^mapper/", include((mapper_urls, "mapper_urls"), namespace="mapper_urls")),
    url(r"^cashfree/", include((cashfree_urls, "cashfree_urls"), namespace="cashfree_urls")),
    url(r"^razorpay/", include((razorpay_urls, "razorpay_urls"), namespace="razorpay_urls")),
    url(r"^webhooks/woocommerce/", include((woocommerce_webhooks_urls, "woocommerce_webhooks_urls"), namespace="woocommerce_webhooks_urls")),
    url(r"^instagram/", include((instagram_urls, "instagram_urls"), namespace="instagram_urls")),
    url(r"^webhooks/shopify/", include((shopify_webhooks_urls, "shopify_webhooks_urls"), namespace="shopify_webhooks_urls")),
    url(r"^wix/", include((wix_urls, "wix"), namespace="wix")),
    url(r"^csv/", include((csv_urls, "csv"), namespace="csv")),
    url(r"^reels/", include((reels_urls, "reels"), namespace="reels")),
    url(r"^zaamo_integration/unicommerce/",include((unicommerce_urls,"unicommerce"), namespace="unicommerce" )),
    url(r"^insights/", include((insights_urls, "insights"), namespace="insights")),

    url(r"^api/v1/", include(router.urls)),


]


if settings.DEBUG:
    import warnings
    from .core import views

    try:
        import debug_toolbar
    except ImportError:
        warnings.warn(
            "The debug toolbar was not installed. Ignore the error. \
            settings.py should already have warned the user about it."
        )
    else:
        urlpatterns += [url(r"^__debug__/", include(debug_toolbar.urls))]

    urlpatterns += static("/media/", document_root=settings.MEDIA_ROOT) + [
        url(r"^static/(?P<path>.*)$", serve),
        url(r"^", views.home, name="home"),
    ]
