from saleor.utilities.mongo_utilities import MongoClient, MongoConn
import json
import gridfs

def run(source_url,target_url):
    source = MongoClient(source_url)
    source_db = source['saleor']
    target = MongoClient(target_url)
    target_db = target['saleor']

    collections = source_db.list_collection_names()

    for c in collections:
        try:
            if not 'collection' in c:
                continue
            c = c.replace('collection.','')
            data = source_db.collection[c].find({})
            for i in data:
                try:
                    target_db.collection[c].insert_one(i)
                except Exception as e:
                    print(e,i.keys())
        except Exception as e:
            print(e,c)
    gridfs_dump(source_url,target_url)
            

def gridfs_dump(source_url,target_url):
    source = MongoClient(source_url)
    source_db = source['saleor']
    source_gridfs = gridfs.GridFS(source_db)
    target = MongoClient(target_url)
    target_db = target['saleor']
    target_gridfs = gridfs.GridFS(target_db)
    data = source_gridfs.find({})
    for i in data:
        
        filename = i.filename
        try:
            post = json.loads(i.read())

            post_data = json.dumps(post)
            target_gridfs.put(post_data, filename=filename , encoding='utf-8')
        except Exception as e:
            print(e,filename)

def ga_analytics_coll():
    conn = MongoConn()
    
    source_db = conn.get_mongo_client()

    data = source_db.collection['GA_Analytics'].find()
    for i in data:
        
        op = []
        try:
            col = i.get('collections')
            print(len(col))
            if not col:
                continue
            date = i.get('date')
            print(date)
            
            op = []
            for id,key in col.items():
                data_r= {'date':date,'collection_id':id,'collection_visit':key.get('collection_visits')}
                op.append(MongoConn.update_one_operation(
                filter={'date':date,'collection_id':id},
                update={"$set": data_r}, 
                upsert=True
                ))
                # source_db.collection['GA_Analytics_collection'].insert_one(data_r)
                data_r = dict()
        except Exception as e:
            print(e)
        
        conn.bulk_update_data(operations=op,collection_name = 'GA_Analytics_collection')
            

def ga_analytics_stor():
    conn = MongoConn()
    
    source_db = conn.get_mongo_client()

    data = source_db.collection['GA_Analytics'].find()
    for i in data:
        
        op = []
        try:
            col = i.get('stores')
            if not col:
                continue
            date = i.get('date')
            print(date)
            print(f"len of store:: {len(col)}")
            
            op = []
            for id,key in col.items():
                data_r= {'date':date,'store_id':id}
                data_r.update(key)
                op.append(MongoConn.update_one_operation(
                filter={'date':date,'store_id':id},
                update={"$set": data_r}, 
                upsert=True
                ))
                
                data_r = dict()
        except Exception as e:
            print(e)
        
        conn.bulk_update_data(operations=op,collection_name = 'GA_Analytics_stores')
