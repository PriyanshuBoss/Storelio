import graphene
import logging

from saleor.utilities.number_utilities import NumberUtilities
from ...checkout import models
from ...core.permissions import CheckoutPermissions
from ...checkout import base_calculations
from ..utils import get_user_or_app_from_context
from saleor.brand.models import Brand
from saleor.discount.models import Voucher
from saleor.account import models as  account_models
from saleor.discount import VoucherOwner, VoucherType
from django.db.models import Q,Case,When,BooleanField
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.request_utilities import RequestUtilities, PlatformTypeEnum

logger = logging.getLogger(__name__)


def resolve_checkout_lines():
    queryset = models.CheckoutLine.objects.all()
    return queryset


def resolve_checkouts():
    queryset = models.Checkout.objects.all()
    return queryset

def resolve_checkouts_by_user(info, user_id, mobile_no, *args, **kwargs):
    queryset = models.Checkout.objects.none()
    
    try:
        if info.context.user:
            queryset = models.Checkout.objects.filter(user_id=info.context.user.id)
            return queryset
    except:
        logger.info("'user not logged in', getting checkouts with user_id :: %s or mobile_no :: %s", user_id, mobile_no)


    if user_id:
        user_id = graphene.Node.from_global_id(user_id)[1]
        queryset = models.Checkout.objects.filter(user_id=user_id)
    elif mobile_no:
        user = account_models.User.objects.filter(mobile_no=mobile_no).first()
        if user:
            queryset = models.Checkout.objects.filter(user=user)

    return queryset

def resolve_checkout(info, token):
    checkout = models.Checkout.objects.filter(token=token).select_related('user').prefetch_related('lines__variant__product__brand').first()

    if checkout is None:
        return None

    # resolve checkout for anonymous customer
    if not checkout.user:
        return checkout

    # resolve checkout for logged-in customer
    if checkout.user == info.context.user:
        return checkout

    # resolve checkout for staff user
    requester = get_user_or_app_from_context(info.context)
    if requester.has_perm(CheckoutPermissions.MANAGE_CHECKOUTS):
        return checkout

    return None

def resolve_brand_shipping_cost(checkout_id):
    
    checkout_instance = models.Checkout.objects.filter(pk=checkout_id).first()
    checkoutlines = models.CheckoutLine.objects.filter(checkout_id=checkout_id)
    brand_instance_dict={}
    _,brand_shipping_cost_dict,_ = base_calculations.calculate_shipping_from_dict(checkout_instance,checkoutlines)
    for brand_id in brand_shipping_cost_dict:
        brand = Brand.objects.filter(pk=brand_id).first()
        brand_instance_dict[brand_id] = brand

    return brand_shipping_cost_dict,brand_instance_dict


def resolve_cod_price(root,info):
    return base_calculations.base_checkout_cod_charge(root,root.lines.all()).net.amount

def resolve_applicable_vouchers(info,store_id,product_id=None,checkout_id=None):
    
    if not store_id or not NumberUtilities.convert_string_to_number(store_id):
        return Voucher.objects.none()
    
    app_code  = RequestUtilities.get_app_code_from_headers(info.context)
    platform_code = RequestUtilities.get_platfrom_type_from_headers(info.context)

    products_list = []
    brand_list = []
    brand_dict = {}
    applied_voucher = None
    if product_id:
        try:
            prod = graphene.Node.get_node_from_global_id(info,product_id)
            brand_id = prod.brand_id
            brand_list.append(brand_id)
            product_id = graphene.Node.from_global_id(product_id)[1]
            products_list.append(product_id)
            brand_dict[brand_id] = [product_id]

        except Exception as e:
            raise ValueError(e)

    elif checkout_id:
        try:
            checkout = graphene.Node.get_node_from_global_id(info,checkout_id)
            checkout_lines = checkout.lines.all().prefetch_related('variant','variant__product','variant__product__brand')
            applied_voucher = checkout.voucher_code
            for checkout_line in checkout_lines:
                prod = checkout_line.variant.product
                brand_id = prod.brand_id
                prod_id = prod.id
                products_list.append(prod_id)
                if brand_id not in brand_list:
                    brand_dict[brand_id] = [prod_id]
                    brand_list.append(brand_id)
                else:
                    brand_dict[brand_id].append(prod_id)

        except Exception as e:
            raise ValueError(e)    

    todays_date = TimeUtilities.get_current_date_time()

    voucher_qs = Voucher.objects.filter(store_id =store_id).active(todays_date).exclude(Q(name__startswith='SZ')|Q(code = applied_voucher)|(Q(metadata__has_key='hide_listing')&Q(metadata__hide_listing = True)))

    if app_code != PlatformTypeEnum.ZAAMO_STORE:
        voucher_qs = voucher_qs.exclude(Q(metadata__has_key='app_code')&Q(metadata__app_code = 'ZS'))

    if not (app_code == "" and platform_code == PlatformTypeEnum.INFLUENCER_STORE):
        voucher_qs = voucher_qs.exclude(Q(metadata__has_key='app_code')&Q(metadata__app_code = 'IS_WEB'))

    voucher_list = voucher_qs.filter(Q(products__in = products_list)|Q(type = VoucherType.ENTIRE_ORDER)|Q(brands__in = brand_list))
    # botd_voucher = voucher_qs.filter(name='BOTD').prefetch_related('brands')
    # cotd_voucher = voucher_qs.filter(name='COTD').prefetch_related('collections')

    voucher_mixed_brand_qs = Voucher.objects.filter(type = VoucherType.SPECIFIC_BRAND_PRODUCTS , brands__in = brand_list).active(todays_date).exclude(Q(name__startswith='SZ')|Q(code = applied_voucher)|(Q(metadata__has_key='hide_listing')&Q(metadata__hide_listing = True))).prefetch_related('brands','collections','products','collections__products','categories__products')

    if app_code != PlatformTypeEnum.ZAAMO_STORE:
        voucher_mixed_brand_qs = voucher_mixed_brand_qs.exclude(Q(metadata__has_key='app_code')&Q(metadata__app_code = 'ZS'))
    
    if not (app_code == "" and platform_code == PlatformTypeEnum.INFLUENCER_STORE):
        voucher_mixed_brand_qs = voucher_mixed_brand_qs.exclude(Q(metadata__has_key='app_code')&Q(metadata__app_code = 'IS_WEB'))

    mixed_brand_brands = voucher_mixed_brand_qs.filter(Q(products__isnull = True)&Q(brands__in = brand_list)&Q(categories__isnull = True)&Q(collections__isnull=True) ).values('id')
    mixed_brand_products = voucher_mixed_brand_qs.filter(Q(products__in = products_list)).values('id')

    for brand_id in brand_dict:
        prod_list = brand_dict[brand_id]
        mixed_brand_category = voucher_mixed_brand_qs.filter(Q(categories__products__in = prod_list)&Q(brands = brand_id)).values('id')
        mixed_brand_collection = voucher_mixed_brand_qs.filter(Q(collections__products__in = prod_list)&Q(brands = brand_id)).values('id')
        
        
        voucher_list = voucher_list.union(mixed_brand_category)
        voucher_list = voucher_list.union(mixed_brand_collection)
        
    voucher_list = voucher_list.union(mixed_brand_products)
    voucher_list = voucher_list.union(mixed_brand_brands)

    # if botd_voucher:
    #     first_botd_voucher = botd_voucher.first()
    #     botd_brand = first_botd_voucher.brands.first()
    #     if botd_brand:
    #         botd_brand_id = botd_brand.id
    #         if botd_brand_id in brand_list:
    #             voucher_list = voucher_list.union(botd_voucher)

    # if cotd_voucher:
    #     first_cotd_voucher = cotd_voucher.first()
    #     cotd_collection = first_cotd_voucher.collections.first()
    #     if cotd_collection:
    #         collection_products = cotd_collection.products.all().values_list('pk',flat=True)
    #         final_list = [value for value in collection_products if value in products_list]
    #         if len(final_list)>0:
    #             voucher_list = voucher_list.union(cotd_voucher)

    if checkout_id:
        voucher_ids_list  = voucher_list.values_list('id',flat=True)

        voucher_qs = Voucher.objects.annotate(is_applicable = Case(When(id__in =voucher_ids_list, then=True), default=False,output_field=BooleanField()))

        voucher_qs = voucher_qs.filter(Q(store_id = store_id)|Q(is_applicable=True)).active(todays_date).exclude(Q(name='COTD')|Q(name='BOTD',owner__in=[VoucherOwner.BRAND,VoucherOwner.ZAAMO])|Q(name__startswith='SZ')|Q(code__icontains = 'DISGRPB30')|Q(code__icontains='DISGRPB_30')|(Q(metadata__has_key='hide_listing')&Q(metadata__hide_listing = True)))

        return voucher_qs.order_by('-owner')
    
    else:
        
        return Voucher.objects.filter(id__in=voucher_list.values('id')).order_by('-owner')


