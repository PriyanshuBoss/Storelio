from collections import defaultdict
from random import shuffle, sample
import random
import re
import graphene
from saleor.order.models import OrderLine
from saleor.store.store_utilities import get_instance_for_store
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.request_utilities import RequestUtilities
from django.db.models import Subquery, OuterRef, Prefetch
from django.db.models.functions import Coalesce,Round
from saleor.wishlist.models import WishlistItem
from django.db.models import Count, Case, When,Q,Sum,Avg, IntegerField,  Value, F
from ...order import OrderStatus
from ...product import models
from ...brand import models as brand_models
from ..utils import get_database_id, get_user_or_app_from_context, get_requested_fields
from ..utils.filters import filter_by_period
from .filters import filter_products_by_stock_availability, product_grouping_search, product_search
from saleor.utilities.django_utilities import Random


def resolve_attributes(info, qs=None, **_kwargs):
    requestor = get_user_or_app_from_context(info.context)
    qs = qs or models.Attribute.objects.get_visible_to_user(requestor)
    return qs.distinct()


def resolve_category_by_slug(slug):
    return models.Category.objects.filter(slug=slug).first()


def resolve_categories(info, level=None, **_kwargs):
    qs = models.Category.objects.prefetch_related("children")
    if level is not None:
        qs = qs.filter(level=level)
    return qs.distinct()


def resolve_collection_by_slug(info, slug):
    return (
        models.Collection.objects.filter(slug=slug).first()
    )


def resolve_collections(info, **_kwargs):
    
    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    store_instance = get_instance_for_store(store_id)
    
    if not store_instance:
        return models.Collection.objects.none()

    if store_instance.store_name != 'zaamo':
        collection_list= list(models.CollectionStore.objects.filter(store=store_id).values_list('collection', flat=True))
        
        store_name = Subquery(
            models.CollectionStore.objects.filter(collection_id=OuterRef("pk"))
            .values_list("store__store_name", flat=True)[:1]
        )
        collection_list = models.Collection.objects.filter(id__in=collection_list, is_default=False).annotate(store_name=store_name)

    else:
        # exclude = Subquery(models.Collection.objects.annotate(
        #     product_count=Count(
        #         'products__id',
        #         distinct=True,
        #         filter=Q(Q(products__is_published=True) , Q(products__brand__status='active'))
        #     )).filter(product_count__lte=15
        #     ).values_list('id', flat=True))
        
        store_name = Subquery(
            models.CollectionStore.objects.filter(collection_id=OuterRef("pk"))
            .values_list("store__store_name", flat=True)[:1]
        )
        

        collection_product_gt_10 = Subquery(models.Collection.objects.filter(Q(products__is_published=True), Q(products__brand__status='active'), Q(products__metadata__instock=True)).annotate(
            product_count=Count("products")).filter(product_count__gt=25).filter(
                is_default=False).values('id'))
        store_name = Subquery(
            models.CollectionStore.objects.filter(collection_id=OuterRef("pk"))
            .values_list("store__store_name", flat=True)[:1]
        )
        
        collection_list = models.Collection.objects.filter(
            id__in=collection_product_gt_10).annotate(store_name=store_name)

        
        
    # if collection_list:
    return collection_list.annotate(random = Round(Random(seed=0)*100000+1,output_field=IntegerField()))
    
    # return models.Collection.objects.none()


def resolve_digital_contents(info):
    return models.DigitalContent.objects.all()


def resolve_product_by_slug(info, slug):
    requestor = get_user_or_app_from_context(info.context)
    return models.Product.objects.select_related("brand").visible_to_user(requestor).filter(slug=slug).first()


def resolve_my_picks(store_id, qs):

    if store_id:
        store_products = (models.CollectionStore.objects.prefetch_related("collection__products").filter(
        store=store_id).values_list("collection__products", flat=True).distinct())
        qs = qs.filter(id__in=Subquery(store_products))

    return qs

def resolve_products(info, stock_availability=None, my_picks=False,  **_kwargs):
    user = get_user_or_app_from_context(info.context)
    store_id = RequestUtilities.get_store_id_from_headers(info.context)
    qs = models.Product.objects.select_related('brand')

    if my_picks:
        qs = resolve_my_picks(store_id, qs)

    if stock_availability:
        qs = filter_products_by_stock_availability(qs, stock_availability)

    if not qs.user_has_access_to_all(user):
        qs = qs.exclude(visible_in_listings=False)

    resolve_visits = False
    requested_fields = get_requested_fields(info)

    try:
    
        if 'visits' in requested_fields['products']['edges']['node']:
            resolve_visits = True
    
    except KeyError:
        pass


    try:
    
        if 'collections' in requested_fields['products']['edges']['node']:
            qs = qs.prefetch_related(Prefetch(
                            "collections"
                        ))
    
    except KeyError:
        pass

    if resolve_visits:

        if store_id:
            product_visits = models.StoreProductViews.objects.filter(product=OuterRef('pk'), store=store_id).values('product')\
                .annotate(sum=Sum('views')).values('sum')
            qs = qs.annotate(visits=Coalesce(Subquery(product_visits), 0))
        else:
            product_visits = models.StoreProductViews.objects.filter(product=OuterRef('pk')).values('product')\
                .annotate(sum=Sum('views')).values('sum')
            qs = qs.annotate(visits=Coalesce(Subquery(product_visits), 0))
            
    return qs.distinct()

def resolve_product_types(info, **_kwargs):
    return models.ProductType.objects.all()


def resolve_product_variant_by_sku(info, sku):
    requestor = get_user_or_app_from_context(info.context)
    visible_products = models.Product.objects.visible_to_user(requestor).values_list(
        "pk", flat=True
    )
    return (
        models.ProductVariant.objects.filter(product__id__in=visible_products)
        .filter(sku=sku)
        .first()
    )


def resolve_product_variants(info, ids=None):
    user = get_user_or_app_from_context(info.context)

    visible_products = models.Product.objects.visible_to_user(user).values_list(
        "pk", flat=True
    )
    if not visible_products.user_has_access_to_all(user):
        visible_products = visible_products.exclude(visible_in_listings=False)

    qs = models.ProductVariant.objects.filter(product__id__in=visible_products)
    if ids:
        db_ids = [get_database_id(info, node_id, "ProductVariant") for node_id in ids]
        qs = qs.filter(pk__in=db_ids)

    return qs


def resolve_all_collections(info, **kwargs):
    
    if kwargs.get('randomized', True):
        qs = models.Collection.objects.filter(metadata__landing= True)
        collection_ids = list(qs.values_list(flat=True))
        collection_ids_len = len(collection_ids)
        shuffle(collection_ids)
        limit = kwargs.get('first',10)

        if limit > collection_ids_len:
            limit = collection_ids_len

        randomized_list = sample(collection_ids, limit)
        
        return qs.filter(id__in=randomized_list)

    else:
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        qs =  models.Collection.objects.filter(ideas=True).exclude(collection_store__store=store_id)
        
        return qs

def resolve_report_product_sales(period):
    qs = models.ProductVariant.objects.all()

    # exclude draft and canceled orders
    exclude_status = [OrderStatus.DRAFT, OrderStatus.CANCELED]
    qs = qs.exclude(order_lines__order__status__in=exclude_status)

    # filter by period
    qs = filter_by_period(qs, period, "order_lines__order__created")

    qs = qs.annotate(quantity_ordered=Sum("order_lines__quantity"))
    qs = qs.filter(quantity_ordered__isnull=False)
    return qs.order_by("-quantity_ordered")

def resolve_landing_categories(info, **kwargs):
    
    return models.LandingPageCategories.objects.filter(is_visible=True)

def resolve_wishlist_count_product(root, _info):
    return WishlistItem.objects.filter(product_id=root.id).count()
    
def resolve_order_count_product(root, _info):
    return (OrderLine.objects.filter(variant_id__in=Subquery(
                models.ProductVariant.objects.filter(product_id=root.id).values('id'))).count())
    
def resolve_store_count_product(root, _info):
    return (models.CollectionStore.objects.filter
            (collection_id__in=Subquery(models.CollectionProduct.objects.filter(product_id=root.id)
            .values('collection_id'))).count())

def clean_product_name_phrase(product_name):
    
    color_tags = ["Lavender", "Black", "Lilac", "Sky blue", "Green", "Brown", "Neon", "Pink", "Contrast", "Gold", "Blue", "Champagne", 
    "Red", "White", "Grey", "Beige", "Mint","Silver","aqua","maroon","mustard","navy","olive","orange","pastel","peach","purple",
    "rainbow","rose","teal","wine","yellow"]
    
    product_name = product_name.lower().split(' ')
    
    for color_tag in color_tags:

        for product_n in product_name:

            if product_n in color_tag.lower() or color_tag.lower() in product_n:
                
                product_name.remove(product_n)

    return ' '.join(product_name)

def product_name_match_id(product_name_phrase,length=0,product_ids = []):
    
    if length>5 or not len(product_name_phrase.split(' '))>1:
        return product_ids

    if length==0:
        product_name_phrase = clean_product_name_phrase(product_name_phrase)

    if length>0:
        product_name_phrase = product_name_phrase.split(' ')
        product_name_phrase.pop()
        product_name_phrase = ' '.join(product_name_phrase)

    product_name_matched_ids = []
    product_name_matched_ids = product_search(product_name_phrase)[:5]
    
    for product in product_name_matched_ids:
        if not product.id in product_ids:
            product_ids.append(product.id)

    return product_name_match_id(product_name_phrase,len(product_ids),product_ids)

def resolve_similar_products(info,less_price=False,**_kwargs):
    product_id_global = _kwargs.get('id')
    # view_all = _kwargs.get('view_all')
    view_all = False
    category_ids_global = _kwargs.get('category_ids')
    tag_ids_global = _kwargs.get('tag_ids')
    category_ids = []
    tag_filter_ids = set()

    if category_ids_global:

        for id in category_ids_global:
            category_ids.append(NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(id)[1]))
    
    
    if tag_ids_global:

        for id in tag_ids_global:
            tag_filter_ids.add(NumberUtilities.convert_string_to_number(graphene.Node.from_global_id(id)[1]))

    product_name_matched_ids=[]
    qs = []
    if product_id_global:

        product_id = graphene.Node.from_global_id(product_id_global)[1]
        product_id = NumberUtilities.convert_string_to_number(product_id)
        tags = models.ProductTagMapping.objects.filter(product_id=product_id)
        tag_ids = [tag.product_tag_id for tag in tags]

        if not tag_ids:
            return qs
        
        product_name = tags.first().product.name
        if tag_filter_ids:
            
            tag_ids = set(tag_ids).intersection(tag_filter_ids)
            tag_ids = list(tag_ids)

        n = len(tag_ids)
        
        if  view_all:
            product_related = models.ProductTagMapping.objects.filter(product_tag_id__in=tag_ids).values('product_id').annotate(strength=(Sum('weight')/n) + Avg('percentile')).order_by('-strength')
            
        else:
            product_related = models.ProductTagMapping.objects.filter(product_tag_id__in=tag_ids).values('product_id').annotate(strength=(Sum('weight')/n) + Avg('percentile')).order_by('-strength')[:50]
        
        product_ids = []
        mapping=models.BrandVariantZaamoMapping.objects.filter(product_zaamo_id=product_id).only('product_id_brand').first()

        if mapping:
            mapped_product = models.BrandVariantZaamoMapping.objects.filter(product_id_brand=mapping.product_id_brand).values_list('product_zaamo_id',flat=True).distinct()
            product_ids.extend(mapped_product_id for mapped_product_id in mapped_product if not mapped_product_id==product_id)

        product_name_matched_ids.clear()
        product_name_matched_ids=[]
        product_name_matched_ids = product_name_match_id(product_name,0,[])

        product_ids.extend([product for product in product_name_matched_ids if not product in product_ids])
        
        product_ids.extend([id['product_id'] for id in product_related if not id['product_id'] in product_ids])
        
        if product_ids:
            
            preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(product_ids)])
            if less_price:
                current_product = models.Product.objects.filter(id=product_id).first()
                qs = models.Product.objects.filter(id__in=product_ids,is_published=True,metadata__instock=True,minimal_variant_price_amount__lte=current_product.minimal_variant_price_amount).exclude(id=product_id).select_related('brand').distinct()
            else:
                qs = models.Product.objects.filter(id__in=product_ids,is_published=True,metadata__instock=True).exclude(id=product_id).select_related('brand').distinct()
                
            if category_ids:
                qs = qs.filter(category_id__in=category_ids)
            
            qs = qs.order_by(preserved)
            
    return qs

def resolve_tagged_products(root,info,**_kwargs):
    
    category_ids_global = _kwargs.get('category_ids')
    category_ids = []

    if category_ids_global:

        for id in category_ids_global:
            category_ids.append(graphene.Node.from_global_id(id)[1])

    if category_ids:
        p_ids = root.through_product_tag.filter(Q(product__category_id__in=category_ids)).select_related('product').order_by('weight')

    else:
        p_ids = root.through_product_tag.all().select_related('product').order_by('weight')

    return [qs.product for qs in p_ids]


def resolve_product_tag_mappings(info, **kwargs):
    product_id = graphene.Node.from_global_id(kwargs.get('productid'))[1]
    return models.ProductTagMapping.objects.filter(product_id=product_id).select_related('product','product_tag').order_by('weight')

def resolve_fetch_product_collections(info, **kwargs):
    product_id = graphene.Node.from_global_id(kwargs.get('productid'))[1]
    store_id = RequestUtilities.get_store_id_from_headers(info.context)
     
    collection_list = models.CollectionProduct.objects.filter(product_id=product_id).values_list('collection_id',flat=True)

    qs = models.Collection.objects.prefetch_related('collection_store').filter(
        id__in = collection_list,
        collection_store__store_id = store_id
    )
    
    return qs

def resolve_product_view(info, slug):
    return models.Product.objects.select_related("brand").filter(slug=slug).first()

def clean_product_grouping_details_to_check(product):
    
    to_check = {
                "category": "",
                "brandCollection": set(),
                "brand": "",
                "productTags": set(),
                "price": 0,
                "discount": 0,
                "valueDeal": False,
                "field": "TAG_STRENGTH",
                "direction": "DESC"
                }
    first_itr = True

    for _prod in product:
    
        if first_itr:

            to_check["category"] = graphene.Node.to_global_id("Category",_prod.get('category_id'))
            to_check["brand"] = graphene.Node.to_global_id("Brand",_prod.get('brand_id'))
            to_check["price"] = NumberUtilities.convert_string_to_float(_prod.get('default_variant__price_amount'))
            to_check["discount"] = NumberUtilities.convert_string_to_float(_prod.get('discount'))
            to_check["valueDeal"] = _prod.get('metadata__value_deal') or False

        to_check["productTags"].add(graphene.Node.to_global_id("ProductTag",_prod.get('through_product_tag_product__product_tag_id')))
        to_check["brandCollection"].add(graphene.Node.to_global_id("BrandCollection",_prod.get('through_brand_collection_product__brand_collection_id')))
        first_itr=False
        
    return to_check

def resolve_product_grouping_mapping(info,**kwargs):
    return models.ProductGrouping.objects.filter(Q(private_metadata__less_than_10_products = False) | Q(private_metadata__less_than_10_products__isnull = True))

def resolve_product_grouping(info, id,group_name,**kwargs):
    if group_name:
        qs = product_grouping_search(group_name)
        
    else:
        qs = models.ProductGrouping.objects.all()

    '''
    Filtering out groups with count less than 10, This would be updated to a filter later
    '''
    qs = qs.filter(Q(private_metadata__less_than_10_products = False) | Q(private_metadata__less_than_10_products__isnull = True))
    
    if id:

        product_id = graphene.Node.from_global_id(id)[1]
        product = models.Product.objects.filter(id=product_id).first()

        if  product:
            '''
            product = (models.Product.objects.filter(id = product_id).values('id','category_id','brand_id','default_variant__price_amount',
                        'through_product_tag_product__product_tag_id','metadata__value_deal').annotate(discount = Case(When(default_variant=None, then=0),default = 
                        (F('default_variant__cost_price_amount') - F('default_variant__price_amount'))*100/F("default_variant__cost_price_amount"))))

            to_check = clean_product_grouping_details_to_check(product)
            
            filter_qs = (
                            Q(Q(rule__brands__contains = to_check['brand']) | Q(rule__brands = [])) & 
                            Q(Q(rule__categories__contains = to_check['category']) | Q(rule__categories = []))
                        )
            if to_check['valueDeal']:
                filter_qs &= Q(rule__valueDeal=to_check['valueDeal'])
            else:
                filter_qs &= Q(Q(rule__valueDeal=to_check['valueDeal']) | Q(rule__valueDeal__isnull=True))
                
            filter_up = (Q(filter_qs) & Q(Q(rule__price__gtequal__lte=to_check['price']) & Q(rule__price__ltequal__gte=to_check['price'])) &
                            Q(Q(rule__discount__gtequal__lte=to_check['discount']) & Q(rule__discount__ltequal__gte=to_check['discount'])))

            qs =  qs.filter(filter_up)

            id_groups = []

            for q in qs:
                if len(set(q.rule.get('productTags')).intersection(to_check['productTags']))==len(q.rule.get('productTags')):
                    id_groups.append(q.id)
            '''
            category_id = graphene.Node.to_global_id('Category',product.category_id)
            
            qs =  qs.filter(Q(id__in=Subquery(models.ProductGroupingMapping.objects.filter(product_id=product_id).values('product_grouping_id'))) | Q(rule__categories__contains=category_id))
            # qs =  qs.filter(id__in=Subquery(models.ProductGroupingMapping.objects.filter(product_id=product_id).values('product_grouping_id')))
    
    seed = kwargs.get('shuffle',0)
    sort_by = kwargs.get('sort_by')

    if sort_by:
    
        field = sort_by.get('field',[])

        if field and 'randomize' in field:
            
            qs = qs.annotate(randomize = Round(Random(seed=seed)*1000+1,output_field=IntegerField()))

    
    return qs

def resolve_product_grouping_meta(info,group_id, **kwargs):
    group_id = graphene.Node.from_global_id(group_id)[1]
    group = models.ProductGrouping.objects.filter(id=group_id).first()

    if group:
        rule = group.rule
        brand_ids_global = rule.get('brands',[])
        category_ids_global = rule.get('categories',[])
        product_tag_ids_global = rule.get('productTags',[])
        brand_collection_ids_global = rule.get('brandCollection',[])

        brand_ids = [graphene.Node.from_global_id(id)[1] for id in brand_ids_global]
        category_ids = [graphene.Node.from_global_id(id)[1] for id in category_ids_global]
        tag_ids = [graphene.Node.from_global_id(id)[1] for id in product_tag_ids_global]
        brand_collection_ids = [graphene.Node.from_global_id(id)[1] for id in brand_collection_ids_global]
        
        return {'brand_ids':brand_ids, 
                'category_ids':category_ids,
                'product_tag_ids':tag_ids,
                'brand_collection_ids':brand_collection_ids}
    
    return defaultdict(list)

def resolve_store_slug(store_id):

    store_instance = get_instance_for_store(store_id)
    return store_instance.slug
    