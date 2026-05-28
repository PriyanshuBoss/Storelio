from saleor.celeryconf import app
from saleor.discount import VoucherOwner
from saleor.discount.models import Voucher
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.settings import IS_BETA
from saleor.store.models import StaffStoreMapping,StoreMemberState
from saleor.product.models import Product,Collection
from saleor.utilities.time_utilities import TimeUtilities
from django.db.models import Q 
from saleor.notifications.utils import send_notifications

@app.task(queue='celery_periodic')
def send_coupon_expire_email():

    if IS_BETA:
        return

    active_vouchers = Voucher.objects.active(
        TimeUtilities.get_current_date_time()).filter(owner=VoucherOwner.BRAND)

    expiring_after_2_days = active_vouchers.filter(
        end_date__lte=TimeUtilities.add_time_in_timestamp(
            TimeUtilities.get_current_date_time(), days=2
            ), end_date__gte=TimeUtilities.add_time_in_timestamp(
            TimeUtilities.get_current_date_time(), days=1
            )
        ).select_related('store')
    if expiring_after_2_days.exists():
        expiring_coupons = expiring_after_2_days.values('name', 'code', 'end_date', 'store__store_name')

        
        text = "Following coupons are expiring within 2 days. Checkout your coupons at home.zaamo.co/coupons {}".format("\n")

        for index, value in enumerate(expiring_coupons):
            text = text + "{}. name : {}{}   code: {}{}  store_name: {}{}  end_date: {}{}".format(index,
                value.get("name", ""), "\n", value.get("code", ""), "\n", value.get("store__store_name", "") , "\n",
                value.get("end_date", ""), "\n")

        store_managers = StaffStoreMapping.objects.all().select_related('user')

        for manager in store_managers:
            email = manager.user.email
            MailImpl.send_mail_without_template('coupon_expire', text, 'Coupons Expiring', recipient_email=email)

def product_value_deal_update(products,categories,collections,brands,condition=False):

    if products:
        products = Product.objects.filter(id__in = products)
        for prod in products:
            prod.metadata['value_deal'] = condition
        
        Product.objects.bulk_update(products,['metadata'])
        
    elif brands and collections:

        prod_list = Collection.objects.filter(Q(id__in = collections)&Q(collectionproduct__product__brand__in = brands)).values_list('collectionproduct__product_id',flat=True)
        products = Product.objects.filter(id__in = prod_list)
        for prod in products:
            prod.metadata['value_deal'] = condition
    
        Product.objects.bulk_update(products,['metadata'])

    elif brands and categories:
        products = Product.objects.filter(brand__in = brands,category__in = categories)
        for prod in products:
            prod.metadata['value_deal'] = condition
        
        Product.objects.bulk_update(products,['metadata'])
    
    elif brands:
        products = Product.objects.filter(brand__in = brands)
        for prod in products:
            prod.metadata['value_deal'] = condition
        
        Product.objects.bulk_update(products,['metadata'])

    return 

@app.task
def update_value_deal_voucher_task(voucher_id):

    voucher_instance = Voucher.objects.filter(id = voucher_id).first()

    brands = voucher_instance.brands.all()
    collections = voucher_instance.collections.all()
    products = voucher_instance.products.all()
    categories = voucher_instance.categories.all()

    product_value_deal_update(products,categories,collections,brands,False)



def notification_coupon_expiry_last_24():
    from saleor.account.models import User
    if IS_BETA:
        return
    active_vouchers = Voucher.objects.active(
        TimeUtilities.get_current_date_time()).filter(owner__in=[VoucherOwner.BRAND])
    expiring_between_24_12_hours = active_vouchers.filter(
        end_date__lte=TimeUtilities.add_time_in_timestamp(
            TimeUtilities.get_current_date_time(), seconds=1,hours=24
            ), end_date__gte=TimeUtilities.add_time_in_timestamp(
            TimeUtilities.get_current_date_time(), hours=12, seconds=1
            )
        ).select_related('store')
    if expiring_between_24_12_hours.exists():
        expiring_coupons = expiring_between_24_12_hours.values('code','brands__brand_name','products__name','store__id')
        user_ids = []
        context_variables = dict()
        for index, value in enumerate(expiring_coupons):
            user_id = StoreMemberState.objects.filter(store_id=value.get('store__id')).first().user_id
            user_ids.append(user_id)
            context_variables[user_id] = {
                "product_name":value.get("products__name",""),
                "brand_name": value.get("brand__brand_name",""),
                "code":value.get("code","")
            }
        users = User.objects.filter(id__in=user_ids)
        return send_notifications(list(users),context_variables,event_code="EV_test_sourcing_expiry")   



def notification_coupon_expiry_last_12():
    from saleor.account.models import User
    if IS_BETA:
        return
    active_vouchers = Voucher.objects.active(
        TimeUtilities.get_current_date_time()).filter(owner__in=[VoucherOwner.BRAND])
    expiring_last_12_hours = active_vouchers.filter(
        end_date__lte=TimeUtilities.add_time_in_timestamp(
            TimeUtilities.get_current_date_time(), seconds=1,hours=12
            )
        ).select_related('store')
    if expiring_last_12_hours.exists():
        expiring_coupons = expiring_last_12_hours.values('code','brands__brand_name','products__name','store__id')
        user_ids = []
        context_variables = dict()
        for index, value in enumerate(expiring_coupons):
            user_id = StoreMemberState.objects.filter(store_id=value.get('store__id')).first().user_id
            user_ids.append(user_id)
            context_variables[user_id] = {
                "product_name":value.get("products__name",""),
                "brand_name": value.get("brand__brand_name",""),
                "code":value.get("code","")
            }
        users = User.objects.filter(id__in=user_ids)
        return send_notifications(list(users),context_variables,event_code="EV_test_sourcing_expiry")   