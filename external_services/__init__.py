
from saleor.settings import CRYPTOGRAPHY_KEY
from cryptography.fernet import Fernet
import logging
logger = logging.getLogger(__name__)
import math
from saleor.utilities.number_utilities import NumberUtilities

def get_fernet_encoder():
    try:
        f_encoder = Fernet(CRYPTOGRAPHY_KEY)
        return f_encoder

    except Exception as e:
        logger.exception(e)
        return None

def get_decoded_string(string):
    try:
        return get_fernet_encoder().decrypt(string.encode()).decode('utf-8')
    except:
        return ''


def gen_chunks(reader, chunksize=250):
        chunk = []
        for i, line in enumerate(reader):
            if (i % chunksize == 0 and i > 0):
                yield chunk
                del chunk[:]
            chunk.append(line)
        yield chunk

def update_order_metadata_with_extra_charge(order_lines,cod_total,is_cod=True):
    
    if is_cod:
        cod_price_cur = NumberUtilities.convert_string_to_decimal(order_lines[0].metadata.get('cod_price'))
        
    else:
        cod_price_cur = 0

        for line in order_lines:
            cod_price_cur += line.shipping_cost_amount

        cod_price_cur = NumberUtilities.convert_string_to_decimal(cod_price_cur)

    cod_total_ind = cod_total -  cod_price_cur
    cod_total_ind = math.ceil(NumberUtilities.convert_string_to_float(cod_total_ind))
    cod_distributed = cod_total_ind/len(order_lines)

    for line in order_lines:

        line.metadata['platform_fees'] = math.ceil(NumberUtilities.convert_string_to_float(line.metadata.get('platform_fees')) + cod_distributed)

        if is_cod:
            line.metadata['brand_due_amount'] = math.ceil(NumberUtilities.convert_string_to_float(line.metadata.get('brand_due_amount')) - cod_distributed)
        
        line.metadata['extra_shopify_charge'] = math.ceil(cod_distributed)

        line.save()
        