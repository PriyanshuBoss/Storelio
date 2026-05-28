from io import BytesIO
from typing import Iterable, List, Optional
import datetime
from django.db.models import Subquery, ExpressionWrapper, F, OuterRef, IntegerField, Func, Sum, Q
from django.db.models.functions import Coalesce, DenseRank, ExtractDay
from django.forms import CharField
from .views import create_productsgroupingmapping
from saleor.settings import IS_BETA
from ..celeryconf import app
from ..discount.models import Sale
from .models import Attribute, CollectionProduct, Product, ProductImage, ProductType, ProductVariant, StoreProductViews
from .utils.attributes import generate_name_for_variant
from saleor.utilities.time_utilities import TimeUtilities
from .utils.variant_prices import (
    update_product_minimal_variant_price,
    update_products_minimal_variant_prices,
    update_products_minimal_variant_prices_of_catalogues,
    update_products_minimal_variant_prices_of_discount,
)
import logging
logger = logging.getLogger(__name__)

import base64
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.base import ContentFile
from saleor.external_services.google_analytics.ga_helper import get_product_views, set_time_date_ga

def _update_variants_names(instance: ProductType, saved_attributes: Iterable):
    """Product variant names are created from names of assigned attributes.

    After change in attribute value name, for all product variants using this
    attributes we need to update the names.
    """
    initial_attributes = set(instance.variant_attributes.all())
    attributes_changed = initial_attributes.intersection(saved_attributes)
    if not attributes_changed:
        return
    variants_to_be_updated = ProductVariant.objects.filter(
        product__in=instance.products.all(),
        product__product_type__variant_attributes__in=attributes_changed,
    )
    variants_to_be_updated = variants_to_be_updated.prefetch_related(
        "attributes__values__translations"
    ).all()
    for variant in variants_to_be_updated:
        variant.name = generate_name_for_variant(variant)
        variant.save(update_fields=["name"])


@app.task
def update_variants_names(product_type_pk: int, saved_attributes_ids: List[int]):
    instance = ProductType.objects.get(pk=product_type_pk)
    saved_attributes = Attribute.objects.filter(pk__in=saved_attributes_ids)
    _update_variants_names(instance, saved_attributes)


@app.task
def update_product_minimal_variant_price_task(product_pk: int):
    product = Product.objects.get(pk=product_pk)
    update_product_minimal_variant_price(product)


@app.task
def update_products_minimal_variant_prices_of_catalogues_task(
    product_ids: Optional[List[int]] = None,
    category_ids: Optional[List[int]] = None,
    collection_ids: Optional[List[int]] = None,
):
    update_products_minimal_variant_prices_of_catalogues(
        product_ids, category_ids, collection_ids
    )


@app.task
def update_products_minimal_variant_prices_of_discount_task(discount_pk: int):
    discount = Sale.objects.get(pk=discount_pk)
    update_products_minimal_variant_prices_of_discount(discount)


@app.task
def update_products_minimal_variant_prices_task(product_ids: List[int]):
    products = Product.objects.filter(pk__in=product_ids)
    update_products_minimal_variant_prices(products)

def reset_weekly_visits():
    reset_products = Product.objects.filter(metadata__weekly_visits__gt=0).only('id', 'metadata')
    bulk_products = []
    for product in reset_products:
        product.metadata.update({'weekly_visits': 0})
        bulk_products.append(product)
    Product.objects.bulk_update(bulk_products, ['metadata'], batch_size=1000)

def update_product_views_in_meta():
    today = TimeUtilities().get_today_start()
    last_week = TimeUtilities().subtract_time_from_timestamp(today, days=7)
    date_range = set_time_date_ga(last_week, today)
    last_7_days_product_views = {product['_id']: product['views'] for product in get_product_views(date_range, group_by='product')}
        
    n_days_before_date = TimeUtilities.get_n_days_before_date(days=1)
    latest_viewed_products = Subquery(StoreProductViews.objects.filter(updated_at__gte=n_days_before_date).values_list('product', flat=True))


    queryset = Product.objects.filter(id__in=latest_viewed_products).annotate(total_pdp_views=Coalesce(Sum(
        'storeproductviews__views', distinct=True, filter=Q(updated_at__gte=n_days_before_date)), 0))\
            .annotate(weeks_since_product_live=1 + (ExtractDay(datetime.datetime.now() - F('updated_at')) / 7))\
                .annotate(product_views=ExpressionWrapper((10**7 * F('total_pdp_views') / F('weeks_since_product_live')) + F('id'), output_field=IntegerField()))
    
    updated_prods = []
    for product in queryset:
        old_product_views = product.metadata.get('product_views', 0)
        product_views = old_product_views + product.product_views
        product.metadata.update({'product_views': product_views})
        product.metadata.update({'weekly_visits': last_7_days_product_views.get(str(product.id), 0)})
        updated_prods.append(product)
    
    reset_weekly_visits()
    Product.objects.bulk_update(updated_prods,['metadata'], batch_size=1000)


@app.task(queue='celery_periodic')
def update_products_meta_ranking_attributes():

    if IS_BETA:
        return

    n_days_before_date = TimeUtilities.get_n_days_before_date(days=100)
        
    trending_products = CollectionProduct.objects.filter(created_at__gte=n_days_before_date)
    collections_added_sq = Subquery(trending_products.filter(product_id=OuterRef('id')).annotate(cnt=Func('id', function='COUNT')).values('cnt')[:1]) 
    
    queryset = Product.objects.annotate(collections_added=Coalesce(collections_added_sq, 0))\
            .annotate(weeks_since_product_live=1 + (ExtractDay(datetime.datetime.now() - F('updated_at')) / 7))\
                .annotate(trending_now=ExpressionWrapper((10**12 * F('collections_added') / F('weeks_since_product_live')) + F('id'), output_field=IntegerField()))

    products = queryset.filter(collections_added__gt=0)

    updated_prods = []
    for product in products:
        product.metadata.update({'trending_now': product.trending_now})
        updated_prods.append(product)

    Product.objects.bulk_update(updated_prods,['metadata'], batch_size=1000)

    update_product_views_in_meta()


@app.task(queue='celery_periodic')
def update_mapping_for_product_grouping():
    
    if IS_BETA:
        return
    
    '''
    from saleor.product.tasks import update_mapping_for_product_grouping
    update_mapping_for_product_grouping.delay()
    '''
    try:
        create_productsgroupingmapping()

    except Exception as e:
        logger.exception(e)


@app.task
def update_mapping_for_product_grouping_from_mutation(new_grouping_id):
    '''
    from saleor.product.tasks import update_mapping_for_product_grouping_from_mutation
    update_mapping_for_product_grouping_from_mutation.delay()
    '''
    try:
        create_productsgroupingmapping(new_grouping_id)

    except Exception as e:
        logger.exception(e)

@app.task(queue='priority_queue')
def delete_product_image(image_id):
    try:
        ProductImage.objects.get(id=image_id).delete()
    except Exception as e:
        logger.exception(f'image not found with id :: {image_id}')

@app.task(queue='priority_queue')
def save_image_with_celery(data,product_id):
    try:
        image = BytesIO(base64.b64decode(data.encode('utf-8')))
        image = InMemoryUploadedFile(image,'ImageField',
                    'amc' + '.png',
                    'image/png',
                    len(image.getbuffer()), None)
        product = Product.objects.get(id=product_id)
        product.images.create(image=image, alt='abc')
    
    except Exception as e:
        logger.exception(e)
