
from ..celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl


@app.task
def send_cashfree_client_capture_email(data):
    mail_type = "cashfree_capture"
    subject = data.pop('subject')
    mail_text = data.get('body')
    recipient_list = ['vaibhav+test@zaamo.co']

    for recipient in recipient_list:
        MailImpl.send_mail_without_template(mail_type,mail_text,subject,recipient)


@app.task
def send_razorpay_client_capture_email(data):
    mail_type = "razorpay_capture"
    subject = data.pop('subject')
    mail_text = data.get('body')
    recipient_list = ['vaibhav+test@zaamo.co']

    for recipient in recipient_list:
        MailImpl.send_mail_without_template(mail_type,mail_text,subject,recipient)
