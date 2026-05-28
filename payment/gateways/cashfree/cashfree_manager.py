import abc


class CashfreeManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'create_payment_link') and
                callable(subclass.create_payment_link) and
                hasattr(subclass, 'get_payments_for_order') and
                callable(subclass.get_payments_for_order) or
                NotImplemented)

    @staticmethod
    def create_payment_link(data) -> dict:
        """
        generates a new payment link 
        """
        raise NotImplementedError

    @staticmethod
    def get_payments_for_order(checkout_id) -> dict:
        """
        get payment status for an order ID
        """
        raise NotImplementedError

    ## To be implemented, returns, refunds, settlement, payouts etc.
