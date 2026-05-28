from google.oauth2 import service_account
from django.conf import settings
from saleor.external_services.google_analytics.constants import GA_COLLECTION_DETAIL_NAME,GA_STORE_DETAIL_NAME, GOOGLE_ANALYTICS_ID, CollectionEvents, ProductEvents, AppProductEvents, AppStoreEvents,StoreEvents,LandingEvents,HomeEvents, AppHomeEvents,GA_COLLECTTION_NAME
from .ga_helper import set_time_date_ga, add_pdp_views
from saleor.external_services.google_analytics.ga_manager import GoogleAnalyticsManager
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest, RunRealtimeReportRequest, Filter, FilterExpression
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.dictionary_utilities import DictionaryUtilities
from saleor.graphql.order.enums import TimePeriod
from saleor.utilities.mongo_utilities import MongoConn
import re


class GoogleAnalyticsImpl(GoogleAnalyticsManager):

    credentials = None

    @classmethod
    def get_credentials(cls):
        if cls.credentials is None:
            cls.credentials = service_account.Credentials.from_service_account_file(settings.GOOGLE_ANALYTICS_CREDENTIALS)
        return cls.credentials

    def _set_analytics_report_context(property_id,metric_d_list,date_range):
        return RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="eventName")],
        metrics=metric_d_list[0].get("metrics"),
        date_ranges=[DateRange(start_date=date_range.get("start_date"), end_date=date_range.get("end_date"))],
    )

    def _set_analytics_realtime_report_context(property_id,metric_d_list):
        return RunRealtimeReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="eventName")],
        metrics=metric_d_list[0].get("metrics")[:1],
    )

    @classmethod
    def run_report(cls, property_id, metrics, date_range):
        client =  BetaAnalyticsDataClient(credentials=cls.get_credentials())
        today = TimeUtilities().get_today_start()
        today_date = set_time_date_ga(today, today).get("start_date")
        if date_range.get("start_date") == today_date:
            request = cls._set_analytics_realtime_report_context(property_id, metrics)
            response = client.run_realtime_report(request)
        else:
            request = cls._set_analytics_report_context(property_id, metrics, date_range)
            response = client.run_report(request)
        return response
    
    @classmethod
    def get_metrics_for_home(cls, date_range={"start_date":"2022-01-01", "end_date":"today"}):
        '''
        sample response dict
        {
            "page_view": 0,
            "user_engagement": 0,
            "homes": {
                "{home_id}": {
                    "earn": 0,
                    "coupons": 0,
                    "brand_click":{
                        "{brand_id}": {clicks}
                    },
                    "cat_click":{
                        "{cat_id}": {clicks}
                    }
                }
            }
        }
        '''
        property_id = GOOGLE_ANALYTICS_ID["home"].get("ga-id")
        metric_d_list = [metric for key, metric in HomeEvents.items()]
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        response = cls.run_report(property_id, metric_d_list, date_range)

        data = {
            "homes": {}
        }
        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                home_id = eventName.split('home_id=')[1].split('_')[0]
                home_values = data["homes"].get(home_id,{
                'brand_click':{}, 
                'cat_click': {}
                })
            except:
                home_id = None 
                home_values = data
            for metric_dict in metric_d_list:
                home_analytics = cls._add_values_to_home_analytics(metric_dict,row,home_values)
                if not home_analytics:
                    continue
                if home_id:
                    data["homes"][home_id] = home_analytics
                else:
                    data.update(home_analytics)

        return data
        
    def _add_values_to_home_analytics(metric_dict,row,home_values):
        key = metric_dict.get("key")
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            value = int(row.metric_values[0].value)
            if key == 'brand_click':
                brand_id = eventName.split('bid=')[1].split('_')[0]
                home_values[key][brand_id] = value
            elif key == 'cat_click':
                cat_id = eventName.split('cid=')[1].split('_')[0]
                home_values[key][cat_id] = value
            else:
                home_values[key] = value

            return home_values
        else:
            return {}

    @classmethod
    def get_metrics_for_app_home(cls, date_range):
        property_id = GOOGLE_ANALYTICS_ID["app-home"].get("ga-id")
        metrics = list(AppHomeEvents.values())
        response = cls.run_report(property_id, metrics, date_range)
        
        data = {"app_homes":{}}

        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                home_id = re.split("home_id_",eventName)[1]
            except:
                continue
            home_values = data["app_homes"].get(home_id, {})
            for metric in metrics:
                home_analytics = cls._add_values_to_app_home_analytics(metric, row, home_values)
                if home_analytics:
                    data["app_homes"][home_id] = home_analytics

        return data

    def _add_values_to_app_home_analytics(metric, row, home_values):
        key = metric.get("key")
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            value = int(row.metric_values[0].value)
            home_values[metric.get("save_key")] = value
        return home_values

    @classmethod
    def get_metrics_for_store(cls, date_range={"start_date":"2022-01-01", "end_date":"today"}):
        '''
        sample response dict
        {
            "stores":{
                "{store_id}":{
                    "store_visits":value,
                    "col_visit_total":value,
                    "pdp_visit_total":value,
                    "return_policy":value,
                    "my_orders":value,
                    "checkout_succ":value,
                    "checkout_fail":value,
                    "support":value,
                    "brand_click":{
                        "{brand_id}": {clicks}
                    },
                    "cat_click":{
                        "{cat_id}": {clicks}
                    }
                },
            }
        }
        '''
        #FIXME Add filters for GA side filtering for store ID

        property_id = GOOGLE_ANALYTICS_ID["store"].get("ga-id")
        metric_d_list = [StoreEvents.get(metric_name) for metric_name in StoreEvents.keys() if StoreEvents.get(metric_name)]
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        response = cls.run_report(property_id, metric_d_list, date_range)

        data = {
                "stores":{}
            }

        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                store_id = re.split("store_id=",eventName)[1]
            except:
                store_id = None 
            
            if not store_id:
                continue
            store_values = data["stores"].get(store_id,{
                'brand_click':{}, 
                'cat_click': {}
                })
            for metric_dict in metric_d_list:
                store_analytics = cls._add_values_to_store_analytics(metric_dict,row,store_values)
                if not store_analytics:
                    continue
                data["stores"][store_id] = store_analytics
                
        return data
        

    def _add_values_to_store_analytics(metric_dict,row,store_values):
        key = metric_dict.get("key")
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            value = int(row.metric_values[0].value)
            if key == 'brand_click':
                brand_id = eventName.split('bid=')[1].split('_')[0]
                store_values[key][brand_id] = value
            elif key == 'cat_click':
                cat_id = eventName.split('cid=')[1].split('_')[0]
                store_values[key][cat_id] = value
            else:
                store_values[key] = value

            return store_values
        else:
            return {}

    @classmethod
    def get_metrics_for_app_store(cls, date_range):
        property_id = GOOGLE_ANALYTICS_ID["app-store"].get("ga-id")
        metrics = list(AppStoreEvents.values())
        response = cls.run_report(property_id, metrics, date_range)
        
        data = {"app_stores":{}}

        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                store_id = re.split("store_id_",eventName)[1]
            except:
                continue
            store_values = data["app_stores"].get(store_id, {})
            for metric in metrics:
                store_analytics = cls._add_values_to_app_store_analytics(metric, row, store_values)
                if store_analytics:
                    data["app_stores"][store_id] = store_analytics

        return data

    def _add_values_to_app_store_analytics(metric, row, store_values):
        key = metric.get("key")
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            value = int(row.metric_values[0].value)
            store_values[metric.get("save_key")] = value
        return store_values
    
    @classmethod
    def get_metrics_for_product(cls,date_range={"start_date":"2022-01-01", "end_date":"today"}):
        '''
        sample response dict
        {
            products:{
                "pid":{
                    "store_id":value,
                },
            }
        }
        '''
        #FIXME Add filters for GA side filtering for store ID 
        property_id = GOOGLE_ANALYTICS_ID["store"].get("ga-id")
        metric_d_list = [ProductEvents.get(metric_name) for metric_name in ProductEvents.keys() if ProductEvents.get(metric_name)]
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        response = cls.run_report(property_id, metric_d_list, date_range)
        
        data = {
                "products":{}
            }
        
        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                pdp_temp = re.split("pdp_visit__pid=",eventName)[1]
                pid = re.split("__",pdp_temp)[0]
            except:
                pid = None 
            
            if not pid:
                continue
            
            product_values = data["products"].get(pid,{})
            for metric_dict in metric_d_list:
                product_analytics = cls._add_values_to_product_analytics(metric_dict,row,product_values)
                if not product_analytics:
                    continue
                product_analytics_dict = {pid:product_analytics}
                data.get("products").update(product_analytics_dict)  
        return data

    def _add_values_to_product_analytics(metric_dict,row,product_values):
        key = metric_dict.get("key")
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        value = int(row.metric_values[0].value)
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            store_id = re.split("store_id=",eventName)[1]
            search_dict = {store_id:value}
            if product_values:
                product_values.update(search_dict)
            else:
                product_values = search_dict
            return product_values
        else:
            return {}
    
    @classmethod
    def get_metrics_for_app_product(cls, date_range):
        """
        sample response dict
        {
            app_products:{
                $pid:{
                    $store_id:$value,
                },
            }
        }
        """
        property_id = GOOGLE_ANALYTICS_ID["app-store"].get("ga-id")
        metrics = list(AppProductEvents.values())
        response = cls.run_report(property_id, metrics, date_range)
        
        data = {"app_products":{}}

        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                pid = re.split("pId_",eventName)[1].split('_')[0]
                store_id = re.split("store_id_",eventName)[1]
            except IndexError:
                continue
            product_values = data["app_products"].get(pid, {})
            for metric in metrics:
                metric['save_key'] = store_id
                product_analytics = cls._add_values_to_app_product_analytics(metric, row, product_values)
                if product_analytics:
                    data["app_products"][pid] = product_analytics

        return data
    
    def _add_values_to_app_product_analytics(metric, row, product_values):
        key = metric.get("key")
        value = int(row.metric_values[0].value)
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            product_values[metric.get('save_key')] = value
        
        return product_values

    @classmethod
    def get_metrics_for_collection(cls, date_range={"start_date":"2022-01-01", "end_date":"today"}):
        #FIXME Add filters for GA side filtering for store ID
        property_id = GOOGLE_ANALYTICS_ID["store"].get("ga-id")
        metric_d_list = [CollectionEvents.get(metric_name) for metric_name in CollectionEvents.keys() if CollectionEvents.get(metric_name)]
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        response = cls.run_report(property_id, metric_d_list, date_range)
        data = {
                "collections":{}
            }
        for row in response.rows:
            eventName = row.dimension_values[0].value
            try:
                collection_temp = re.split("col_visit__col_id=",eventName)[1]
                collection_id = re.split("__",collection_temp)[0]
            except:
                collection_id = None 
            
            if not collection_id:
                continue
            
            collection_values = data["collections"].get(collection_id,{})
            for metric_dict in metric_d_list:
                collection_analytics = cls._add_values_to_collection_analytics(metric_dict,row,collection_values)
                if not collection_analytics:
                    continue
                collection_analytics_dict = {collection_id:collection_analytics}
                data.get("collections").update(collection_analytics_dict)  
        return data

    
    def _add_values_to_collection_analytics(metric_dict,row,collection_values):
        key = metric_dict.get("key")
        #FIXME change if different metrics for different dimensions required. For now only total hits being taken
        value = int(row.metric_values[0].value)
        eventName = row.dimension_values[0].value
        if re.search("^"+key+".*$", eventName):
            search_dict = {"collection_visits":value}
            if collection_values:
                collection_values.update(search_dict)
            else:
                collection_values = search_dict
            return collection_values
        else:
            return {}
    
    @classmethod
    def get_metrics_for_landing(cls, date_range={"start_date":"2022-01-01", "end_date":"today"}):
        property_id = GOOGLE_ANALYTICS_ID["landing-page"].get("ga-id")
        metric_d_list = [LandingEvents.get("TotalVisits")]
        response = cls.run_report(property_id, metric_d_list, date_range)
        
        data = {}
        key = metric_d_list[0].get("key")
        for row in response.rows:
            eventName = row.dimension_values[0].value
            value = int(row.metric_values[0].value)
            if re.search(key,eventName):
                data.update({key:value})  
                return data
            else:
                continue
       
    @classmethod
    def _set_date_range_values(cls,value):
        time_utilities = TimeUtilities()
        date_range = ""
        date_format = "%Y-%m-%d"
        today_start = time_utilities.parse_date(time_utilities.get_today_start().date(),date_format)
        if value:
            if value==TimePeriod.LASTHOUR:
                #FIXME returns the Last 30 mins data not LASTHOUR
                date_range = {"start_date": today_start, "end_date": today_start}
            
            elif value==TimePeriod.TODAY: 
                date_range = {"start_date": today_start,"end_date":today_start}

            elif value==TimePeriod.YESTERDAY: 
                yesterday_start = time_utilities.parse_date(time_utilities.get_yesterdays_date().date(),date_format)
                date_range = {"start_date": yesterday_start, "end_date": yesterday_start}

            elif value==TimePeriod.TILLTODAYTHISWEEK: 
                
                this_week_start = time_utilities.parse_date(time_utilities.get_current_week_start().date(),date_format)
                date_range = {"start_date": this_week_start,"end_date":today_start}
                
            elif value==TimePeriod.LASTWEEK: 
                
                last_week_start, last_week_end = time_utilities.get_prev_week_boundaries()
                date_range = {"start_date": time_utilities.parse_date(last_week_start.date(),date_format), "end_date": time_utilities.parse_date(last_week_end.date(),date_format)}
                
            elif value==TimePeriod.TILLTODAYTHISMONTH: 
                curr_month_start_date = time_utilities.parse_date(time_utilities.get_current_month_start().date(),date_format)
                date_range = {"start_date": curr_month_start_date,"end_date":today_start}
                
            elif value==TimePeriod.LASTMONTH: 
                prev_month_start_date, prev_month_end_date = time_utilities.get_prev_month_boundaries()
                date_range = {"start_date": time_utilities.parse_date(prev_month_start_date.date(),date_format), "end_date": time_utilities.parse_date(prev_month_end_date.date(),date_format)}
                
            elif value==TimePeriod.OVERALL:
                date_range = {"start_date": "2022-01-01", "end_date":today_start}
        else:
            date_range = {"start_date": "2022-01-01", "end_date":today_start}
        return date_range
    
    def set_date_range_from_start_end_date(start_date,end_date):
        return set_time_date_ga(start_date,end_date)

    def _update_brand_clicks(brand, brand_clicks, store_id, click_type="store_clicks"):
        for brand_id in brand_clicks:
            if not brand_id in brand:
                brand[brand_id] = {store_id:{}}
            elif not store_id in brand[brand_id]:
                brand[brand_id][store_id] = {}

        for brand_id, clicks in brand_clicks.items():
            brand[brand_id][store_id][click_type] = clicks

    def _update_cat_clicks(category, cat_clicks, store_id, click_type="store_clicks"):
        for cat_id in cat_clicks:
            if not cat_id in category:
                category[cat_id] = {store_id:{}}
            elif not store_id in category[cat_id]:
                category[cat_id][store_id] = {}

        for cat_id, clicks in cat_clicks.items():
            category[cat_id][store_id][click_type] = clicks

    @classmethod
    def save_overall_dashboard_data_to_mongo(cls,start_date,end_date):
        mongo_client = MongoConn()
        operations = []
        today = TimeUtilities().get_today_start()
        today_date = set_time_date_ga(today, today).get("start_date")
        data_to_update_col_details = []

        while(start_date < end_date):
            range_1 = start_date
            start_date = TimeUtilities.add_time_in_timestamp(start_date, days=1)
            date_range = set_time_date_ga(range_1,range_1)
            store_queryset = GoogleAnalyticsImpl.get_metrics_for_store(date_range=date_range)
            home_queryset = GoogleAnalyticsImpl.get_metrics_for_home(date_range=date_range)
            app_home_metrics = GoogleAnalyticsImpl.get_metrics_for_app_home(date_range=date_range)
            app_store_metrics = GoogleAnalyticsImpl.get_metrics_for_app_store(date_range=date_range)
            store_visits = 0
            product_visits = 0
            col_visits = 0
            brand, category = {}, {}
            for store_id, store in store_queryset.get("stores").items():
                store_id_visit = store.get("store_visits")
                store_id_product_visit = store.get("pdp_visit_total")
                store_id_col_visit = store.get("col_visits_total")
                if store_id_visit:
                    store_visits += int(store_id_visit)
                if store_id_product_visit:
                    product_visits += int(store_id_product_visit)
                if store_id_col_visit:
                    col_visits += int(store_id_col_visit)
                
                brand_clicks = store.pop("brand_click")
                cat_clicks = store.pop("cat_click")
                store_queryset["stores"][store_id]["brand_click_total"] = sum(brand_clicks.values())
                store_queryset["stores"][store_id]["cat_click_total"] = sum(cat_clicks.values())

                cls._update_brand_clicks(brand, brand_clicks, store_id, "store_clicks")
                cls._update_cat_clicks(category, cat_clicks, store_id, "store_clicks")
            
            for home_id, home in home_queryset.get("homes").items():
                brand_clicks = home.pop("brand_click")
                cat_clicks = home.pop("cat_click")
                home["brand_click_total"] = sum(brand_clicks.values())
                home["cat_click_total"] = sum(cat_clicks.values())

                cls._update_brand_clicks(brand, brand_clicks, home_id, "home_clicks")
                cls._update_cat_clicks(category, cat_clicks, home_id, "home_clicks")

            post_data = {
                "date":date_range.get("start_date"),
                "site_visits": home_queryset.get("page_view", 0) + store_visits,
                "store_visits":store_visits,
                "product_visits":product_visits,
                "col_visits":col_visits,
                "brand": brand,
                "category": category,
                **store_queryset,
                **home_queryset,
                **app_store_metrics,
                **app_home_metrics
            }
            data_to_update_col_details.append({"date":date_range.get("start_date"),**store_queryset})
            if date_range.get("start_date") == today_date:
                current_data = mongo_client.fetch_one({'date': today_date}, GA_COLLECTTION_NAME)
                if current_data:
                    post_data = DictionaryUtilities.add_common_keys(post_data, current_data)

            operations.append(
                MongoConn.update_one_operation(
                filter={"date": date_range.get("start_date")},
                update={"$set": post_data}, 
                upsert=True
                )
            )
        mongo_client.bulk_update_data(operations=operations,collection_name = GA_COLLECTTION_NAME)
        GoogleAnalyticsImpl.save_store_details_data_to_mongo(data_to_update_col_details)



    @classmethod
    def save_product_data_to_mongo(cls,start_date,end_date):
        mongo_client = MongoConn()
        operations = []
        today = TimeUtilities().get_today_start()
        yesterday = TimeUtilities().get_yesterdays_date()
        today_date = set_time_date_ga(today, today).get("start_date")
        yesterday_date = set_time_date_ga(yesterday, yesterday).get("start_date")
        while(start_date < end_date):
            range_1 = start_date
            start_date = TimeUtilities.add_time_in_timestamp(start_date, days=1)
            date_range = set_time_date_ga(range_1,range_1)
            product_queryset = GoogleAnalyticsImpl.get_metrics_for_product(date_range=date_range)
            app_product_queryset = GoogleAnalyticsImpl.get_metrics_for_app_product(date_range=date_range)
            post_data = {
                "date":date_range.get("start_date"),
                **product_queryset,
                **app_product_queryset
            }
            if date_range.get("start_date") == yesterday_date:
                add_pdp_views(post_data)
                
            if date_range.get("start_date") == today_date:
                current_data = mongo_client.fetch_one({'date': today_date}, GA_COLLECTTION_NAME)
                if current_data:
                    post_data = DictionaryUtilities.add_common_keys(post_data, current_data)

            operations.append(
                MongoConn.update_one_operation(
                filter={"date": date_range.get("start_date")},
                update={"$set": post_data}, 
                upsert=True
                )
            )
        mongo_client.bulk_update_data(operations=operations,collection_name = GA_COLLECTTION_NAME)

    
    @classmethod
    def save_collection_details_data_to_mongo(cls,data_to_update_col_details):
        mongo_client = MongoConn()
        operations = []
        for collection_data in data_to_update_col_details:
            date = collection_data.get('date')
            collections = collection_data.get('collections')
            if not collections:
                continue
            for col_id,col_visit_dict in collections.items():
                post_data= {'date':date,'collection_id':col_id,'collection_visit':col_visit_dict.get('collection_visits')}

                operations.append(
                    MongoConn.update_one_operation(
                    filter={"date": date,'collection_id':col_id},
                    update={"$set": post_data}, 
                    upsert=True
                    )
                )

        mongo_client.bulk_update_data(operations=operations,collection_name = GA_COLLECTION_DETAIL_NAME)

    @classmethod
    def save_store_details_data_to_mongo(cls,data_to_update_col_details):
        mongo_client = MongoConn()
        operations = []
        for store_data in data_to_update_col_details:
            date = store_data.get('date')
            stores = store_data.get('stores')

            if not stores:
                continue
            
            for store_id,store_visit_dict in stores.items():
                post_data= {'date':date,'store_id':store_id, **store_visit_dict}

                operations.append(
                    MongoConn.update_one_operation(
                    filter={'date':date,'store_id':store_id},
                    update={"$set": post_data}, 
                    upsert=True
                    )
                )

        mongo_client.bulk_update_data(operations=operations,collection_name = GA_STORE_DETAIL_NAME)


    @classmethod
    def save_collection_data_to_mongo(cls,start_date,end_date):
        mongo_client = MongoConn()
        operations = []
        today = TimeUtilities().get_today_start()
        today_date = set_time_date_ga(today, today).get("start_date")
        data_to_update_col_details = []
        while(start_date < end_date):
            range_1 = start_date
            start_date = TimeUtilities.add_time_in_timestamp(start_date, days=1)
            date_range = set_time_date_ga(range_1,range_1)
            col_queryset = GoogleAnalyticsImpl.get_metrics_for_collection(date_range=date_range)
            if not col_queryset:
                continue
            post_data = {
                "date":date_range.get("start_date"),
                **col_queryset
            }
            if date_range.get("start_date") == today_date:
                current_data = mongo_client.fetch_one({'date': today_date}, GA_COLLECTTION_NAME)
                if current_data:
                    post_data = DictionaryUtilities.add_common_keys(post_data, current_data)

            data_to_update_col_details.append(post_data)
            operations.append(
                MongoConn.update_one_operation(
                filter={"date": date_range.get("start_date")},
                update={"$set": post_data}, 
                upsert=True
                )
            )
        mongo_client.bulk_update_data(operations=operations,collection_name = GA_COLLECTTION_NAME)
        GoogleAnalyticsImpl.save_collection_details_data_to_mongo(data_to_update_col_details)



    @classmethod
    def save_landing_data_to_mongo(cls,start_date,end_date):
        mongo_client = MongoConn()
        operations = []
        today = TimeUtilities().get_today_start()
        today_date = set_time_date_ga(today, today).get("start_date")
        while(start_date < end_date):
            range_1 = start_date
            start_date = TimeUtilities.add_time_in_timestamp(start_date, days=1)
            date_range = set_time_date_ga(range_1,range_1)
            landing_queryset = GoogleAnalyticsImpl.get_metrics_for_landing(date_range=date_range)
            if not landing_queryset:
                continue
            post_data = {
                "date":date_range.get("start_date"),
                **landing_queryset
            }
            if date_range.get("start_date") == today_date:
                current_data = mongo_client.fetch_one({'date': today_date}, GA_COLLECTTION_NAME)
                if current_data:
                    post_data = DictionaryUtilities.add_common_keys(post_data, current_data)

            operations.append(
                MongoConn.update_one_operation(
                filter={"date": date_range.get("start_date")},
                update={"$set": post_data}, 
                upsert=True
                )
            )
        mongo_client.bulk_update_data(operations=operations,collection_name = GA_COLLECTTION_NAME)

    @classmethod
    def get_store_total_visitors(cls, store_id, date_range=None):
        if not date_range:
            date_range = set_time_date_ga(TimeUtilities.get_current_date_time(), TimeUtilities.get_current_date_time())
            date_range['start_date'] = '2022-01-01'
        
        property_id = GOOGLE_ANALYTICS_ID["store"].get("ga-id")
        client =  BetaAnalyticsDataClient(credentials=cls.get_credentials())
        request =  RunReportRequest(
                property=f"properties/{property_id}",
                dimensions=[],
                metrics=[Metric(name="totalUsers")],
                dimension_filter=FilterExpression( 
                    filter=Filter(field_name="eventName",
                    string_filter=Filter.StringFilter(value=f"store_id={store_id}", match_type=3)) # match type 3 - ends_with
                ),
                date_ranges=[DateRange(start_date=date_range.get("start_date"), end_date=date_range.get("end_date"))],
            )
        response = client.run_report(request)
        total_visitors = 0
        for row in response.rows:
            total_visitors = NumberUtilities.convert_string_to_number(row.metric_values[0].value)
        return total_visitors


