from saleor.graphql.core.fields import BaseDjangoConnectionField, FilterInputConnectionField, PrefetchingConnectionField
from saleor.graphql.store.filters import StoreCategoryPageFilterInput, StoreManagerCommentFilterInput, StoreTileFilterInput, StoreFilterInput, BrandSourceRequestFilterInput
from saleor.graphql.store.mutations import BrandOfTheDayCreateOrUpdate, BrandSourceRequestBulkCreate, NotificationCreate, StoreManagerActionsUpdate, StoreManagerCommentCreate, StoreUpdate, BrandSourceRequestCreate, BrandSourceRequestUpdate, StoreManagerCreate, IntegrateStoreLinkTree
from saleor.graphql.store.resolvers import resolve_category_page, resolve_notifications, resolve_store, resolve_stores, resolve_tiles, resolve_store_members,resolve_store_by_slug,resolve_store_by_user,resolve_store_by_host,resolve_payout_for_store
import graphene
from saleor.utilities.request_utilities import RequestUtilities
from .types import Store, StoreCategoryField, StoreCategoryPage, StoreManagerComment, StoreNotification, StoreTile, StoreMember,StoreRetrievalState,StorePayout, BrandSourceRequest, Linktree
from .sorters import StoreManagerCommentInput, StorePayoutSortingInput, BrandSourceRequestInput, StoreSortingInput

class StoreQueries(graphene.ObjectType):
    store = graphene.Field(Store,  store_id=graphene.String(
            description="primary id of store", required=False), 
            id = graphene.ID(description="id of store"),
            description="store meta details"
            )

    stores = FilterInputConnectionField(
         Store, description="List of stores.",
         filter=StoreFilterInput(description="Filtering options for stores."),
         brand_id=graphene.Argument(graphene.String, description="Exclude stores having this brand in sourcing."),
         campaign_name=graphene.Argument(graphene.String, description="Exclude stores having this campaign name in sourcing."),
         shuffle = graphene.Argument(graphene.Int, description="Shuffling the stores. Pass an Int value between 1-60 for the shuffling"),
         sort_by = StoreSortingInput(description="Sorting options for stores.")
    )

    store_manager_comments = FilterInputConnectionField(
         StoreManagerComment, description="Comments by store managers on store.",
         filter=StoreManagerCommentFilterInput(description="Filtering options for store comments."),
         sort_by = StoreManagerCommentInput(description="sorting options for store manager commentss.")
    )

    notifications = BaseDjangoConnectionField(
        StoreNotification,
        description="Notifications of particular store"
    )
    tiles = FilterInputConnectionField(
        StoreTile, description="Store Tiles",
        filter=StoreTileFilterInput(description="Filtering options for store tiles."),
        
    )

    store_category_page = FilterInputConnectionField(
        StoreCategoryPage, description="Store category brands",
        filter = StoreCategoryPageFilterInput(description="Filtering options for store category pages")
        
    )

    store_category_page_fields = graphene.Field(StoreCategoryField, description="store category page fields")

    store_members = graphene.List(
        StoreMember, description="Store member details",
        
    )
    
    store_id_by_slug = graphene.Field(StoreRetrievalState,slug = graphene.String(description="Slug for store retrieval",required=True))

    store_id_by_user = graphene.Field(StoreRetrievalState,user_id = graphene.ID(description="User id for store retrieval",required=True))

    store_id_by_host = graphene.Field(StoreRetrievalState,host= graphene.String(description="host for store retrieval",required=True))

    store_payout = FilterInputConnectionField(StorePayout,
        store_id = graphene.Argument(graphene.ID , description = "Store ID for payout",required = True),
        description = "store payout details",
        sort_by = StorePayoutSortingInput()
    )

    brand_source_requests = FilterInputConnectionField(
        BrandSourceRequest, description="brand sourcing requests",
        filter=BrandSourceRequestFilterInput(description="Filtering options for brand source request"),
        sort_by=BrandSourceRequestInput(description="Sorting options for brand source request")
    )
    
    linktree = FilterInputConnectionField(
        Linktree, description="linktree"
    )

    def resolve_store(self, info, store_id=None, id=None):
        
        header_store_id = RequestUtilities.get_store_id_from_headers(info.context)

        if not header_store_id:
            
            if store_id:
                header_store_id = store_id
            
            elif id:
                header_store_id = graphene.Node.from_global_id(id)[-1]

        return resolve_store(header_store_id)

    def resolve_notifications(self, info, **kwargs):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)

        return resolve_notifications(store_id)

    def resolve_stores(self, info, **kwargs):
        return resolve_stores(info, **kwargs)

    def resolve_tiles(self, info, **kwargs):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)

        return resolve_tiles(store_id)

    def resolve_store_category_page(self, info, **kwargs):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)

        return resolve_category_page(store_id)
    
    def resolve_store_members(self, info, **kwargs):
        store_id = RequestUtilities.get_store_id_from_headers(info.context)

        return resolve_store_members(store_id)

    def resolve_store_category_page_fields(self, info, **kwargs):
        
        return StoreCategoryField()

    def resolve_store_id_by_slug(self,info,slug,**kwargs):
        
        store_id = resolve_store_by_slug(slug)
        if not store_id:
            return StoreRetrievalState(store_id = None,success=False,error = "In-valid slug")
        else:
            return StoreRetrievalState(store_id = store_id,success=True)

    def resolve_store_id_by_user(self,info,user_id,**kwargs):

        store_id = resolve_store_by_user(user_id)

        if not store_id:
            return StoreRetrievalState(store_id = None,success=False,error = "In-valid user id")
        else:
            return StoreRetrievalState(store_id = store_id,success=True)


    def resolve_store_id_by_host(self,info,host,**kwargs):

        store_id = resolve_store_by_host(host)
        
        if not store_id:
            return StoreRetrievalState(store_id = None,success=False,error = "In-valid host or default host")
        
        else:
            return StoreRetrievalState(store_id = store_id,success=True)

    def resolve_store_payout(self,info,store_id,**kwargs):
        store_id = graphene.Node.from_global_id(store_id)[1]
        return resolve_payout_for_store(store_id)

class StoreMutations(graphene.ObjectType):
    notification_create = NotificationCreate.Field()

    store_manager_comment_create = StoreManagerCommentCreate.Field()

    store_manager_action_update = StoreManagerActionsUpdate.Field()

    brand_of_the_day_create_or_update = BrandOfTheDayCreateOrUpdate.Field()

    store_update = StoreUpdate.Field()

    brand_source_request_create = BrandSourceRequestCreate.Field()

    brand_source_request_update = BrandSourceRequestUpdate.Field()

    brand_source_request_bulk_create = BrandSourceRequestBulkCreate.Field()

    store_manager_create = StoreManagerCreate.Field()

    integrate_store_linktree = IntegrateStoreLinkTree.Field()
