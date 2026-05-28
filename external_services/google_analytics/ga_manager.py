import abc


class GoogleAnalyticsManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'get_metrics_for_store') and
                callable(subclass.get_metrics_for_store) or
                hasattr(subclass, 'get_metrics_for_products') and
                callable(subclass.get_metrics_for_products) or
                hasattr(subclass, 'get_metrics_for_collections') and
                callable(subclass.get_metrics_for_collections) or
                NotImplemented)

    @classmethod
    def get_metrics_for_products() -> dict:
        """
        get Products Report Data
        """
        raise NotImplementedError
    @classmethod
    def get_metrics_for_store() -> dict:
        """
        get Store Report Data
        """
        raise NotImplementedError
    @classmethod
    def get_metrics_for_collections() -> dict:
        """
        get Collections Report Data
        """
        raise NotImplementedError
    
