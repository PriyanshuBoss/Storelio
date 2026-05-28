import logging
from saleor.store.models import StoreInfo
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.mongo_utilities import MongoConn
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.external_services.google_analytics.constants import GA_COLLECTTION_NAME
from saleor.product.models import Product, StoreProductViews

logger = logging.getLogger(__name__)

def set_time_date_ga(start_date,end_date):
    date_format = "%Y-%m-%d"
    start_date_ga = TimeUtilities.parse_date(start_date.date(),date_format)
    end_date_ga = TimeUtilities.parse_date(end_date.date(),date_format)
    return {"start_date":start_date_ga,"end_date":end_date_ga}

def fetch_dashboard_store_metrics(start_date, end_date, datewise=False):
    date_range = set_time_date_ga(start_date, end_date)
    groupby = 'null'
    if datewise:
        groupby = "$date"
    pipeline = [
        {
            "$match": {
                    "date": { 
                    "$gte": date_range.get("start_date"),
                    "$lt": date_range.get("end_date")
                }
            }
        },
        {
            "$group": {
                "_id": groupby,
                "collection_visits_total": {
                    "$sum": "$col_visits"
                },
                "store_visits_total": {
                    "$sum": "$store_visits"
                },
                "site_visits_total": {
                    "$sum": "$site_visits"
                },
                "product_visits_total": {
                    "$sum": "$product_visits"
                }
            }
        },
        {
            "$project": {
                "_id": 1,
                "site_visits_total": 1,
                "store_visits_total": 1,
                "product_visits_total": 1,
                "collection_visits_total": 1
            }
        }
    ]

    docs = MongoConn().aggregate(pipeline, GA_COLLECTTION_NAME)
    res = dict()
    for doc in docs:
        res[doc['_id']] = doc
        
    return res

def get_product_views(date_range: dict = None, group_by: str = 'product_store'):
    """
    date_range = {'start_date': '2022-01-01', 'end_date': '2022-02-01'}
    group_by = 'product_store' or 'product'
    """
    pipeline = []
    if date_range:
        pipeline += [ 
            {
                "$match": {
                        "date": { 
                        "$gte": date_range.get("start_date"),
                        "$lt": date_range.get("end_date")
                    }
                }
            }
        ]
    pipeline += [
        {
            "$project": {
                "_id": 0,
                "products": {
                    "$concatArrays": [
                        {"$ifNull": [{"$objectToArray": "$products"}, []]},
                        {"$ifNull": [{"$objectToArray": "$app_products"}, []]}
                    ]
                } 
            }
        },
        {
            "$unwind": "$products"
        },
        {
            "$project": {
                "pid": "$products.k",
                "stores": { "$objectToArray": "$products.v" }
            }
        },
        {
            "$unwind": "$stores"
        }
    ]
    if group_by == 'product_store':
        pipeline += [
            {
                "$group": {
                    "_id": {
                        "product_id": "$pid",
                        "store_id": "$stores.k"
                    },
                    "views": {
                        "$sum": "$stores.v"
                    }
                }
            }
        ]
    elif group_by == 'product':
        pipeline += [
            {
                "$group": {
                    "_id": "$pid",
                    "views": {
                        "$sum": "$stores.v"
                    }
                }
            }
        ]
    elif group_by == 'store':
        pipeline += [
            {
                "$group": {
                    "_id": "$stores.k",
                    "views": {
                        "$sum": "$stores.v"
                    }
                }
            }
        ]

    product_views = MongoConn().aggregate(pipeline, GA_COLLECTTION_NAME)

    return product_views


def update_product_views(product_views):
    store_ids = set(view['store_id'] for view in product_views)
    product_ids = set(view['product_id'] for view in product_views)
    
    stores = set(StoreInfo.objects.filter(pk__in=store_ids).values_list('pk', flat=True))
    products = set(Product.objects.filter(pk__in=product_ids).values_list('pk', flat=True))
    
    for views in product_views:
        if views['product_id'] in products and views['store_id'] in stores:
            try:
                product, created = StoreProductViews.objects.get_or_create(product_id=views['product_id'], store_id=views['store_id'])
                product.views += views['views']
                product.save()
            except Exception as e:
                logger.error(f'update_product_views: {e}')

def add_pdp_views(data):
    product_views = []
    for type in ['products', 'app_products']:
        for pid, stores in data.get(type).items():
            product_id = NumberUtilities.convert_string_to_number(pid)
            for store_id, views in stores.items():
                product_views.append({
                    "product_id": product_id,
                    "store_id": NumberUtilities.convert_string_to_number(store_id),
                    "views": views 
                })
    update_product_views(product_views)

def get_store_visits(store_ids, gte_date, lt_date):
    pipeline = [
        {
            "$match": {
                    "date": { 
                    "$gte": gte_date,
                    "$lt": lt_date
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "stores": { "$objectToArray": "$stores" }
            }
        },
        { "$project":{
                "store_ids": {
                    "$filter": {
                        "input": "$stores",
                        "as": "store",
                        "cond": {"$in":["$$store.k", store_ids]}
                    }
                }
            }
        },
        {
            "$unwind": "$store_ids"
        },
        {
            "$group": {
                "_id": "$store_ids.k",
                "visits": {
                    "$sum": "$store_ids.v.store_visits"
                }
            }
        }
    ]

    store_visits = MongoConn().aggregate(pipeline, GA_COLLECTTION_NAME)

    return store_visits

def get_top_products_by_views(date_range, product_ids: list=None, limit=1000):
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": date_range.get('start_date'),
                    "$lt": date_range.get('end_date')
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "products": {
                    "$concatArrays": [
                        {"$ifNull": [{"$objectToArray": "$products"}, []]},
                        {"$ifNull": [{"$objectToArray": "$app_products"}, []]}
                    ]
                }
            }
        },
        {
            "$unwind": "$products"
        },
        {
            "$project": {
                "pid": "$products.k",
                "stores": { "$objectToArray": "$products.v" }
            }
        }
    ]
    if product_ids:
        pipeline += [
            {
                "$match": {
                    "pid": {
                        "$in": product_ids
                    }
                }
            }
        ]
    pipeline += [
        {
            "$unwind": "$stores"
        },
        {
            "$group": {
                "_id": "$pid",
                "views": {
                    "$sum": "$stores.v"
                }
            }
        },
        {
            "$sort": {"views": -1, "_id": -1}
        }
    ]
    if limit:
        pipeline += [
            {
                "$limit": limit
            }
        ]

    product_cursor = MongoConn().aggregate(pipeline, GA_COLLECTTION_NAME)
    product_views = dict()
    for product in product_cursor:
        product_views[product['_id']] = product['views']
    
    return product_views    

def fetch_store_landing_zaamo(start_date, end_date, datewise=False):
    date_range = set_time_date_ga(start_date, end_date)
    groupby = 'null'
    if datewise:
        groupby = "$date"

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": date_range.get("start_date"),
                    "$lt": date_range.get("end_date")
                }
            }
        },
        {
            "$group": {
                "_id": groupby,
                "store_landing_zaamo": {
                    "$sum": "$store_landing_zaamo"
                }
            }
        }
    ]

    docs = MongoConn().aggregate(pipeline, GA_COLLECTTION_NAME)
    res = dict()
    for doc in docs:
        res[doc['_id']] = doc
        
    return res

def get_visited_store_ids(gte_date, lt_date):
    pipeline = [
        {
            "$match": {
                    "date": { 
                    "$gte": gte_date,
                    "$lt": lt_date
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "stores": { "$objectToArray": "$stores" }
            }
        },
        {
            "$unwind": "$stores"
        },
        { 
            "$group": {
                "_id": "$stores.k"
            }
        },
    ]

    store_ids = [NumberUtilities.convert_string_to_number(doc['_id']) for doc in MongoConn().aggregate(pipeline, GA_COLLECTTION_NAME)]

    return store_ids