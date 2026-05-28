import datetime
import graphene
from django.db.models import Count, F, IntegerField, BigIntegerField, Min, OuterRef, QuerySet, Subquery,Case, When ,Q, Sum, ExpressionWrapper,Avg, Func
from django.db.models.expressions import Window
from django.db.models.functions import Coalesce, DenseRank, ExtractDay, Cast
from ...product.models import Category, CollectionProduct, Product
from ..core.types import SortInputObjectType
from saleor.utilities.time_utilities import TimeUtilities
from django.contrib.postgres.fields.jsonb import KeyTextTransform


class AttributeSortField(graphene.Enum):
    NAME = ["name", "slug"]
    SLUG = ["slug"]
    VALUE_REQUIRED = ["value_required", "name", "slug"]
    IS_VARIANT_ONLY = ["is_variant_only", "name", "slug"]
    VISIBLE_IN_STOREFRONT = ["visible_in_storefront", "name", "slug"]
    FILTERABLE_IN_STOREFRONT = ["filterable_in_storefront", "name", "slug"]
    FILTERABLE_IN_DASHBOARD = ["filterable_in_dashboard", "name", "slug"]
    STOREFRONT_SEARCH_POSITION = ["storefront_search_position", "name", "pk"]
    AVAILABLE_IN_GRID = ["available_in_grid", "name", "pk"]

    @property
    def description(self):
        # pylint: disable=no-member
        descriptions = {
            AttributeSortField.NAME.name: "Sort attributes by name",
            AttributeSortField.SLUG.name: "Sort attributes by slug",
            AttributeSortField.VALUE_REQUIRED.name: (
                "Sort attributes by the value required flag"
            ),
            AttributeSortField.IS_VARIANT_ONLY.name: (
                "Sort attributes by the variant only flag"
            ),
            AttributeSortField.VISIBLE_IN_STOREFRONT.name: (
                "Sort attributes by visibility in the storefront"
            ),
            AttributeSortField.FILTERABLE_IN_STOREFRONT.name: (
                "Sort attributes by the filterable in storefront flag"
            ),
            AttributeSortField.FILTERABLE_IN_DASHBOARD.name: (
                "Sort attributes by the filterable in dashboard flag"
            ),
            AttributeSortField.STOREFRONT_SEARCH_POSITION.name: (
                "Sort attributes by their position in storefront"
            ),
            AttributeSortField.AVAILABLE_IN_GRID.name: (
                "Sort attributes based on whether they can be displayed "
                "or not in a product grid."
            ),
        }
        if self.name in descriptions:
            return descriptions[self.name]
        raise ValueError("Unsupported enum value: %s" % self.value)


class AttributeSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = AttributeSortField
        type_name = "attributes"


class AttributeChoicesSortField(graphene.Enum):
    NAME = ["name", "slug"]
    SLUG = ["slug"]

    @property
    def description(self):
        descriptions = {
            AttributeSortField.NAME.name: "Sort attribute choice by name.",
            AttributeSortField.SLUG.name: "Sort attribute choice by slug.",
        }
        if self.name in descriptions:
            return descriptions[self.name]
        raise ValueError("Unsupported enum value: %s" % self.value)


class AttributeChoicesSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = AttributeChoicesSortField
        type_name = "attribute choices"


class CategorySortField(graphene.Enum):
    NAME = ["name", "slug"]
    PRODUCT_COUNT = ["product_count", "name", "slug"]
    SUBCATEGORY_COUNT = ["subcategory_count", "name", "slug"]

    @property
    def description(self):
        # pylint: disable=no-member
        if self in [
            CategorySortField.NAME,
            CategorySortField.PRODUCT_COUNT,
            CategorySortField.SUBCATEGORY_COUNT,
        ]:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort categories by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    @staticmethod
    def qs_with_product_count(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(
            product_count=Coalesce(
                Subquery(
                    Category.tree.add_related_count(
                        queryset, Product, "category", "p_c", cumulative=True
                    )
                    .values("p_c")
                    .filter(pk=OuterRef("pk"))[:1]
                ),
                0,
                output_field=IntegerField(),
            )
        )

    @staticmethod
    def qs_with_subcategory_count(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(subcategory_count=Count("children__id"))


class CategorySortingInput(SortInputObjectType):
    class Meta:
        sort_enum = CategorySortField
        type_name = "categories"


class CollectionSortField(graphene.Enum):
    NAME = ["name"]
    AVAILABILITY = ["is_published", "name"]
    PRODUCT_COUNT = ["product_count", "name"]
    PUBLICATION_DATE = ["publication_date", "name"]
    UPDATED_AT = ["updated_at", "name"]
    RANDOM = ["random"]

    @property
    def description(self):
        # pylint: disable=no-member
        if self in [
            CollectionSortField.NAME,
            CollectionSortField.AVAILABILITY,
            CollectionSortField.PRODUCT_COUNT,
            CollectionSortField.PUBLICATION_DATE,
            CollectionSortField.UPDATED_AT,
            CollectionSortField.RANDOM
        ]:
            sort_name = self.name.lower().replace("_", " ")
            return f"Sort collections by {sort_name}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    @staticmethod
    def qs_with_product_count(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(product_count=Count("collectionproduct__id"))
    
    @staticmethod
    def qs_with_random(queryset: QuerySet) -> QuerySet:
        return queryset

class CollectionSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = CollectionSortField
        type_name = "collections"


class ProductOrderField(graphene.Enum):
    NAME = ["name", "slug"]
    PRICE = ["min_variants_price_amount", "name", "slug"]
    MINIMAL_PRICE = ["minimal_variant_price_amount", "name", "slug"]
    DATE = ["updated_at", "name", "slug"]
    TYPE = ["product_type__name", "name", "slug"]
    PUBLISHED = ["is_published", "name", "slug"]
    PUBLICATION_DATE = ["publication_date", "name", "slug"]
    COLLECTION = ["sort_order"]
    POPULARITY = ["popularity_product","name","slug"]
    HOT_SELLING = ["product_views","name","slug"]
    SALES_THIS_MONTH = ["sales_this_month"]
    WEEKLY_VISITS = ["weekly_visits", "product_views", "slug"]
    TRENDING_NOW = ["trending_now","publication_date","slug"]
    SELLING_FAST = ["selling_fast","product_views","slug"]
    BRAND_DISCOUNT = ["brand_discount","name","slug"]
    COMMISSION = ["commission","name","slug"]
    VALUE_UPDATED_AT = ["value_updated_at","name","slug"]
    TAG_STRENGTH = ["strength","name","slug"]
    GROUPING_ORDER = ["grouping_weight","name","slug"]

    @property
    def description(self):
        # pylint: disable=no-member
        descriptions = {
            ProductOrderField.COLLECTION.name: (
                "collection. Note: "
                "This option is available only for the `Collection.products` query."
            ),
            ProductOrderField.NAME.name: "name.",
            ProductOrderField.PRICE.name: "price.",
            ProductOrderField.TYPE.name: "type.",
            ProductOrderField.MINIMAL_PRICE.name: (
                "a minimal price of a product's variant."
            ),
            ProductOrderField.DATE.name: "update date.",
            ProductOrderField.PUBLISHED.name: "publication status.",
            ProductOrderField.PUBLICATION_DATE.name: "publication date.",
            ProductOrderField.POPULARITY.name:"Count of collection in which product exists",
            ProductOrderField.SALES_THIS_MONTH.name:"quantity of product sold this month",
            ProductOrderField.WEEKLY_VISITS.name:"weekly visits",
            ProductOrderField.TRENDING_NOW.name: "trending now",
            ProductOrderField.BRAND_DISCOUNT.name : "brand discount",
            ProductOrderField.HOT_SELLING.name:"pdp views of product",
            ProductOrderField.TAG_STRENGTH.name:"tag stength of product",
            ProductOrderField.SELLING_FAST.name:"count of orders on brand site",
            ProductOrderField.COMMISSION.name:"product commission",
            ProductOrderField.VALUE_UPDATED_AT.name:"product metadata value updated at",
            ProductOrderField.GROUPING_ORDER.name:"product grouping weight"

        }
        if self.name in descriptions:
            return f"Sort products by {descriptions[self.name]}"
        raise ValueError("Unsupported enum value: %s" % self.value)

    @staticmethod
    def qs_with_price(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(
            min_variants_price_amount=Min("variants__price_amount")
        )

    @staticmethod
    def qs_with_collection(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(
            sort_order=Window(
                expression=DenseRank(),
                order_by=(
                    F("collectionproduct__sort_order").asc(nulls_last=True),
                    F("collectionproduct__id"),
                ),
            )
        )
    @staticmethod
    def qs_with_popularity(queryset:QuerySet) -> QuerySet:
        return queryset.annotate(popularity_product = Count("collectionproduct"))

    @staticmethod
    def qs_with_sales_this_month(queryset: QuerySet) -> QuerySet:
        return queryset
    
    @staticmethod
    def qs_with_weekly_visits(queryset: QuerySet) -> QuerySet:
        queryset = queryset.annotate(weekly_visits=Coalesce(Cast(KeyTextTransform('weekly_visits', 'metadata'), BigIntegerField()), 0))
        queryset = queryset.annotate(product_views=Coalesce(Cast(KeyTextTransform('product_views', 'metadata'), BigIntegerField()), 0))
        return queryset
    
    @staticmethod
    def qs_with_trending_now(queryset:QuerySet) -> QuerySet:
        
        # n_days_before_date = TimeUtilities.get_n_days_before_date(days=15)

        # trending_products = CollectionProduct.objects.filter(created_at__gte=n_days_before_date)
        # collections_added_sq = Subquery(trending_products.filter(product_id=OuterRef('id')).annotate(cnt=Func('id', function='COUNT')).values('cnt')[:1]) 

        # queryset = queryset.annotate(collections_added=Coalesce(collections_added_sq, 0))\
        #         .annotate(weeks_since_product_live=1 + (ExtractDay(datetime.datetime.now() - F('updated_at')) / 7))\
        #             .annotate(trending_now=ExpressionWrapper((10**12 * F('collections_added') / F('weeks_since_product_live')) + F('id'), output_field=IntegerField()))
       
        queryset = queryset.annotate(trending_now=Coalesce(Cast(KeyTextTransform('trending_now', 'metadata'), BigIntegerField()), 0))
        return queryset

    @staticmethod
    def qs_with_selling_fast(queryset:QuerySet) -> QuerySet:
        
        queryset = queryset.annotate(selling_fast=Coalesce(Cast(KeyTextTransform('brand_order_count_weekly', 'metadata'), BigIntegerField()), 0),
                                     product_views=Coalesce(Cast(KeyTextTransform('product_views', 'metadata'), BigIntegerField()), 0))
        
        return queryset

    @staticmethod
    def qs_with_brand_discount(queryset:QuerySet) -> QuerySet:  
        queryset = queryset.annotate(brand_discount = Case(When(default_variant=None, then=0),default = (F('default_variant__cost_price_amount') - F('default_variant__price_amount'))*100/F("default_variant__cost_price_amount")))
        return queryset
    
    @staticmethod
    def qs_with_hot_selling(queryset:QuerySet) -> QuerySet: 
        # queryset = queryset.annotate(total_pdp_views=Coalesce(Sum('storeproductviews__views', distinct=True), 0))\
        #     .annotate(weeks_since_product_live=1 + (ExtractDay(datetime.datetime.now() - F('updated_at')) / 7))\
        #         .annotate(product_views=ExpressionWrapper((10**7 * F('total_pdp_views') / F('weeks_since_product_live')) + F('id'), output_field=IntegerField()))

        queryset = queryset.annotate(product_views=Coalesce(Cast(KeyTextTransform('product_views', 'metadata'), BigIntegerField()), 0))
        return queryset

    @staticmethod
    def qs_with_tag_strength(queryset:QuerySet) -> QuerySet: 
        queryset = queryset.annotate(strength=Avg('through_product_tag_product__weight') + Avg('through_product_tag_product__percentile'))

        return queryset

    @staticmethod
    def qs_with_commission(queryset:QuerySet) -> QuerySet:
        return queryset.annotate(commission = Case(When(has_custom_commission = True ,then = 'commission_percentage'),When(brand__commission__commission_percentage = None , then =0 ) , default='brand__commission__commission_percentage'))

    @staticmethod
    def qs_with_value_updated_at(queryset:QuerySet) -> QuerySet:
        return queryset.annotate(value_updated_at = KeyTextTransform('value_updated_at', 'metadata'))

class ProductOrder(SortInputObjectType):
    attribute_id = graphene.Argument(
        graphene.ID,
        description=(
            "Sort product by the selected attribute's values.\n"
            "Note: this doesn't take translations into account yet."
        ),
    )
    field = graphene.Argument(
        ProductOrderField, description="Sort products by the selected field."
    )

    class Meta:
        sort_enum = ProductOrderField


class ProductTypeSortField(graphene.Enum):
    NAME = ["name", "slug"]
    DIGITAL = ["is_digital", "name", "slug"]
    SHIPPING_REQUIRED = ["is_shipping_required", "name", "slug"]

    @property
    def description(self):
        # pylint: disable=no-member
        descriptions = {
            ProductTypeSortField.NAME.name: "name",
            ProductTypeSortField.DIGITAL.name: "type",
            ProductTypeSortField.SHIPPING_REQUIRED.name: "shipping",
        }
        if self.name in descriptions:
            return f"Sort products by {descriptions[self.name]}."
        raise ValueError("Unsupported enum value: %s" % self.value)


class SourcingRequestSortField(graphene.Enum):
    CREATED_AT = ["created_at"]
    UPDATED_AT = ["updated_at"]
    NEXT_DATE = ["next_date"]

    @property
    def description(self):
        descriptions = {
            ProductTypeSortField.UPDATED_AT.name: "updated_at",
            ProductTypeSortField.CREATED_AT.name: "created_at",
            ProductTypeSortField.NEXT_DATE.name: "next_date"
        }
        if self.name in descriptions:
            return f"Sort products by {descriptions[self.name]}."
        raise ValueError("Unsupported enum value: %s" % self.value)


class ProductCollectionSortField(graphene.Enum):
    UPDATED_AT = ["updated_at"]

    @property
    def description(self):
        descriptions = {
            ProductCollectionSortField.UPDATED_AT.name: "updated_at"
        }
        if self.name in descriptions:
            return f"Sort collections by {descriptions[self.name]}."
        raise ValueError("Unsupported enum value: %s" % self.value)


class ProductGroupingSortField(graphene.Enum):
    RANDOM = ["randomize","id"]
    UPDATED_AT = ["updated_at"]


    @property
    def description(self):
        descriptions = {
            ProductGroupingSortField.UPDATED_AT.name: "updated_at",
            ProductGroupingSortField.RANDOM.name: "random"
        }
        if self.name in descriptions:
            return f"Sort collections by {descriptions[self.name]}."
        raise ValueError("Unsupported enum value: %s" % self.value)

    @staticmethod
    def qs_with_randomize(queryset: QuerySet) -> QuerySet:     
        return queryset    

class ProductTypeSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = ProductTypeSortField
        type_name = "product types"

class SourcingRequestInput(SortInputObjectType):
    class Meta:
        sort_enum = SourcingRequestSortField
        type_name = "sourcing request"

class ProductCollectionSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = ProductCollectionSortField
        type_name = "Product Collection"


class ProductGroupingSortingInput(SortInputObjectType):
    class Meta:
        sort_enum = ProductGroupingSortField
        type_name = "Product Grouping"
