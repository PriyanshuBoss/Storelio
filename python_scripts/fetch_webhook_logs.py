from saleor.utilities.mongo_utilities import MongoConn

def run(name=''):
    m = MongoConn()
    fs = m.get_grid_fs_conn()
    data = fs.find({'filename':name})

    n = []
    for i in data:
        import json
        n.append(json.loads(i.read()))

    with open(f'{name}_gridfs.json','w') as t:
        json.dump(n,t,indent=4)
