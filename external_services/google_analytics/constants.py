from django.conf import settings
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
GOOGLE_ANALYTICS_ID = {
    "landing-page": {
        "ga-id":settings.GOOGLE_ANALYTICS.get("LANDING_GA_ID"),
        },
    "home": {
        "ga-id":settings.GOOGLE_ANALYTICS.get("HOME_GA_ID"),
        },
    "store": {
        "ga-id":settings.GOOGLE_ANALYTICS.get("STORE_GA_ID"),
        },
    "app-store": {
        "ga-id":settings.GOOGLE_ANALYTICS.get("APP_STORE_GA_ID"),
        },
    "app-home": {
        "ga-id":settings.GOOGLE_ANALYTICS.get("APP_HOME_GA_ID"),
        }
}

HomeEvents = {
    "TotalVisits":{
        "key":"page_view",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "Engagement":{
        "key":"user_engagement",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "BrandClicks":{
        "key":"brand_click",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "CategoryClicks":{
        "key":"cat_click",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "Earnings":{
        "key":"earn",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "Coupons":{
        "key":"coupons",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    }
}

StoreEvents = {
    "TotalVisits":{
        "key":"store_visits",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "TotalCollectionVisits":{
        "key":"col_visits_total",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "TotalProductVists":{
        "key":"pdp_visit_total",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "CheckoutSuccess":{
        "key":"checkout_succ",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "CheckoutFail":{
        "key":"checkout_fail",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "CheckoutBack":{
        "key":"checkout_back",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "AccountsMyOrders":{
        "key":"my_orders",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "AccountsReturnPolicy":{
        "key":"return_policy",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "AccountsSupport":{
        "key":"support",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "BrandClicks":{
        "key":"brand_click",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "CategoryClicks":{
        "key":"cat_click",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    }
}

ProductEvents = {
    "TotalVisits":{
        "key":"pdp_visit__pid=",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    }
}

CollectionEvents = {
    "TotalVisits":{
        "key":"col_visit__col_id=",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    }
}



LandingEvents = {
    "TotalVisits":{
        "key":"store_landing_zaamo",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    },
    "TryNowInfluencer":{},
    "TryNowBrand":{}
}

AppStoreEvents = {
    "TotalProductVisits":{
        "key":"pdp_view__store_id_",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"],
        "save_key": "pdp_visit_total"
    }
}

AppHomeEvents = {
    "TotalProductVisits":{
        "key":"pdp_view__home_id_",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"],
        "save_key": "pdp_visit_total"
    }
}

AppProductEvents = {
    "TotalVisits":{
        "key":"pdp_view_pId_",
        "metrics":[Metric(name="eventCount"),Metric(name="totalUsers")],
        "metricValues":["eventCount","totalUsers"]
    }
}

GA_COLLECTTION_NAME = "GA_Analytics"
GA_COLLECTION_DETAIL_NAME = "GA_Analytics_collection"
GA_STORE_DETAIL_NAME = "GA_Analytics_stores"
