from collections import defaultdict
from decimal import Decimal
import time
from typing import Dict, List, Optional
from django.contrib.postgres.search import SearchVector,SearchQuery
from django.db.models import Q
from django.db.models import TextField
from django.db.models.functions import Cast
import django_filters
import graphene
from django.db.models import F, Q, Subquery, Sum, Case, When, Exists, OuterRef
from django.db.models.functions import Coalesce,Round
from graphene_django.filter import GlobalIDFilter, GlobalIDMultipleChoiceFilter
import re
from saleor.brand.models import Brand, BrandCollectionMapping, BrandTag, BrandTagMapping
from saleor.graphql.integrations.enums import BarterTypeEnum
from saleor.product import BarterType
from saleor.store.models import StoreInfo
from saleor.brand.states import BrandSourceEnum, BrandStatusEnum

from ...product.filters import filter_products_by_attributes_values
from ...product.models import (
    Attribute,
    AttributeValue,
    Category,
    Collection,
    Product,
    ProductGrouping,
    ProductTag,
    ProductTagMapping,
    ProductType,
    ProductVariant,
    BrandVariantZaamoMapping,
    SourcingRequest,
    BrandPriceRecord
)
from ...warehouse.models import Stock
from ..core.filters import EnumFilter, ListObjectTypeFilter, ObjectTypeFilter
from ..core.types import FilterInputObjectType
from ..core.types.common import IntRangeInput, PriceRangeInput,DateRangeInput
from ..core.utils import from_global_id_strict_type
from ..utils import (
    get_nodes,
    get_user_or_app_from_context,
    resolve_global_ids_to_primary_keys,
)
from ..utils.filters import filter_by_query_param, filter_range_field
from ..warehouse import types as warehouse_types
from .enums import (
    CollectionPublished,
    ProductTypeConfigurable,
    ProductTypeEnum,
    StockAvailability,
    CollectionMediaTypeEnum,
    SourcingRequestStatusTypeEnum,
    BrandCollabStatusForSouringRequestEnum
)
from saleor.graphql.brand.enums import BrandStatusEnums
from saleor.graphql.store.enums import StoreStatusEnums
from saleor.utilities.time_utilities import TimeUtilities
from saleor.graphql.order.enums import SourcingRequestOrderStatusFilterEnum

def filter_fields_containing_value(*search_fields: str):
    """Create a icontains filters through given fields on a given query set object."""

    def _filter_qs(qs, _, value):
        if value:
            qs = filter_by_query_param(qs, value, search_fields)
        return qs

    return _filter_qs


def _clean_product_attributes_filter_input(
    filter_value,
) -> Dict[int, List[Optional[int]]]:
    attributes = Attribute.objects.prefetch_related("values")
    attributes_map: Dict[str, int] = {
        attribute.slug: attribute.pk for attribute in attributes
    }
    values_map: Dict[str, Dict[str, int]] = {
        attr.slug: {value.slug: value.pk for value in attr.values.all()}
        for attr in attributes
    }
    queries: Dict[int, List[Optional[int]]] = defaultdict(list)
    # Convert attribute:value pairs into a dictionary where
    # attributes are keys and values are grouped in lists
    for attr_name, val_slugs in filter_value:
        if attr_name not in attributes_map:
            raise ValueError("Unknown attribute name: %r" % (attr_name,))
        attr_pk = attributes_map[attr_name]
        attr_val_pk = [
            values_map[attr_name][val_slug]
            for val_slug in val_slugs
            if val_slug in values_map[attr_name]
        ]
        queries[attr_pk] += attr_val_pk

    return queries

def filter_thrift_products(qs,_,value):
    if value:
        from saleor.product.models import Product
        store_id = graphene.Node.from_global_id(value)[1]
        store_collection = Collection.objects.filter(collection_store__store__id=store_id,is_thrift=True).first()
        qs = Product.objects.filter(collectionproduct__collection=store_collection,is_published = True)
      
    return qs


def filter_products_by_attributes(qs, filter_value):
    queries = _clean_product_attributes_filter_input(filter_value)
    return filter_products_by_attributes_values(qs, queries)

def filter_products_by_store(qs,_,value):
    if value:
        store_id = graphene.Node.from_global_id(value)[1]
        store_collection = Collection.objects.filter(collection_store__store__id=store_id)
        qs = qs.filter(collectionproduct__collection__in=store_collection).distinct()
    return qs

def filter_products_by_discount_price(qs, discount_lte=None, discount_gte=None):
    
    if not discount_lte==None:
        qs = qs.annotate(discount = Case(When(default_variant=None, then=0), When(default_variant__cost_price_amount=0,then=0),default = (F('default_variant__cost_price_amount') - F('default_variant__price_amount'))*100/F("default_variant__cost_price_amount"))).filter(discount__lte=Decimal(discount_lte))

    if not discount_gte==None:
        qs = qs.annotate(discount = Case(When(default_variant=None, then=0), When(default_variant__cost_price_amount=0,then=0),default = (F('default_variant__cost_price_amount') - F('default_variant__price_amount'))*100/F("default_variant__cost_price_amount"))).filter(discount__gte=Decimal(discount_gte))

    return qs

def filter_products_by_variant_price(qs, price_lte=None, price_gte=None):
    
    if not price_lte==None:
        
        qs = qs.filter(variants__price_amount__lte=price_lte)
    if not price_gte==None:
        
        qs = qs.filter(variants__price_amount__gte=price_gte)
    return qs

def filter_products_by_minimal_price(
    qs, minimal_price_lte=None, minimal_price_gte=None
):
    if minimal_price_lte:
        qs = qs.filter(minimal_variant_price_amount__lte=minimal_price_lte)
    if minimal_price_gte:
        qs = qs.filter(minimal_variant_price_amount__gte=minimal_price_gte)
    return qs


def filter_products_by_categories(qs, categories):
    
    categories = Category.objects.filter(id__in=categories)
    
    categories = [
        category.get_descendants(include_self=True).values('id') 
        if category.get_descendant_count()!=0 else [{'id': category.id}]
        for category in categories 
    ]
    
    ids = {category['id'] for tree in categories for category in tree}
    
    if len(ids)==1:
        return qs.filter(category=ids.pop())

    return qs.filter(category__in=ids)


def filter_products_by_collections(qs, collections):
    if isinstance(collections, (list, tuple, set)) and len(collections)==1:
        return qs.filter(collections=collections.pop())

    return qs.filter(collections__in=collections)

def filter_products_by_brands(qs, brands):
    
    if isinstance(brands, (list, tuple, set)) and len(brands)==1:
        return qs.filter(brand=brands.pop())
    return qs.filter(brand__in=brands)

def filter_products_by_tags(qs, tags):
    return qs.filter(id__in=Subquery(ProductTagMapping.objects.filter(product_tag_id__in=tags).values('product_id')))

def filter_products_by_brand_tags(qs, tags):
    return qs.filter(id__in=Subquery(BrandTagMapping.objects.filter(brand_tag_id__in=tags).values('product_id')))

def filter_products_by_brand_collections(qs, collections):
    return qs.filter(id__in=Subquery(BrandCollectionMapping.objects.filter(brand_collection_id__in=collections).values('product_id')))

# def filter_products_by_stock_availability(qs, stock_availability):
#     total_stock = (
#         Stock.objects.select_related("product_variant")
#         .values("product_variant__product_id")
#         .annotate(
#             total_quantity_allocated=Coalesce(Sum("allocations__quantity_allocated"), 0)
#         )
#         .annotate(total_quantity=Coalesce(Sum("quantity"), 0))
#         .annotate(total_available=Case(When(product_variant__track_inventory=False, then=1), 
#         default=(F("total_quantity") - F("total_quantity_allocated"))))
#         .filter(total_available__lte=0)
#     )
    
#     qs = qs.annotate(out_of_stock=Exists(total_stock.filter(product_variant__product_id=OuterRef('id'))))

#     if stock_availability == StockAvailability.IN_STOCK:
#         qs = qs.filter(out_of_stock=False)
        
#     elif stock_availability == StockAvailability.OUT_OF_STOCK:
#         qs = qs.filter(out_of_stock=True)

#     return qs


def filter_products_by_stock_availability(qs, stock_availability):
    # total_stock = (
    #     Stock.objects.select_related("product_variant")
    #     .values("product_variant__product_id")
    #     .annotate(
    #         total_quantity_allocated=Coalesce(Sum("allocations__quantity_allocated"), 0)
    #     )
    #     .annotate(total_quantity=Coalesce(Sum("quantity"), 0))
    #     .annotate(total_available=Case(When(product_variant__track_inventory=False, then=1), 
    #     default=(F("total_quantity") - F("total_quantity_allocated"))))
    #     .filter(total_available__lte=0)
    # )
    
    # qs = qs.annotate(out_of_stock=Exists(total_stock.filter(product_variant__product_id=OuterRef('id'))))

    if stock_availability == StockAvailability.IN_STOCK:
        qs = qs.filter(Q(metadata__instock=True) | Q(metadata__instock__isnull=True))
        
    elif stock_availability == StockAvailability.OUT_OF_STOCK:
        qs = qs.filter(metadata__instock=False)

    return qs


def filter_attributes(qs, _, value):
    if value:
        value_list = []
        for v in value:
            slug = v["slug"]
            values = [v["value"]] if "value" in v else v.get("values", [])
            value_list.append((slug, values))
        qs = filter_products_by_attributes(qs, value_list)
    return qs

def filter_products_by_timestamp(qs,_,value):
    end_date = TimeUtilities.get_current_date(False)
    if value:
        qs = qs.filter(publication_date__gte = value , publication_date__lte = end_date , is_published = True)
    return qs

def filter_collections_by_media(qs,_,value):
    if value:
        qs = qs.filter(media_type = value)
    return qs

def filter_categories(qs, _, value):
    if value:
        categories = resolve_global_ids_to_primary_keys(value, graphene_type="Category")[1]
        qs = filter_products_by_categories(qs, categories)
    return qs

def filter_brands(qs, _, value):
    if value:
        brands = resolve_global_ids_to_primary_keys(value, graphene_type="Brand")[1]
        qs = filter_products_by_brands(qs, brands)
    return qs

def filter_product_tags(qs, _, value):
    if value:
        tags = resolve_global_ids_to_primary_keys(value, graphene_type="ProductTag")[1]
        qs = filter_produt_tag_intersection(qs, tags)

    return qs

def filter_produt_tag_intersection(qs, tags):
    tags_length = len(tags)
    
    if tags_length > 5:
        return Product.objects.none()
    
    product_list = list(ProductTagMapping.objects.filter(product_tag_id__in=tags).values_list('product_id', flat=True))
        
    intersection_dict = {}
    product_intersection_list = []

    for product in product_list:
        if intersection_dict.get(product) is not None:
            intersection_dict[product] += 1   
        else:
            intersection_dict[product] = 1

        if intersection_dict.get(product) == tags_length:
            product_intersection_list.append(product)   

    qs = qs.filter(id__in=product_intersection_list)
        
    return qs

def filter_brand_tags(qs, _, value):
    
    if value:
        tags = resolve_global_ids_to_primary_keys(value, graphene_type="BrandTag")[1]
        qs = filter_products_by_brand_tags(qs, tags)
        
    return qs

def filter_brand_collections(qs, _, value):
    
    if value:
        tags = resolve_global_ids_to_primary_keys(value, graphene_type="BrandCollection")[1]
        qs = filter_products_by_brand_collections(qs, tags)
        
    return qs

def filter_has_category(qs, _, value):
    return qs.filter(category__isnull=not value)


def filter_collections(qs, _, value):
    if value:
        collections = resolve_global_ids_to_primary_keys(value, graphene_type="Collection")[1]
        qs = filter_products_by_collections(qs, collections)
    return qs


def filter_variant_price(qs, _, value):
    qs = filter_products_by_variant_price(
        qs, price_lte=value.get("lte"), price_gte=value.get("gte")
    )
    return qs


def filter_variant_discount(qs, _, value):
    qs = filter_products_by_discount_price(
        qs, discount_lte=value.get("lte"), discount_gte=value.get("gte")
    )
    
    return qs

def filter_minimal_price(qs, _, value):
    qs = filter_products_by_minimal_price(
        qs, minimal_price_lte=value.get("lte"), minimal_price_gte=value.get("gte")
    )
    return qs


def filter_stock_availability(qs, _, value):
    if value:
        qs = filter_products_by_stock_availability(qs, value)

    return qs

def filter_sourcing_request_by_stores(qs,_,value):

    if value:
        stores = get_nodes(value, "Store", StoreInfo)
        qs = qs.filter(store__in = stores)
    
    return qs

def filter_sourcing_request_by_category_ids(qs,_,value):
    if value:
        category_ids = resolve_global_ids_to_primary_keys(value, graphene_type="Category")[1]
        qs = qs.filter(product__category_id__in = category_ids)
    
    return qs

def filter_sourcing_request_by_next_date(qs,_,value):
    return filter_range_field(qs,"next_date",value)

def filter_sourcing_request_by_order_status(qs,_,value):
    
    if value:
        qs = qs.filter(order_status__in = value)
    
    return qs

def filter_sourcing_request_by_brands(qs,_,value):

    if value:
        brands = get_nodes(value,"Brand",Brand)
        qs = qs.filter(brand__in = brands)
    
    return qs

def filter_sourcing_request_by_status(qs,_,value):

    if value:
        qs = qs.filter(status__in = value)
    
    return qs

def filter_sourcing_request_by_store_status(qs,_,value):

    if value:
        qs = qs.filter(store__actions__status__in = value)
    
    return qs

def filter_sourcing_request_by_timeperiod(qs,_,value):
    return filter_range_field(qs,"updated_at",value)

def filter_sourcing_request_by_store_barter(qs,_,value):
    
    return qs.filter(store__metadata__store_barter=value)

def filter_sourcing_request_by_recommended(qs,_,value):
    if value is not None:
        qs = qs.filter(recommended=value)
    
    return qs

def filter_sourcing_request_by_brand_collab(qs,_,value):
    
    if value:
        qs = qs.filter(brand_collab = value)

    return qs

def product_search(phrase):
    """Return matching products for storefront views.

    Fuzzy storefront search that is resistant to small typing errors made
    by user. Name and description is matched using search vector.

    Args:
        phrase (str): searched phrase

    """
    # First four unused, can add description to search_vector when we want, before that
    # FIXME have to add weights to these values
    # ft_in_name = Q(search_vector=phrase)
    # ft_by_brand = Q(brand__brand_name__search=phrase)
    # ft_by_category = Q(category__name__search=phrase)
    # ft_by_product_type = Q(product_type__name__search=phrase)
    # ft_by_description_json = Q(descriptionsearch=phrase)
    # descriptionsearch=SearchVector(Cast('description_json', TextField()))
    search_vector = SearchVector('name')+SearchVector('brand__brand_name')\
        +SearchVector('category__name')+SearchVector('product_type__name')
    query = parse_phrase_for_search(phrase)
    qs =  Product.objects.annotate(vector = search_vector).select_related('brand')
    qs = qs.extra(
            where=[
                '''
                to_tsvector('english',concat_ws(' ',
                    product_product.name,
                    brand_brand.brand_name,
                    product_category.name
                )) @@ to_tsquery('english', %s)
                '''
            ],
            params=[query],
        )
    return qs

def product_grouping_search(phrase):
    """Return matching product grouping.

    Fuzzy storefront search that is resistant to small typing errors made
    by user. Name and description is matched using search vector.

    Args:
        phrase (str): searched phrase

    """
    search_vector = SearchVector('name')
    query = parse_phrase_for_search(phrase)
    qs =  ProductGrouping.objects.annotate(vector = search_vector)
    qs = qs.extra(
            where=[
                '''
                to_tsvector('english',concat_ws(' ',
                    product_productgrouping.name
                )) @@ to_tsquery('english', %s)
                '''
            ],
            params=[query],
        )
    return qs

def parse_phrase_for_search(phrase):
    query = re.sub(r'[!\'()|&:]', ' ', phrase).strip()
    if query:
        query = re.sub(r'\s+', ' & ', query)
        # Support prefix search on the last word. A tsquery of 'toda:*' will
        # match against any words that start with 'toda', which is good for
        # search-as-you-type.
        query += ':*'
    return query


def filter_search(qs, _, value):
    if value:
        qs =  product_search(value).distinct() & qs.distinct()
    return qs


def filter_collection_publish(qs, _, value):
    if value == CollectionPublished.PUBLISHED:
        qs = qs.filter(is_published=True)
    elif value == CollectionPublished.HIDDEN:
        qs = qs.filter(is_published=False)
    return qs


def filter_product_type_configurable(qs, _, value):
    if value == ProductTypeConfigurable.CONFIGURABLE:
        qs = qs.filter(has_variants=True)
    elif value == ProductTypeConfigurable.SIMPLE:
        qs = qs.filter(has_variants=False)
    return qs


def filter_product_type(qs, _, value):
    if value == ProductTypeEnum.DIGITAL:
        qs = qs.filter(is_digital=True)
    elif value == ProductTypeEnum.SHIPPABLE:
        qs = qs.filter(is_shipping_required=True)
    return qs


def filter_attributes_by_product_types(qs, field, value, requestor):
    if not value:
        return qs

    product_qs = Product.objects.visible_to_user(requestor)

    if field == "in_category":
        category_id = from_global_id_strict_type(
            value, only_type="Category", field=field
        )
        category = Category.objects.filter(pk=category_id).first()

        if category is None:
            return qs.none()

        tree = category.get_descendants(include_self=True)
        product_qs = product_qs.filter(category__in=tree)

        if not product_qs.user_has_access_to_all(requestor):
            product_qs = product_qs.exclude(visible_in_listings=False)

    elif field == "in_collection":
        collection_id = from_global_id_strict_type(
            value, only_type="Collection", field=field
        )
        product_qs = product_qs.filter(collections__id=collection_id)

    else:
        raise NotImplementedError(f"Filtering by {field} is unsupported")

    product_types = set(product_qs.values_list("product_type_id", flat=True))
    return qs.filter(
        Q(product_types__in=product_types) | Q(product_variant_types__in=product_types)
    )


def filter_stocks(qs, _, value):
    warehouse_ids = value.get("warehouse_ids")
    quantity = value.get("quantity")
    if warehouse_ids and not quantity:
        return filter_warehouses(qs, _, warehouse_ids)
    if quantity and not warehouse_ids:
        return filter_quantity(qs, quantity)
    if quantity and warehouse_ids:
        return filter_quantity(qs, quantity, warehouse_ids)
    return qs


def filter_warehouses(qs, _, value):
    if value:
        _, warehouse_pks = resolve_global_ids_to_primary_keys(
            value, warehouse_types.Warehouse
        )
        return qs.filter(variants__stocks__warehouse__pk__in=warehouse_pks)
    return qs


def filter_sku_list(qs, _, value):
    return qs.filter(sku__in=value)

def filter_products_by_price_drop(qs,_,value):

    price_drop_percentage  = value.get('price_drop_percentage',0)
    price_drop_days = value.get('price_drop_days',None)

    if price_drop_days:
        date_time = TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(),price_drop_days)

    global_products_id = BrandPriceRecord.objects.annotate(price_drop = Round((F("current_price_amount")-F("prev_price_amount"))*100/F("prev_price_amount"))).filter(price_drop=price_drop_percentage)
    if price_drop_days:
        global_products_id = global_products_id.filter(updated_at__gte=date_time)
    global_products_id_list = global_products_id.values_list('product_id_brand',flat=True).distinct()
    zaamo_product_id_list = BrandVariantZaamoMapping.objects.filter(product_id_brand__in = global_products_id_list).values_list('product_zaamo_id',flat=True).distinct()

    qs  = qs.filter(id__in = zaamo_product_id_list,is_published = True)

    return qs


def filter_quantity(qs, quantity_value, warehouses=None):
    """Filter products queryset by product variants quantity.

    Return product queryset which contains at least one variant with aggregated quantity
    between given range. If warehouses is given, it aggregates quantity only
    from stocks which are in given warehouses.
    """
    product_variants = ProductVariant.objects.filter(product__in=qs)
    if warehouses:
        _, warehouse_pks = resolve_global_ids_to_primary_keys(
            warehouses, warehouse_types.Warehouse
        )
        product_variants = product_variants.annotate(
            total_quantity=Sum(
                "stocks__quantity", filter=Q(stocks__warehouse__pk__in=warehouse_pks)
            )
        )
    else:
        product_variants = product_variants.annotate(
            total_quantity=Sum("stocks__quantity")
        )

    product_variants = filter_range_field(
        product_variants, "total_quantity", quantity_value
    )
    return qs.filter(variants__in=product_variants)

def filter_product_by_brand_status(qs, _, value):

    if value:
        if isinstance(value, (list, tuple, set)) and len(value)==1:
            return qs.filter(brand__status=value.pop())
        qs = qs.filter(brand__status__in = value)
    
    return qs

def filter_product_by_brand_barter(qs,_, value):

    if value:
        qs = qs.filter(Q(brand_barter__in = (BarterType.ACTIVE_BARTER , BarterType.ACTIVE_ONLY_BARTER)) & Q(brand__brand_barter = True))
    
    return qs

def filter_stock_order(qs, _, value):
    
    if value:
        qs_for_in_stock = filter_products_by_stock_availability(qs, StockAvailability.IN_STOCK) 
        
        if qs_for_in_stock.exists():
            qs = qs_for_in_stock

        else:
            qs_for_out_of_stock = filter_products_by_stock_availability(qs, StockAvailability.OUT_OF_STOCK)
            qs = qs_for_out_of_stock
        
    else:
        qs_for_out_of_stock = filter_products_by_stock_availability(qs, StockAvailability.OUT_OF_STOCK)
        
        if qs_for_out_of_stock.exists():
            qs = qs_for_out_of_stock
        else:
            qs_for_in_stock = filter_products_by_stock_availability(qs, StockAvailability.IN_STOCK)
            qs = qs_for_in_stock
    
    return qs 

def filter_request_containing_mail(qs,_,value):
    if value:
        qs = qs.filter(Q(influencer_managers__contains = value) | Q(brand_managers__contains = value))

    return qs

def filter_collection_by_steal_deal(qs,_,value):

    if value:
        qs = qs.filter(metadata__steal_deal = True)
    else:
        qs = qs.filter(Q(metadata__steal_deal = False) | Q(metadata__steal_deal__isnull = True))
    
    return qs

def filter_collection_by_landing(qs,_,value):

    if value:
        qs = qs.filter(metadata__landing = True)
    else:
        qs = qs.filter(Q(metadata__landing = False) | Q(metadata__landing__isnull = True))
    
    return qs
    

def filter_products_by_value_deal(qs,_,value):
    
    if value:
        qs = qs.filter(metadata__value_deal = True)
    
    return qs

def filter_products_by_shopify(qs,_,value):
    
    if value:
        qs = qs.filter(metadata__shopify = True)
    else:
        qs = qs.filter(Q(metadata__shopify = False) | Q(metadata__shopify__isnull = True))
    
    return qs

def filter_products_by_steal_deal(qs,_,value):
    
    if value:
        qs = qs.filter(id__in = Subquery(Collection.objects.filter(metadata__steal_deal = True).values('products')))
    
    return qs

def filter_collections_by_share(qs,_,value):
    
    if value==True:
        qs = qs.filter(Q(metadata__share=True) | Q(metadata__share__isnull=True))

    if value==False:
        qs = qs.filter(metadata__share=False)

    return qs

def filter_groups_by_share(qs,_,value):

    if value==True:
        qs = qs.filter(Q(rule__share=True) | Q(rule__share__isnull=True))

    if value==False:
        qs = qs.filter(rule__share=False)
    
    return qs

def filter_groups_by_steal_deal(qs,_,value):
    
    if value==True:
        qs = qs.filter(rule__stealDeal=True)

    if value==False:
        qs = qs.filter(Q(rule__stealDeal=False) | Q(rule__stealDeal__isnull=True))
    
    return qs


def filter_groups_by_category(qs,_,value):
    
    if value:
        qs_filter = Q()

        for category_id in value:
            qs_filter &= Q(rule__categories__contains=category_id)
        
        qs = qs.filter(qs_filter)
    
    return qs

def filter_product_tag(qs, _, values):
    
    if values:
        product_tag_list = []
        for value in values:

            product_tag = graphene.Node.from_global_id(value)[1]
            product_tag_list.append(product_tag)

        qs = qs.filter(id__in=product_tag_list)

    return qs

def filter_product_by_published(qs, _, value):

    if value:
        qs = qs.filter(is_published = value).exclude(Q(brand_barter=BarterType.ACTIVE_ONLY_BARTER) | Q(brand__status=BrandStatusEnum.INACTIVE) )

    return qs

def all_published_barter_products(qs, _, values):

    if values:
        qs = qs.filter(Q(is_published = True) & Q(brand_barter__in=values))
    
    return qs

class ProductStockFilterInput(graphene.InputObjectType):
    warehouse_ids = graphene.List(graphene.NonNull(graphene.ID), required=False)
    quantity = graphene.Field(IntRangeInput, required=False)

class PriceDropFilterInput(graphene.InputObjectType):
    price_drop_percentage = graphene.Int(required = True)
    price_drop_days = graphene.Int(required = False)

class ProductFilter(django_filters.FilterSet):
    is_published = django_filters.BooleanFilter(method = filter_product_by_published)
    thrift = GlobalIDFilter(method=filter_thrift_products)
    collections = GlobalIDMultipleChoiceFilter(method=filter_collections)
    categories = GlobalIDMultipleChoiceFilter(method=filter_categories)
    brands = GlobalIDMultipleChoiceFilter(method=filter_brands, field_name="brand")
    has_category = django_filters.BooleanFilter(method=filter_has_category)
    price = ObjectTypeFilter(input_class=PriceRangeInput, method=filter_variant_price)
    minimal_price = ObjectTypeFilter(
        input_class=PriceRangeInput,
        method=filter_minimal_price,
        field_name="minimal_price_amount",
    )
    attributes = ListObjectTypeFilter(
        input_class="saleor.graphql.product.types.attributes.AttributeInput",
        method=filter_attributes,
    )
    stock_availability = EnumFilter(
        input_class=StockAvailability, method=filter_stock_availability
    )
    stock_order = django_filters.BooleanFilter(method=filter_stock_order)
    product_type = GlobalIDFilter()  # Deprecated
    product_types = GlobalIDMultipleChoiceFilter(field_name="product_type")
    store = GlobalIDFilter(method=filter_products_by_store)
    stocks = ObjectTypeFilter(input_class=ProductStockFilterInput, method=filter_stocks)
    search = django_filters.CharFilter(method=filter_search)
    ids = GlobalIDMultipleChoiceFilter(field_name="id")
    brand_status = ListObjectTypeFilter(input_class=BrandStatusEnums, method=filter_product_by_brand_status)
    timestamp = django_filters.DateFilter(method = filter_products_by_timestamp)
    brand_barter =  django_filters.BooleanFilter(method = filter_product_by_brand_barter)
    product_tags = GlobalIDMultipleChoiceFilter(method=filter_product_tags, field_name="product_tag")
    brand_tags = GlobalIDMultipleChoiceFilter(method=filter_brand_tags, field_name="brand_tag")
    brand_collections = GlobalIDMultipleChoiceFilter(method=filter_brand_collections, field_name="brand_collection")
    discount = ObjectTypeFilter(input_class=PriceRangeInput, method=filter_variant_discount)
    steal_deal = django_filters.BooleanFilter(method = filter_products_by_steal_deal)
    value_deal = django_filters.BooleanFilter(method = filter_products_by_value_deal)
    shopify = django_filters.BooleanFilter(method = filter_products_by_shopify)
    all_published_barter_products = ListObjectTypeFilter(input_class=BarterTypeEnum, method=all_published_barter_products)
    price_drop = ObjectTypeFilter(input_class= PriceDropFilterInput, method =filter_products_by_price_drop)
    class Meta:
        model = Product
        fields = [
            "is_published",
            "thrift",
            "collections",
            "categories",
            "brands",
            "has_category",
            "attributes",
            "stock_availability",
            "product_type",
            "stocks",
            "search",
            "store",
            "category__slug",
            "brand_status",
            "timestamp",
            "brand_barter",
            "value_deal",
            "all_published_barter_products",
            "discount",
            "brand_tags",
            "product_tags",
            "price_drop"
        ]


class ProductVariantFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("name", "product__name", "sku")
    )
    sku = ListObjectTypeFilter(input_class=graphene.String, method=filter_sku_list)

    class Meta:
        model = ProductVariant
        fields = ["search", "sku"]


class CollectionFilter(django_filters.FilterSet):
    published = EnumFilter(
        input_class=CollectionPublished, method=filter_collection_publish
    )
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("slug", "name")
    )
    shop_look = django_filters.BooleanFilter()
    ids = GlobalIDMultipleChoiceFilter(field_name="id")
    media_type = EnumFilter(input_class=CollectionMediaTypeEnum,method = filter_collections_by_media)
    steal_deal = django_filters.BooleanFilter(method = filter_collection_by_steal_deal)
    landing = django_filters.BooleanFilter(method = filter_collection_by_landing)
    share = django_filters.BooleanFilter(method = filter_collections_by_share)

    class Meta:
        model = Collection
        fields = ["published", "search","shop_look","media_type","share"]


class CategoryFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("slug", "name", "description")
    )
    ids = GlobalIDMultipleChoiceFilter(field_name="id")

    class Meta:
        model = Category
        fields = ["search"]

class BrandZaamoMappingFilter(django_filters.FilterSet):
    brand_name = django_filters.CharFilter(field_name='brand_name', lookup_expr='iexact')
    product_name = django_filters.CharFilter(field_name='product_name', lookup_expr='iexact')
    product_id_brand = django_filters.CharFilter(field_name='product_id_brand', lookup_expr='iexact')
    sku_id_brand = django_filters.CharFilter(field_name='sku_id_brand', lookup_expr='iexact')
    variant_id_brand = django_filters.CharFilter(field_name='variant_id_brand', lookup_expr='iexact')
    source = django_filters.CharFilter(field_name='source', lookup_expr='iexact')
    variant_sku = django_filters.CharFilter(field_name='variant_zaamo__sku', lookup_expr='iexact')


    search = django_filters.CharFilter(
        method=filter_fields_containing_value("brand_name", "product_name")
    )
    ids = GlobalIDMultipleChoiceFilter(field_name="id")

    class Meta:
        model = BrandVariantZaamoMapping
        fields = ["search", "brand_name", "product_name", "product_id_brand", 
                 "sku_id_brand", "variant_id_brand", "source", 'variant_sku']


class ProductTypeFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("name", "slug")
    )

    configurable = EnumFilter(
        input_class=ProductTypeConfigurable, method=filter_product_type_configurable
    )

    product_type = EnumFilter(input_class=ProductTypeEnum, method=filter_product_type)
    ids = GlobalIDMultipleChoiceFilter(field_name="id")

    class Meta:
        model = ProductType
        fields = ["search", "configurable", "product_type"]


class AttributeFilter(django_filters.FilterSet):
    # Search by attribute name and slug
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("slug", "name")
    )
    ids = GlobalIDMultipleChoiceFilter(field_name="id")

    in_collection = GlobalIDFilter(method="filter_in_collection")
    in_category = GlobalIDFilter(method="filter_in_category")

    class Meta:
        model = Attribute
        fields = [
            "value_required",
            "is_variant_only",
            "visible_in_storefront",
            "filterable_in_storefront",
            "filterable_in_dashboard",
            "available_in_grid",
        ]

    def filter_in_collection(self, queryset, name, value):
        requestor = get_user_or_app_from_context(self.request)
        return filter_attributes_by_product_types(queryset, name, value, requestor)

    def filter_in_category(self, queryset, name, value):
        requestor = get_user_or_app_from_context(self.request)
        return filter_attributes_by_product_types(queryset, name, value, requestor)


class AttributeChoiceFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method=filter_fields_containing_value("slug", "name")
    )

    class Meta:
        model = AttributeValue
        fields = ["search"]

class SourcingRequestFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method = filter_request_containing_mail)
    stores = GlobalIDMultipleChoiceFilter(method = filter_sourcing_request_by_stores)
    brands = GlobalIDMultipleChoiceFilter(method = filter_sourcing_request_by_brands)
    sourcing_request_status = ListObjectTypeFilter(input_class = SourcingRequestStatusTypeEnum , method = filter_sourcing_request_by_status)
    store_status = ListObjectTypeFilter(input_class = StoreStatusEnums , method = filter_sourcing_request_by_store_status)
    time_period = ObjectTypeFilter(
        input_class=DateRangeInput, method=filter_sourcing_request_by_timeperiod)
    id = GlobalIDFilter(field_name="id")
    ids = GlobalIDMultipleChoiceFilter(field_name="id")
    brand_collab = EnumFilter(input_class=BrandCollabStatusForSouringRequestEnum, method = filter_sourcing_request_by_brand_collab)
    store_barter = django_filters.BooleanFilter(method=filter_sourcing_request_by_store_barter)
    category_ids = GlobalIDMultipleChoiceFilter(method = filter_sourcing_request_by_category_ids)
    next_date = ObjectTypeFilter(
        input_class=DateRangeInput, method=filter_sourcing_request_by_next_date
    )
    order_status = ListObjectTypeFilter(input_class=SourcingRequestOrderStatusFilterEnum, method=filter_sourcing_request_by_order_status)
    recommended = django_filters.BooleanFilter(method=filter_sourcing_request_by_recommended)

    class Meta:
        model = SourcingRequest
        fields = ["search","stores","brands","sourcing_request_status","time_period", "ids"]


class ProductFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = ProductFilter


class ProductVariantFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = ProductVariantFilter


class CollectionFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = CollectionFilter


class CategoryFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = CategoryFilter


class ProductTypeFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = ProductTypeFilter


class AttributeFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = AttributeFilter


class AttributeChoiceFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = AttributeChoiceFilter


class BrandZaamoMappingFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = BrandZaamoMappingFilter

class SourcingRequestFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = SourcingRequestFilter

class ProductTagFilter(django_filters.FilterSet):
    tags = GlobalIDMultipleChoiceFilter(method=filter_product_tag)
   
    class Meta:
        model = ProductTag
        fields = []


class ProductGroupingFilter(django_filters.FilterSet):
    steal_deal = django_filters.BooleanFilter(method = filter_groups_by_steal_deal)
    category_ids = GlobalIDMultipleChoiceFilter(method=filter_groups_by_category)
    ids = GlobalIDMultipleChoiceFilter(field_name="id")
    slug = django_filters.CharFilter(field_name='slug', lookup_expr='iexact')
    share = django_filters.BooleanFilter(method = filter_groups_by_share)

    class Meta:
        model = ProductGrouping
        fields = []

class ProductTagFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = ProductTagFilter


class ProductGroupingFilterInput(FilterInputObjectType):
    class Meta:
        filterset_class = ProductGroupingFilter
