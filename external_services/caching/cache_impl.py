from .cache_manager import CacheManager
import redis
from django.conf import settings
from django.core.cache import cache
import logging
logger = logging.getLogger(__name__)


class CacheImpl(CacheManager):

    @staticmethod
    def set_cache(key, value, timeout=None) -> bool:

        status = False

        try:
            cache.set(key, value, timeout)
            status = True

        except Exception as e:
            logger.exception(e.args)

        return status

    @staticmethod
    def add_cache(key, value, timeout=None) -> bool:

        status = False

        try:
            status = cache.add(key, value, timeout)

        except Exception as e:
            logger.exception(e.args)

        return status

    @staticmethod
    def get_cache(key) -> dict():

        result = {}
        try:

            if key in cache:
                result = cache.get(key)
            
        except Exception as e:
            logger.exception(e.args)

        return result

    @staticmethod
    def delete_key(key) -> bool:

        status = False
        try:

            if key in cache:
                cache.delete(key)

                status = True

        except Exception as e:
            logger.exception(e.args)
            status = False

        return status

