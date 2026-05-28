from google.cloud import storage
from google.oauth2 import service_account
import googleapiclient.discovery
import json
import logging

from django.db.models import QuerySet, Case, When, Value, CharField, IntegerField, Sum
from django.conf import settings

from .constants import *
from saleor.product.models import ProductImage, ProductVariant
from saleor.brand.states import BrandStatusEnum
from saleor.utilities.time_utilities import TimeUtilities
import io
import csv
import traceback

logger = logging.getLogger(__name__)


class GoogleMerchant:
    """
    https://developers.google.com/shopping-content/guides/quickstart
    https://developers.google.com/shopping-content/reference/rest/v2.1/products/custombatch
    """
    BATCH_SIZE = 1000
    BUCKET_NAME = 'gmc_product_catalog'
    
    def __init__(self, merchant_id=None) -> None:
        self.MERCHANT_ID = merchant_id or settings.GOOGLE_MERCHANT_ID
        # self.BUCKET_CREDENTIALS = service_account.Credentials.from_service_account_file(settings.GM_CATALOG_BUCKET_CREDENTIALS)
        if not self.MERCHANT_ID:
            raise ValueError('Invalid Merchant ID')

    @staticmethod
    def get_service_client():
        credentials = service_account.Credentials.from_service_account_file(settings.GOOGLE_MERCHANT_CREDENTIALS, scopes=CONTENT_API_SCOPE)
        service = googleapiclient.discovery.build(SERVICE_NAME, SERVICE_VERSION, credentials=credentials, cache_discovery=False)
        return service

    @staticmethod
    def get_product_rest_id(id):
        return f"{CHANNEL}:{CONTENT_LANGUAGE}:{TARGET_COUNTRY}:{id}"
    
    @classmethod
    def get_csv_key_value(cls, key, value):
        """
        join nested dict keys with _
        """
        data = {}
        if isinstance(value, dict):
            cdata = {}
            for ckey, cvalue in value.items():
                cdata.update(cls.get_csv_key_value(ckey, cvalue))
            for k, v in cdata.items():
                data['_'.join([key, k])] = v
        else:
            data[key] = value
        return data
    
    def upload_fileobj_to_gcs(self, fileobj, filepath, content_type='text/csv'):
        bucket_name = self.BUCKET_NAME
        
        storage_client = storage.Client(credentials=self.BUCKET_CREDENTIALS)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filepath)
        try:
            blob.upload_from_string(fileobj.read(), content_type=content_type)
            return True
        except Exception as e:
            logger.error(f"file upload failed || filepath::{filepath} || bucket::{bucket_name}")
            return False
        
    @classmethod
    def get_csv_dict_fileobj(cls, rows: "list[dict]"):
        if not rows:
            return False
        
        header = list(rows[0].keys())
        fileobj = io.StringIO()
        csv_writer = csv.DictWriter(fileobj, fieldnames=header)
        csv_writer.writeheader()
        csv_writer.writerows(rows)
        fileobj.seek(0)
        return fileobj

    @classmethod
    def get_all_insert_keys(cls):
        ids = ProductImage.objects.all().values_list('product__default_variant_id', flat=True)[:100]
        variants = ProductVariant.objects.filter(id__in=ids)
        products = cls.get_product_create_details(variants, start=0, end=100)
        keys = list(cls.get_csv_key_value(key='product', value=products[0]).keys())
        return keys

    def upload_product_catalog(self, products, method, batch_size=10000):
        try:
            rows = []
            all_keys = []
            if method == 'update':
                all_keys = self.get_all_insert_keys()
            for product in products:
                row = dict()
                for key, value in product.items():
                    data = self.get_csv_key_value(key, value)
                    row.update(data)
                for key in all_keys:
                    row[key] = row.get(key, '')
                row['product_archive'] = True if product['product'].get('excludedDestinations') else False
                rows.append(row)
            if rows:
                for i in range(0, len(rows), batch_size):
                    fileobj = self.get_csv_dict_fileobj(rows[i: i + batch_size])
                    filepath = f'gmc_catalog_{method}_{TimeUtilities.current_time_in_milliseconds()}.csv'
                    self.upload_fileobj_to_gcs(fileobj, filepath)
        except Exception as e:
            logger.error(traceback.format_exc())

    @classmethod
    def product_batch_requests(cls, _entries: "list[dict]"):
        try:
            service = cls.get_service_client()
            batch = {
                'entries': _entries
            }
            request = service.products().custombatch(body=batch)
            result = request.execute()
            
            if result['kind'] == 'content#productsCustomBatchResponse':
                entries = result['entries']
                for entry in entries:
                    product = entry.get('product')
                    errors = entry.get('errors')
                    if product:
                        logger.info('Product "%s" with offerId "%s" was %sd.' % (product['id'], product['offerId'], _entries[0]['method']))
                    elif errors:
                        logger.error('Errors for batch entry %d:' % entry['batchId'])
                        logger.error(json.dumps(errors, sort_keys=True, indent=2, separators=(',', ': ')))
            else:
                logger.error('There was an error. Response: %s' % result)

            return result
        
        except Exception as e:
            logger.error(e)
            return None

    def insert_products(self, variants: QuerySet, batch_size=BATCH_SIZE):
        """
        https://developers.google.com/shopping-content/reference/rest/v2.1/products/insert
        """
        method = 'insert'
        size = variants.count()
        for start in range(0, size, batch_size):
            end = start + batch_size
            products = self.get_product_create_details(variants, start, end)
            entries = []
            for idx, product in enumerate(products):
                entries.append({
                    'batchId': idx,
                    'merchantId': self.MERCHANT_ID,
                    'method': method,
                    'product': product
                })
            accepted = self.product_batch_requests(entries)

    def get_products(self, variants: QuerySet, batch_size=BATCH_SIZE):
        size = variants.count()
        data = []
        for start in range(0, size, batch_size):
            end = start + batch_size
            products = self.get_product_ids(variants, start, end)
            entries = []
            for idx, product in enumerate(products):
                entries.append({
                    'batchId': idx,
                    'merchantId': self.MERCHANT_ID,
                    'method': 'get',
                    'productId': self.get_product_rest_id(product['id'])
                })
            
            data.append(self.product_batch_requests(entries))
        return data

    def delete_products(self, variants: QuerySet, batch_size=BATCH_SIZE):
        """
        https://developers.google.com/shopping-content/reference/rest/v2.1/products/delete
        """
        method = 'delete'
        size = variants.count()
        for start in range(0, size, batch_size):
            end = start + batch_size
            products = self.get_product_ids(variants, start, end)
            entries = []
            for idx, product in enumerate(products):
                entries.append({
                    'batchId': idx,
                    'merchantId': self.MERCHANT_ID,
                    'method': method,
                    'productId': self.get_product_rest_id(product['id'])
                })
            
            accepted = self.product_batch_requests(entries)

    def update_products(self, variants: QuerySet, batch_size=BATCH_SIZE):
        """
        https://developers.google.com/shopping-content/reference/rest/v2.1/products/update
        """
        method = 'update'
        size = variants.count()
        for start in range(0, size, batch_size):
            end = start + batch_size
            products = self.get_product_update_details(variants, start, end)
            entries = []
            for idx, product in enumerate(products):
                entries.append({
                    'batchId': idx,
                    'merchantId': self.MERCHANT_ID,
                    'method': method,
                    'productId': self.get_product_rest_id(product.pop('id')),
                    'product': product,
                    'updateMask': "availability,price,salePrice,excludedDestinations"
                })
            accepted = self.product_batch_requests(entries)

    @classmethod
    def get_product_update_details(cls, variants: QuerySet, start, end):
        queryset = variants.annotate(quantity=Case(When(track_inventory=False, then=Value('50')), default=Sum('stocks__quantity'), output_field=IntegerField()))\
                    .annotate(availability=Case(When(quantity__gt=0, then=Value(Availability.IN_STOCK)), default=Value(Availability.OUT_OF_STOCK), output_field=CharField()))\
                    .values('id', 'product__is_published', 'product__brand__status', 'availability', 'cost_price_amount', 'price_amount')

        queryset = queryset[start: end]
        
        products = []
        for variant in queryset:
            data = {
                'id': variant['id'],
                'availability': variant['availability'],
                'price': {
                    "value": f"{variant['cost_price_amount']:.2f}", 
                    "currency": "INR"
                },
                'salePrice': {
                    "value": f"{variant['price_amount']:.2f}", 
                    "currency": "INR"
                },
            }
            excluded_destinations = cls.get_product_excluded_destinations(variant)
            if excluded_destinations:
                data['excludedDestinations'] = excluded_destinations
            products.append(data)
        
        return products

    @classmethod
    def get_product_ids(cls, variants: QuerySet, start, end):
        queryset = variants.values('id')[start: end]
        
        products = list(queryset)
        
        return products


    @classmethod
    def get_product_create_details(cls, variants: QuerySet, start, end):
        queryset = variants.annotate(quantity=Case(When(track_inventory=False, then=Value('50')), default=Sum('stocks__quantity'), output_field=IntegerField()))\
                .annotate(availability=Case(When(quantity__gt=0, then=Value(Availability.IN_STOCK)), default=Value(Availability.OUT_OF_STOCK), output_field=CharField()))\
                .values('id', 'product__name', 'product__description_json__description_text', 'availability', 'cost_price_amount', 'product__slug', 'product__brand__brand_name', 
                    'product__category__name', 'quantity', 'price_amount', 'product__publication_date', 'product_id', 'name', 'product__brand__status', 'product__is_published'
                )
        queryset = queryset[start: end]
        
        products = []
        product_images = cls.get_product_images(queryset)
        for variant in queryset:
            if not variant['product_id'] in product_images or not variant.get('cost_price_amount') or not variant.get('price_amount'):
                logger.info(f"image/price not found for product_id {variant['product_id']}")
                continue
            image_key = product_images.get(variant['product_id'])
            
            data = {
                'id': variant['id'],
                'offerId': variant['id'],
                'title': variant['product__name'],
                'description': variant.get('product__description_json__description_text', '-'),
                'link': 'https://zaamo.co/zaamo/products/' + variant['product__slug'],
                # 'imageLink': f"https://{settings.AWS_MEDIA_BUCKET_NAME}.s3.amazonaws.com/{settings.AWS_LOCATION}/{image_key}",
                'imageLink': f"https://storage.googleapis.com/{settings.GS_MEDIA_BUCKET_NAME}/{settings.GS_LOCATION}/{image_key}",
                'availability': variant['availability'],
                'price': {
                    "value": f"{variant['cost_price_amount']:.2f}", 
                    "currency": "INR"
                    },
                'salePrice': {
                    "value": f"{variant['price_amount']:.2f}", 
                    "currency": "INR"
                    },
                'googleProductCategory': GPC.get(variant['product__category__name'].strip()) or "Apparel & Accessories",
                'brand': variant['product__brand__brand_name'],
                'condition': Condition.NEW,
                'ageGroup': 'adult',
                'sizes': [variant['name']],
                'itemGroupId': variant['product_id'],
                'channel': CHANNEL,
                'contentLanguage': CONTENT_LANGUAGE,
                'targetCountry': TARGET_COUNTRY,

            }
            excluded_destinations = cls.get_product_excluded_destinations(variant)
            if excluded_destinations:
                data['excludedDestinations'] = excluded_destinations
            else:
                data['excludedDestinations'] = ''
            products.append(data)
        return products

    @staticmethod
    def get_product_images(product_variants: dict):
        product_ids = set(variant['product_id'] for variant in product_variants)
        image_qs = ProductImage.objects.filter(product_id__in=product_ids).order_by('id').values_list('product_id', 'image')
        
        images = dict()
        for pid, image in image_qs:
            if not pid in images:
                images[pid] = image

        return images

    @staticmethod
    def get_product_pause_ads(variant: dict):
        """
        temporarily pause showing product in (ads or all) destinations.
        """
        pause = 'ads' # or 'all'
        if variant['product__brand__status'] == BrandStatusEnum.ACTIVE and variant['product__is_published'] == True:
            pause = None
        return pause

    @staticmethod
    def get_product_excluded_destinations(variant: dict):
        """
        controls product visibility
        """
        if variant['product__brand__status'] == BrandStatusEnum.ACTIVE and variant['product__is_published'] == True:
            return None
        return EXCLUDED_DESTINATIONS

