import abc


class wixManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'insert_product_data_from_wix_store') and
                callable(subclass.insert_product_data_from_wix_store) and
                hasattr(subclass, 'insert_store_data_from_wix_store') and
                callable(subclass.insert_store_data_from_wix_store) and
                hasattr(subclass, 'create_brand_from_wix') and
                callable(subclass.create_brand_from_wix) and
                hasattr(subclass, 'generate_initial_access_refresh_token') and
                callable(subclass.generate_initial_access_refresh_token) and
                hasattr(subclass, 'generate_access_refresh_token') and
                callable(subclass.generate_access_refresh_token) and
                hasattr(subclass, 'set_instance_id') and
                callable(subclass.set_instance_id) and
                hasattr(subclass, 'set_refresh_token') and
                callable(subclass.set_refresh_token) and
                hasattr(subclass, 'place_orders_util') and
                callable(subclass.place_orders_util)
                or
                NotImplemented)

    def insert_product_data_from_wix_store(shop):
        """
        insert products from wix store to mongo
        """
        raise NotImplementedError

    def insert_store_data_from_wix_store(wix_cred_dict: dict):
        """
        create shop data from wix store
        """
        raise NotImplementedError

    def create_brand_from_wix(shop):
        """
        Create brand in DB from Woo Commerce store Collection
        """
        raise NotImplementedError
    
    def generate_initial_access_refresh_token(code):
        """
        generate first access token and refresh token for wix
        """
        raise NotImplementedError

    def generate_access_refresh_token():
        """        
        generate access token and refresh token for wix
        """
        raise NotImplementedError

    def set_instance_id(instance_id):
        """
        set instance_id
        """
        raise NotImplementedError
        
    def set_refresh_token(instance_id):
        """
        set refresh_token
        """
        raise NotImplementedError

    def place_orders_util(order_lines, brand_name,brand_mappings):
        """
        Place Orders for wix
        """
        raise NotImplementedError
