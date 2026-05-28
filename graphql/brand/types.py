import graphene
from saleor.brand.states import BrandStatusEnum
from saleor.graphql.core.fields import FilterInputConnectionField , PrefetchingConnectionField
from saleor.graphql.core.types.common import Image
from saleor.graphql.brand.filters import BrandBarterStoreFilterInput, BrandFilterInput
from saleor.graphql.brand.sorters import BrandSortingInput
from saleor.graphql.product.filters import ProductFilterInput
from saleor.graphql.product.types import Product, Category
from saleor.graphql.product.sorters import ProductOrder
from saleor.graphql.store.sorters import StoreSortingInput
from saleor.graphql.warehouse.resolvers import resolve_warehouse
from ..core.connection import CountableDjangoObjectType
from .dataloaders import BrandShippingDataLoader
from graphene import relay 
from graphene_federation import key
from saleor.graphql.store import types as store_types
from saleor.brand import models
from saleor.graphql.brand.resolvers import resolve_brands, BrandBarterRequestClubbedResolvers
from django.db.models import Sum, OuterRef, Subquery
from decimal import Decimal

class BrandBankAccount(CountableDjangoObjectType):
    
    class Meta:
        description = "Brand Bank Details"
        model = models.BrandBankAccount
        interfaces = [relay.Node]
        exclude = ()


class BrandUpiId(CountableDjangoObjectType):
    
    class Meta:
        description = "Brand UPI ID details"
        model = models.BrandUpiId
        interfaces = [relay.Node]
        exclude = ()


class BrandEmail(CountableDjangoObjectType):
    class Meta:
        description = "Brand Email Id details"
        model = models.BrandEmail
        interfaces = [relay.Node]
        exclude = ()

class BrandMobile(CountableDjangoObjectType):
    class Meta:
        description = "Brand Mobile no's details"
        model = models.BrandMobile
        interfaces = [relay.Node]
        exclude = ()    

class BrandShippingData(CountableDjangoObjectType):
    class Meta:
        description = "Brand Shipping data details"
        model = models.BrandShippingData
        interfaces = [relay.Node]
        exclude = () 

class BrandMember(graphene.ObjectType):
    id = graphene.ID(description="store member id")
    email = graphene.String(description="store member emailId")
    first_name = graphene.String(description="store member first name")
    last_name = graphene.String(description="store member last name")
   
    class Meta:
        description = "Represents brand member address data."

@key(fields="id")
class Brand(CountableDjangoObjectType):

    # assumming only one commssion for all products by brand.
    commission = graphene.String(description="Commssions for products", required=False)
    zaamo_commission = graphene.String(description="zaamo commission", required=False)
    warehouse = graphene.ID(description="ID of warehouse for brand")
    store = graphene.Field(store_types.Store, description="Return brand's store.")
    image = graphene.Field(
        Image, size=graphene.Int(description="Size of the image.")
    )
    products = FilterInputConnectionField(
        Product, 
        filter=ProductFilterInput(description="Filtering options for products."),
        sort_by=ProductOrder(description="Sort products."),
        description="List of products in the brand."
    )
    emails = graphene.List(BrandEmail,description="email ids")
    mobiles = graphene.List(BrandMobile,description="mobile numbers")

    bank_account = graphene.List(
        lambda: BrandBankAccount, description="List of the bank accounts of brand."
    )

    upi_ids = graphene.List(
        lambda: BrandUpiId, description="List of the Upi Id of a brand."
    )

    brand_shipping_data = graphene.Field(BrandShippingData,description="Brand's Shipping location data")
    
    total_amount_paid = graphene.Decimal(description = "Total amount paid in payout")

    brand_staff_members = graphene.List(BrandMember , description = "Brand staff memebers user instance")

    brand_barter_ongoing_request = FilterInputConnectionField(store_types.Store, 
                                    filter=BrandBarterStoreFilterInput(description="Filtering options for stores."),
                                    sort_by=StoreSortingInput(description="Sorting options for stores."),
                                    description="Influencers with whom barter requests in ongoing state."
                                )

    brand_barter_request_received = FilterInputConnectionField(store_types.Store, 
                                    filter=BrandBarterStoreFilterInput(description="Filtering options for stores."),
                                    sort_by=StoreSortingInput(description="Sorting options for stores."),
                                    description="Influencers with whom barter requests received."
                                )

    brand_barter_store_count = FilterInputConnectionField(
                                store_types.Store, 
                                filter=BrandBarterStoreFilterInput(description="Filtering options for stores."),
                                sort_by=StoreSortingInput(description="Sorting options for stores."),
                                description="no of requests with individual stores."
                            )
    
    brand_barter_total_store_count = graphene.Int(description="total barter requests count.")

    no_of_requests = graphene.Int(description="no of requests with a specific store.")

    categories = graphene.List(Category, description='List of categories in brand')
    active = graphene.Boolean(description="active/in-active status")
    last_brand_payment_timestamp = graphene.DateTime(description="Timestamp of last brand payout")

    class Meta:
        description = "Brand details"
        model = models.Brand
        interfaces = [relay.Node]
        exclude = ()

    @classmethod
    def get_queryset(cls, queryset, info):
        commissions =  models.Commission.objects.filter(brand=OuterRef("id")).order_by('-created_at')
        queryset = queryset.annotate(first_commission_percentage=Subquery(commissions.values('commission_percentage')[:1]),
                        zaamo_commission=Subquery(commissions.values('zaamo_commission')[:1])
                        )
        return super().get_queryset(queryset, info)
    
    def resolve_warehouse(self, info, **data):
        
        return resolve_warehouse(info, **data)
    
    def resolve_store(root: models.Brand, info, **data):
        
        return root.store

    def resolve_commission(root: models.Brand, info, **data):
        # assuming only one commission per brand

        if not hasattr(root, "first_commission_percentage"):

            commission_obj = root.commission.first()

            if commission_obj:

                return commission_obj.commission_percentage
        else:
            return root.first_commission_percentage
            
        return 0.0

    def resolve_zaamo_commission(root: models.Brand, info, **data):
        # assuming only one commission object per brand
        
        if not hasattr(root, "zaamo_commission"):

            commission_obj = root.commission.first()

            if commission_obj:

                return commission_obj.zaamo_commission
                
        else:
            return root.zaamo_commission
            
        return 0.0
    
    def resolve_emails(root:models.Brand,info,**data):

        email_obj = root.brand_emails.all()
        
        return email_obj
    
    def resolve_mobiles(root:models.Brand,info,**data):
    
        mobiles = root.mobiles.all()
        
        return mobiles

    def resolve_brand_shipping_data(root:models.Brand,info,**data):
        return BrandShippingDataLoader(info.context).load(root.id)

    def resolve_bank_account(root:models.Brand, info, **data):
        return root.bank_accounts.all()

    def resolve_upi_ids(root:models.Brand, info, **data):
        return root.upi_ids.all()
    
    def resolve_total_amount_paid(root,info,**kwargs):

        total_amount = root.brand_payout.all().aggregate(Sum('amount'))
        if total_amount.get('amount__sum'):
            return total_amount.get('amount__sum')
        else:
            return Decimal(0)
        
    def resolve_brand_staff_members(root,info,**kwargs):

        user_list = []

        authorized_user_instance = root.staff_brand_mappings.all().prefetch_related('user')
        
        for data in authorized_user_instance:
            user_instance = data.user
            user_instance.id = graphene.Node.to_global_id("User", user_instance.id)
            user_instance.email = user_instance.email
            user_instance.first_name = user_instance.first_name
            user_instance.last_name = user_instance.last_name

            user_list.append(user_instance)

        return user_list


    @staticmethod
    def resolve_image(root: models.Brand, info, size=None, **_kwargs):
        
        if root.image:
            return Image.get_adjusted(
                image=root.image,
                alt="NA",
                size=size,
                rendition_key_set="image",
                info=info,
            )

    def resolve_brand_barter_ongoing_request(root, info, **_kwargs):
        return BrandBarterRequestClubbedResolvers.resolve_ongoing(root, info)

    def resolve_brand_barter_request_received(root, info, **_kwargs):
        return BrandBarterRequestClubbedResolvers.resolve_request_received(root, info)

    def resolve_brand_barter_total_store_count(root, info, **_kwargs):
        return BrandBarterRequestClubbedResolvers.resolve_total_store_count(root, info)

    def resolve_brand_barter_store_count(root, info, **_kwargs):
        return BrandBarterRequestClubbedResolvers.resolve_store_count(root, info)

    def resolve_no_of_requests(root, info, **_kwargs):
        return BrandBarterRequestClubbedResolvers.resolve_no_of_requests(root, info)

    def resolve_categories(root, info, **_kwargs):
        from saleor.product.models import Category

        ids = root.products.all().values_list("category", flat=True).distinct()
        categories = Category.objects.filter(id__in=ids)
        return categories

    def resolve_active(root, info, **kwargs):
        
        return root.status in [BrandStatusEnum.ACTIVE, BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER]
    
    def resolve_last_brand_payment_timestamp(root, info, **kwargs):
        timestamp = None
        timestamp_qs = models.BrandPayout.objects.filter(brand_id=root.id).order_by('-created_at').values_list('created_at', flat=True)[:1]
        if timestamp_qs:
            timestamp = timestamp_qs[0]

        return timestamp

@key(fields="id")
class BrandGrouping(CountableDjangoObjectType):

    brands = FilterInputConnectionField(
        Brand,
        filter=BrandFilterInput(description="Filtering options for Brands."),
        sort_by=BrandSortingInput(description="Sort brands."),
        description="All Brands"
    )
    class Meta:
        description = "Brand Grouping details"
        model = models.BrandGrouping
        interfaces = [relay.Node]
    
    def resolve_brands(root:models.BrandGrouping,info,*_args,**_kwargs):
        return resolve_brands(root,info)
        
class BrandPayout(CountableDjangoObjectType):
    class Meta:
        description = "Brand Payout details"
        model = models.BrandPayout
        interfaces = [relay.Node]
        exclude = ()

class BrandCollection(CountableDjangoObjectType):
    products = FilterInputConnectionField(
        Product,
        filter=ProductFilterInput(description="Filtering options for products."),
        sort_by=ProductOrder(description="Sort products."),
        description="All products of a collection",
    )
    class Meta:
        description = "Brand Collection details"
        model = models.BrandCollection
        interfaces = [relay.Node]

    def resolve_products(root:models.BrandCollection,info,*_args,**_kwargs):
        return root.product.all()

class BrandCommission(CountableDjangoObjectType):
    class Meta:
        description = "Brand Commission details"
        model = models.Commission
        interfaces = [relay.Node]
        exclude = ()

class BrandTag(CountableDjangoObjectType):
    products = FilterInputConnectionField(
        Product,
        filter=ProductFilterInput(description="Filtering options for products."),
        sort_by=ProductOrder(description="Sort products."),
        description="All products of a collection",
    )
    class Meta:
        description = "Brand Tag details"
        model = models.BrandTag
        interfaces = [relay.Node]

    def resolve_products(root:models.BrandTag,info,*_args,**_kwargs):
        return root.product.filter(metadata__instock=True).all()