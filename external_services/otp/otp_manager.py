import abc


class OtpManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'generate_otp') and
                callable(subclass.generate_otp) and
                hasattr(subclass, 'verify_otp') and
                callable(subclass.verify_otp) or
                NotImplemented)

    @staticmethod
    def generate_otp(mobile_no) -> dict:
        """
        generates a new otp 
        """
        raise NotImplementedError

    @staticmethod
    def verify_otp(mobile_no, otp) -> dict:
        """
        verify an otp
        """
        raise NotImplementedError
