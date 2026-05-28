from collections import defaultdict
from saleor.brand.models import Brand, BrandTagMapping
from saleor.external_services.integrations import BrandTagCreate
from saleor.graphql.product.enums import StockAvailability
from saleor.graphql.product.filters import filter_products_by_stock_availability
from saleor.product.models import ProductTag, ProductTagMapping, Product,BrandVariantZaamoMapping as bz, StoreProductViews
import re
from saleor.utilities.mongo_utilities import MongoConn
from django.db.models import Q
from django.contrib.postgres.search import SearchVector
import ujson as json

def match_regex(string_lst,x):

    if not x or not string_lst:
        return False
    
    regex = re.compile("(?=(" + "|".join(map(re.escape, string_lst)) + "))")
    matched = re.findall(regex, f" {x.lower()} ")

    
    if matched:
        return True
    
    return False


def parse_phrase_for_search(phrase):
    query = re.sub(r'[!\'()|&\s+]', ' {#} ', phrase.strip()).strip()

    if query and '#' in query:
        query = query.replace('{#}','<2>') + " | " + query.replace('{#}','<1>') + " | " + query.replace('{#}','<->')

    return query

def create_product_name_matching_dict(phrase,qs):
    query = parse_phrase_for_search(phrase)
    
    qs = qs.extra(
            where=[
                '''
                to_tsvector('english',
                    product_product.name                   
                ) @@ to_tsquery('english', %s)
                '''
            ],
            params=[query],
        )
        
    return {q.id for q in qs}

def clean_description_text(description):
    
    if not description:
        return ''

    description=re.sub("\<.*?\>","",description)
    
    return description

def clean_string_list(string_lst):
    text = string_lst[0].strip()

    if not ' ' in text:
        return string_lst

    symbols = ['/','@','-','_','.','*']

    for s in symbols:
        c_text = text.replace(' ',s)
        string_lst.append(f" {c_text} ")
    
    return string_lst

def create_product_description_matching_dict(string_lst,products):
    string_lst = clean_string_list(string_lst)
    matched_product_ids = []

    for product in products:
        clean_description = clean_description_text(product.description_json.get('description_text'))
        
        if match_regex(string_lst,clean_description):
            matched_product_ids.append(product.id)
    
    return matched_product_ids

def create_product_name_exact_matching_dict(tag,products):
    string_lst = []
    sub_tags = tag.metadata.get('sub_tags',[])
    string_lst.append(f" {tag.name} ")
    
    for subtag in sub_tags:
        string_lst.append(f" {subtag} ")
    
    matched_product_ids = []

    for product in products:
        
        if match_regex(string_lst,product.name):
            matched_product_ids.append(product.id)
    
    return matched_product_ids

def create_brand_tag_exact_matching_dict(tag,products,brand_tag_d):
    string_lst = []
    sub_tags = tag.metadata.get('sub_tags',[])
    string_lst.append(f" {tag.name} ")
    
    for subtag in sub_tags:
        string_lst.append(f" {subtag} ")
    
    matched_product_ids = []

    for product in products:
        brand_tags = brand_tag_d[product.id]

        for brand_tag in brand_tags:

            if match_regex(string_lst,brand_tag):
                matched_product_ids.append(product.id)
    
    return list(set(matched_product_ids))

def create_product_brand_tag_matching_dict(phrase,qs):
    query = parse_phrase_for_search(phrase)
    
    qs = qs.extra(
            where=[
                '''
                to_tsvector('english',
                    brand_brandtag.name 
                ) @@ to_tsquery('english', %s)
                '''
            ],
            params=[query],
        )
        
    return {q.id for q in qs}

def create_tags():
    tags = ["Lavender", "Black", "Lilac", "Sky blue", "Green", "Brown", "Neon", "Pink", "Contrast", "Gold", "Blue", "Champagne", "Silver",
    "Red", "White", "Grey", "Beige", "Mint", "Satin", "Sheer", "Lace", "Cotton", "Velvet", "Knit", "Sequin", "Ikat", "Linen", 
    "Jute", "Fur", "Organza", "Mesh", "Chiffon", "Rib knit", "Suede", "Floral", "polka", "Zebra", "Stripe", "Leopard", 
    "Animal print", "Check", "tropical", "Chic", "Crop", "One Shoulder", "bell bottom", "Cut out", "Ruffle", "Bodycon", "Square Neck", 
    "Backless", "side cut", "Off shoulder", "Slip", "Corset", "Rouched", "Drawstring", "Split", "Knee length", "Tennis", "Corset", 
    "Plunging neck", "Patchwork", "Mini", "Cowl", "Sundress", "Sweetheart", "Skater", "A line", "Criss Cross", "Puff Sleeve", "Halter", 
    "Summer", "Gathered", "Midi", "Asymetrical", "Pleated", "Sleeveless", "U neck", "Boat neck", "Flared", "Oversized", "Full sleeves", 
    "V neck", "Front twist", "Blouse", "Paperbag", "Elasticated", "High waist", "Ripped", "Skinny", "Smocked", "Lace", "Kimono", 
    "Romper", "Dungaree", "Frill", "Layered", "Solid", "Belted", "Wide leg", "Embroidered", "Blazer", "Overlap", "Printed", "Puffer", 
    "Baguette", "Handbag", "Satchel", "Textured", "Sling", "Cloud", "Beaded", "Tote", "Structured", "Crossbody", "Quilted", "Pearl", 
    "Bucket", "Adjustable", "Band", "Bandana", "Bandeau ", "Heart", "Chain", "Chunky", "Bracelet", "Ring", "Shades", "Sunglasses", 
    "Hoops", "Gloves", "Stocking", "Link", "y2k", "Statement", "Pendant", "Circular", "Evil eye", "Headband", "Butterfly", "jewellery", 
    "Necklace", "Long", "Pack", "Twisted", "Boho", "Rhinestone", "Flower", "Drop shoulder", "Summer", "Charm", "Basic", "Unisex", 
    "Sporty", "Leggings ", "Hoodie", "Racer", "Tee", "Regular", "Half sleeve", "Tie Dye", "Wrap", "Formal", "Polo", "Half ", 
    "Colour block", "Retro", "strap", "Tie-up", "tube", "Cardigan", "Camisole", "Tank", "Bustier", "Vest", "High neck", "Collar", 
    "Notch", "dual", "Mettalic", "Bishop", "Pullover", "Lapel", "Lettuce", "Button", "Lantern", "Slim ", "Relaxed", "Crochet", 
    "Set", "Ribbed", "Long sleeve",'jacket','skirt','casual','heel','flat','shoe','boot','anime','cargo''abstract', 'acid', 'acrylic', 
    'aesthetic', 'alloy', 'american', 'angel', 'ankle', 'anti', 'apple', 'apricot', 'aqua', 'astrid', 'asymmetric', 'asymmetrical', 
    'baby', 'baggy', 'bags', 'bagsy', 'balloon', 'beach', 'bermuda', 'berry', 'better', 'blend', 'bloom', 'blossom', 'blush', 
    'bodyfit', 'bodysuit', 'bohemian', 'bomber', 'boning', 'border', 'bottle', 'bow', 'boxy', 'braided', 'bralette', 'brass', 
    'bright', 'brush', 'bubble', 'buckle', 'bumper', 'burger', 'burgundy', 'camel', 'camera', 'candy', 'canvas', 'cap', 'case', 
    'chanderi', 'charcoal', 'cherry', 'chimpaaanzee', 'chocolate', 'choker', 'classic', 'clutch', 'coat', 'cocktail', 'coffee', 
    'coin', 'colourblocked', 'combo', 'comfort', 'conditioner', 'coral', 'corduroy', 'couple', 'cream', 'creative', 'crepe', 
    'crew', 'croco', 'crystal', 'cuff', 'cultific', 'curve', 'cute', 'cutout', 'daisy', 'darzi', 'debelle', 'deebaco', 'deep',
    'denim', 'designer', 'detail', 'diamond', 'disrupt', 'distressed', 'draped', 'dream', 'dreamy', 'dupatta', 'dusty', 
    'dyed', 'ecru', 'electroplated', 'elegant', 'embellished', 'embroidery', 'emerald', 'empire', 'enamel', 'essential', 'european', 
    'evening', 'eyeshadow', 'fabric', 'face', 'fade', 'fame', 'fancy', 'fargo', 'fashion', 'faux', 'fighting', 'fitted', 'flap', 
    'fleece', 'flipflops', 'forest', 'french', 'gel', 'geometric', 'georgette', 'girl', 'glitter', 'gloss', 'glow', 'gnist', 'gown', 
    'grace', 'gradient', 'graphic', 'gray', 'hair', 'hat', 'hem', 'hooded', 'hues', 'hydes', 'indigo', 'ivory', 'jacquard', 'jeans', 
    'jersey', 'jewelry', 'jogger', 'joggers', 'jumpsuit', 'kaftan', 'khaki', 'kit', 'kleio', 'knot', 'knotted', 'korea', 'korean', 
    'kurta', 'kurti', 'lacquer', 'lafille', 'latest', 'leaf', 'leather', 'lehenga', 'lemon', 'lime', 'lipstick', 'liquid', 'loafers', 
    'loose', 'lycra', 'make', 'makeup', 'malone', 'manaca', 'marble', 'maroon', 'mask', 'matte', 'mauve', 'maxi', 'medium', 'melange', 
    'metal', 'metallic', 'midnight', 'modern', 'moisturizing', 'moon', 'moraze', 'mules', 'multicolor', 'muslin', 'mustard', 'myth', 
    'nail', 'natural', 'navy', 'neckline', 'neyah', 'night', 'nude', 'oil', 'olive', 'ombre', 'orange', 'outfits', 'overshirt', 
    'paint', 'paisley', 'palazzo', 'pale', 'palette', 'party', 'pastel', 'pattern', 'peach', 'pencil', 'peplum', 
    'personality', 'piece', 'plaid', 'plain', 'plated', 'platform', 'play', 'plum', 'plunge', 'pocket', 'pockets', 'polish', 'poly', 
    'polyester', 'poplin', 'positioning', 'potli', 'pouch', 'powder', 'power', 'premium', 'pretty', 'protection', 'pumps', 'pure', 
    'purple', 'quartz', 'quotient', 'rainbow', 'rayon', 'reflective', 'relove', 'remanika', 'retail', 'revolution', 'rigo', 'rise', 
    'rose', 'royal', 'ruched', 'rust', 'sage', 'sandal', 'sandals', 'scarlet', 'schiffli', 'scoop', 'scorpius', 'scrub', 'sea', 
    'serum', 'sexy', 'shampoo', 'shape', 'sheath', 'sheczzar', 'shibori', 'shimmer', 'shorts', 'shrug', 'silicone', 'silk', 
    'simple', 'sliders', 'slit', 'smart', 'snake', 'sneakers', 'soap', 'socks', 'space', 'spaghetti', 'spice', 'sports', 'star', 
    'stilettos', 'straight', 'street', 'streetwear', 'stretch', 'stretchable', 'studded', 'studs', 'stylestry', 'stylish', 'suit', 
    'super', 'sweater', 'sweatshirt', 'synthetic', 'tassel', 'tea', 'teal', 'teddy', 'temperament', 'terry', 
    'threadcurry', 'together', 'track', 'transparent', 'travel', 'tree', 'trendy', 'trendyol', 'trendyolmi̇lla', 'trim', 
    'trouser', 'trousers', 'turquoise', 'turtle', 'valkyre', 'vegan', 'vintage', 'viscose', 'vitamin', 'vivinkaa', 'watch', 'water', 
    'wild', 'wine', 'world', 'yellow', 'zheia', 'zipper', 'zodiac']

    for tag in tags:
        ProductTag.objects.update_or_create(name=tag.lower().strip())

def create_product_tag_mapping(tag,product_ids,weight,source):

    if not product_ids:
        return
    products = Product.objects.filter(id__in=product_ids)
    
    tag.product.add(*product_ids)
    brand_product_dict = defaultdict(list)
    for product in products:
        brand_product_dict[product.brand_id].append(product.id)

    for b_id,p_list in brand_product_dict.items():
        ProductTagMapping.objects.filter(product_tag=tag,product_id__in=p_list).update(weight=weight,source=source,brand_id=b_id)

def update_brand_id_in_products():
    product_without_brand = ProductTagMapping.objects.filter(brand_id__isnull=True).select_related('product')
    mapping_to_update = []

    for mapping in product_without_brand:
        mapping.brand = mapping.product.brand
        mapping_to_update.append(mapping)
    
    ProductTagMapping.objects.bulk_update(mapping_to_update,['brand'],batch_size=1000)

def get_query_for_percentile():
    query = """
            SELECT distinct(ab."product_id"),ab.id, aa.pviews, 1 - (PERCENT_RANK() OVER (ORDER BY aa.pviews DESC)) AS "percentile"
            FROM "product_storeproductviews" as ab
            inner join (select product_id, sum(views) as pviews from product_storeproductviews group by product_id) as aa
            on ab.product_id=aa.product_id order by percentile desc
            """
    
    return query

def get_remove_words():
    removal_list = set(["a", "about", "above", "after", "again", "against", "all", "am", "an", 
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below", 
    "between", "both", "but", "by", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", 
    "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further",
    "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", 
    "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", 
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", 
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", 
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", 
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", 
    "that's", "the", "their", "theirs", "them", "themselves", "then", "there", "there's", "these", 
    "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too", 
    "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", 
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", 
    "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", 
    "you've", "your", "yours", "yourself", "yourselves"])

    return removal_list

def run():

    create_tags()
    
    color_tags = ["Lavender", "Black", "Lilac", "Sky blue", "Green", "Brown", "Neon", "Pink", "Contrast", "Gold", "Blue", "Champagne", 
    "Red", "White", "Grey", "Beige", "Mint","Silver","aqua","maroon","mustard","navy","olive","orange","pastel","peach","purple",
    "rainbow","rose","teal","wine","yellow"]
    brand_tag_create = BrandTagCreate()
    brand_tag_create.fetch_brand_source_tag_product_id()
    
    percentile_dict = defaultdict(float)

    query = get_query_for_percentile()
    stock_views = StoreProductViews.objects.raw(query)

    for row in stock_views:
        percentile_dict[row.product_id]=row.percentile*0.2
        
    tags = ProductTag.objects.all()

    tags_product_name_dict = defaultdict(list)
    tags_brand_tag_dict = defaultdict(list)
    tags_product_description_dict = defaultdict(list)
    products = Product.objects.filter(is_published=True, minimal_variant_price_amount__isnull=False)
    products = filter_products_by_stock_availability(products,StockAvailability.IN_STOCK)
    
    product_ids = products.values_list("id",flat=True)

    search_vector_name = SearchVector('name')
    search_vector_tag = SearchVector('brandtag__name')
    qs_name =  products.annotate(vector = search_vector_name)
    qs_tag =  products.annotate(vector = search_vector_tag)
    constant_multiplier = 1

    removal_list  = get_remove_words()
    brand_tag = BrandTagMapping.objects.all().select_related('product','brand_tag')
    brand_tag_d = defaultdict(list)

    for i in brand_tag:
        brand_tag_d[i.product.id].append(i.brand_tag.name)

    for tag in tags:
        
        ProductTagMapping.objects.filter(product_tag_id=tag.id).delete()
        print(tag.name)

        score = defaultdict(int)
        product_matched_source_d = defaultdict(list)
        
        if set(tag.name.split(" ")).intersection(removal_list)  or tag.private_metadata.get('ignore_case'):
            print(f"removal tag name :: {tag.name}")
            product_name_matched = create_product_name_exact_matching_dict(tag,products)
            tags_product_name_dict[tag.id] = product_name_matched
            
            product_brand_tag_matched = create_brand_tag_exact_matching_dict(tag,products,brand_tag_d)
            tags_brand_tag_dict[tag.id] = product_brand_tag_matched

        else:    
            product_name_matched = create_product_name_matching_dict(tag.name,qs_name)
            tags_product_name_dict[tag.id] = product_name_matched
            
            product_brand_tag_matched = create_product_brand_tag_matching_dict(tag.name,qs_tag)
            tags_brand_tag_dict[tag.id] = product_brand_tag_matched
        
        product_description_matched = create_product_description_matching_dict([f" {tag.name} "],products)
        tags_product_description_dict[tag.id] = product_description_matched

        if tag.name in color_tags:
            constant_multiplier = 1.5
        else:
            constant_multiplier = 1
            
        for i in product_description_matched:
            score[i]+=0.1 * constant_multiplier
            product_matched_source_d[i].append('Description')

        for i in product_brand_tag_matched:
            score[i]+=0.2 * constant_multiplier
            product_matched_source_d[i].append('Brand_Tag')
            
        for i in product_name_matched:
            score[i]+=0.5 * constant_multiplier
            product_matched_source_d[i].append('Name')
        
        all_matched = []
        all_matched.extend(product_description_matched)
        all_matched.extend(product_brand_tag_matched)
        all_matched.extend(product_name_matched)
        all_matched = list(set(all_matched))

        score_id_dict = defaultdict(list)

        for i,v in score.items():
            score_id_dict[v].append(i)

        to_create = []

        for score,product_ids in score_id_dict.items():
            for product in product_ids:
                
                if not product:
                    continue

                p = ProductTagMapping()
                p.product_tag=tag
                p.product_id=product
                p.percentile=percentile_dict[product]
                p.weight = score
                p.source = ', '.join(product_matched_source_d[product])
                to_create.append(p)

        ProductTagMapping.objects.bulk_create(to_create)
        products_not_in_tag = tag.product.exclude(id__in=all_matched)
        tag.product.remove(*products_not_in_tag)
        update_brand_id_in_products()
        
# run()
