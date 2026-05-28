SERVICE_NAME = 'content'
SERVICE_VERSION = 'v2.1'
CONTENT_API_SCOPE = ['https://www.googleapis.com/auth/' + SERVICE_NAME]
CHANNEL = 'online'
CONTENT_LANGUAGE = 'en'
TARGET_COUNTRY = 'IN'

class Availability:
    IN_STOCK = 'in_stock'
    OUT_OF_STOCK = 'out_of_stock'
    PREORDER = 'preorder'
    BACKORDER = 'backorder'

class Condition:
    NEW = 'new'
    REFURBISHED = 'refurbished'
    USED = 'used'

EXCLUDED_DESTINATIONS = [
    "Shopping_ads", "Buy_on_Google_listings", "Display_ads", "Local_inventory_ads", "Free_listings", "Free_local_listings"
]

# google_product_categories
GPC = {
    "acha_india_uncategorized": "",
    "Dresses & Co-ords": "Apparel & Accessories > Clothing > Dresses",
    "swix_uncategorized": "",
    "wix_uncategorized": "",
    "custom_brand_uncategorized": "",
    "Hats": "Apparel & Accessories > Clothing Accessories > Hats",
    "T-shirt": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Shirt": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Skirt": "Apparel & Accessories > Clothing > Skirts",
    "Westernwear": "",
    "Heels": "Apparel & Accessories > Shoes",
    "Flats": "Apparel & Accessories > Shoes",
    "Floral": "",
    "Trousers & Pants": "Apparel & Accessories > Clothing > Pants",
    "Joggers": "Apparel & Accessories > Clothing > Pants",
    "Short": "Apparel & Accessories > Clothing > Shorts",
    "Apparel": "",
    "Shorts": "Apparel & Accessories > Clothing > Shorts",
    "Menswear": "",
    "Sweatshirt": "Apparel & Accessories > Clothing > Outerwear",
    "Bottomwear": "",
    "Bodysuit": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Footwear": "Apparel & Accessories > Shoes",
    "Foot-wear": "Apparel & Accessories > Shoes",
    "Athleisure": "Apparel & Accessories > Clothing > Activewear",
    "Hot Picks": "",
    "T-shirts": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Bottom-wear": "",
    "Unisex": "clothing & accessories > clothing > unisex clothing",
    "Shoes": "Apparel & Accessories > Shoes",
    "Bags": "Apparel & Accessories > Handbags",
    "shopify_uncategorized": "",
    "woocommerce_uncategorized": "",
    "thrift_category": "",
    "Co-ord Sets": "Apparel & Accessories > Clothing > Outfit Sets",
    "Co-ord Set": "Apparel & Accessories > Clothing > Outfit Sets",
    "Beauty & Skincare": "Health & Beauty > Personal Care > Cosmetics > Skin Care",
    "Outerwear": "Apparel & Accessories > Clothing > Outerwear",
    "Shirts": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Topwear": "",
    "Loungewear": "Apparel & Accessories > Clothing > Sleepwear & Loungewear",
    "Tops": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Jeans & Jeggings": "Apparel & Accessories > Clothing > Pants",
    "Phone Cases": "Electronics > Communications > Telephony > Mobile Phone Accessories > Mobile Phone Cases",
    "Dresses": "Apparel & Accessories > Clothing > Dresses",
    "Jumpsuits": "Apparel & Accessories > Clothing > One-Pieces > Jumpsuits & Rompers",
    "Sunglasses": "Apparel & Accessories > Clothing Accessories > Sunglasses",
    "Jewelry": "Apparel & Accessories > Jewelry",
    "Accessories": "Apparel & Accessories > Jewelry",
    "Slip Ons": "Apparel & Accessories > Clothing Accessories",
    "Makeup": "Health & Beauty > Personal Care > Cosmetics > Makeup",
    "Skin": "Health & Beauty > Personal Care > Cosmetics > Skin Care",
    "Bath & Body": "Health & Beauty > Personal Care > Cosmetics > Bath & Body",
    "Hair": "Health & Beauty > Personal Care > Hair Care",
    "Sweatshirt & Hoodies": "Apparel & Accessories > Clothing > Outerwear",
    "Swimwear": "Apparel & Accessories > Clothing > Swimwear",
    "Ethnicwear": "",
    "Kurta": "",

}
