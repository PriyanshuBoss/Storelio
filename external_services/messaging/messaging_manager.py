import abc


class MessagingManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'send_message_for_account_activation') and
                callable(subclass.send_message_for_account_activation) or
                NotImplemented)

    @staticmethod
    def send_message_for_account_activation(mobile_no) -> dict:
        """
        sends message for account activation
        """
        raise NotImplementedError
