import abc


class MailManager(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'send_mail') and
                callable(subclass.generate_otp) or
                NotImplemented)

    @staticmethod
    def send_mail(mail_to, username, subject, message) -> int:
        """
        sending mail
        """
        raise NotImplementedError
