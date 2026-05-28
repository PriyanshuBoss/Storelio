from saleor.discount.models import Voucher
from saleor.discount import VoucherType
from saleor.discount.tasks import product_value_deal_update,update_value_deal_voucher_task
from saleor.utilities.time_utilities import TimeUtilities

def update_steal_deal(condition = False):

    todays_date = TimeUtilities.get_current_date_time()
    vouchers = Voucher.objects.filter(type = VoucherType.SPECIFIC_BRAND_PRODUCTS).active(todays_date)

    for voucher in vouchers:

        brands = voucher.brands.all()
        collections = voucher.collections.all()
        products = voucher.products.all()
        categories = voucher.categories.all()

        product_value_deal_update(products,categories,collections,brands,condition)
        trigger_date =  TimeUtilities.subtract_time_from_timestamp(voucher.end_date,0,5,30)
        update_value_deal_voucher_task.apply_async(([voucher.id]),eta =trigger_date)


    print("DONE")

#from saleor.python_scripts.mark_coupon_steal_deal import update_steal_deal
#update_steal_deal(True)

