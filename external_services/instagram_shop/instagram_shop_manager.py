from .constants import INSTAGRAM_GRAPH_API
import logging

from django.db.models import QuerySet
from django.conf import settings

from saleor.utilities.api_client import ApiClient
from .instagram_shop_helper import CatalogHelper

logger = logging.getLogger(__name__)

class CatalogManager:
    """
    https://developers.facebook.com/docs/marketing-api/catalog-batch/reference
    https://developers.facebook.com/docs/marketing-api/catalog-batch/reference#supported-fields-batch
    """
    
    def __init__(self, catalog_id=None, access_token=None):
        self.catalog_id = catalog_id
        self.access_token = access_token

    def update_catalog(self, requests_list: "list[dict]"):
        """
        One or more handles will be returned.
        "handles": ["AczwaOW7j_EuQ5peV3kGq8X9qc7cDiv_kFrrHkdKuG7LkpkkqK5939-wgdoduSQ45FGK5vKdVqOaSDJEun"]
        requests_list size limit = 5000
        """
        if not self.catalog_id or not self.access_token:
            logger.error("Invalid catalog_id or access_token")
            return
        update_catalog_url = f'{INSTAGRAM_GRAPH_API}/{self.catalog_id}/batch'

        data = {
            'access_token': self.access_token,
            'requests': requests_list
        }
        api_client = ApiClient(url=update_catalog_url)
        api_client.update_body(data)
        api_client.post()
        res = api_client.response.json()
        if not 'handles' in res:
            logger.error(res)
        else:
            logger.info(res)

        return res

    def get_batch_request_status(self, handle):
        endpoint = f'{INSTAGRAM_GRAPH_API}/{self.catalog_id}/check_batch_request_status'
        params = {
            'access_token': self.access_token,
            'handle': handle
        }
        
        api_client = ApiClient(url=endpoint)
        
        api_client.update_url_params(params)
        url = api_client.get_request_url() + api_client.get_url_params()
        api_client.update_request_url(url)

        api_client.get()
        res = api_client.fetch_response()

        return res

    def add_products_to_catalog(self, product_variants: QuerySet, batch_size=5000):
        size = product_variants.count()
        for start_index in range(0, size, batch_size):
            end_index = start_index + batch_size
            requests_list = CatalogHelper.get_product_create_requests_list(product_variants, start_index, end_index)
            self.update_catalog(requests_list)

    def update_product_status(self, product_variants: QuerySet, batch_size=5000):
        size = product_variants.count()
        for start_index in range(0, size, batch_size):
            end_index = start_index + batch_size
            requests_list = CatalogHelper.get_product_status_requests_list(product_variants, start_index, end_index)
            self.update_catalog(requests_list)

    def delete_product_from_catalog(self, product_variants: QuerySet, batch_size=5000):
        size = product_variants.count()
        for start_index in range(0, size, batch_size):
            end_index = start_index + batch_size
            requests_list = CatalogHelper.get_product_delete_requests_list(product_variants, start_index, end_index)
            self.update_catalog(requests_list)

