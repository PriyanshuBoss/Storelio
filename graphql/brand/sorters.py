import graphene
from django.db.models import QuerySet , Max ,Case,When, OuterRef, Subquery, Value,Count,PositiveIntegerField,F,Q

import datetime
from saleor.store.models import StoreCategoryPage
from saleor.graphql.core.types.sort_input import SortInputObjectType
from saleor.utilities.request_utilities import RequestUtilities
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db.models.functions import Coalesce

class BrandSortField(graphene.Enum):
    BRAND_NAME = ["brand_name"]
    CREATED_AT = ["created_at"]
    UPDATED_AT = ["updated_at"]
    LAST_PRODUCT = ["last_product"]
    LATEST_PRODUCT_ADDED_TO_STORE = ["latest_product_added_to_store", "id"]
    RECENT_BRAND_BARTER = ["brand_barter_active_date"]
    COUPON_CREATED = ["coupon_created"]
    BRAND_GROUP_RANK = ["brand_group_rank", "created_at"]

    @property
    def description(self):
        if self in [
            BrandSortField.BRAND_NAME,
            BrandSortField.UPDATED_AT,
            BrandSortField.CREATED_AT,
            BrandSortField.LAST_PRODUCT,
            BrandSortField.LATEST_PRODUCT_ADDED_TO_STORE,
            BrandSortField.RECENT_BRAND_BARTER,
            BrandSortField.COUPON_CREATED,
            BrandSortField.BRAND_GROUP_RANK
        ]:
            sort_name = self.name.lower().replace("_", " ")

            return f"Sort brands by {sort_name}."
        
        raise ValueError("Unsupported enum value: %s" % self.value)

    @staticmethod
    def qs_with_last_product(queryset: QuerySet) -> QuerySet:
        release_date = datetime.datetime(2022, 1, 4)
        return queryset.annotate(last_product = Case(When(products__publication_date=None , then =release_date ) , default= Max('products__publication_date')))
    
    @staticmethod
    def qs_with_latest_product_added_to_store(queryset: QuerySet) -> QuerySet:
        
        
        if hasattr(queryset, "context"):
            store_id = RequestUtilities.get_store_id_from_headers(queryset.context)
        else:
            store_id=None
        
        if store_id:
            store_category_page_filter  = StoreCategoryPage.objects.filter(
                store=store_id, brand=OuterRef("id")).order_by('-updated_at')

            queryset = queryset.annotate(latest_product_added_to_store = Subquery(store_category_page_filter.values("updated_at")[:1]))
        return queryset

    @staticmethod
    def qs_with_recent_brand_barter(queryset: QuerySet) -> QuerySet:
        release_date = "2022-01-04T07:33:24.454"
        return queryset.annotate(brand_barter_active_date = Coalesce(KeyTextTransform('brand_barter_active_date', 'metadata'), Value(release_date)))

    @staticmethod
    def qs_with_coupon_created(queryset: QuerySet) -> QuerySet:
        return queryset
    
    @staticmethod
    def qs_with_brand_group_rank(queryset: QuerySet) -> QuerySet:
        return queryset

class BrandPayoutSortField(graphene.Enum):
    DATE = ["date"]

    @property
    def description(self):
        if self in [
            BrandPayoutSortField.BRAND_NAME,
            BrandPayoutSortField.UPDATED_AT,
            BrandPayoutSortField.CREATED_AT
        ]:
            sort_name = self.name.lower().replace("_", " ")

            return f"Sort brands by {sort_name}."
        
        raise ValueError("Unsupported enum value: %s" % self.value)

class BrandCollectionOrderField(graphene.Enum):
    SORT_ORDER = ["sort_order",'updated_at','name']

    @property
    def description(self):
        if self in [
            BrandCollectionOrderField.sort_order
        ]:
            sort_name = self.name.lower().replace("_", " ")

            return f"Sort brands by {sort_name}."
        
        raise ValueError("Unsupported enum value: %s" % self.value)
    
    def qs_with_sort_order(queryset:QuerySet):
        return queryset.annotate(
            product_count=Count("product",
                distinct=True,
                filter=Q(product__is_published=True))).annotate(sort_order=Case(
                When(product_count__gt=3, then=100),
                default=F('product_count'),
                output_field=PositiveIntegerField()
            )
            )

class BrandSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = BrandSortField
        type_name = "brands"

class BrandPayoutSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = BrandPayoutSortField
        type_name = "brand payout"

class BrandCollectionOrder(SortInputObjectType):
    class Meta:
        sort_enum = BrandCollectionOrderField
        type_name = "brand Collection"