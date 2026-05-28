import abc

class CacheManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'set_cache') and
                callable(subclass.set_cache) and
                hasattr(subclass, 'get_cache') and
                callable(subclass.get_cache) and
                hasattr(subclass, 'delete_key') and
                callable(subclass.delete_key) and
                hasattr(subclass, 'add_cache') and
                callable(subclass.add_cache)
                or
                NotImplemented)

    @staticmethod
    def set_cache(key, value, timeout=None) -> bool:
        """
        sets up a cache
        """
        raise NotImplementedError

    @staticmethod
    def get_cache(key) -> dict():
        """
        gets the result from the cache
        """
        raise NotImplementedError

    @staticmethod
    def delete_key(key) -> bool:
        """
        delete key from cache
        """
        raise NotImplementedError

    @staticmethod
    def add_cache(key) -> dict():
        """
        add to the cache
        """
        raise NotImplementedError
