from django.conf import settings
from saleor.brand.states import BrandStatusEnum
from saleor.utilities.request_utilities import RequestUtilities, PlatformTypeEnum
from saleor.store.store_utilities import get_instance_for_store
from saleor.store.models import StoreCategoryPage,StoreCategoryPageLevels
from saleor.brand import models as brand_models
from django.db.models import Count, Q, F, Case, When,PositiveIntegerField
from saleor.store.models import StoreCategoryPage, StoreInfo
from saleor.product.models import SourcingRequestStatus

def resolve_brands(root,info):

    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    platform = RequestUtilities.get_platfrom_type_from_headers(info.context)
    store_instance = get_instance_for_store(store_id)
    
    

    if store_instance.store_name == 'zaamo' or (platform==PlatformTypeEnum.INFLUENCER_STORE and store_instance.store_category_page_level == StoreCategoryPageLevels.LEVEL_3):
        brand_ids = [instance.brand_id for instance in root.through_brand_group_mapping.filter(brand__status__in=[BrandStatusEnum.ACTIVE])]
        return brand_models.Brand.objects.filter(id__in=brand_ids).prefetch_related('through_brand_group_mapping').filter(through_brand_group_mapping__brand_group_id=root.id).annotate(
            brand_group_rank = F('through_brand_group_mapping__brand_group_rank')
        )


    if platform==PlatformTypeEnum.INFLUENCER_STORE:
        brand_ids_from_brand_group_mapping = [instance.brand_id for instance in root.through_brand_group_mapping.filter(brand__status__in=[BrandStatusEnum.ACTIVE])]
        brand_ids = StoreCategoryPage.objects.filter(
            store_id =store_id,
            brand_id__in = brand_ids_from_brand_group_mapping
        ).values_list('brand_id',flat = True)

        
        return brand_models.Brand.objects.filter(id__in=brand_ids).filter(status__in=[BrandStatusEnum.ACTIVE]).prefetch_related('through_brand_group_mapping').filter(through_brand_group_mapping__brand_group_id=root.id).annotate(
            brand_group_rank = F('through_brand_group_mapping__brand_group_rank')
        )

    else:
        brand_ids = [instance.brand_id for instance in root.through_brand_group_mapping.filter(brand__status__in=[BrandStatusEnum.ACTIVE])]

        return brand_models.Brand.objects.filter(id__in=brand_ids).prefetch_related('through_brand_group_mapping').filter(through_brand_group_mapping__brand_group_id=root.id).annotate(
            brand_group_rank = F('through_brand_group_mapping__brand_group_rank')
        )

def resolve_payout_for_brand(brand_id):
    brand_payout = brand_models.BrandPayout.objects.filter(brand_id = brand_id)

    return brand_payout

def resolve_brand_collections():
    qs = brand_models.BrandCollection.objects.filter(active=True)
    return qs

def resolve_botd_brands(root, info, **kwargs):
    
    return brand_models.Brand.objects.filter(Q(status__in=[BrandStatusEnum.ACTIVE]) & Q(botd=True) & Q(too_many_orders = False))


def resolve_brand_from_slug(slug):
    
    return brand_models.Brand.objects.filter(slug=slug).first()

class BrandBarterRequestClubbedResolvers:

    @staticmethod
    def resolve_ongoing(root, info):
        coupon_created = [SourcingRequestStatus.BRAND_COUPON_CREATED, SourcingRequestStatus.ZAAMO_COUPON_CREATED]
        exclude_status = [
            SourcingRequestStatus.BRAND_COLLAB_APPROVED,
        ]
        include_status = [
            SourcingRequestStatus.BRAND_SHARED_DELIVERABLES,
            SourcingRequestStatus.INFLUENCER_HAS_SHARED_THE_DELIVERABLES,
        ]

        exclude_stores = StoreInfo.objects.filter(product_sourcing__brand_id=root.id, product_sourcing__status__in=exclude_status).distinct()

        qs = StoreInfo.objects.all()
        qs = qs.exclude(id__in=exclude_stores)
        qs = qs.filter(product_sourcing__brand_id=root.id, product_sourcing__status__in=include_status).distinct()
        qs = qs.annotate(no_of_requests=Count('product_sourcing', filter=Q(product_sourcing__brand_id=root.id)))
        qs = qs.annotate(recommended=Count('product_sourcing',filter=Q(product_sourcing__brand_id=root.id,product_sourcing__recommended=True)))
        return qs

    @staticmethod
    def resolve_request_received(root, info):
        coupon_created = [SourcingRequestStatus.BRAND_COUPON_CREATED, SourcingRequestStatus.ZAAMO_COUPON_CREATED]
        exclude_status = [
            SourcingRequestStatus.BRAND_SHARED_DELIVERABLES,
            SourcingRequestStatus.INFLUENCER_HAS_SHARED_THE_DELIVERABLES,
            SourcingRequestStatus.BRAND_COLLAB_APPROVED,
        ]
        include_status = [
            SourcingRequestStatus.REQUEST_RECIEVED,
            SourcingRequestStatus.BRAND_HOLD,
        ]

        exclude_stores = StoreInfo.objects.filter(product_sourcing__brand_id=root.id, product_sourcing__status__in=exclude_status).distinct()

        qs = StoreInfo.objects.all()
        qs = qs.exclude(id__in=exclude_stores)
        qs = qs.filter(product_sourcing__brand_id=root.id, product_sourcing__status__in=include_status).distinct()
        qs = qs.annotate(no_of_requests=Count('product_sourcing', filter=Q(product_sourcing__brand_id=root.id)))
        qs = qs.annotate(recommended=Count('product_sourcing',filter=Q(product_sourcing__brand_id=root.id,product_sourcing__recommended=True)))
        return qs

    @staticmethod
    def resolve_total_store_count(root, info):
        return StoreInfo.objects.filter(product_sourcing__brand_id=root.id).values_list('product_sourcing').count()
    
    @staticmethod
    def resolve_store_count(root, info):
        coupon_created = [SourcingRequestStatus.BRAND_COUPON_CREATED, SourcingRequestStatus.ZAAMO_COUPON_CREATED]

        qs = StoreInfo.objects.all()
        qs = qs.exclude(metadata__store_barter=False)
        qs = qs.filter(product_sourcing__brand_id=root.id)
        qs = qs.annotate(no_of_requests=Count('product_sourcing', filter=Q(product_sourcing__brand_id=root.id)))
        qs = qs.annotate(coupon_created=Count('product_sourcing', filter=Q(product_sourcing__brand_id=root.id, product_sourcing__status__in=coupon_created)))
        qs = qs.annotate(recommended=Count('product_sourcing',filter=Q(product_sourcing__brand_id=root.id,product_sourcing__recommended=True)))
        return qs

    @staticmethod
    def resolve_no_of_requests(root, info):
        count = 0
        if hasattr(root, 'no_of_requests'):
            count = root.no_of_requests
        
        return count

