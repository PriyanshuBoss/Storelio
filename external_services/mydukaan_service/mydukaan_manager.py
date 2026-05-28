import abc


class MyDukaanManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'insert_product_data_from_mydukaan_store') and
                callable(subclass.insert_product_data_from_mydukaan_store) and
                hasattr(subclass, 'fetch_product_data_from_mydukaan_store') and
                callable(subclass.fetch_product_data_from_mydukaan_store) and
                hasattr(subclass, 'insert_store_data_from_mydukaan_store') and
                callable(subclass.insert_store_data_from_mydukaan_store) and
                hasattr(subclass, 'fetch_store_by_url_from_mydukaan_store') and
                callable(subclass.fetch_store_by_url_from_mydukaan_store) and
                hasattr(subclass, 'add_new_product_to_store_from_webhook') and
                callable(subclass.add_new_product_to_store_from_webhook) and
                hasattr(subclass, 'update_product_to_store_from_webhook') and
                callable(subclass.update_product_to_store_from_webhook) and
                hasattr(subclass, 'delete_product_from_store') and
                callable(subclass.delete_product_from_store) and
                hasattr(subclass, 'create_brand_from_MyDukaan') and
                callable(subclass.create_brand_from_MyDukaan) and
                hasattr(subclass, 'create_product_from_MyDukaan') and
                callable(subclass.create_product_from_MyDukaan) and
                hasattr(subclass, 'place_orders_util') and
                callable(subclass.place_orders_util) 
                or
                NotImplemented)

    def insert_product_data_from_mydukaan_store(shop):
        """
        insert products from mydukaan store to mongo
        """
        raise NotImplementedError

    def fetch_product_data_from_mydukaan_store(store_url):
        """
        fetch product of mydukaan store from mongo
        """
        raise NotImplementedError

    def insert_store_data_from_mydukaan_store(mydukaan_cred_dict: dict):
        """
        create shop data from mydukaan store
        """
        raise NotImplementedError

    def fetch_store_by_url_from_mydukaan_store():
        """
        fetch store data from mydukaan store
        """
        raise NotImplementedError

    def add_new_product_to_store_from_webhook(data: dict):
        """
        add new product to store from webhook
        """
        raise NotImplementedError

    def update_product_to_store_from_webhook(data: dict):
        """
        update product to store from webhook
        """
        raise NotImplementedError

    def create_brand_from_MyDukaan(shop):
        """
        Create brand in DB from My Dukaan store Collection
        """
        raise NotImplementedError

    def create_product_from_MyDukaan(shop):
        """
        Create Product in DB from My Dukaan store Collection
        """
        raise NotImplementedError

    def place_orders_util(order_line_obj, brand_mapping):
        """
        Place orders from My Dukaan API
        """
        raise NotImplementedError
    
    def delete_product_from_store(product_id):
        """
        Delete product
        """
        raise NotImplementedError
        