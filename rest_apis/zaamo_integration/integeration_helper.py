from collections import defaultdict
import time
from saleor.utilities.number_utilities import NumberUtilities


class IntegerationHelper():
    @staticmethod
    def gen_chunks(reader, chunksize=100):
        chunk = []
        for i, line in enumerate(reader):
            if (i % chunksize == 0 and i > 0):
                yield chunk
                del chunk[:]
            chunk.append(line)
        yield chunk

    @staticmethod
    def structure_stylestry_response(obj):
        items=[]
        
        product_map = defaultdict(list)
        for p_map in obj:
            product_map[p_map.product_id_brand].append(p_map)

        for prod,mappings in product_map.items():
            t = time.time()

            if not mappings:
                continue

            variants_resp = []

            for mapping in mappings:

                try:
                    image_url = mapping.product_zaamo.images.first().image.url

                except:
                    image_url = ''

                try:
                    in_stock = mapping.variant_zaamo.stocks.first().quantity
                except:
                    in_stock = 0

                variant_resp={
                        "variant_id": NumberUtilities.convert_string_to_number(mapping.variant_id_brand),
                        "sku_code": mapping.sku_id_brand,
                        "title": mapping.product_name,
                        "in_stock": in_stock,
                        "selling_price": mapping.variant_zaamo.price_amount,
                        "retail_price": mapping.variant_zaamo.cost_price_amount,
                        "image_url": image_url,
                        "site_url": "",
                        "size": mapping.variant_zaamo.name
                        }

                variants_resp.append(variant_resp)

            structure = {
                    "product_id": NumberUtilities.convert_string_to_number(prod),
                    "category": mappings[0].product_zaamo.category.name,
                    "variants": variants_resp
                    }
            items.append(structure)
            
        return items
