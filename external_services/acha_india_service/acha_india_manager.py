import abc


class AchaIndiaManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'insert_product_data_from_acha_india_store') and
                callable(subclass.insert_product_data_from_acha_india_store) and
                hasattr(subclass, 'fetch_product_data_from_acha_india_store') and
                callable(subclass.fetch_product_data_from_acha_india_store) and
                hasattr(subclass, 'insert_store_data_from_acha_india_store') and
                callable(subclass.insert_store_data_from_acha_india_store) and
                hasattr(subclass, 'fetch_store_by_url_from_acha_india_store') and
                callable(subclass.fetch_store_by_url_from_acha_india_store) and
                hasattr(subclass, 'create_brand_from_acha_india') and
                callable(subclass.create_brand_from_acha_india) and
                hasattr(subclass, 'create_product_from_acha_india') and
                callable(subclass.create_product_from_acha_india)
                or
                NotImplemented)

    def insert_product_data_from_acha_india_store(shop):
        """
        insert products from acha_india store to mongo
        """
        raise NotImplementedError

    def fetch_product_data_from_acha_india_store(store_url):
        """
        fetch product of acha_india store from mongo
        """
        raise NotImplementedError

    def insert_store_data_from_acha_india_store(acha_india_cred_dict: dict):
        """
        create shop data from acha_india store
        """
        raise NotImplementedError

    def fetch_store_by_url_from_acha_india_store():
        """
        fetch store data from acha_india store
        """
        raise NotImplementedError

    def create_brand_from_acha_india(shop):
        """
        Create brand in DB from Woo Commerce store Collection
        """
        raise NotImplementedError

    def create_product_from_acha_india(shop):
        """
        Create Product in DB from Woo Commerce store Collection
        """
        raise NotImplementedError
