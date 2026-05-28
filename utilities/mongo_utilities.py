import time
from pymongo import MongoClient, UpdateOne
from saleor.settings import MONGO_CLIENT
import gridfs
class MongoConn:

    client = None
    db = None

    def get_mongo_client(self):
        
        if self.client is None:
            self.client = MongoClient(MONGO_CLIENT.get('url'))
            self.db = self.client[MONGO_CLIENT.get('db')]
        
        return self.db
    
    def insert_data(self, post, collection_name):
        try:
            db = self.get_mongo_client()
            db.collection[collection_name].insert_one(post)
        
        except Exception as e:
            print(str(e))

    def fetch_data(self, get, collection_name, timeout_off = False):
        db = self.get_mongo_client()
        
        if not timeout_off:
            results = db.collection[collection_name].find(get)
        
        else:
            results = db.collection[collection_name].find(get,no_cursor_timeout=True)
        
        return results
    
    def fetch_one(self, filter, collection_name, **kwargs):
        db = self.get_mongo_client()
        result = db.collection[collection_name].find_one(filter, **kwargs)

        return result
        
    def update_data(self, filter_query, update_query, collection_name, upsert=False):
        db = self.get_mongo_client()
        results = db.collection[collection_name].update_one(filter_query, update_query, upsert=upsert)
        
        return results
    
    def bulk_update_data(self, operations, collection_name):
        db = self.get_mongo_client()
        results = None
        if operations:
            results = db.collection[collection_name].bulk_write(operations)

        return results

    def delete_data(self, filter_query, collection_name):
        db = self.get_mongo_client()
        results = db.collection[collection_name].delete_one(filter_query)
        
        return results

    @staticmethod
    def update_one_operation(filter, update, upsert=False, **kwargs):
        operation = UpdateOne(filter, update, upsert=upsert, **kwargs)

        return operation

    def get_grid_fs_conn(self):
        db = self.get_mongo_client()

        return gridfs.GridFS(db)
    
    def fetch_one_gridfs(self, filter,retry=0,**kwargs):

        if retry>2:
            return None

        try:
            fs = self.get_grid_fs_conn()
            result = fs.find_one(filter, **kwargs)

            return result
            
        except:
            self.client = None
            retry+=1
            return self.fetch_one_gridfs(filter,retry,**kwargs)
    
    def insert_one_gridfs(self, data, filename, **kwargs):
        fs = self.get_grid_fs_conn()
        result = fs.put(data, filename=filename ,**kwargs)
        
        return result
        
    def delete_gridfs(self, name):
        fs = self.get_grid_fs_conn()
        files = fs.find({'filename':name})
        for file in files:
            fs.delete(file._id)

    def aggregate(self, pipeline, collection_name, **kwargs):
        db = self.get_mongo_client()
        results = db.collection[collection_name].aggregate(pipeline, **kwargs)
        return results

    def sum_collection_views(self, collection_ids, collection_name):
        db = self.get_mongo_client()
        results = db.collection[collection_name].aggregate([
            
            {
        '$match': {
            'collection_id': {'$in': collection_ids}
        }
    },
            {
                "$group": {
                    "_id": "$collection_id", 
                    "collection_views": {"$sum": "$collection_visit"}
                }
            }
        ])

        return results

    
    def sum_store_metrics(self, date_range, collection_name):
        db = self.get_mongo_client()
        results = db.collection[collection_name].aggregate([{
            '$match':{
                "date": { 
                "$gte":date_range.get("start_date"),
                "$lte": date_range.get("end_date")
            }
            }
            },
            {
                "$group": {
                    "_id": "$store_id", 
                    "col_visits_total": {"$sum": "$col_visits_total"},
                    "pdp_visit_total": {"$sum": "$pdp_visit_total"},
                    "store_visits": {"$sum": "$store_visits"},
                    "brand_click_total": {"$sum": "$brand_click_total"},
                    "cat_click_total": {"$sum": "$cat_click_total"},
                    "return_policy": {"$sum": "$return_policy"},
                    "checkout_success": {"$sum": "$checkout_success"},
                    "checkout_fail": {"$sum": "$checkout_fail"},
                    "my_orders": {"$sum": "$my_orders"},
                    "total_category_clicks": {"$sum": "$total_category_clicks"}
                }
            }
        ])

        return results
