from collections import defaultdict
import datetime
from typing import DefaultDict
from django.http import JsonResponse
import logging
import json
from saleor.checkout import calculations
from saleor.checkout.models import Checkout, CheckoutLine
from saleor.external_services.wix.wix_impl import WixImpl
from saleor.external_services.shopify_service.shopify_impl import ShopifyImpl
from saleor.external_services.woo_commerce_service.woo_commerce_impl import WooCommerceImpl
from datetime import timedelta
from saleor.external_services import get_fernet_encoder
from django.utils import timezone
from saleor.brand.states import BrandStatusEnum
from saleor.brand.models import Brand, BrandCollection, BrandCred, BrandMemberState, BrandOrderCount, BrandShippingData, Commission, StaffBrandMapping, BrandEmail
from saleor.brand.emails import send_email_brand_ledger
from saleor.discount.models import Voucher
from saleor.external_services import get_decoded_string
from saleor.graphql.analytics.resolvers import create_store_count_dictionary
from saleor.invoice.tasks import create_invoice_for_brands_task
from saleor.order.models import Order, OrderBrandZaamoMapping, OrderLine
from saleor.product.models import BrandPriceRecord, BrandVariantZaamoMapping, CollectionStore, Product, ProductVariant, SourcingRequestStatus, ZaamoShopifyProductMapping
from saleor.utilities.api_client import ApiClient
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.raw_sql_queries_utilities import RawSQLUtilities
from saleor.warehouse.models import Stock
from saleor.rest_apis.csv.csv_context import BrandLedgerXLSX, BrandLedgerOld, ExploreProductCSV, InfluencerLedgerXLSX, BrandManagerCSVhelper, ManagerAndBrandWiseGMV, ManagerAndInfluencerWiseGMV, InfluencerAndMrpWiseGMV, InfluencerManagerWiseGMV, BrandManagerWiseGMV, OrderCalculations, OrderCsvContext , BrandPaymentCsvContext,InfluencerPaymentCsvContext, ShopifyProductDetailsCSV, SourcingRequestCSV, StoreGMVCsvContext, BrandPriceRecordCSV, AllCollectionsDumpCSVContext, BrandDashboardCsvContext,OrderLineCashgramCSV, ZaamoShopifyOrder, reel_up_details_by_brand ,TaxReport
from saleor.rest_apis.csv.csv_context import BrandSourcingRequestCSV, BotdStoresCSV, CouponsCSV, AllBrandDetailsCSV, ExploreProductUploadCSV, PublishedProductsCSV, ShopifyCSV
import csv
from saleor.utilities.mongo_utilities import MongoConn
from dateutil import parser as date_parser
from saleor.graphql.api import schema
from django.http import HttpResponse
from saleor.account.models import User, Influencer
from saleor.store.models import StoreInfo, StoreMemberState, StoreTypeEnum
from saleor.plugins.manager import PluginsManager
import graphene
from django.conf import settings
from saleor.external_services.mail.mail_impl import MailImpl
from io import StringIO
import base64
logger = logging.getLogger(__name__)
from saleor.graphql.utils import get_nodes
from django.db.models import Count,Subquery,Max,Sum
from saleor.product import BrandCollabStatusForSouringRequest
from saleor.discount.models import Voucher
from django.contrib.postgres.aggregates import StringAgg, ArrayAgg
from saleor.discount import VoucherOwner
from django.db.models.functions import Cast
from django.db.models import TextField,Q,F
from .helper import fetch_structure_data_ad, send_order_csv_to_email , order_instance_data_list,sourcing_request_data_list,send_sourcing_request_csv_to_email,orderline_cashgram_list, tax_report_data_list, update_product_search_image

try:
    params = {"user": User.objects.get(email=settings.PRODUCT_IMPORT_USER_EMAIL),
    "plugins": PluginsManager(plugins=settings.PLUGINS), 'app': None}
    schema_context = graphene.types.Context(**params)
except Exception as e:
    print(e)

def export_csv_for_master_dashboard(request):
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not TimeUtilities.validate_date(start_date) or not TimeUtilities.validate_date(end_date):
        return HttpResponse("Invalid date")

    start_date = date_parser.parse(start_date)
    end_date = date_parser.parse(end_date)

  
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="export.csv"'

    writer = csv.writer(response)
    order_csv = OrderCsvContext(start_date, end_date)
    headers = order_csv.get_headers_of_order_for_csv()
    writer.writerow(headers)

    order_filter = order_csv.get_queryset()

    if request.GET.get('brand_id') is not None:
      values = []
      values.append(request.GET.get('brand_id'))
      brands = get_nodes(values, "Brand", Brand)
      brand_id = brands[0].id
      order_filter = order_filter.filter(brand_id = brand_id)

    all_rows = order_instance_data_list(order_filter,order_csv)

    writer.writerows(all_rows)

    return response

def export_tax_reports(request):
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if not TimeUtilities.validate_date(start_date) or not TimeUtilities.validate_date(end_date):
        return HttpResponse("Invalid date")

    file_name = f"tax_report_{start_date}-{end_date}.csv"

    start_date = date_parser.parse(start_date)
    end_date = date_parser.parse(end_date)
  
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'

    writer = csv.writer(response)
    order_csv = TaxReport(start_date, end_date)
    headers = order_csv.get_headers_of_order_for_csv()
    writer.writerow(headers)
    
    order_filter = order_csv.get_queryset()
    
    all_rows = tax_report_data_list(order_filter,order_csv)

    writer.writerows(all_rows)
    
    return response

def export_zaamo_shopify_order(request,email=False):
    current_date = StringUtilities.convert_object_to_string(TimeUtilities.get_n_days_before_date(-1))
    prev_date = StringUtilities.convert_object_to_string(TimeUtilities.get_n_days_before_date(2))
    start_date = request.GET.get('start_date') if request else prev_date
    end_date = request.GET.get('end_date') if request else current_date
    
    if not TimeUtilities.validate_date(start_date) or not TimeUtilities.validate_date(end_date):
        return HttpResponse("Invalid date")

    start_date = date_parser.parse(start_date)
    end_date = date_parser.parse(end_date)
    filename = f"order_export_{start_date}-{end_date}"
    order_csv = ZaamoShopifyOrder(start_date, end_date)

    if not email:
      response = HttpResponse(content_type='text/csv')
      response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'

      writer = csv.writer(response)
      writer.writerows(order_csv)
      return response

    m = MailImpl()
    order_attachment = m.get_csv_attachment_dict(filename,order_csv)
    attachments = [order_attachment]
    
    for owner_email in ['nitanshub@zaamo.co','priyanshu@zaamo.co']:

      summary = order_csv[-4:]
      summary = [' : '.join(map(str, inner_list)) for inner_list in summary]
      summary = '\n'.join(summary)
      
      m.send_mail_with_attachment('brand_owner_csv',f'Hi, Please find the attached CSVs for Order export between {start_date} to {end_date}.\n\n{summary}','Zaamo Shopify Order Export',attachments,owner_email)
      

def export_reel_up_brand_details(request):
    brand_name = request.GET.get('brand_name')
    current_date = StringUtilities.convert_object_to_string(TimeUtilities.get_n_days_before_date(0))
    
    filename = f"reel_up_export_{brand_name}-{current_date}"
    rows = reel_up_details_by_brand(brand_name)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'

    writer = csv.writer(response)
    writer.writerows(rows)
    return response


def export_csv_for_brand_price_record(request):
    
    start_date = request.GET.get('start_date')

    if not TimeUtilities.validate_date(start_date):
        return HttpResponse("Invalid date")

    start_date = date_parser.parse(start_date)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="export.csv"'
    brand_price_records = BrandPriceRecordCSV(start_date)

    writer = csv.writer(response)
    headers = brand_price_records.get_headers_for_brand_price_record()
    writer.writerow(headers)
    records = brand_price_records.get_query_set()
    for record in records:
        row = [
            record.brand_name,
            record.product_name,
            record.variant_name,
            record.is_published,
            record.data_source,
            record.current_cost_price_amount,
            record.current_price_amount,
            record.prev_cost_price_amount,
            record.prev_price_amount,
            record.updated_at

        ]

        writer.writerow(row)

    return response

def export_csv_for_sourcing_request(request):

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = "attachment; filename=sourcing_request_export.csv"

    sourcing_request = SourcingRequestCSV(start_date, end_date)
  
    writer = csv.writer(response)

    all_data_list = sourcing_request_data_list(sourcing_request)

    writer.writerows(all_data_list)
    
    return response

def export_csv_for_brand_sourcing_request(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = "attachment; filename=brand_sourcing_request.csv"

    sourcing_request = BrandSourcingRequestCSV(start_date, end_date)
    queryset = sourcing_request.get_queryset()
    
    headers = sourcing_request.get_headers()
    field_names = sourcing_request.get_header_field_mapping()

    writer = csv.writer(response)
    writer.writerow(headers)
    
    for row in queryset:
        row = [row.get(field_names.get(header)) for header in headers]
        writer.writerow(row)

    return response

def export_csv_store_analytics():
    
    variables = {
    "stores": [],
    "timePeriod": "OVERALL",
    }
    
    query = """
    query StoreAnalytics($stores: [ID], $timePeriod: TimePeriod, $endCursor: String) {
  storeAnalytics(
    first: 5
    filter: {stores: $stores}
    timePeriod: $timePeriod
    after: $endCursor
  ) {
    pageInfo {
      hasNextPage
      endCursor
      __typename
    }
    edges {
      node {
        id
        createdAt
        storeName
        storeUrl
        totalVisitors
        totalProductPageViews
        totalCollectionViews
        wishlistOfProducts
        totalOrders
        averageOrderValue
        averageNumberOfItemsInOrder
        averageAbandonedCart
        noOfCouponsUsed
        totalStoreSales
        totalEarnings
        lastPayout
        netPayoutDue
        phoneNumber
        totalMspSales
        __typename
      }
      __typename
    }
    __typename
  }
}
    
    """

    response = schema.execute(query, variables=variables,
                                context_value=schema_context)
    #print(response)
    import csv

    f = open('saleor/rest_apis/csv/csv_file.csv', 'w')

    headers = ["storeName", "visitors", "collection views", "pdp views"," wishlist", "abandoned carts", "orders", "items per order", "total store sales", "earnings","phone_number","discount amount on orders"]
    writer = csv.writer(f)
    writer.writerow(headers)
    count=0
    while response.data['storeAnalytics']["pageInfo"]['hasNextPage']==True:
        if count>0:
            response = schema.execute(query, variables=variables,
                                context_value=schema_context)
        count=count+1
        print(count)
        variables.update({"endCursor":response.data['storeAnalytics']["pageInfo"]['endCursor']})
        print(variables)
        rows = response.data['storeAnalytics']["edges"]
        for row in rows:
            rown = row["node"]    
            row1 = [
                rown["storeName"],
                rown["totalVisitors"],
                rown["totalCollectionViews"],
                rown["totalProductPageViews"],
                rown["wishlistOfProducts"],
                rown["averageAbandonedCart"],
                rown["totalOrders"],
                rown["averageNumberOfItemsInOrder"],
                rown["totalStoreSales"],
                rown["totalEarnings"],
                rown["totalEarnings"],
                rown["phoneNumber"],
                rown["totalMspSales"],
                
            ]

            writer.writerow(row1)
        
    f.close()
    return 
  
def export_csv_for_brand_upi_payment(request):
 
  end_date = request.GET.get('end_date')

  if end_date is not None:
    if not TimeUtilities.validate_date(end_date):
      return HttpResponse("Invalid date")
    else:
      end_date = date_parser.parse(end_date)

  else:
    end_date = TimeUtilities.get_current_date(False)

  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="export.csv"'
  writer = csv.writer(response)
  brand_payment_csv = BrandPaymentCsvContext(end_date)
  headers = brand_payment_csv.get_headers_of_upi_payment_for_csv()
  writer.writerow(headers)

  brand_filter = brand_payment_csv.get_queryset()
  brand_filter = brand_filter.filter(private_metadata__payment_verified=True)

  for brand_instance in brand_filter:

    if brand_instance.upi_ids.first() is None:
      continue
    
    row = [
          brand_payment_csv.get_brand_name(brand_instance),
          brand_payment_csv.get_upi_id(brand_instance),
          brand_payment_csv.get_brand_owner_name(brand_instance),
          brand_payment_csv.get_brand_email(brand_instance),
          brand_payment_csv.get_contact_number(brand_instance),
          brand_payment_csv.get_due_amount(brand_instance),
          brand_payment_csv.get_remarks(),
          brand_instance.id

      ]

    writer.writerow(row)

  return response


def export_csv_for_brand_bank_payment(request):

  end_date = request.GET.get('end_date')
  if end_date is not None:
    if not TimeUtilities.validate_date(end_date):
      return HttpResponse("Invalid date")
    else:
      end_date = date_parser.parse(end_date)

  else:
    end_date = TimeUtilities.get_current_date(False)

  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="export.csv"'

  writer = csv.writer(response)
  brand_payment_csv = BrandPaymentCsvContext(end_date)
  headers = brand_payment_csv.get_headers_of_neft_payment_for_csv()
  writer.writerow(headers)

  brand_filter = brand_payment_csv.get_queryset()
  brand_filter = brand_filter.filter(private_metadata__payment_verified=True)

  for brand_instance in brand_filter:

    if brand_instance.upi_ids.first() is not None or brand_instance.bank_accounts.first() is None:
      continue
    
    row = [
          brand_payment_csv.get_brand_name(brand_instance),
          brand_payment_csv.get_brand_account(brand_instance),
          brand_payment_csv.get_ifsc_code(brand_instance),
          brand_payment_csv.get_brand_account_holder_name(brand_instance),
          brand_payment_csv.get_brand_email(brand_instance),
          brand_payment_csv.get_contact_number(brand_instance),
          brand_payment_csv.get_due_amount(brand_instance),
          brand_payment_csv.get_remarks(),
          brand_instance.id

      ]

    writer.writerow(row)

  return response

def export_csv_for_influencer_upi_payment(request):

  end_date = request.GET.get('end_date')
  if end_date is not None:
    if not TimeUtilities.validate_date(end_date):
      return HttpResponse("Invalid date")
    else:
      end_date = date_parser.parse(end_date)

  else:
    end_date = TimeUtilities.get_current_date(False)

  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="export.csv"'

  writer = csv.writer(response)
  influencer_payment_csv = InfluencerPaymentCsvContext(end_date)
  headers = influencer_payment_csv.get_headers_of_upi_payment_for_csv()
  writer.writerow(headers)

  store_filter = influencer_payment_csv.get_queryset()
  store_filter = store_filter.filter(metadata__payment_verified=True)

  for store_instance in store_filter:

    try:
      user = store_instance.get_store_authorized_users()[0]
      influencer = user.influencer.first()
    except Exception as e:
      continue

    if influencer is None or influencer.upi_ids.first() is None:
      continue
    
    row = [
          influencer_payment_csv.get_store_name(store_instance),
          influencer_payment_csv.get_upi_id(influencer),
          influencer_payment_csv.get_influencer_name(user),
          influencer_payment_csv.get_influencer_email(user),
          influencer_payment_csv.get_contact_number(user),
          influencer_payment_csv.get_due_amount(store_instance),
          influencer_payment_csv.get_remarks(),
          store_instance.id

      ]

    writer.writerow(row)

  return response


def export_csv_for_influencer_bank_payment(request):

  end_date = request.GET.get('end_date')
  if end_date is not None:
    if not TimeUtilities.validate_date(end_date):
      return HttpResponse("Invalid date")
    else:
      end_date = date_parser.parse(end_date)

  else:
    end_date = TimeUtilities.get_current_date(False)

  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="export.csv"'

  writer = csv.writer(response)
  influencer_payment_csv = InfluencerPaymentCsvContext(end_date)
  headers = influencer_payment_csv.get_headers_of_neft_payment_for_csv()
  writer.writerow(headers)

  store_filter = influencer_payment_csv.get_queryset()
  store_filter = store_filter.filter(metadata__payment_verified=True)

  for store_instance in store_filter:

    try:
      user = store_instance.get_store_authorized_users()[0]
      influencer = user.influencer.first()
    except Exception as e:
      continue

    if influencer is None or influencer.upi_ids.first() is not None or influencer.bank_accounts.first() is None:
      continue
    
    row = [
          influencer_payment_csv.get_store_name(store_instance),
          influencer_payment_csv.get_influencer_account(influencer),
          influencer_payment_csv.get_ifsc_code(influencer),
          influencer_payment_csv.get_bank_account_holder_name(influencer),
          influencer_payment_csv.get_influencer_email(user),
          influencer_payment_csv.get_contact_number(user),
          influencer_payment_csv.get_due_amount(store_instance),
          influencer_payment_csv.get_remarks(),
          store_instance.id

      ]

    writer.writerow(row)

  return response


def export_csv_for_store_gmv(request):

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="export.csv"'
    days = request.GET.get('days',7)
    
    writer = csv.writer(response)
    store_csv = StoreGMVCsvContext(days)
    headers = store_csv.get_headers_of_store_gmv_for_csv()
    writer.writerow(headers)

    store_filter = store_csv.get_queryset()
    
    store_ids = [StringUtilities.convert_number_to_string(store.id) for store in store_filter]
    store_visits = store_csv.get_store_visits(store_ids)
    
    for store_instance in store_filter:
        store_sourcing_requests_status_count = store_csv.get_store_sourcing_requests_status_count(store_instance)
        row = [
           store_csv.get_store_name(store_instance),
           store_csv.get_store_managers(store_instance),
           store_csv.get_last_product_added_timestamp(store_instance),
           store_csv.get_n_days_gmv(store_instance),
           store_csv.get_overall_gmv(store_instance),
           store_csv.get_n_days_gmv(store_instance, platform_code='IH'),
           store_csv.get_overall_gmv(store_instance, platform_code='IH'),
           store_csv.get_store_status(store_instance),
           store_csv.get_store_next_actions(store_instance),
           store_visits.get('visits_1_to_3_days').get(StringUtilities.convert_number_to_string(store_instance.id), 0),
           store_visits.get('visits_4_to_10_days').get(StringUtilities.convert_number_to_string(store_instance.id), 0),
           store_visits.get('visits_11_to_40_days').get(StringUtilities.convert_number_to_string(store_instance.id), 0),
           store_visits.get('visits_before_40_days').get(StringUtilities.convert_number_to_string(store_instance.id), 0),
           store_csv.get_total_sourcing_requests(store_instance),
           store_csv.get_count_of_brand_related_requests(store_instance),
           store_csv.get_count_of_zaamo_related_requests(store_instance),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.REQUEST_RECIEVED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.BRAND_SHARED_DELIVERABLES, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.BRAND_CONTACT_INFLUENCER, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.BRAND_COLLAB_APPROVED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.BRAND_COUPON_CREATED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.BRAND_NOT_INTERESTED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.ZAAMO_FULFILL_REQUEST, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.ZAAMO_COUPON_CREATED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.ZAAMO_NOT_INTERESTED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_ZAAMO, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_BRAND, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.PRODUCT_EXCHANGE_RETURN_REQUESTED, 0),
           store_sourcing_requests_status_count.get(SourcingRequestStatus.REQUEST_CANCELLED_INFLUENCER, 0),
           store_csv.get_brand_interested_in_influencer(store_instance),
           store_csv.get_instagram_link(store_instance),
           store_csv.get_store_barter(store_instance),
           store_csv.get_stop_source_with_zaamo(store_instance),
           store_csv.get_days_since_sign_up(store_instance),
           store_csv.get_user_last_login(store_instance)
        ]

        writer.writerow(row)
        

    return response

def send_csv_to_brand_owners_request(request):
  try:
    days = request.GET.get('days',1)
    store_id = request.GET.get('store_id')
    user_id = request.GET.get('user_id')
    days = NumberUtilities.convert_string_to_number(days)


    if user_id:
      user_id_list = [graphene.Node.from_global_id(user_id)[1]]

    if not user_id:

      if not store_id:
        return JsonResponse({'Success':False,'message':'Please add a valid store id'})

      store_id = graphene.Node.from_global_id(store_id)[1]

      user_ids = StoreMemberState.objects.filter(store_id=store_id).values('user_id')
      user_id_list = [user.get('user_id') for user in user_ids]

    from saleor.rest_apis.csv.tasks import send_csv_to_brand_owners_task
    send_csv_to_brand_owners_task.delay(user_id_list,days)

    return JsonResponse({'Success':True,'message':'Email will be sent shortly.'})
  
  except Exception as e:
    return JsonResponse({'Success':False,'message':'Invalid Params.'})

def send_csv_to_brand_owners(user_id_list,days,send_to_all_brand=False):
  '''
  TO send every saturday for last 15 days

  from saleor.rest_apis.csv.view_impl import send_csv_to_brand_owners
  send_csv_to_brand_owners([],15,send_to_all_brand=True)
  '''
  
  staff_brand_mappings = StaffBrandMapping.objects.filter(user_id__in=user_id_list).select_related('user','brand')
  super_user_check = User.objects.filter(id__in=user_id_list,is_superuser=True).exclude(id__in=staff_brand_mappings.values('user_id'))

  user_email_brand_dict = defaultdict(list)
  user_email_brand_id_dict = defaultdict(list)
  brand_status_dict = dict()
  
  for staff_mapping in staff_brand_mappings:
    brand_name = staff_mapping.brand.private_metadata.get('source_name')

    if not brand_name:
      brand_name = staff_mapping.brand.brand_name

    brand_status_dict[brand_name]=staff_mapping.brand.status
    user_email_brand_dict[staff_mapping.user.email].append(brand_name)
    user_email_brand_id_dict[staff_mapping.user.email].append(staff_mapping.brand_id)
  
  if super_user_check or send_to_all_brand:
    all_brands = Brand.objects.all().values('id','private_metadata__source_name','brand_name','status')
    user_email_brand_dict['zaamobrandupdates@zaamo.co'] = [brand.get('private_metadata__source_name') if brand.get('private_metadata__source_name') else brand.get('brand_name') for brand in all_brands]
    user_email_brand_id_dict['zaamobrandupdates@zaamo.co'] = [brand.get('id') for brand in all_brands]

    for brand_cur in all_brands:

      brand_name = brand_cur.get('private_metadata__source_name') if brand_cur.get('private_metadata__source_name') else brand_cur.get('brand_name')

      brand_status_dict[brand_name]=brand_cur.get('status')

  logger.info(f"total emails to be sent :: {len(user_email_brand_id_dict)}")

  failed_emails = []
  
  for owner_email,owner_brand_ids in user_email_brand_id_dict.items():
    try:
      m = MailImpl()

      price_drop_attachment = brand_owner_price_change_csv(user_email_brand_dict[owner_email],days,brand_status_dict)

      new_product_attachment = brand_owner_new_product_csv(user_email_brand_dict[owner_email],days,brand_status_dict)

      unpublish_product_attachment = brand_owner_unpublished_product_csv(user_email_brand_dict[owner_email],brand_status_dict)
      
      product_oos_attachment = brand_owner_product_oos_csv(owner_brand_ids)
      
      brand_list_attachment = BrandManagerCSVhelper.brand_owner_brand_list_csv(owner_brand_ids)

      brand_shopify_active_attachment = brand_shopify_active_csv(owner_brand_ids)

      brand_collections_attachment = brand_collections_list_csv(owner_brand_ids,days)

      brand_validation_attachment = brand_validation_csv(owner_brand_ids)

      brand_uncategorized_products_attachment = brand_uncategorized_products_csv(owner_brand_ids)

      brand_perc_discount_coupon_attachment,brand_fix_discount_coupon_attachment = brand_discount_coupon_csv(owner_brand_ids)
      
      brand_hotseller_attachment = m.get_csv_attachment_dict(filename=f'Hotseller_ON_brand_{TimeUtilities.get_current_date_time()}.csv', rows=brand_hotseller_csv(owner_brand_ids))

      attachments = [price_drop_attachment,new_product_attachment,product_oos_attachment,brand_shopify_active_attachment,
                    brand_list_attachment,brand_collections_attachment,brand_validation_attachment,brand_hotseller_attachment,
                    brand_uncategorized_products_attachment,brand_perc_discount_coupon_attachment,brand_fix_discount_coupon_attachment,unpublish_product_attachment]
      
      m.send_mail_with_attachment('brand_owner_csv',f'Hi, Please find the attached CSVs for your brand analytics.','Brand Analytics CSV',attachments,owner_email)
      logger.info(f"CSV Email Sent successfully for {owner_email}, with {len(attachments)} attachments.")

      if super_user_check or send_to_all_brand:
        owner_email='neeraj.singh@zaamo.co'
        m.send_mail_with_attachment('brand_owner_csv',f'Hi, Please find the attached CSVs for your brand analytics.','Brand Analytics CSV',attachments,owner_email)
        logger.info(f"CSV Email Sent successfully for {owner_email}, with {len(attachments)} attachments.")

    except Exception as e:
      failed_emails.append(owner_email)
      logger.exception(e)
      continue
  
  return failed_emails

def get_store_count_with_brand_and_category(brand_id=None,category_id=None, brand_name=None):

  if brand_name:
    store_count = (CollectionStore.objects.prefetch_related('collection__products').filter
                    (collection__products__in=Subquery(Product.objects.filter(
                      Q(brand__private_metadata__source_name=brand_name )).values('id'))).distinct('store_id').count())
  
  else:
    store_count = (CollectionStore.objects.prefetch_related('collection__products').filter(
                    collection__products__in=Subquery(Product.objects.filter(Q(brand_id=brand_id) |  
                    Q(category_id=category_id)).values('id'))).distinct('store_id').count())

  return store_count

def brand_owner_price_change_csv(brand_obj_list,days,brand_status_dict):
  time_utilities = TimeUtilities()
  days_to_check = time_utilities.convert_date_to_datetime(time_utilities.get_n_days_before_date(days))
  brand_price_records = BrandPriceRecord.objects.filter(brand_name__in=brand_obj_list,updated_at__gte = days_to_check)
  rows = []
  rows.append(BrandManagerCSVhelper.get_headers_for_brand_price_record())
  row_price_dict = list()
  mappings = BrandVariantZaamoMapping.objects.filter(product_id_brand__in=brand_price_records.values('product_id_brand')).values('product_id_brand','variant_id_brand','product_zaamo_id')
  mapping_tuple_dict = dict()

  product_zaamo_id_list = set()

  for mapping in mappings:
    mapping_tuple_dict[(mapping.get('product_id_brand'),mapping.get('variant_id_brand'))] = mapping.get('product_zaamo_id')
    product_zaamo_id_list.add(mapping.get('product_zaamo_id'))

  store_count_dict = create_store_count_dictionary(product_zaamo_id_list)
  products_for_category_brand = Product.objects.filter(id__in=product_zaamo_id_list).only('category_id','brand_id')
  category_product_id_dict = dict()

  for product in products_for_category_brand:
    category_product_id_dict[product.id] = (product.brand_id,product.category_id)
    
  store_relative_count_dict = dict()
  store_brand_count_dict = dict()

  for record in brand_price_records:
    price_drop = True if record.current_price_amount<record.prev_price_amount else False

    if not price_drop:
      continue

    drop_percentage = round(abs(record.current_price_amount-record.prev_price_amount)*100/record.prev_price_amount,2)
    product_zaamo_id = mapping_tuple_dict.get((record.product_id_brand, record.variant_id_brand))
    store_count = 0
    store_relative_count = 0

    if product_zaamo_id:

      brand_collection_tuple = category_product_id_dict.get(product_zaamo_id)
      store_count = store_count_dict.get(product_zaamo_id,0)

      if brand_collection_tuple:

        store_relative_count = store_relative_count_dict.get(brand_collection_tuple) or 0

        if not store_relative_count:
          store_relative_count = get_store_count_with_brand_and_category(brand_id=brand_collection_tuple[0],category_id=brand_collection_tuple[1])
          store_relative_count_dict[brand_collection_tuple] = store_relative_count
        
    else:
      
        store_relative_count = store_brand_count_dict.get(record.brand_name) or 0

        if not store_relative_count:
          store_relative_count = get_store_count_with_brand_and_category(brand_name=record.brand_name)
          store_brand_count_dict[record.brand_name] = store_relative_count

    row_price_dict.append([record.brand_name,record.product_name,record.variant_name,record.data_source,
                  record.current_price_amount,record.prev_price_amount,drop_percentage,record.updated_at,store_count,store_relative_count,brand_status_dict.get(record.brand_name)])

  # sorted_row_dict = {k: row_price_dict[k] for k in sorted(row_price_dict,reverse=True)}
  
  sorted_data = sorted(row_price_dict,key=lambda row: (row[10], -row[6]))
  
  rows.extend(sorted_data)

  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"price_record_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json

def brand_owner_unpublished_product_csv(brand_obj_list,brand_status_dict):
    rows = []
    exported_rows = []
    exported_rows.append(BrandManagerCSVhelper.get_headers_for_unpublish_product_csv())

    mappings = BrandVariantZaamoMapping.objects.all().select_related('product_zaamo')
    published_dict = dict()

    orderbrand = BrandOrderCount.objects.all()
    mongo_conn = MongoConn()

    brandordercount = defaultdict(int)
    brandordercount_monthly = defaultdict(int)

    for order in orderbrand:
        brandordercount[(order.brand_name,order.product_id_brand,order.variant_id_brand)]+=order.brand_order_count
        brandordercount_monthly[(order.brand_name,order.product_id_brand,order.variant_id_brand)]+=order.brand_order_count_last_month

    for mapping in mappings:
        published_dict[(mapping.product_id_brand,mapping.variant_id_brand)] = mapping.product_zaamo.is_published


    for brand_name in brand_obj_list:
        
        data = mongo_conn.fetch_one_gridfs({'filename':f'{brand_name}_mapped'})
        
        mapped_product_data = []

        if data:
            product_data = json.loads(data.read())
            mapped_product_data = product_data.get('mapped_product_data',[])

        for mapped_product in mapped_product_data:
            
            if not mapped_product:
                continue
            
            created_at = mapped_product.get('product.created_at')
            
            product_id_brand = mapped_product["product.brand_variant_zaamomapping"]["product_id_brand"]
            product_id_brand = StringUtilities.convert_object_to_string(product_id_brand)

            brand_order_count_total = brandordercount[(brand_name,product_id_brand,None)]
            brand_order_count_month_total = brandordercount_monthly[(brand_name,product_id_brand,None)]
            variants = mapped_product["product.productvariant"]
            
            for variant in variants:
                variant_id_brand = variant["fields"]["variant_id_brand"]
                variant_id_brand = StringUtilities.convert_object_to_string(variant_id_brand)
                    
                ispublished = published_dict.get((product_id_brand,variant_id_brand))
                source = True
                brand_order_count_total+=brandordercount[(brand_name,product_id_brand,variant_id_brand)]
                brand_order_count_month_total+=brandordercount_monthly[(brand_name,product_id_brand,variant_id_brand)]

                if ispublished:
                  break

                if ispublished==None:
                    source = False
                    ispublished=False

            if not ispublished and brand_order_count_month_total>0:
                rows.append([brand_name,mapped_product["product.product"]["fields"]["name"],
                                source,brand_order_count_total,brand_order_count_month_total,created_at,brand_status_dict.get(brand_name)])
    
    rows = sorted(rows, key=lambda row: row[4], reverse=True)
    exported_rows.extend(rows)
    f = StringIO() 
    csv.writer(f).writerows(exported_rows)
    base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
    attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"unpublished_product_{TimeUtilities.get_current_date_time()}",base_encoded_file)

    return attachment_json              

def brand_owner_new_product_csv(brand_obj_list,days,brand_status_dict):
  time_utilities = TimeUtilities()
  rows = []
  rows.append(BrandManagerCSVhelper.get_headers_for_new_product_csv())

  yesterday_date = time_utilities.get_n_days_before_date(days)
  yesterday_date = time_utilities.convert_date_to_datetime(yesterday_date)
  mappings = BrandVariantZaamoMapping.objects.filter(brand_name__in=brand_obj_list).select_related('product_zaamo')
  published_dict = dict()
  collection_brand_product_dict = dict()

  for mapping in mappings:
    published_dict[(mapping.product_id_brand,mapping.variant_id_brand)] = mapping.product_zaamo.is_published
    collection_brand_product_dict[(mapping.product_id_brand,mapping.variant_id_brand)] = (mapping.product_zaamo.brand_id,mapping.product_zaamo.category_id)

  store_relative_count_dict = dict()
  store_brand_count_dict = dict()
  
  mongo_conn = MongoConn()

  for brand_name in brand_obj_list:
    data = mongo_conn.fetch_one_gridfs({'filename':f'{brand_name}_mapped'})
    mapped_product_data = []

    if data:
      product_data = json.loads(data.read())
      mapped_product_data = product_data.get('mapped_product_data',[])

    for mapped_product in mapped_product_data:

      if not mapped_product:
        continue
      created_at = mapped_product.get('product.created_at')

      if not created_at:
        continue
      
      created_at = TimeUtilities.convert_string_to_datetime(created_at)
      
      if not created_at:
        continue
      
      if created_at<yesterday_date:
        continue
      
      product_id_brand = mapped_product["product.brand_variant_zaamomapping"]["product_id_brand"]
      product_id_brand = StringUtilities.convert_object_to_string(product_id_brand)
      variants = mapped_product["product.productvariant"]
      
      for variant in variants:
        variant_id_brand = variant["fields"]["variant_id_brand"]
        variant_id_brand = StringUtilities.convert_object_to_string(variant_id_brand)
        store_relative_count = 0
        brand_collection_tuple = collection_brand_product_dict.get((product_id_brand,variant_id_brand))

        if brand_collection_tuple:
          store_relative_count = store_relative_count_dict.get(brand_collection_tuple) or 0

          if not store_relative_count:
            store_relative_count = get_store_count_with_brand_and_category(brand_collection_tuple[0],brand_collection_tuple[1])
            store_relative_count_dict[brand_collection_tuple] = store_relative_count

        else:
          store_relative_count = store_brand_count_dict.get(brand_name) or 0

          if not store_relative_count:
            store_relative_count = get_store_count_with_brand_and_category(brand_name=brand_name)
            store_brand_count_dict[brand_name] = store_relative_count
            
        ispublished = published_dict.get((product_id_brand,variant_id_brand))
        source = 'postgres'

        if ispublished==None:
          source = 'mongo'
          ispublished=False

        rows.append([brand_name,mapped_product["product.product"]["fields"]["name"],variant["fields"]["name"],source,
                  variant["fields"]["price_amount"],variant["fields"]["cost_price_amount"],ispublished,variant["stock"]["quantity"],store_relative_count,brand_status_dict.get(brand_name)])
  
  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"new_product_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json

def brand_owner_product_oos_csv(brand_obj_list):
  product_variants = ProductVariant.objects.filter(product__brand_id__in=brand_obj_list,track_inventory=True,product__is_published=True)
  oos_variants = Stock.objects.filter(product_variant_id__in = product_variants.values('id'),quantity=0).select_related('product_variant')
  all_variant_count_dict = defaultdict(int)
  
  for variant in product_variants:
    all_variant_count_dict[variant.product_id]+=1

  oos_variants_count_dict = defaultdict(int)
  oos_stock_updated_dict = dict()

  for stock in oos_variants:
    oos_variants_count_dict[stock.product_variant.product_id]+=1

    last_updated = stock.updated_at

    if oos_stock_updated_dict.get(stock.product_variant.product_id) and oos_stock_updated_dict.get(stock.product_variant.product_id)>last_updated:
      continue
    
    oos_stock_updated_dict[stock.product_variant.product_id]=stock.updated_at

  rows = []
  rows.append(BrandManagerCSVhelper.get_headers_for_oos_product_csv())

  product_with_oos = []

  for p_id,number in oos_variants_count_dict.items():

    if all_variant_count_dict[p_id] == number:
      product_with_oos.append(p_id)

  oos_products = Product.objects.filter(id__in=product_with_oos).select_related('brand')

  for product in oos_products:
    
    last_updated = oos_stock_updated_dict.get(product.id)

    rows.append([product.brand.brand_name,product.name,product.minimal_variant_price_amount,product.is_published,product.publication_date,last_updated,product.brand.status])

  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"product_out_of_stock_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json

def shopify_validation_check(brand):

    brand_cred = BrandCred.objects.filter(brand_id=brand.id).first()

    invalid = False
    write_orders = False

    if not brand_cred:
      return invalid, write_orders

    try:
      pas = get_decoded_string(brand_cred.access_pass)
      api = ApiClient(host=brand_cred.url,path='admin/oauth/access_scopes.json')
      api.headers = {'X-Shopify-Access-Token':pas}
      api.get(send_body=False)
      res = api.fetch_response()

      access = []
      
      if res:
      
        invalid=True
        
        ac = res['access_scopes']

        for j in ac:
        
            access.append(j['handle'])
        
        if 'write_orders' in access:
            write_orders=True

      return invalid, write_orders
    
    except Exception as e:
      return invalid, write_orders
      
        

def woocommerce_validation_check(brand):
  
  last_sixty_day_time = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=60)
  last_sixty_day_orders = OrderBrandZaamoMapping.objects.filter(brand_id=brand.id, created_at__gte=last_sixty_day_time)
  brand_cred = BrandCred.objects.filter(brand_id=brand.id).first()
  invalid = False
  write_orders = False

  if not brand_cred:
    return invalid, write_orders
    
  try:

    pas = get_decoded_string(brand_cred.access_pass)
    key = get_decoded_string(brand_cred.access_key)
    url = brand_cred.url
    url = url.replace('http://','')
    url = url.replace('https://','')

    if '/' in url:
        url = url[:url.index('/')]
    
    api = ApiClient(host=url,path='wp-json/wc/v3/products')
    api.params = {'consumer_key':key,'consumer_secret':pas}

    api.get(send_body=False,verify=False)
    res = api.fetch_response()

    if res:
        invalid=True
    
    if last_sixty_day_orders:
      write_orders=True
      
    return invalid,write_orders

  except Exception as e:

    return invalid,write_orders

def brand_validation_csv(brand_obj_list):
  rows = []
  rows.append(BrandManagerCSVhelper.get_headers_for_brand_validation_csv())
  
  brands = Brand.objects.filter(id__in=brand_obj_list)
  
  order_30_days_count = OrderLine.objects.filter(created_at__gte=TimeUtilities.get_n_days_before_date(30),brand_id__in=brand_obj_list).exclude(metadata__fake='true',metadata__fake__isnull=False).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))

  order_30_days_count_dict = {order_c['brand_id']:order_c['order_counts'] for order_c in order_30_days_count}

  order_overall_count = OrderLine.objects.filter(brand_id__in=brand_obj_list).exclude(metadata__fake='true',metadata__fake__isnull=False).values('brand_id').order_by('brand_id').annotate(order_counts=Count('order_id',distinct=True))

  order_overall_count_dict = {order_c['brand_id']:order_c['order_counts'] for order_c in order_overall_count}

  brand_order_weekly_count = BrandOrderCount.objects.filter(brand_name__in=list(brands.values_list('private_metadata__source_name',flat=True))).values('brand_name').order_by('brand_name').annotate(order_counts=Sum('brand_order_count_last_week'))

  brand_order_weekly_count_dict = {order_c['brand_name']:order_c['order_counts'] for order_c in brand_order_weekly_count}

  export_rows = []
  
  for brand in brands:
    
    brand_name = brand.private_metadata.get('source_name')

    if not brand_name:
      brand_name = brand.brand_name
    
    valid = False
    write_orders = False

    if brand.brand_source=='shopify':
      valid,write_orders = shopify_validation_check(brand)

    elif brand.brand_source=='woocommerce':
      valid,write_orders = woocommerce_validation_check(brand)
    
    else:
      continue
    
    if not valid or not write_orders:
      export_rows.append(
        [
          brand_name,
          brand.brand_source,
          valid,
          write_orders,
          order_30_days_count_dict.get(brand.id) or 0,
          brand.status,
          order_overall_count_dict.get(brand.id) or 0,
          brand_order_weekly_count_dict.get(brand_name) or 0,
          brand.history_notes
        ])
      
  
  export_rows = sorted(export_rows, key=lambda row: row[4], reverse=True)
  rows.extend(export_rows)

  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"brand_validation_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json

def brand_uncategorized_products_csv(brand_obj_list):
  rows = []
  rows.append(BrandManagerCSVhelper.get_headers_for_brand_uncategorized_csv())
  uncategorized_products = Product.objects.filter(brand_id__in=brand_obj_list, category__name__contains='uncategorized',is_published=True).select_related('brand','category')

  for product in uncategorized_products:

    rows.append(
      [
        product.name,
        product.brand.brand_name,
        product.brand.brand_source,
        product.category.name,
        product.publication_date,
        product.brand.status
      ])
      
  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"uncategorized_products_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json

def fetch_discount_from_shopify(brand_cred):
  
  rows = []
  shopify_inst = ShopifyImpl()
  
  try:
    collection_name_ids = shopify_inst.fetch_collection_name_id_from_brand_cred(brand_cred)
    price_rules = shopify_inst.fetch_last_7_days_price_rules_from_brand_cred(brand_cred)
    
    brand_name = brand_cred.brand.brand_name
    brand_source = brand_cred.brand.brand_source
    brand_name_private = brand_cred.brand.private_metadata.get('source_name')

    product_data = shopify_inst.fetch_product_data_from_shopify_store_by_name(brand_name_private)

    if product_data and isinstance(product_data,str):
      product_data = json.loads(product_data)
        
    if not product_data:
      product_data = shopify_inst.fetch_product_data_from_gridfs_by_name(brand_name_private)
      
    for rule in price_rules:
      product_ids = rule.entitled_product_ids
      collection_names = []

      if not product_ids:
        collection_ids = rule.entitled_collection_ids

        if collection_ids:
          
          for id in collection_ids:

            if not collection_name_ids.get(id):
              continue

            collection_names.append(collection_name_ids.get(id))

      
      product_names = []
  
      for product in product_data:

        if product.get('id') in product_ids or set(product.get('collections',[])).intersection(collection_names):
          product_names.append(product.get('title'))

      if not product_names:
        product_names = ["All Products"]
      
      rows.append([brand_name,brand_source,rule.title,rule.value,
                    rule.value_type,False,rule.minimum_order_amount if hasattr(rule, 'minimum_order_amount') else 0,
                    ', '.join(product_names),
                    rule.starts_at,rule.ends_at, 1 if hasattr(rule, 'once_per_customer') else 0,
                    rule.usage_limit or 'No Limit'])
      
    return rows

  except Exception:
    return rows

def fetch_discount_from_woocommerce(brand_cred):
  rows = []
  woo_inst = WooCommerceImpl()

  try:
      
    brand_name = brand_cred.brand.brand_name
    brand_name_private = brand_cred.brand.private_metadata.get('source_name')

    product_data = woo_inst.fetch_product_data_from_woo_commerce_store_by_name(brand_name_private)
    product_data = woo_inst.get_value_by_key(product_data,'product_data')

    if product_data and isinstance(product_data,str):
      product_data = json.loads(product_data)
        
    if not product_data:
      product_data = woo_inst.fetch_product_data_from_gridfs_by_name(brand_name_private)

    category_name_dict = defaultdict(list)
    product_name_dict = dict()

    for product in product_data:
      product_name_dict[product.get('id')]=product.get('name')
      categories = product.get('categories') or []
      
      for category in categories:
        category_name_dict[category['id']].append(product.get('name'))

    pas = get_decoded_string(brand_cred.access_pass)
    key = get_decoded_string(brand_cred.access_key)
    url = brand_cred.url

    url = url.replace('http://','')

    url = url.replace('https://','')

    if '/' in url:
      url = url[:url.index('/')]

    api = ApiClient(host=url,path='wp-json/wc/v3/coupons')

    api.params = {'consumer_key':key,'consumer_secret':pas}

    api.add_url_param('per_page',100)
    api.add_url_param('after',TimeUtilities.convert_date_to_datetime(TimeUtilities.get_n_days_before_date(7)))
    api.get(send_body=False,verify=False)

    res = api.fetch_response()

    if res:

      for j in res:
        product_ids = j.get('product_ids',[])
        category_ids = j.get('product_categories',[])
        
        product_names = []

        for id in product_ids:

          if product_name_dict.get(id):
          
            product_names.append(product_name_dict.get(id))
        
        
        for id in category_ids:

          if category_name_dict.get(id):
          
            product_names.extend(category_name_dict.get(id))

        if not product_names:
          product_names = ["All Products"]

        rows.append([brand_name,'woocommerce',
                    j.get('code'),j.get('amount'),j.get('discount_type'), 
                    j.get('free_shipping'),
                    j.get('minimum_amount'),
                    ', '.join(product_names),
                    j.get('date_created'),j.get('date_expires'),
                    j.get('usage_limit_per_user') or 'No Limit',
                    j.get('usage_limit') or 'No Limit'])
    return rows

  except Exception as e:
    return rows

def fetch_discount_from_wix(brand_cred):
  rows =[]
  try:
    wix_impl_inst = WixImpl()
    wix_impl_inst.set_instance_id(get_decoded_string(brand_cred.access_key))
    wix_impl_inst.set_refresh_token(get_decoded_string(brand_cred.access_pass))
    rows = wix_impl_inst.fetch_discount_list(brand_cred)
    return rows
  
  except Exception as e:
    logger.exception(e)
    return rows

def distribute_rows_by_value_type(rows):
    perc_row, fix_amount_row = [],[]

    for row in rows:
      if 'percent' in row[4].lower():
        row[3] = abs(NumberUtilities.convert_string_to_float(row[3]))
        perc_row.append(row)
      
      else:
        fix_amount_row.append(row)

    return perc_row, fix_amount_row

def brand_discount_coupon_csv(brand_obj_list):
  percentage_rows = []
  fixed_amount_rows = []
  sorted_percentage_rows = []
  sorted_fixed_amount_rows = []
  
  sorted_percentage_rows.append(BrandManagerCSVhelper.get_headers_for_brand_discount_coupon_csv())
  sorted_fixed_amount_rows.append(BrandManagerCSVhelper.get_headers_for_brand_discount_coupon_csv())

  brand_creds = BrandCred.objects.filter(brand_id__in=brand_obj_list).select_related('brand')

  for brand_cred in brand_creds:
    row = []
    if brand_cred.brand.brand_source=='shopify':
      row = fetch_discount_from_shopify(brand_cred)
    
    if brand_cred.brand.brand_source=='woocommerce':
      row = fetch_discount_from_woocommerce(brand_cred)

    if brand_cred.brand.brand_source=='wix':
      row = fetch_discount_from_wix(brand_cred)

    if not row:
      continue

    perc_row, fix_amount_row = distribute_rows_by_value_type(row)
    percentage_rows.extend(perc_row)
    fixed_amount_rows.extend(fix_amount_row)
  
  percentage_row_dict = defaultdict(list)
  fixed_row_dict = defaultdict(list)

  for data in percentage_rows:
    percentage_row_dict[data[3]].append(data)
  
  for data in fixed_amount_rows:
    fixed_row_dict[data[3]].append(data)

  sorted_percentage_row_dict = {k: percentage_row_dict[k] for k in sorted(percentage_row_dict,reverse=True)}
  sorted_fixed_row_dict = {k: fixed_row_dict[k] for k in sorted(fixed_row_dict,reverse=True)}
  
  for row in sorted_percentage_row_dict.values():
    sorted_percentage_rows.extend(row)
    
  for row in sorted_fixed_row_dict.values():
    sorted_fixed_amount_rows.extend(row)
  
  f = StringIO() 

  csv.writer(f).writerows(sorted_percentage_rows)
  base_encoded_file1 = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json_1 = BrandManagerCSVhelper.create_attachment_dict_for_email(f"brand_percentage_discount_{TimeUtilities.get_current_date_time()}",base_encoded_file1)
  
  h = StringIO() 

  csv.writer(h).writerows(sorted_fixed_amount_rows)
  base_encoded_file2 = base64.b64encode(h.getvalue().encode()).decode()
  attachment_json_2 = BrandManagerCSVhelper.create_attachment_dict_for_email(f"brand_fixed_discount_{TimeUtilities.get_current_date_time()}",base_encoded_file2)
  
  return attachment_json_1,attachment_json_2

def brand_hotseller_csv(brand_ids):
  brands_qs = Brand.objects.all().filter(status__in=[BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER])
  brand_qs = brands_qs.values('id', 'brand_name', 'status', 'importance')
  brands = {brand['id']: brand for brand in brand_qs}
  bvzm_qs = BrandVariantZaamoMapping.objects.filter(brand_zaamo_id__in=brands_qs.values('id'))
  brand_count_insts = BrandOrderCount.objects.filter(brand_name__in=list(brands_qs.values_list('private_metadata__source_name',flat=True))).exclude(Q(product_id_brand__in=bvzm_qs.values('product_id_brand')))

  order_count_dict_weekly = defaultdict(int)
  order_count_dict = defaultdict(int)

  for inst in brand_count_insts:
      order_count_dict_weekly[(inst.brand_name,inst.product_id_brand,inst.variant_id_brand)] += inst.brand_order_count_last_week
      order_count_dict[(inst.brand_name,inst.product_id_brand,inst.variant_id_brand)] += inst.brand_order_count
      

  products = Product.objects.filter(brand_id__in=list(brands.keys())).filter(is_published=False).filter(metadata__brand_order_count_weekly__gte=2)\
    .values('id', 'brand_id', 'metadata__brand_order_count', 'metadata__brand_order_count_weekly', 'name', 'is_published', 'default_variant__cost_price_amount', 'default_variant__price_amount')
  
  product_published = Product.objects.filter(brand_id__in=list(brands.keys())).filter(is_published=True).values('name')
  product_published_dict = {prod.get('name'):True for prod in product_published}

  header = ['brand name', 'product name', 'in zaamo', 'brand status', 'brand importance', 'weekly order count', 'total order count', 'mrp', 'msp']
  rows = []
  for product in products:
    brand = brands.get(product['brand_id'])

    if product_published_dict.get(product.get('name')):
      continue

    row = [
      brand.get('brand_name'),
      product.get('name'),
      True,
      brand.get('status'),
      brand.get('importance'),
      product.get('metadata__brand_order_count_weekly'),
      product.get('metadata__brand_order_count'),
      product.get('default_variant__cost_price_amount'),
      product.get('default_variant__price_amount')
    ]
    rows.append(row)

  mongo_conn = MongoConn()

  for brand_name in list(brands_qs.values_list('private_metadata__source_name',flat=True)):
    
    data = mongo_conn.fetch_one_gridfs({'filename':f'{brand_name}_mapped'})
    mapped_product_data = []

    if data:
      product_data = json.loads(data.read())
      mapped_product_data = product_data.get('mapped_product_data',[])

    for mapped_product in mapped_product_data:

      try:
        if not mapped_product:
          continue
        product_id_brand = mapped_product["product.brand_variant_zaamomapping"]["product_id_brand"]
        product_id_brand = StringUtilities.convert_object_to_string(product_id_brand)
        product_name = mapped_product['product.product']["fields"]["name"]
        variants = mapped_product["product.productvariant"]
        brand_order_count = order_count_dict[(brand_name,product_id_brand,None)]
        brand_order_count_weekly = order_count_dict_weekly[(brand_name,product_id_brand,None)]
        
        if product_published_dict.get(product_name):
          continue

        for variant in variants:
          variant_id_brand = variant["fields"]["variant_id_brand"]
          variant_id_brand = StringUtilities.convert_object_to_string(variant_id_brand)
          brand_order_count_weekly += order_count_dict_weekly[(brand_name,product_id_brand,variant_id_brand)]
          brand_order_count += order_count_dict[(brand_name,product_id_brand,variant_id_brand)]

        msp = variant["fields"]["price_amount"]
        mrp = variant["fields"]["cost_price_amount"]

        if brand_order_count_weekly>2:
            
          brand_id = mapped_product.get('brand.brand')
          
          if not brand_id:
            continue
          
          brand = brands.get(NumberUtilities.convert_string_to_number(brand_id))
          
          row = [
            brand.get('brand_name'),
            product_name,
            False,
            brand.get('status'),
            brand.get('importance'),
            brand_order_count_weekly,
            brand_order_count,
            mrp,
            msp
          ]
          rows.append(row)
      except: continue
  
  rows.sort(key=lambda x: x[5], reverse=True)
  rows = [header] + rows
  return rows



def brand_shopify_active_csv(brand_obj_list):
  
  exportrows = []
  exportrows.append(BrandManagerCSVhelper.get_headers_for_brand_shopify_active_csv())
  brands = Brand.objects.filter(id__in=brand_obj_list)

  brands_with_shopify_active_product = list(ZaamoShopifyProductMapping.objects.filter(status='active',product_zaamo__brand_id__in=brand_obj_list).order_by('product_zaamo__brand_id').values_list('product_zaamo__brand_id',flat=True).distinct())

  for brand in brands:
    
    brand_name = brand.private_metadata.get('source_name')

    if not brand_name:
      brand_name = brand.brand_name

    if brand.id in brands_with_shopify_active_product and not brand.cod:

      is_shopify_active = True  
      exportrows.append(
        [
          brand_name, 
          brand.status,
          brand.cod,
          is_shopify_active,
          brand.brand_source
        ])
      
    else: 
      continue

  f = StringIO() 
  csv.writer(f).writerows(exportrows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"brand_shopify_active_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json

def brand_collections_list_csv(brand_obj_list,days):
  rows = []
  rows.append(BrandManagerCSVhelper.get_headers_for_brand_collection_csv())
  time_utilities = TimeUtilities()
  days_to_check = time_utilities.convert_date_to_datetime(time_utilities.get_n_days_before_date(days))
  brand_collections = BrandCollection.objects.filter(brand_id__in=brand_obj_list,updated_at__gte=days_to_check).select_related('brand').annotate(product_count=Count('product'))

  for brand_collection in brand_collections:
    
    brand_name = brand_collection.brand.private_metadata.get('source_name')

    if not brand_name:
      brand_name = brand_collection.brand.brand_name
      
    brand_id_global = graphene.Node.to_global_id('Brand',brand_collection.brand_id)
    brand_collections_id_global = graphene.Node.to_global_id('BrandCollection',brand_collection.id)
    rows.append(
      [
        brand_name,
        brand_collection.name,
        brand_collection.product_count,
        brand_collection.brand.status,
        brand_collection.type,
        brand_collection.created_at,
        brand_collection.updated_at,
        f"https://zaamo.co/zaamo/explore-brands/{brand_id_global}/{brand_collections_id_global}"
       ])
  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"brand_collections_{TimeUtilities.get_current_date_time()}",base_encoded_file)

  return attachment_json


def send_all_collections_dump_csv_data():
  collections_email = "allcollections@zaamo.co"
  sql_query = """
    select
    product_collectionStore.store_id,
    store_storeinfo.store_name,
    store_storeinfo.store_url,
    store_StoreManagerActions.status,
    store_storeinfo.created_at as store_creation_date,
    product_collection.id as collection_id,
    product_collection.name as collection_name,
    product_collection.is_default,
    product_collection.metadata as collection_info,
    product_collection.image_url,
    product_collection.created_at as collection_created_date,
    product_collection.updated_at as last_modified_date,
    CONCAT('https://production.zaamo.co/admin/product/collection/', product_collection.id, '/change/') as collection_admin_link,
    CONCAT('https://home.zaamo.co/collection/', product_collection.slug) as collection_link,
    case
    when product_collection.metadata->>'landing' = 'true' then 'true'
    else 'false'
    end
    as on_zaamo_page,
    case
    when product_collection.metadata->>'steal_deal' = 'true' then 'true'
    else 'false'
    end
    as is_steal_deal,
    ideas,
    productcollectiongroup.product_count,
    productcollectiongrouplive.product_count as total_live_products_count_published_brand_active,
    product_collection.shop_look,
    productcollectionstealgroup.product_count as steal_deal_products
    from product_collectionStore
    inner join store_storeinfo on product_collectionStore.store_id=store_storeinfo.id
    inner join product_collection on product_collectionStore.collection_id = product_collection.id
    inner join store_StoreManagerActions on store_storeinfo.id = store_StoreManagerActions.store_id
    left join (select collection_id, count(*) as product_count from product_collectionproduct 
    where product_id in (select id from product_product where is_published = true) 
    group by collection_id) as productcollectiongroup
    on productcollectiongroup.collection_id=product_collection.id
	left join (select collection_id, count(*) as product_count from product_collectionproduct 
    where product_id in (select id from product_product where is_published = true and brand_id in
    (select id from brand_brand where status in ('active','active only for barter'))) 
    group by collection_id) as productcollectiongrouplive
    on productcollectiongrouplive.collection_id=product_collection.id
    left join (select collection_id, count(*) as product_count from product_collectionproduct 
    where product_id in (select id from product_product where is_published = true and metadata->>'value_deal'='true') 
    group by collection_id) as productcollectionstealgroup
    on productcollectionstealgroup.collection_id=product_collection.id
    order by product_collection.updated_at desc
  """
  query_result = RawSQLUtilities.run_raw_sql_quries(sql_query)

  all_collections_attachments = all_collections_csv(query_result)
  attachments = [all_collections_attachments]
  
  try:
    m = MailImpl()   
    m.send_mail_with_attachment('all_collections_csv',f'Hi, Please find the attached CSV of All Collections.','All Collections CSV',attachments)
    logger.info(f"CSV Email Sent successfully to {collections_email}, with All Collections CSV attachment.")
  
  except Exception as e:
    logger.exception(e)

def send_recent_checkout_csv_data():
  time_utilities = TimeUtilities()
  yesterday_date = time_utilities.get_yesterdays_date()
  checkout_details = Checkout.objects.filter(last_change__gte=yesterday_date, user_id__isnull=False, lines__isnull=False).select_related('user','shipping_address').prefetch_related('lines','lines__variant','lines__variant__product')
  attachment = structure_rows_for_checkout_details(checkout_details)
  attachments = [attachment]
  
  try:
    m = MailImpl()   
    m.send_mail_with_attachment('recent_checkout_csv',f"Hi, Please find the attached CSV of yesterday's checkout initiation.","Yesterday's Checkout Details",attachments)
    logger.info(f"CSV Email Sent successfully to zaamobrandupdates@zaamo.co, with yesterday's checkout CSV attachment.")
  
  except Exception as e:
    logger.exception(e)


def structure_rows_for_checkout_details(checkout_details):
  rows = defaultdict(list)

  for result in checkout_details:
    lines = result.lines.all()

    total_cart_value = calculations.checkout_total(
                    checkout=result, lines=result.lines.all()
                ).net.amount
    
    if result.email=='guest@zaamo.co':
      continue
      
    products = lines.values_list('variant__product__name',flat=True)
    name = ''
    mobile_no = ''
    user_id = ''
    platform = result.app_code + ' APP' if result.app_code else result.platform_code

    if result.user:
      mobile_no = result.user.mobile_no
      user_id = result.user_id

    address_obj = result.shipping_address or result.billing_address
    address = ''
    
    if address_obj:
      
      name = (address_obj.first_name or '') + (address_obj.last_name or '')
      address = (address_obj.street_address_1 or '') + (address_obj.city or '') + (address_obj.country_area or '')

    rows[total_cart_value].append(
      [
      user_id,platform,name,result.email,mobile_no,address,total_cart_value,result.discount_amount,', '.join(products)
      ])
    
  sorted_row_dict = {k: rows[k] for k in sorted(rows,reverse=True)}
  
  exportrows = [['user id','platform','customer_name','email','contact','address','total_cart_value','discount','product_details']]
  
  for row in sorted_row_dict.values():
    exportrows.extend(row)

  f = StringIO() 
  csv.writer(f).writerows(exportrows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"Checkout_yesterday_{TimeUtilities.get_current_date_time()}",base_encoded_file)
  
  return attachment_json

def all_collections_csv(query_result):
  rows = []
  rows.append(AllCollectionsDumpCSVContext.get_headers_for_all_collections_dump())

  for result in query_result:
    rows.append(
      [
        result['store_id'],
        result['store_name'],
        result['store_url'],
        result['status'],
        result['store_creation_date'],
        result['collection_id'],
        result['collection_name'],
        result['is_default'],
        result['collection_info'],
        result['image_url'], 
        result['collection_admin_link'],
        result['collection_link'],
        result['on_zaamo_page'],
        result['is_steal_deal'],
        result['ideas'],
        result['collection_created_date'],
        result['last_modified_date'],
        result.get('product_count') or 0,
        result.get('total_live_products_count_published_brand_active') or 0,
        result['shop_look'],
        result.get('steal_deal_products') or 0,

       ])
  
  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"all_collections_{TimeUtilities.get_current_date_time()}",base_encoded_file)
  
  return attachment_json


def export_csv_for_brand_dashboard(request):
  
  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="export.csv"'
  brand_id = request.GET.get('brand_id')
  
  if request.GET.get('brand_id'):
    brand_id = graphene.Node.from_global_id(request.GET.get('brand_id'))[1]
  
  writer = csv.writer(response)
  brand_dashboard_csv = BrandDashboardCsvContext(brand_id)
  headers = brand_dashboard_csv.get_headers_of_brand_dashboard_for_csv()
  writer.writerow(headers)

  queryset = brand_dashboard_csv.get_queryset()
  queryset = queryset.order_by('-created_at').values_list(
    'pk', 'status', 'store__store_members__user__influencer__instagram_username',
    'brand_collab', 'store__metadata__store_barter','recommended', 'product__name', 'variant__name', 'variant__price_amount',
    'created_at', 'content', 'product_url')
  
  export_requests_status_list = []
  export_requests_status_list.append(SourcingRequestStatus.ZAAMO_FULFILL_REQUEST)
  export_requests_status_list.append(SourcingRequestStatus.ZAAMO_COUPON_CREATED)
  export_requests_status_list.append(SourcingRequestStatus.INFLUENCER_CONTENT_CREATED_FOR_ZAAMO)
  export_requests_status_list.append(SourcingRequestStatus.BRAND_NOT_INTERESTED)
  export_requests_status_list.append(SourcingRequestStatus.ZAAMO_NOT_INTERESTED)
  export_requests_status_list.append(SourcingRequestStatus.BRAND_CONTACT_INFLUENCER)
  export_requests_status_list.append(SourcingRequestStatus.REQUEST_CANCELLED_INFLUENCER)

  for row in queryset:
    row = list(row)
    if row[2]:
      row[2] = 'https://www.instagram.com/' + row[2]
    
    if row[9]:
      row[9] = row[9].date()
    
    if row[4] is not None:
      if row[4]:
        row[4] = "Available"
      else:
        row[4] = "Busy"
    else:
      row[4] = "Available"

    if row[5]:
      row[5] = "recommended"
    else:
      row[5] = ""
    
    if(row[1] in export_requests_status_list):
      continue
    else:
      writer.writerow(row)

  return response

def export_csv_for_brand_ledger(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    brand_id = request.GET.get('brand_id')
    send_to_brand = request.GET.get('send_to_brand', '')
    brand_email = request.GET.get('brand_email')
        
    if brand_id:
        brand_id = graphene.Node.from_global_id(brand_id)[1]
        
    if send_to_brand.lower() == 'true':
      send_email_brand_ledger.delay([brand_id], brand_email)
      return HttpResponse(f"Email sent to {brand_email or 'brand'}")
    
    brand_ledger = BrandLedgerXLSX([brand_id], start_date, end_date)
    ledger = brand_ledger.get_ledger()
    response = HttpResponse(ledger, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = "attachment; filename=brand_ledger.xlsx"
    
    return response


def export_csv_for_brand_list(request):
            
    download = request.GET.get('download')
    email = request.GET.get('email', 'rachit@zaamo.co')

    brand_ids = Brand.objects.all().values_list('id', flat=True)
    
    if download == 'true':
      rows = BrandManagerCSVhelper.brand_owner_brand_list_csv(brand_ids, return_rows=True)
      filename = f"brand_list_{TimeUtilities.get_current_date_time()}.csv"
      response = HttpResponse(content_type='text/csv')
      response['Content-Disposition'] = f"attachment; filename={filename}"
      
      writer = csv.writer(response)
      writer.writerows(rows)

      return response

    else:
      BrandManagerCSVhelper.send_brand_list_csv_to_email.delay(list(brand_ids), email)

      return HttpResponse("csv will be sent in an email.")

def export_csv_for_gmv(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    type = request.GET.get('type')
    rows = [[]]

    if not type:
        return HttpResponse("missing parameter - type", status=400)
    
    type = type.lower()
    if type == 'brandmanager':
        rows = BrandManagerWiseGMV(start_date, end_date).get_rows()
    elif type == 'influencermanager':
        rows = InfluencerManagerWiseGMV(start_date, end_date).get_rows()
    elif type == 'influencerandmrp':
        rows = InfluencerAndMrpWiseGMV(start_date, end_date).get_rows()
    elif type == 'managerandbrand':
        rows = ManagerAndBrandWiseGMV(start_date, end_date).get_rows()
    elif type == 'managerandinfluencer':
        rows = ManagerAndInfluencerWiseGMV(start_date, end_date).get_rows()
    else:
        return HttpResponse("invalid value for - type", status=400)
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{type}_gmv.csv"'

    writer = csv.writer(response)
    writer.writerows(rows)

    return response

def export_csv_for_influencer_ledger(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    store_name = request.GET.get('store_name')
    
    ledger = InfluencerLedgerXLSX(store_name, start_date, end_date).get_ledger()
    
    response = HttpResponse(ledger, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f"attachment; filename={store_name}-ledger.xlsx"
    
    return response


def export_csv_to_mail(request):
  type = request.GET.get('type')
  if not type:
    return HttpResponse("Choose Type for Mail")
  start_date = request.GET.get('start_date')
  end_date = request.GET.get('end_date')

  if not TimeUtilities.validate_date(start_date) or not TimeUtilities.validate_date(end_date):
      return HttpResponse("Invalid date")

  start_date = date_parser.parse(start_date)
  end_date = date_parser.parse(end_date)

  if(type=='order'):
    send_order_csv_to_email.delay(start_date,end_date)
  elif(type=='sourcing'):
    send_sourcing_request_csv_to_email.delay(start_date,end_date)
  else:
    return HttpResponse("Invalid Type of Mail")
  return HttpResponse("Mail has been sent to export@zaamo.co",status=200)


def export_csv_for_user_contacts(request):

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    user_type = request.GET.get('user_type')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="contacts.csv"'
    writer = csv.writer(response)
    
    contacts = []
    if user_type.lower() == 'brand':
        contacts = Brand.objects.values_list('brand_name', 'brand_emails__brand_email', 'mobiles__mobile_no').distinct()
    elif user_type.lower() == 'influencer':
        contacts = StoreInfo.objects.filter(store_type=StoreTypeEnum.INFLUENCER)\
          .values_list('store_name', 'store_members__user__email', 'store_members__user__mobile_no').distinct()
    elif user_type.lower() == 'customer':
        contacts = Order.objects.all()
        if start_date:
            contacts = contacts.filter(created__gte=start_date)
        if end_date:
            contacts = contacts.filter(created_lt=end_date)
        contacts = contacts.values_list('user__first_name', 'user__email', 'user__mobile_no').distinct()
    
    writer.writerows(contacts)

    return response



def export_csv_for_botd_stores(request):
  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = f'attachment; filename="botd_stores.csv"'
  
  botd_stores_csv = BotdStoresCSV()

  writer = csv.writer(response)

  headers = botd_stores_csv.get_headers()
  writer.writerow(headers)

  stores_list = list(StoreInfo.objects.all().values_list('id', flat=True))

  stores = StoreInfo.objects.all().values('id', 'store_name', 'store_url')

  voucher_queryset = Voucher.objects.filter(store_id__in=stores_list, name='BOTD').select_related('store').prefetch_related('voucher_brands').values(
    'store__id','store__store_name', 'store__store_url', 'start_date', 'end_date', 'brands__brand_name'
  )
  voucher_dict = {}


  for voucher_instace in voucher_queryset:
    if not voucher_dict.get(voucher_instace.get('store__id')):
      voucher_dict[voucher_instace.get('store__id')] = voucher_instace
  
  for store in stores:

    store_name = store.get('store_name')
    store_url = store.get('store_url')
    botd = "Off"
    start_date = ""
    end_date = ""
    brand_name = ""
    
    if voucher_dict.get(store.get('id')) is not None:
      voucher_instance = voucher_dict.get(store.get('id'))
      if voucher_instance.get('end_date') >= TimeUtilities.get_current_date_time():
        botd = "On"

      start_date = voucher_instance.get('start_date')
      end_date = voucher_instance.get('end_date')
      brand_name = voucher_instance.get('brands__brand_name')
      
    row = [store_name, store_url, botd, start_date, end_date, brand_name]
    writer.writerow(row)
  
  return response

def export_csv_for_coupons(request):
  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = f'attachment; filename="coupons.csv"'
  
  coupons_csv = CouponsCSV()

  writer = csv.writer(response)

  headers = coupons_csv.get_headers()
  writer.writerow(headers)

  qs = Voucher.objects.all().select_related('store', 'products', 'collections', 'brands').values().order_by('-id').annotate(
    products = StringAgg(Cast('products__name', TextField()), delimiter=','),
    collections = StringAgg(Cast('collections__name', TextField()), delimiter=','),
    brands = StringAgg(Cast('brands__brand_name', TextField()), delimiter=','),
    product_brand_names = ArrayAgg(Cast('products__brand__brand_name', TextField()), delimiter=',')
  ).values(
    'type',
    'name',
    'code',
    'usage_limit',
    'used',
    'start_date',
    'end_date',
    'discount_value_type',
    'discount_value',
    'min_spent_amount',
    'apply_once_per_order',
    'min_checkout_items_quantity',
    'apply_once_per_customer',
    'max_discount_value',
    'store__store_name',
    'store__store_url',
    'owner',
    'brands',
    'product_brand_names',
    'products',
    'collections'
  )

  for row in qs:
    brands_set = set(row.get('brands').split(','))
    products_set = set(row.get('products').split(','))
    collections_set = set(row.get('collections').split(','))

    brands_table_data = ', '.join(brands_set)
    if row.get('product_brand_names'):
      products_brands_table_data = row.get('product_brand_names')[0]
    else:
      products_brands_table_data = None
    
    brands = ""
    if row.get('owner') == VoucherOwner.BRAND and products_brands_table_data is not None:
      brands = products_brands_table_data
    else:
      brands = brands_table_data
    
    coupon_row = [
      row.get('type'),
      row.get('name'),
      row.get('code'),
      row.get('usage_limit'),
      row.get('used'),
      row.get('start_date'),
      row.get('end_date'),
      row.get('discount_value_type'),
      row.get('discount_value'),
      row.get('min_spent_amount'),
      row.get('apply_once_per_order'),
      row.get('min_checkout_items_quantity'),
      row.get('apply_once_per_customer'),
      row.get('max_discount_value'),
      row.get('store__store_name'),
      row.get('store__store_url'),
      row.get('owner'),
      brands,
      ', '.join(products_set),
      ', '.join(collections_set)
    ]

    writer.writerow(coupon_row)
  
  return response

def export_csv_for_all_brand_details(request):

  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="brand_details.csv"'

  brand_details = AllBrandDetailsCSV()
  headers = brand_details.get_headers()
  rows = brand_details.get_rows()
  
  writer = csv.DictWriter(response, fieldnames=headers)
  writer.writeheader()
  writer.writerows(rows)

  return response

def export_csv_for_explore_products(request):
    
    filters = request.GET
    download = request.GET.get('download')
    
    if download and download.lower() != 'false':
        products = ExploreProductCSV(filters)
        header = products.get_headers()
        rows = products.get_rows()

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="explore.csv"'

        writer = csv.DictWriter(response, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)

        return response
    else:
        ExploreProductCSV.send_csv_email.delay(filters)
        return HttpResponse('An email will be sent shortly.', status=202)

def upload_csv_for_explore_products(request):
    
    csv_file = request.FILES.get('file')
    explore = ExploreProductUploadCSV(csv_file)
    header = explore.get_headers()
    if not 'state' in header or not 'media_url' in header or not 'product_id' in header:
        return HttpResponse('incorrect csv format', status=400)
    rows = explore.get_rows()
    products = ExploreProductUploadCSV.upload_csv.delay(rows)
        
    return HttpResponse('csv successfully uploaded.', status=202)

def export_csv_for_orderline_cashgram(request):

  start_date = request.GET.get('start_date')
  end_date = request.GET.get('end_date')

  release_date = '2022-01-04'
  if not start_date:
      start_date = release_date
  if not end_date:
    end_date = TimeUtilities.get_current_date(False)
    end_date = end_date.strftime('%Y-%m-%d')
  
  if not TimeUtilities.validate_date(start_date) or not TimeUtilities.validate_date(end_date):
      return HttpResponse("Invalid date")

  start_date = date_parser.parse(start_date)
  end_date = date_parser.parse(end_date)


  response = HttpResponse(content_type='text/csv')
  response['Content-Disposition'] = 'attachment; filename="export.csv"'

  writer = csv.writer(response)
  orderline_cashgram_csv = OrderLineCashgramCSV(start_date,end_date)
  headers = orderline_cashgram_csv.get_headers_of_orderline_cashgram()
  writer.writerow(headers)

  query_set = orderline_cashgram_csv.get_queryset()
  all_rows = orderline_cashgram_list(query_set,orderline_cashgram_csv)

  writer.writerows(all_rows)

  return response  

def export_csv_for_published_products(request):
  try:
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="export.csv"'

    writer = csv.writer(response)
    published_products_csv = PublishedProductsCSV()
    headers = published_products_csv.get_headers_of_published_products_csv()
    writer.writerow(headers)

    brand_ids = request.GET.get('brand_ids')
    category_ids = request.GET.get('category_ids')
    shopify = request.GET.get('shopify')

    Q_filter = Q()
    
    if brand_ids:

      brand_ids = brand_ids.replace('[','').replace(']','').split(',')

      brand_id_list = []

      for brand_id in brand_ids:
        brand_id = graphene.Node.from_global_id(brand_id)[1]
        brand_id_list.append(brand_id)

      Q_filter &= Q(brand_id__in=brand_id_list)
    
    if category_ids:

      category_ids = category_ids.replace('[','').replace(']','').split(',')

      category_id_list = []
      
      for category_id in category_ids:
        category_id = graphene.Node.from_global_id(category_id)[1]
        category_id_list.append(category_id)

      Q_filter &= Q(category_id__in=category_id_list)
    
    if shopify:
      Q_filter &= Q(metadata__shopify = True)
      
    queryset = published_products_csv.get_queryset()
    
    queryset = queryset.filter(Q_filter).values_list(
      'id','name', 'brand__brand_name', 'default_variant__cost_price_amount','default_variant__price_amount','step_price','default_variant__metadata__true_msp','metadata__weekly_visits','metadata__brand_order_count_weekly','category__name','metadata__shopify','brand__cod_base_price','brand__cod','brand_id'
    )
    brandshippingdata_details = dict()
    
    brandshippingdata = BrandShippingData.objects.all()

    for i in brandshippingdata:
        brandshippingdata_details[i.brand_id]=i

    for row in queryset:
      row = list(row)

      brand_id = row.pop(-1)
      
      shipping_data = brandshippingdata_details.get(brand_id)
      
      shipping_cost_same_state_amount = 0
      shipping_cost_other_state_amount = 0
      min_order_value_free_cost_amount = 0

      if shipping_data:
        shipping_cost_same_state_amount = shipping_data.shipping_cost_same_state_amount
        shipping_cost_other_state_amount = shipping_data.shipping_cost_other_state_amount
        min_order_value_free_cost_amount = shipping_data.min_order_value_free_cost_amount
        

      is_step_price = True
      
      if row[6]==None:
        row[6]=row[4]
      
      if not row[5]:
        is_step_price = False

      if not row[10]:
        row[10] = False
        
      row.extend([is_step_price,shipping_cost_same_state_amount,shipping_cost_other_state_amount,min_order_value_free_cost_amount])

      writer.writerow(row)

    return response
  
  except Exception as e:
    return ({'success':False, 'message':'Please select correct filter values', 'error':e})


def update_split_price_published_products(request):

  if request.method == 'POST':
    
    try:
      csv_file = request.FILES.get('file')

      if not csv_file:
        response = {'success':'False','message':'No csv File is attached'}

      rows = csv_file.read().decode('utf-8').splitlines()
      
      product_list = [row for row in csv.DictReader(rows)]

      product_id_list_split_price_dict = dict()

      for product in product_list:
        product_id_list_split_price_dict[product['Id']] = product['Step Price']
        
      from saleor.rest_apis.csv.tasks import update_product_variant_from_step_price
      update_product_variant_from_step_price(product_id_list_split_price_dict) #TODO turn delay on after testing and for big load
      
      from saleor.external_services.shopify_service.tasks import resync_price_and_inventory_for_zaamo_shopify_for_step_price_update
      resync_price_and_inventory_for_zaamo_shopify_for_step_price_update.delay(list(product_id_list_split_price_dict.keys()))

      response = {'success':'True'}

      return JsonResponse(response)

    except Exception as e:
      response = {'success':False,'message':e}
      return JsonResponse(response) 

  response = {'success':False,'message':'Only Post Request is allowed'}

  return JsonResponse(response)


def send_structure_data_ad_on_mail(brand_names,brand_ids_decoded):
  rows = fetch_structure_data_ad(brand_names,brand_ids_decoded)
  
  f = StringIO() 
  csv.writer(f).writerows(rows)
  base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
  attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email(f"ad_format_{TimeUtilities.get_current_date_time()}",base_encoded_file)
  attachments = [attachment_json]
  
  try:
    m = MailImpl()   
    m.send_mail_with_attachment('brand_ad_csv',f"Hi, Please find the attached CSV of Brand Ad for {', '.join(brand_names)}",'Brand ad CSV',attachments)
  
  except Exception as e:
    logger.exception(e)


def export_ad_data_in_FB_format_by_brand(request):
  
  response = HttpResponse(content_type='text/csv')
  current_date = TimeUtilities.get_current_date()
  response['Content-Disposition'] = f"attachment; filename=ad_format_{current_date}.csv"
  brand_ids = request.GET.get('brand_ids') or []
  in_mail = request.GET.get('in_mail') or False
  brand_ids_decoded = []
  if brand_ids:

    brand_ids = brand_ids.replace('[','').replace(']','').split(',')

    for brand_id in brand_ids:
      brand_id = graphene.Node.from_global_id(brand_id)[1]
      brand_ids_decoded.append(brand_id)
  
  brand_names = list(Brand.objects.filter(id__in=brand_ids_decoded).values_list('private_metadata__source_name',flat=True))
  writer = csv.writer(response)

  if not brand_names or not brand_ids_decoded:
    
    return JsonResponse({'success':False,'message':'Please mention correct brand id.'})
  
  if not in_mail:
    rows = fetch_structure_data_ad(brand_names,brand_ids_decoded)
  
    writer.writerows(rows)
    
    return response
  
  else:
    from saleor.rest_apis.csv.tasks import send_fb_ad_data_to_mail
    send_fb_ad_data_to_mail.delay(brand_names,brand_ids_decoded)

    return JsonResponse({'success':True,'message':'CSV will be shared on email shortly.'})
  
def variant_inventory_dict(variant_ids):
  results = Stock.objects.filter(product_variant_id__in=variant_ids)
  results = results.annotate_available_quantity()

  results = results.values_list(
      "product_variant_id", "warehouse__shipping_zones", "available_quantity"
  )

  quantity_by_shipping_zone_by_product_variant: DefaultDict[
      int, DefaultDict[int, int]
  ] = defaultdict(lambda: defaultdict(int))
  for variant_id, shipping_zone_id, quantity in results:
      quantity_by_shipping_zone_by_product_variant[variant_id][
          shipping_zone_id
      ] += quantity
  quantity_map: DefaultDict[int, int] = defaultdict(int)
  for (
      variant_id,
      quantity_by_shipping_zone,
  ) in quantity_by_shipping_zone_by_product_variant.items():
      quantity_map[variant_id] = max(quantity_by_shipping_zone.values())
      
  return quantity_map

def export_brand_inventory_csv(request):
  
  response = HttpResponse(content_type='text/csv')
  current_date = TimeUtilities.get_current_date()
  response['Content-Disposition'] = f"attachment; filename=brand_inventory_{current_date}.csv"
  brand_id = request.GET.get('brand_id')
  brand_name = request.GET.get('brand_name')
  queryset = None
  
  if brand_id:

    brand_id = graphene.Node.from_global_id(brand_id)[1]
    queryset = ProductVariant.objects.filter(product__brand_id=brand_id).select_related('product','product__brand')
  
  elif brand_name:
    brand_name = brand_name.replace("'",'').replace('"','')
    queryset = ProductVariant.objects.filter(product__brand__brand_name=brand_name).select_related('product','product__brand')
  
  else:
    return JsonResponse({'success':False,'message':'Please mention correct brand id.'})
  
  if not queryset:
    return JsonResponse({'success':False,'message':'Please mention correct brand id.'})

  stock_map = variant_inventory_dict(queryset.values('id'))

  writer = csv.writer(response)
  rows = [['brand_name', 'brand_status', 'product_name','handle', 'is_published','variant_name',  'track_inventory', 'stock']]
  brand = queryset[0].product.brand

  for obj in queryset:
    
    rows.append([brand.brand_name,brand.status,obj.product.name,obj.product.slug,obj.product.is_published,obj.name,obj.track_inventory,stock_map[obj.id]])

  writer.writerows(rows)
  
  return response

def export_shopify_csv(request):

  brand_ids = request.GET.get('brand_id')
  size_chart = request.GET.get('size_chart')
  limit = int(request.GET.get('limit', 0))
  page = int(request.GET.get('page', 1))

  if brand_ids:
    brand_ids = [graphene.Node.from_global_id(brand_id)[1] for brand_id in brand_ids.split(',')]

  shopify = ShopifyCSV(brand_ids, size_chart)
  headers = shopify.get_headers()
  rows = shopify.get_rows()
  
  if limit:
    rows = sorted(rows, key=lambda x: x[headers[0]])
    rows = rows[(page - 1)*limit: page * limit]

  response = HttpResponse(content_type='text/csv')
  current_date = TimeUtilities.get_current_date()
  response['Content-Disposition'] = f"attachment; filename=shopify_{current_date}.csv"
  
  writer = csv.DictWriter(response, fieldnames=headers)
  writer.writeheader()
  writer.writerows(rows)

  return response

def export_shopify_product_details(request):
  
  start_date = request.GET.get('start_date')
  end_date = request.GET.get('end_date',StringUtilities.convert_object_to_string(TimeUtilities.get_current_date(False)))

  if start_date:

    if not TimeUtilities.validate_date(start_date) or not TimeUtilities.validate_date(end_date):
        return HttpResponse("Invalid date")

    start_date = date_parser.parse(start_date)
    end_date = date_parser.parse(end_date)
    
  shopify = ShopifyProductDetailsCSV(start_date, end_date)
  
  headers = shopify.get_headers()
  rows = shopify.get_rows()
  response = HttpResponse(content_type='text/csv')
  current_date = TimeUtilities.get_current_date()
  response['Content-Disposition'] = f"attachment; filename=shopify_product_{current_date}.csv"
  
  writer = csv.writer(response)
  writer.writerow(headers)
  writer.writerows(rows)
  return response


def explore_product_status(request):

  data = json.loads(request.body.decode('utf-8'))
  brand_ids = data.get('brand_ids')
  product_ids = data.get('product_ids')
  
  res = {0: [], 1: []}
  if brand_ids:
    brand_ids = [graphene.Node.from_global_id(brand_id)[1] for brand_id in brand_ids]
    queryset = Brand.objects.filter(id__in=brand_ids).values_list('id', 'status')
    for brand_id, status in queryset:
      key = 1 if status == 'active' else 0
      res[key].append(graphene.Node.to_global_id('Brand', brand_id))
  
  if product_ids:
    product_ids = [graphene.Node.from_global_id(product_id)[1] for product_id in product_ids]
    queryset = Product.objects.filter(id__in=product_ids).values_list('id', 'is_published', 'metadata__instock')
    for pid, published, instock in queryset:
      key = 1 if published == True and instock == True else 0
      res[key].append(graphene.Node.to_global_id('Product', pid))

  return JsonResponse(data=res)

def update_search_image(request):
  brand_ids = request.GET.get('brand_id')
  product_ids = request.GET.get('product_id')
  if not brand_ids and not product_ids:
    return JsonResponse({'message': 'Please provide a valid brand_id or product_id'})
  
  if brand_ids:
    brand_ids = [graphene.Node.to_global_id('Brand', brand_id) for brand_id in brand_ids.split(',')]
  if product_ids:
    product_ids = [graphene.Node.to_global_id('Product', product_id) for product_id in product_ids.split(',')]

  update_count = update_product_search_image(brand_ids, product_ids)

  return JsonResponse({'message': f'{update_count} search images updated'})


def send_invoice_email_for_brand(request):
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    brand_id = request.GET.get('brand_id')
    email = request.GET.get('email')

    if not TimeUtilities.validate_date(start_date) and not TimeUtilities.validate_date(end_date):
      start_date = None
      end_date = None
      
    start_date = date_parser.parse(start_date)
    end_date = date_parser.parse(end_date)

    create_invoice_for_brands_task.delay(brand_id,start_date,end_date,email)

    return JsonResponse({'message': f'Invoice will be sent shortly.'})
    
def order_related_calculations(request):
  try:
    order_id = request.GET.get('order_id')
    
    if not order_id:
      return JsonResponse({'message': 'Please provide a valid order_id'})
    
    try:
      order_id = graphene.Node.from_global_id(order_id)[1]
    except:
      pass

    order_calc_inst = OrderCalculations()
    response = order_calc_inst.get_order_related_calculations(order_id)

    if response.get('lines'):
      return JsonResponse({'success':True,'data': response})

    else:
      return JsonResponse({'success':False,'data': response})
  
  except Exception as e:

    return JsonResponse({'success':False,'message': e})
