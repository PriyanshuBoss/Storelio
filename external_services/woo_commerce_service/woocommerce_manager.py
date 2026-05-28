import abc


class WooCommerceManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'insert_product_data_from_woo_commerce_store') and
                callable(subclass.insert_product_data_from_woo_commerce_store) and
                hasattr(subclass, 'fetch_product_data_from_woo_commerce_store') and
                callable(subclass.fetch_product_data_from_woo_commerce_store) and
                hasattr(subclass, 'insert_store_data_from_woocommerce_store') and
                callable(subclass.insert_store_data_from_woocommerce_store) and
                hasattr(subclass, 'fetch_store_by_url_from_woo_commerce_store') and
                callable(subclass.fetch_store_by_url_from_woo_commerce_store) and
                hasattr(subclass, 'add_new_product_to_store_from_webhook') and
                callable(subclass.add_new_product_to_store_from_webhook) and
                hasattr(subclass, 'update_product_to_store_from_webhook') and
                callable(subclass.update_product_to_store_from_webhook) and
                hasattr(subclass, 'delete_product_from_store') and
                callable(subclass.delete_product_from_store) and
                hasattr(subclass, 'create_brand_from_WooCommerce') and
                callable(subclass.create_brand_from_WooCommerce) and
                hasattr(subclass, 'create_product_from_WooCommerce') and
                callable(subclass.create_product_from_WooCommerce) and
                hasattr(subclass, 'place_orders_util') and
                callable(subclass.place_orders_util) 
                or
                NotImplemented)

    def insert_product_data_from_woo_commerce_store(shop):
        """
        insert products from woocommerce store to mongo
        """
        raise NotImplementedError

    def fetch_product_data_from_woo_commerce_store(store_url):
        """
        fetch product of woocommerce store from mongo
        """
        raise NotImplementedError

    def insert_store_data_from_woocommerce_store(woocommerce_cred_dict: dict):
        """
        create shop data from woocommerce store
        """
        raise NotImplementedError

    def fetch_store_by_url_from_woo_commerce_store():
        """
        fetch store data from woocommerce store
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

    def create_brand_from_WooCommerce(shop):
        """
        Create brand in DB from Woo Commerce store Collection
        """
        raise NotImplementedError

    def create_product_from_WooCommerce(shop):
        """
        Create Product in DB from Woo Commerce store Collection
        """
        raise NotImplementedError

    def place_orders_util(order_line_obj, brand_mapping):
        """
        Place orders from Woo Commerce API
        """
        raise NotImplementedError
    
    def delete_product_from_store(product_id):
        """
        Delete product
        """
        raise NotImplementedError
        