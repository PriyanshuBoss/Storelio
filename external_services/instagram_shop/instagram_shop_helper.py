import logging
from django.db.models import QuerySet, Case, When, Value, Sum, CharField, IntegerField
from django.conf import settings

from .constants import Status, Availability, Condition, GPC
from saleor.utilities.number_utilities import NumberUtilities
from saleor.product.models import ProductImage
from saleor.brand.states import BrandStatusEnum

logger = logging.getLogger(__name__)

class CatalogHelper:

    @staticmethod
    def get_product_status_requests_list(variants: QuerySet, start_index, end_index):
        queryset = variants.annotate(quantity=Case(When(track_inventory=False, then=Value('50')), default=Sum('stocks__quantity'), output_field=IntegerField()))\
                    .annotate(availability=Case(When(quantity__gt=0, then=Value(Availability.IN_STOCK)), default=Value(Availability.OUT_OF_STOCK), output_field=CharField()))\
                    .values('id', 'product__is_published', 'product__brand__status', 'availability', 'cost_price_amount', 'price_amount')
                    
        queryset = queryset[start_index: end_index]
        
        _requests = []
        for variant in queryset:
            status = Status.ARCHIVED
            if variant['product__brand__status'] == BrandStatusEnum.ACTIVE and variant['product__is_published'] == True:
                status = Status.ACTIVE
            _request = {
                'method': 'UPDATE',
                'retailer_id': variant['id'],
                'data': {
                    'visibility': status,
                    'availability': variant['availability'],
                    'price': NumberUtilities.convert_string_to_number(variant['cost_price_amount'] * 100),
                    'sale_price': NumberUtilities.convert_string_to_number(variant['price_amount'] * 100),
                    'currency': 'INR'
                }
            }
            _requests.append(_request)

        return _requests

    @staticmethod
    def get_product_delete_requests_list(variants: QuerySet, start_index, end_index):
        queryset = variants.values('id')[start_index: end_index]
        
        _requests = []
        for variant in queryset:
            _request = {
                'method': 'DELETE',
                'retailer_id': variant['id']
            }
            _requests.append(_request)

        return _requests

    @staticmethod
    def get_product_create_requests_list(variants: QuerySet, start_index, end_index):
        queryset = variants\
                    .annotate(quantity=Case(When(track_inventory=False, then=Value('50')), default=Sum('stocks__quantity'), output_field=IntegerField()))\
                    .annotate(availability=Case(When(quantity__gt=0, then=Value(Availability.IN_STOCK)), default=Value(Availability.OUT_OF_STOCK), output_field=CharField()))\
                    .values('id', 'product__name', 'product__description_json__description_text', 'availability', 'cost_price_amount', 'product__slug', 'product__brand__brand_name', 
                        'product__category__name', 'quantity', 'price_amount', 'product__publication_date', 'product_id', 'name', 'product__brand__status', 'product__is_published'
                    )
        queryset = queryset[start_index: end_index]
        
        product_image = CatalogHelper.get_product_image(queryset)

        _requests = []
        for variant in queryset:
            if not variant['product_id'] in product_image or not variant.get('cost_price_amount') or not variant.get('price_amount'):
                logger.info(f"image/price not found for product_id {variant['product_id']}")
                continue
            image_key = product_image.get(variant['product_id'])
            
            data = CatalogHelper.get_variant_data_for_catalog(variant, image_key)
            _request = {
                'method': "CREATE",
                'retailer_id': variant['id'],
                'data': data
            }
            _requests.append(_request)

        return _requests

    @staticmethod
    def get_variant_data_for_catalog(variant, image_key):
        """
        https://developers.facebook.com/docs/marketing-api/catalog-batch/reference#supported-fields-batch
        """
        status = Status.ARCHIVED
        if variant['product__brand__status'] == BrandStatusEnum.ACTIVE and variant['product__is_published'] == True:
            status = Status.ACTIVE
        data = {
            'retailer_product_group_id': variant['product_id'],
            'brand': variant['product__brand__brand_name'],
            'name': variant['product__name'],
            'size': variant['name'].upper(),
            'url': 'https://zaamo.co/zaamo/products/' + variant['product__slug'],
            # 'image_url': f"https://{settings.AWS_MEDIA_BUCKET_NAME}.s3.amazonaws.com/{settings.AWS_LOCATION}/{image_key}",
            'image_url': f"https://storage.googleapis.com/{settings.GS_MEDIA_BUCKET_NAME}/{settings.GS_LOCATION}/{image_key}",
            'category': GPC.get(variant['product__category__name'].strip()) or "Apparel & Accessories",
            'description': variant['product__description_json__description_text'] or "-",
            'availability': variant['availability'],
            'inventory': variant['quantity'],
            'visibility': status,
            'price': NumberUtilities.convert_string_to_number(variant['cost_price_amount'] * 100),
            'sale_price': NumberUtilities.convert_string_to_number(variant['price_amount'] * 100),
            'condition': Condition.NEW,
            'currency': 'INR',
            'age_group': 'adult'
        }

        return data

    @staticmethod
    def get_product_image(product_variants: dict):
        product_ids = set(variant['product_id'] for variant in product_variants)
        image_qs = ProductImage.objects.filter(product_id__in=product_ids).order_by('id').values_list('product_id', 'image')
        
        images = dict()
        for pid, image in image_qs:
            if not pid in images:
                images[pid] = image

        return images


