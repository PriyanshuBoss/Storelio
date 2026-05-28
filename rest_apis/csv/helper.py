import graphene
from django.conf import settings
from saleor.utilities.api_client import ApiClient
from saleor.product.models import Product, ProductVariant
from saleor.utilities.brand_order_db_utilities import get_brand_order_table_connection
from saleor.utilities.number_utilities import NumberUtilities
from ...celeryconf import app
from saleor.external_services.mail.mail_impl import MailImpl
import logging
from io import StringIO
import csv
import base64
from saleor.rest_apis.csv.csv_context import BrandManagerCSVhelper , OrderCsvContext,SourcingRequestCSV
from django.db.models import Case, When, Value, CharField, Q, Subquery, OuterRef, BigIntegerField
from saleor.order.models import FulfillmentLine, Order, Fulfillment
from django.db.models.functions import Concat, Cast
from saleor.discount.models import Voucher
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from saleor.account.models import User
from saleor.order.models import Order,OrderLine
from saleor.store.models import StoreMemberState
from saleor.brand.models import Brand


logger = logging.getLogger(__name__)


def order_instance_data_list(order_filter,order_csv):

  all_rows = []
  for orderline_instance in order_filter:
        row = [
            order_csv.get_date(orderline_instance),
            order_csv.get_timestamp(orderline_instance),
            order_csv.get_brand_name(orderline_instance),
            order_csv.get_product_name(orderline_instance),
            order_csv.get_order_id(orderline_instance),
            order_csv.get_user_id(orderline_instance),
            order_csv.get_quantity(orderline_instance),
            order_csv.get_msp(orderline_instance),
            order_csv.get_mrp(orderline_instance),
            order_csv.get_true_msp(orderline_instance),
            order_csv.get_final_price_paid(orderline_instance),
            order_csv.get_post_pay_brand_due_amount(orderline_instance),
            order_csv.get_shipping_price(orderline_instance),
            order_csv.get_coupon_code(orderline_instance),
            order_csv.get_zaamo_discount_amount(orderline_instance),
            order_csv.get_brand_discount_amount(orderline_instance),
            order_csv.get_influencer_commission(orderline_instance),
            order_csv.get_zaamo_commission(orderline_instance.brand_id),
            order_csv.get_customer_name(orderline_instance),
            order_csv.get_customer_email(orderline_instance),
            order_csv.get_customer_phone_number(orderline_instance),
            order_csv.get_store_name(orderline_instance),
            order_csv.get_order_status(orderline_instance),
            order_csv.get_brand_order_status(orderline_instance),
            order_csv.get_store_app(orderline_instance),
            order_csv.get_if_order_streakorder(orderline_instance),
            order_csv.get_coupon_owner(orderline_instance),
            order_csv.get_if_user_store_owner(orderline_instance),
            order_csv.get_brand_order_id(orderline_instance),
            order_csv.get_platform_fees(orderline_instance),
            order_csv.get_penalty(orderline_instance),
            order_csv.get_cod_amount(orderline_instance),
            order_csv.get_if_cod(orderline_instance),
            order_csv.get_app_code(orderline_instance),
            order_csv.get_orderline_id(orderline_instance),
            order_csv.get_is_fake(orderline_instance),
            # order_csv.get_revenue(orderline_instance),
            order_csv.get_shopify_markup_revenue(orderline_instance),
            order_csv.get_order_note(orderline_instance),
            order_csv.get_order_note_timestamp(orderline_instance),
            order_csv.get_shopify_order_bool(orderline_instance),
            order_csv.get_lost_revenue_bool(orderline_instance)
        ]
        all_rows.append(row)
  
  return all_rows

def tax_report_data_list(order_filter,order_csv):

  all_rows = []
  for orderline_instance in order_filter:
        try:
            row = [
                order_csv.get_brand_pay(orderline_instance),
                order_csv.get_tds(orderline_instance),
                order_csv.get_date(orderline_instance),
                order_csv.get_timestamp(orderline_instance),
                order_csv.get_brand_name(orderline_instance),
                order_csv.get_product_name(orderline_instance),
                order_csv.get_order_id(orderline_instance),
                order_csv.get_user_id(orderline_instance),
                order_csv.get_quantity(orderline_instance),
                order_csv.get_msp(orderline_instance),
                order_csv.get_mrp(orderline_instance),
                order_csv.get_true_msp(orderline_instance),
                order_csv.get_final_price_paid(orderline_instance),
                order_csv.get_post_pay_brand_due_amount(orderline_instance),
                order_csv.get_shipping_price(orderline_instance),
                order_csv.get_customer_name(orderline_instance),
                order_csv.get_customer_email(orderline_instance),
                order_csv.get_customer_state(orderline_instance),
                order_csv.get_brand_state(orderline_instance),
                order_csv.get_brand_gst_number(orderline_instance),
                order_csv.get_cgst(orderline_instance),
                order_csv.get_sgst(orderline_instance),
                order_csv.get_igst(orderline_instance),
                order_csv.get_brand_status(orderline_instance),
                order_csv.get_order_status(orderline_instance),
                order_csv.get_order_note_timestamp(orderline_instance),
                order_csv.get_brand_order_id(orderline_instance),
                order_csv.get_orderline_id(orderline_instance),
                order_csv.get_is_cod(orderline_instance),
                order_csv.get_brand_pan_number(orderline_instance),
                order_csv.get_brand_due_amount(orderline_instance),
                order_csv.get_zaamo_commission(orderline_instance),
                order_csv.get_influencer_commission(orderline_instance),
                order_csv.get_extra_shopify_charge(orderline_instance),
                order_csv.get_tax_deducted_bool(orderline_instance),
            ]
            all_rows.append(row)
            
        except Exception as e:
            logger.exception(e)
            continue
  
  return all_rows

def sourcing_request_data_list(sourcing_request):

    sourcing_date_list =[]
    headers = sourcing_request.get_headers()
    field_names = sourcing_request.get_header_field_mapping()

    sourcing_date_list.append(headers)

    queryset = sourcing_request.get_queryset()

    if queryset:
        queryset = queryset.select_related('store', 'brand', 'product', 'variant', 'user_last_updated')\
            .annotate(order_id = Cast(KeyTextTransform('order_id', 'metadata'), BigIntegerField())
            ).annotate(fulfillment_id = Cast(KeyTextTransform('fulfillment_id', 'metadata'), BigIntegerField())
            ).annotate(order_status=Subquery(Fulfillment.objects.filter(id=OuterRef('fulfillment_id')).values('status')[:1])
            ).annotate(
                order_created_at = Subquery(Order.objects.filter(id=OuterRef('order_id')).values('created')[:1])
            ).annotate(
                recommend = Case(
                    When(recommended=True, then=Value("recommended")), 
                    default=Value(""), 
                    output_field=CharField()
                )
            ).values('id', 'store__store_name', 'influencer_managers', 'product__name', 'variant__name', 'brand__brand_name',
            'brand_managers', 'status', 'store__actions__status', 'content','store__metadata__store_barter',
            'created_at', 'updated_at', 'recommend', 'order_status', 'order_created_at', 'store__metadata__influencer_notes', 'store__metadata__barter_guidelines')

    for row in queryset:
        row['store__metadata__store_barter'] = not row['store__metadata__store_barter']
        row['delivery_date'] = sourcing_request.get_order_delivery_date(row['id'])
        row['city'] = sourcing_request.get_last_order_city(row['store__store_name'])
        row['days_since_products_delivered'] = sourcing_request.get_days_since_products_delivered(row['id'])
        
        sheeko_data = sourcing_request.get_sheeko_data(row['store__store_name'])
        row['sheeko_owner1'] = sheeko_data.get('owner1')
        row['sheeko_status'] = sheeko_data.get('status')
        row['sheeko_text_1'] = sheeko_data.get('text_1')
        row['sheeko_text_2'] = sheeko_data.get('text_2')
        row['sheeko_date'] = sheeko_data.get('date')

        
        final_row = []
        for header in headers:
            if header=="Availability":
                if row.get(field_names.get(header)):
                    final_row.append("Busy")
                else:
                    final_row.append("Available")
            elif header=="Order Status":
                if row.get(field_names.get(header)):
                    final_row.append(row.get(field_names.get(header)))
                else:
                    final_row.append("No Order Placed")
            else:
                final_row.append(row.get(field_names.get(header)))
        sourcing_date_list.append(final_row)
    
    return sourcing_date_list

@app.task(queue='priority_queue')
def send_order_csv_to_email(start_date,end_date):

    try:
        f = StringIO()
  
        order_csv = OrderCsvContext(start_date, end_date)
        headers = order_csv.get_headers_of_order_for_csv()
        csv.writer(f).writerow(headers)

        order_filter = order_csv.get_queryset()
        all_rows = order_instance_data_list(order_filter,order_csv)
        csv.writer(f).writerows(all_rows)
        base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
        attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email("export.csv",base_encoded_file)
        attachments = [attachment_json]
        m = MailImpl()
        m.send_mail_with_attachment('mail_sender',f'Hi, Please find the attached CSV for your Order analytics.','Order Analytics CSV',attachments)
    
    except Exception as e:
        logger.exception(f"Error in sending csv in Email: {e}")

@app.task(queue='priority_queue')
def send_sourcing_request_csv_to_email(start_date,end_date):

    try:

        f=StringIO()

        sourcing_request = SourcingRequestCSV(start_date, end_date)
        
        all_data_list = sourcing_request_data_list(sourcing_request)
        csv.writer(f).writerows(all_data_list)
        
        base_encoded_file = base64.b64encode(f.getvalue().encode()).decode()
        attachment_json = BrandManagerCSVhelper.create_attachment_dict_for_email("export.csv",base_encoded_file)
        attachments = [attachment_json]
        m = MailImpl()
        m.send_mail_with_attachment('mail_sender',f'Hi, Please find the attached CSV for your Sourcing Request .','Soucing Request CSV',attachments)
    
    except Exception as e:
        logger.exception(f"Error in sending csv in Email: {e}")

def orderline_cashgram_list(query_set,orderline_cashgram):

    all_rows = []
    for orderline_cash in query_set:
        row = [
            orderline_cashgram.get_order_id(orderline_cash),
            orderline_cashgram.get_refund_by_user(orderline_cash),
            orderline_cashgram.get_refund_status(orderline_cash),
            orderline_cashgram.get_brand_id(orderline_cash),
            orderline_cashgram.get_brand_name(orderline_cash),
            orderline_cashgram.get_refund_amount(orderline_cash),
            orderline_cashgram.get_created_at(orderline_cash),
            orderline_cashgram.get_updated_at(orderline_cash)
        ]
        all_rows.append(row)
    
    return all_rows

def bulk_update_variant_for_step_price(product_id_list_split_price_dict):
  
    variants = ProductVariant.objects.filter(product_id__in=product_id_list_split_price_dict.keys())
    variant_to_update = []

    for variant in variants:
        step_price = NumberUtilities.convert_string_to_decimal(product_id_list_split_price_dict[variant.product_id])

        true_msp = NumberUtilities.convert_string_to_decimal(variant.metadata.get('true_msp'))

        if not true_msp:
            true_msp = variant.price_amount
            variant.metadata['true_msp'] = true_msp

        price_amount = true_msp + step_price 

        if variant.price_amount == price_amount:
            continue

        variant.price_amount = price_amount
        
        if variant.price_amount>variant.cost_price_amount:
            variant.cost_price_amount = variant.price_amount

        variant_to_update.append(variant)

    ProductVariant.objects.bulk_update(variant_to_update,['price_amount','cost_price_amount','metadata'],batch_size=10000)
  

def bulk_update_product_for_step_price(product_id_list_split_price_dict):
      
    product_insts = Product.objects.filter(id__in = product_id_list_split_price_dict.keys())

    products_to_update = []

    for product_inst in product_insts:
        
        if product_inst.step_price == product_id_list_split_price_dict[product_inst.id]:
            continue

        product_inst.step_price = product_id_list_split_price_dict[product_inst.id]
        products_to_update.append(product_inst)

    Product.objects.bulk_update(products_to_update,['step_price'],batch_size=10000)


def get_data_for_ad(brand_ids):

    data = []
    data.append(["email", "email", "email", "phone", "phone", "phone", "madid", "fn", "ln", "zip", "ct", "st", "country", "dob", "doby", "gen", "age", "uid", "value"])

    id_if = StoreMemberState.objects.all().values('user_id')
    
    user_email = Order.objects.filter(id__in=Subquery(OrderLine.objects.filter(brand_id__in=brand_ids).values('order_id'))).exclude(user_id__in=id_if).only('user_id','user_email')

    user_email_dict = {i.user_id:i.user_email for i in user_email}
    
    all_users = User.objects.filter(id__in=user_email_dict.keys()).exclude(id__in=id_if).only('mobile_no','email','id')
    
    for user in all_users:
        email = user_email_dict.get(user.id) or user.email
        if email:
            if 'zaamo' in email:
                continue
            data.append([email,email,email, user.mobile_no,user.mobile_no,user.mobile_no, "", "", "", "", "", "", "IN", "", "", "", "", "", ""])

    return data

def structure_brand_customer_data(data,brand_ids):
    
    rows = get_data_for_ad(brand_ids)
    covered = {(row[0],row[3]):True for row in rows}

    id_if = StoreMemberState.objects.all().values('user_id')
    user_email = Order.objects.filter(user_id__in=id_if).only('user_id','user_email')
    memberemaildict = [u.user_email for u in user_email]
    
    brands = []
    brands_source = list(Brand.objects.filter(id__in=brand_ids).values_list('private_metadata__source_name',flat=True))

    brands.extend(brands_source)
    
    for i in data:
        if not i[2] in brands:
            continue
        phone = i[0]
        phone = '+91' + ''.join(phone.replace(' ','').strip()[-10:])
        email = i[1]
        if email in memberemaildict:
            continue

        if covered.get((phone,email)):
            continue

        rows.append([email,email,email, phone,phone,phone, "", "", "", "", "", "", "IN", "", "", "", "", "", ""])
        covered[(phone,email)]=True
    return rows


def fetch_structure_data_ad(brand_name_list,brand_ids):
    
    connection = get_brand_order_table_connection()
    cursor = connection.cursor()
    repl = ["%s"]
    
    query = f"SELECT contact,email,brand_name from brandorderdata where brand_name in ({', '.join(repl * len(brand_name_list))}) order by date desc;"

    cursor.execute(query,tuple(brand_name_list))
    data = cursor.fetchall()
    
    return structure_brand_customer_data(data,brand_ids)

def get_product_search_image(brand_gids: list=None, product_gids: list=None):
    api_client = ApiClient(host=settings.CONTENT_SERVICE_URL, path='streaming/api/search_image/', schema='https')
    api_client.add_header('SERVICE-TOKEN', settings.CONTENT_SERVICE_TOKEN)
    if brand_gids:
        api_client.add_url_param('brand_id', ','.join(brand_gids))
    if product_gids:
        api_client.add_url_param('product_id', ','.join(product_gids))
    
    api_client.get()
    res = api_client.fetch_response()
    return res

def update_product_search_image(brand_gids: list=None, product_gids: list=None):
    data = get_product_search_image(brand_gids, product_gids).get('data')
    if not data:
        return 0
    
    product_images = dict()
    for product_gid, image_url in data.items():
        product_id = NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(product_gid)[1])
        product_images[product_id] = image_url

    queryset = Product.objects.filter(id__in=product_images.keys()).only('id', 'metadata')
    for product in queryset:
        product.metadata['search_image'] = product_images.get(product.id)

    Product.objects.bulk_update(queryset, fields=['metadata'], batch_size=1000)
    update_count = queryset.count()
    return update_count
