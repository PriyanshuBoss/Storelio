from saleor.celeryconf import app
from saleor.external_services.google_analytics.ga_impl import GoogleAnalyticsImpl
from saleor.external_services.google_analytics.ga_helper import get_visited_store_ids
from saleor.settings import IS_BETA
from saleor.utilities.time_utilities import TimeUtilities
from saleor.store.models import StoreInfo



@app.task
def save_dashboard_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_overall_dashboard_data_to_mongo(start_date, end_date)

@app.task
def save_realtime_dashboard_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_overall_dashboard_data_to_mongo(start_date, end_date)

@app.task
def save_product_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_product_data_to_mongo(start_date, end_date)

@app.task
def save_realtime_product_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_product_data_to_mongo(start_date, end_date)

@app.task
def save_collection_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_collection_data_to_mongo(start_date, end_date)

@app.task
def save_realtime_collection_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_collection_data_to_mongo(start_date, end_date)

@app.task
def save_landing_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_landing_data_to_mongo(start_date, end_date)

@app.task
def save_store_total_visitors():
    end_date = TimeUtilities.get_current_date_time().strftime('%Y-%m-%d')
    start_date = TimeUtilities.get_n_days_before_date(days=7).strftime('%Y-%m-%d')
    store_ids = get_visited_store_ids(start_date, end_date)
    total_visitors = dict()
    weekly_visitors = dict()
    for store_id in store_ids:
        overall_visitors = GoogleAnalyticsImpl.get_store_total_visitors(store_id)
        last_7_days_visitors = GoogleAnalyticsImpl.get_store_total_visitors(store_id, date_range={"start_date": start_date, "end_date": end_date})
        total_visitors[store_id] = overall_visitors
        weekly_visitors[store_id] = last_7_days_visitors

    stores = StoreInfo.objects.all().only('id', 'metadata')
    for store in stores:
        store.metadata.update({'weekly_visitors': weekly_visitors.get(store.id, 0)})
        if store.id in total_visitors:
            store.metadata.update({'total_visitors': total_visitors.get(store.id)})

    StoreInfo.objects.bulk_update(stores, fields=['metadata'], batch_size=1000)

@app.task
def save_realtime_landing_metrics_to_mongo(start_date, end_date):
    GoogleAnalyticsImpl.save_landing_data_to_mongo(start_date, end_date)


@app.task(queue='celery_periodic')
def save_past_google_analytics():
    
    if IS_BETA:
        return
    
    end_date = TimeUtilities().get_today_start()
    start_date = TimeUtilities.subtract_time_from_timestamp(end_date, days=2)

    save_dashboard_metrics_to_mongo(start_date, end_date)
    save_product_metrics_to_mongo(start_date, end_date)
    save_collection_metrics_to_mongo(start_date, end_date)
    save_landing_metrics_to_mongo(start_date, end_date)
    save_store_total_visitors()


@app.task(queue='celery_periodic')
def save_realtime_google_analytics():
    
    if IS_BETA:
        return
    
    start_date = TimeUtilities().get_today_start()
    end_date = TimeUtilities().get_today_end()

    save_realtime_dashboard_metrics_to_mongo(start_date, end_date)
    save_realtime_product_metrics_to_mongo(start_date, end_date)
    save_realtime_collection_metrics_to_mongo(start_date, end_date)
    save_realtime_landing_metrics_to_mongo(start_date, end_date)
    
