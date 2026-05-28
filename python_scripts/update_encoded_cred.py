from saleor.brand.models import BrandCred
from saleor.external_services import get_fernet_encoder
import logging
logger = logging.getLogger(__name__)



def run():
    brand_creds = BrandCred.objects.all()
    f_encoder = get_fernet_encoder()

    if not f_encoder:
        logger.exception("Generate Key for cryptography Fernet")
        return
    
    for cred in brand_creds:
        if cred.access_key:
            
            cred.access_key = f_encoder.encrypt(cred.access_key.encode()).decode('utf-8')

        if cred.access_pass:   
            
            cred.access_pass = f_encoder.encrypt(cred.access_pass.encode()).decode('utf-8')
        
        if cred.auth_token:
            
            cred.auth_token = f_encoder.encrypt(cred.auth_token.encode()).decode('utf-8')

        cred.save()
