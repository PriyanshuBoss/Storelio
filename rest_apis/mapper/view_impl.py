from django.conf import settings
from django.db.models.query_utils import Q
from django.http import JsonResponse
from saleor.product.models import BrandVariantZaamoMapping
import graphene
import saleor.store.models as store_models
from urllib.parse import urlparse

def fetch_store_id_by_slug(request):
    
    slug = request.GET.get('slug')

    if not slug:
        return JsonResponse({'success': False, 'error_message': "In-valid slug"})

    registory_filter = store_models.StoreInfo.objects.filter(slug=slug)

    if not registory_filter:
        return JsonResponse({'success': False, 'error_message': "In-valid slug"})

    return JsonResponse({'success': True, 'store_id': registory_filter[0].id})


def fetch_store_id_by_user(request):
    user_id = request.GET.get('user_id')

    if not user_id:
        return JsonResponse({'success': False, 'error_message': "In-valid user id"})

    state_filter = store_models.StoreMemberState.objects.filter(user_id=user_id)

    if not state_filter:
        return JsonResponse({
            'success': False,
            'error_message': "In-valid user id"
        })

    store_id = state_filter[0].store_id

    return JsonResponse({'success': True, 'store_id': store_id})


def fetch_store_id_by_host(request):
    
    host = request.GET.get('host')

    if not host or host in settings.DEFAULT_STORE_URL:
        return JsonResponse({'success': False, 'error_message': "In-valid host or default host"})

    registory_filter = store_models.StoreInfo.objects.filter(Q(store_url__contains=host))

    if not registory_filter:
        return JsonResponse({'success': False, 'error_message': "In-valid host"})

    return JsonResponse({'success': True, 'store_id': registory_filter[0].id})


def fetch_product_id_from_brand_product_id(request):
    '''
    take product_id_brand and return list of zaamo encoded product ids associated with it.
    '''

    product_id_brand = request.GET.get('product_id_brand')

    if not product_id_brand:
        return JsonResponse({'success': False, 'error_message': "No product id brand recieved"}, status=404)

    product_zaamo_ids = BrandVariantZaamoMapping.objects.filter(product_id_brand=product_id_brand).distinct('product_zaamo_id').values_list('product_zaamo_id',flat=True)
    
    if not product_zaamo_ids:
        return JsonResponse({'success': False, 'error_message': "No product mapped with this product id"}, status=404)

    product_zaamo_ids_global = []

    for p_id in product_zaamo_ids:
        product_zaamo_ids_global.append(graphene.Node.to_global_id('Product',p_id))

    return JsonResponse({'success': True, 'product_zaamo_ids': product_zaamo_ids_global})