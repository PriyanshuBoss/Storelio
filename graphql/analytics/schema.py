import graphene
from saleor.graphql.analytics.types import (Dashboard, MasterDashboard, PdpAnalytics, ProductAnalytics, 
                                             CollectionAnalytics, StoreAnalytics, EarningAnalytics, MasterDashboardKPI, pdpproducttype, SourceWithZaamoKPI)
from saleor.graphql.analytics.resolvers import paginated_resolve_product_search_pdp, resolve_brand_for_pdp, resolve_earning_analytics_single_store, resolve_overall_dashboard,resolve_earnings_analytics, resolve_master_dashboard_kpi, resolve_pdp_product_search, resolve_source_with_zaamo_kpi
from saleor.graphql.order.schema import OrderFilterInput
from saleor.graphql.order.sorters import OrderSortingInput
from saleor.graphql.product.sorters import CollectionSortingInput, ProductOrder
from saleor.graphql.core.fields import FilterInputConnectionField
from saleor.graphql.analytics.filters import ProductAnalyticsFilterInput, CollectionAnalyticsFilterInput, StoreAnalyticsFilterInput
from saleor.graphql.order.enums import TimePeriod,OrderFullfillmentStatusEnum
from saleor.graphql.analytics.mutations import pdpPublishProduct
from saleor.graphql.analytics.sorters import StoreAnalyticsSortingInput


class DashboardQueries(graphene.ObjectType):
   
   overall_dashboard = graphene.List(
               Dashboard, 
               description="overall dashboard analytics", 
               page=graphene.Int(description="page number for overall dashboard"))

   master_dashboard = FilterInputConnectionField(
               MasterDashboard,
               sort_by=OrderSortingInput(description="Sort orders."),
               filter=OrderFilterInput(description="Filtering options for orders."),
               description="List of Dashboard entries.")

   products_analytics = FilterInputConnectionField(
               ProductAnalytics, 
               description="Products Analytics",
               filter=ProductAnalyticsFilterInput(description="Filtering options for products."),
               sort_by=ProductOrder(description="Sort products anlytics."),
               )

   collection_analytics = FilterInputConnectionField(
               CollectionAnalytics, 
               description="Collections Analytics",
               filter=CollectionAnalyticsFilterInput(description="Filtering options for Collections."),
               sort_by=CollectionSortingInput(description="Sort collections analytics."),
               )

   store_analytics = FilterInputConnectionField(
               StoreAnalytics, 
               description="Store Analytics",
               filter=StoreAnalyticsFilterInput(description="Filtering options for Store."),
               time_period=graphene.Argument(
               TimePeriod, description="Time period filter"),
               sort_by=StoreAnalyticsSortingInput(description="Sort by store analytics.")
               )
   
   earnings_analytics = FilterInputConnectionField(EarningAnalytics,      
               description="Earning Page Analytics",
               store_ids=graphene.Argument(graphene.List(graphene.ID), description="list of store ids"))

   earning_analytics = graphene.Field(EarningAnalytics,      
               description="Earning Page Analytics for single store",
               store_id=graphene.Argument(graphene.ID, description="store id"))

   pdp_analytics = graphene.Field(PdpAnalytics,      
               description="Data required for dropdown for a particular brand",
               brand_id=graphene.Argument(graphene.ID, description="brand id"))

   pdp_product_search = graphene.List(pdpproducttype,      
               description="pdp product search",
              product_name=graphene.Argument(graphene.String, description='name of product'),
              brand_name=graphene.Argument(graphene.String, description='name of brand'),
              page=graphene.Argument(graphene.Int, description='page number')
              )

   master_dashboard_kpi = graphene.Field(
               MasterDashboardKPI,
               description="Represents master dashboard kpis.",
               time_period=graphene.Argument(
               TimePeriod, description="Time period filter"),
               brand_ids=graphene.List(graphene.ID, description="brand id filter"),
               order_status = graphene.List(OrderFullfillmentStatusEnum,description = "OrderFullfilment Status filter")
               )

   source_with_zaamo_kpi = graphene.Field(
       SourceWithZaamoKPI,
       description = "Source with zaamo page kpis.",
       brand_ids=graphene.List(graphene.ID, description="brand id filter"),
       start_date = graphene.Date(description="Start date."),
       end_date = graphene.Date(description="End date.")
   )

   def resolve_overall_dashboard(self, _info, page=1):
     
          return resolve_overall_dashboard(page)
     
   def resolve_earnings_analytics(self, _info, store_ids=None, **args):
          
          return resolve_earnings_analytics(store_ids,_info)
          
   def resolve_earning_analytics(self, _info, store_id=None):
          
          return resolve_earning_analytics_single_store(store_id,_info)
          
   def resolve_pdp_analytics(self, _info, brand_id=None):
          
          return resolve_brand_for_pdp(brand_id,_info)
       

   def resolve_master_dashboard_kpi(self, _info, time_period=None, brand_ids=None,order_status=None):
           
           return resolve_master_dashboard_kpi(self, _info, time_period, brand_ids,order_status)

   def resolve_pdp_product_search(self, _info,product_name,page=1, brand_name=None):
          
          return paginated_resolve_product_search_pdp(product_name,brand_name, page, _info)
   
   def resolve_source_with_zaamo_kpi(self, _info, brand_ids=None, start_date=None, end_date=None):

           return resolve_source_with_zaamo_kpi(self, _info, brand_ids, start_date, end_date)

class pdpPublishProductMutation(graphene.ObjectType):
   pdp_publish_product = pdpPublishProduct.Field()
