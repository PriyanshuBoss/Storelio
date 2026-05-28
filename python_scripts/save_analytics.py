from saleor.external_services.google_analytics.tasks import *
from saleor.external_services.google_analytics.ga_helper import set_time_date_ga
import datetime

def run(start_date=None, end_date=None):
    if not end_date:
        end_date = datetime.datetime.today()
    if not start_date:
        start_date = end_date - datetime.timedelta(days=10)
    print(set_time_date_ga(start_date, end_date))
    try:
        print('running...')
        save_dashboard_metrics_to_mongo(start_date, end_date)
        save_product_metrics_to_mongo(start_date, end_date)
        save_collection_metrics_to_mongo(start_date, end_date)
        save_landing_metrics_to_mongo(start_date, end_date)
    except Exception as e:
        print(str(e))
    print('done')

if __name__=='__main__':
    run()