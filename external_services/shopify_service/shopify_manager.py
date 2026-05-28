import abc


class ShopifyManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'create_brand_from_shopify') and
                callable(subclass.create_brand_from_shopify) and
                hasattr(subclass, 'create_products_in_shopify') and
                callable(subclass.create_products_in_shopify) and
                hasattr(subclass, 'insert_product_data_from_shopify_store') and
                callable(subclass.insert_product_data_from_shopify_store) and
                hasattr(subclass, 'fetch_product_data_from_shopify_store') and
                callable(subclass.fetch_product_data_from_shopify_store) and
                hasattr(subclass, 'insert_store_data_from_shopify_store') and
                callable(subclass.insert_store_data_from_shopify_store) and
                hasattr(subclass, 'fetch_store_by_id_from_shopify_store') and
                callable(subclass.fetch_store_by_id_from_shopify_store) 
                or
                NotImplemented)

    def create_brand_from_shopify():
        """
        create a brand from shopify
        """
        raise NotImplementedError

    def create_products_from_shopify():
        """
        create products from shopify
        """
        raise NotImplementedError

    def insert_product_data_from_shopify_store(store):
        """
        insert products from shopify store to mongo
        """
        raise NotImplementedError

    def fetch_product_data_from_shopify_store(store):
        """
        fetch product of shopify store from mongo
        """
        raise NotImplementedError

    def insert_store_data_from_shopify_store():
        """
        create shop data from shopify store
        """
        raise NotImplementedError

    def fetch_store_by_id_from_shopify_store():
        """
        fetch store data from shopify store
        """
        raise NotImplementedError
