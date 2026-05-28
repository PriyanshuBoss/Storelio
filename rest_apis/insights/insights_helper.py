from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.mongo_utilities import MongoConn
from .constants import INSIGHTS_COLLECTION_NAME


def page_load_time_current_data():
    today = TimeUtilities.get_current_date()
    mongo_client = MongoConn()
    current_data = mongo_client.fetch_one({"date": today}, INSIGHTS_COLLECTION_NAME)
    if not current_data:
        current_data = {}
    
    return current_data

def page_load_time_format_new_data(new_data):
    for page, metrics in new_data.items():
        for key, value in metrics.items():
            metrics[key] = {
                'min': value,
                'max': value,
                'avg': value,
                'count': 1
            }
    return new_data

def page_load_time_merge_current_data(new_data):
    current_data = page_load_time_current_data()
    for page, metrics in new_data.items():
        for key, metric in metrics.items():
            curr_metric = current_data.get(page, {}).get(key, {})
            if curr_metric:
                metric['min'] = min(metric['min'], curr_metric['min'])
                metric['max'] = max(metric['max'], curr_metric['max'])
                metric['avg'] = (curr_metric['avg'] * curr_metric['count'] + metric['avg']) / (curr_metric['count'] + 1)
                metric['count'] += curr_metric['count']
    return new_data

def page_load_time_save_new_data(new_data):
    today = TimeUtilities.get_current_date()
    try:
        mongo_client = MongoConn()
        mongo_client.update_data({"date": today}, {"$set": new_data}, INSIGHTS_COLLECTION_NAME, upsert=True)
        return True
    except Exception as e:
        return False

def page_load_time_get_data(start_date, end_date):
    query = {
        "date": { 
        "$gte": start_date,
        "$lte": end_date
        }
    }
    cursor = MongoConn().fetch_data(query, INSIGHTS_COLLECTION_NAME)
    data = [
        {
            **doc, 
            '_id': StringUtilities.convert_object_to_string(doc.get('_id'))
        } 
        for doc in cursor
    ]
    return data

