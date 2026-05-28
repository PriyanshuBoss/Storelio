from saleor.utilities.request_utilities import RequestUtilities, PlatformTypeEnum
from saleor.utilities.time_utilities import TimeUtilities
from ...discount import models
from ...store.store_utilities import get_default_zaamo_store,get_instance_for_store
from ..utils.filters import filter_by_query_param

VOUCHER_SEARCH_FIELDS = ("name", "code")
SALE_SEARCH_FIELDS = ("name", "value", "type")


def resolve_vouchers(info, query, **kwargs):
    store_id=RequestUtilities.get_store_id_from_headers(info.context)
    platform=RequestUtilities.get_platfrom_type_from_headers(info.context)
    default_store_id = None
    
    if kwargs.get('filter',{}).get('voucher_type',{}) == 'specific_brand_products':
        default_store = get_default_zaamo_store()

        if default_store:
            default_store_id = default_store.id

    if platform == PlatformTypeEnum.BRAND_HOME:
        qs = models.Voucher.objects.all()
    
    elif store_id and store_id!="null" :
        qs = models.Voucher.objects.filter(store__in=[store_id, default_store_id])
    
    else:
        qs = models.Voucher.objects.all()
    
    return filter_by_query_param(qs, query, VOUCHER_SEARCH_FIELDS)
   


def resolve_sales(info, query, **_kwargs):
    qs = models.Sale.objects.all()
    return filter_by_query_param(qs, query, SALE_SEARCH_FIELDS)

def resolve_voucher_store_deals(info, query, **_kwargs):
    store_id=RequestUtilities.get_store_id_from_headers(info.context)
    active_voucher_ids = list(models.Voucher.objects.active(TimeUtilities.get_current_date_time()).values_list('id', flat=True))
    qs = models.VoucherStoreDealMapping.objects.filter(
        store_id = store_id,
        voucher_id__in  = active_voucher_ids
    )
    return qs

def resolve_store_slug(store_id):

    store = get_instance_for_store(store_id)

    return store
