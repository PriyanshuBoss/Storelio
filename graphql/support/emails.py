from ...celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl

@app.task()
def send_mail_to_email_ids(mail_type, mail_text, subject, recipient_list):
    
    for recipient in recipient_list:
        response_code = MailImpl.send_mail_without_template(mail_type,mail_text,subject,recipient)

