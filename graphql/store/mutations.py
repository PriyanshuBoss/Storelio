import datetime
from babel.core import default_locale
from django.conf import settings
from django.core.exceptions import ValidationError
import graphene
from django.contrib.postgres.aggregates import StringAgg

from saleor.account import models
from saleor.core.utils.promo_code import generate_promo_code, is_available_promo_code
from saleor.discount import DiscountValueType, VoucherType
from saleor.discount.error_codes import DiscountErrorCode
from saleor.discount.models import Voucher, VoucherStoreDealMapping
from saleor.graphql.meta.mutations import MetadataInput
from saleor.graphql.brand.types import Brand

from saleor.graphql.core.mutations import BaseMutation, ModelMutation
from saleor.graphql.store.types import BrandOfTheDay, StoreManagerActions, StoreNotification, Store, BrandSourceRequest
from saleor.graphql.store.enums import StoreStatusEnums, StoreNextActionsEnums, BrandCollabEnums
from saleor.store import models as store_models
from saleor.store.emails import send_email_marked_botd, brand_sourcing_request_email_context, send_brand_sourcing_request_email, prepare_email_text_store_barter_changed, send_email_store_barter_changed
from saleor.store.states import StoreStatus, StoreBrandSourcingRequestEnum, StoreCategoryPageLevels
from saleor.store.store_utilities import get_instance_for_store, get_store_instances_by_ids
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.request_utilities import RequestUtilities
from saleor.utilities.time_utilities import TimeUtilities
from django.utils.dateparse import parse_datetime
from saleor.product.models import Collection, SourcingRequest
from saleor.brand import models as brand_models
from .enums import StoreStatusEnums, BrandSourceRequestEnums
from saleor.graphql.utils import get_nodes
from ..core.types.common import StoreError
from saleor.notifications.tasks import send_notification_brand_interested_in_me
from saleor.store.tasks import crawl_linktree

class NotificationCreateInput(graphene.InputObjectType):
    text = graphene.String(description="Text of notification")
    image_url = graphene.String(description="image icon link of notification")
    route = graphene.String(description="route of notification")
    stores = graphene.List(graphene.ID, description="store ids for creating notification", required=True)

class NotificationCreate(BaseMutation):
    
    class Arguments:
        input = NotificationCreateInput(
            description="Fields required to register a influencer.", required=True
        )
    
    success = graphene.Boolean(description="status of notification create")

    notification = graphene.Field(StoreNotification, description="Notification instance")

    class Meta:
        description = "Create a new notification"
        exclude = []
       

    @classmethod
    def get_type_for_model(cls):
        return StoreNotification


    @classmethod
    def perform_mutation(cls, root, info, **data):

        stores = cls.get_nodes_or_error(data["input"].pop("stores"), "stores", Store)
        store_notification = store_models.StoreNotification.objects.create(**data["input"])
        store_notification.stores.add(*stores)

        return cls(success=True, notification=store_notification)

class StoreManagerActionsInput(graphene.InputObjectType):
    id = graphene.ID(description = "store manager action id")
    status = StoreStatusEnums(description="Store Status.", required=True)
    next_actions = StoreNextActionsEnums(description="next planned action for store", required=True)


class StoreManagerActionsUpdate(BaseMutation):

    store_manager_action = graphene.Field(StoreManagerActions, description="Store manager action")
    class Arguments:
        input = StoreManagerActionsInput(
            description="Fields required to create store manager action.", required=True
        )
    class Meta:
        description = "Update a store manager action."
        exclude = []
        return_field_name = "StoreManagerActions"
        
    @classmethod
    def perform_mutation(cls, root, info, **data):
        data = data.get("input")

        store_manager_action : store_models.StoreManagerActions = graphene.Node.get_node_from_global_id(
            info, data.get('id'), only_type=StoreManagerActions
        )

        store_manager_action.status = data.get("status", '')
        store_manager_action.next_actions = data.get("next_actions", '')
        store_manager_action.save()

        if store_manager_action.status == StoreStatus.CAMPUS_AMBASSADOR:
            store_manager_action.store.store_category_page_level = StoreCategoryPageLevels.LEVEL_3
            store_manager_action.store.save()

        store_models.BrandSourcingRequest.objects.filter(store_id=store_manager_action.store_id).update(store_bucket=store_manager_action.status)

        return cls(store_manager_action=store_manager_action)


class StoreManagerCommentCreateInput(graphene.InputObjectType):
    store = graphene.ID(description="ID of store", required=True)
    comment = graphene.String(description="Comment by store manager.")


class StoreManagerCommentCreate(ModelMutation):
    class Arguments:
        input = StoreManagerCommentCreateInput(
            required=True, description="Fields required to create comments"
        )

    class Meta:
        description = "Create a new Comment by store manager."
        model =store_models.StoreManagerComment
        return_field_name = "StoreManagerComment"

    @classmethod
    def clean_input(cls, info, instance, data, input_cls=None):

        store : store_models.StoreInfo = graphene.Node.get_node_from_global_id(
            info, data.get('store'), only_type=Store
        )

        if not store:
             raise ValidationError(message="In-valid store id")
        
        cleaned_input = super().clean_input(info, instance, data, input_cls=input_cls)
        cleaned_input['store'] = store
        cleaned_input['user'] = info.context.user

        return cleaned_input


class BrandOfTheDayInput(graphene.InputObjectType):
    store = graphene.ID(description = "Store ID")
    brand = graphene.ID(description = "Brand ID")
    bio_text = graphene.String(description = "Bio text for brand of the day")

class BrandOfTheDayCreateOrUpdate(BaseMutation):

    brand_of_the_day = graphene.Field(BrandOfTheDay, description="Brand of the Day")

    class Arguments:
        input = BrandOfTheDayInput(
            description="Fields required to create or update an brand of the day.", required=True
        )
    class Meta:
        description = "Create or update an Brand Of The Day."
        exclude = []
        return_field_name = "BrandOfTheDay"
        error_type_class = StoreError
        error_type_field = "store_errors"
        
    @classmethod
    def generate_code_for_voucher(cls):
       
        code = generate_promo_code()
        if not is_available_promo_code(code):
            raise ValidationError(
                {
                    "code": ValidationError(
                        "Promo code already exists.",
                        code=DiscountErrorCode.ALREADY_EXISTS,
                    )
                }
            )
        
        return code

    @classmethod
    def check_if_botd_used_frequently(cls, brand_queue):
        
        brand_added_within_7_days = [ 
            (datetime.datetime.now() - datetime.timedelta(7)) < parse_datetime(brand_data["datetime"]) 
            for brand_data in brand_queue
            ]
        
        return all(brand_added_within_7_days)

    @classmethod
    def create_voucher_store_deal(cls, store, voucher):
        check_existance = VoucherStoreDealMapping.objects.filter(voucher=voucher, store=store)
        if not check_existance:
            VoucherStoreDealMapping.objects.create(
                voucher=voucher, 
                store=store
            )

    @classmethod
    def check_if_botd_used_frequently_on_store(cls, store, brand_queue):
        max_time_botd_allowed = store.metadata.get('max_time_botd_allowed', 2)
        if max_time_botd_allowed==None:
            max_time_botd_allowed = 2

        current_botd_count = 0
        for brand_data in brand_queue:
            if parse_datetime(brand_data["datetime"]) >= TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(), days=7):
                current_botd_count += 1
        
        if max_time_botd_allowed:

            if current_botd_count >= max_time_botd_allowed:
                return True
            
        return False
        
    @classmethod
    def perform_mutation(cls, root, info, **data):
        data = data.get("input")

        store = graphene.Node.get_node_from_global_id(
            info, data.get('store'), only_type=Store
        )

        brand = graphene.Node.get_node_from_global_id(
            info, data.get('brand'), only_type=Brand
        )
        
        bio_text = data.get('bio_text', '')

        deactivation_time = TimeUtilities.add_time_in_timestamp(TimeUtilities.get_current_date_time(), days=1)

        voucher = Voucher.objects.filter(name="BOTD", store = store).first()

        if voucher:
            brand_queue = voucher.metadata.get("brand_queue", [])
            old_brand = voucher.brands.first()
            
            if not old_brand == brand:
                max_time_botd_allowed = store.metadata.get('max_time_botd_allowed', 2)

                if max_time_botd_allowed==0:

                    raise ValidationError(
                        "You recently used a BOTD on your store. Try with a brand deal meanwhile."
                    )

                if cls.check_if_botd_used_frequently_on_store(store, brand_queue):
                    new_brand_queue = []
                    for brand_data in brand_queue:
                        if parse_datetime(brand_data["datetime"]) > TimeUtilities.subtract_time_from_timestamp(TimeUtilities.get_current_date_time(), days=7):
                            new_brand_queue.append(brand_data)

                    voucher.metadata["brand_queue"] = new_brand_queue
                    voucher.save()
                    latest_botd = parse_datetime(max(brand_data["datetime"] for brand_data in new_brand_queue))
                    next_allowed_time = TimeUtilities.add_time_in_timestamp(latest_botd, days=7)
                    next_allowed_time = TimeUtilities.convert_datetime_to_string(next_allowed_time)
                    raise ValidationError(
                        ("You have recently used a BOTD on your store. Try back later on %s" % next_allowed_time)
                        
                    )

        defaults={
                "type": VoucherType.SPECIFIC_PRODUCT,
                "discount_value_type": DiscountValueType.PERCENTAGE,
                "discount_value": NumberUtilities.convert_string_to_float(settings.BOTD_DISCOUNT_PERCENTAGE),
                "max_discount_value":NumberUtilities.convert_string_to_float(settings.BOTD_MAX_DISC),
                "start_date": TimeUtilities.get_current_date_time(),
                "end_date": deactivation_time,
            }


        if voucher:
            
            for key, value in defaults.items():
                setattr(voucher, key, value)
                voucher.save()
            created = False
        else:
            created = True
            defaults.update({
                "name": "BOTD",
                "store": store,
                "code": "BOTD_{}".format(cls.generate_code_for_voucher())
                })

            voucher = Voucher(**defaults)
            voucher.save()

        message_text = ""
        voucher.metadata.update({"BOTD_BIO": bio_text})

        if created:
            voucher.brands.add(brand)
            voucher.metadata["brand_queue"] = [{"brand": brand.id, "datetime": TimeUtilities.get_current_date_time()}]
            voucher.save()
        else:
            old_brand = voucher.brands.first()
            
            if not old_brand == brand:
                brand_queue = voucher.metadata.get("brand_queue", [])
                brand_queue.append({"brand": brand.id, "datetime": TimeUtilities.get_current_date_time()})
                voucher.metadata["brand_queue"] = brand_queue
                voucher.save()

                voucher.brands.remove(old_brand)
                voucher.brands.add(brand)

        send_email_marked_botd.delay(brand.id, store.id)
        #cls.create_voucher_store_deal(store, voucher)

        return cls(brand_of_the_day= BrandOfTheDay(
            brand=brand, voucher_code=voucher.code, 
            voucher_name=voucher.name, bio_text=bio_text, message_text=message_text))

class StoreUpdateInput(graphene.InputObjectType):
    store = graphene.ID(required=True, description = "Store ID")
    slug = graphene.String(description = "Slug for Store")
    metadata = graphene.List(MetadataInput,description="metadata updation")
    content = graphene.String(description = "Content for Store")

class StoreUpdate(BaseMutation):
    store = graphene.Field(Store, description="update store info")

    class Arguments:
        input = StoreUpdateInput(
            required=True, description = "Fields required to update the slug of a store"
        )

    class Meta:
        description = "Update Slug of the Store."
        exclude = []
        return_field_name = "Store"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        input = data['input']
        store : store_models.StoreInfo = graphene.Node.get_node_from_global_id(
            info, input.get('store'), only_type=Store
        )
        
        if not store:
            raise ValidationError(message="In-valid store id")
        
        store_barter_changed = False
        if input.get('metadata'):
            metadata_dict = store.metadata
            for field in input.get('metadata'):
                if field.key == "store_barter":
                    val = field.value
                    val = val.lower()
                    if val == "true":
                        field.value = True
                    else:
                        field.value = False
                    if field.value != store.metadata.get('store_barter'):
                        store_barter_changed = True

                metadata_dict[field.key] = field.value
            
            store.metadata = metadata_dict
        
        if input.get('slug'):
            store_url = f"{settings.DEFAULT_STORE_URL}/{input.get('slug')}"
            store.slug = input.get('slug')
            store.store_url = store_url

        if input.get('content'):
            store.content = input.get('content')

        store.save()
        if store_barter_changed:
            subject, mail_text = prepare_email_text_store_barter_changed(store, info.context.user)
            send_email_store_barter_changed.delay(subject, mail_text)

        if input.get('slug'):
            defalut_collection = store.collection_store.filter(collection__is_default=True).values('collection_id').first()
            default_collection_instance = Collection.objects.filter(id=defalut_collection['collection_id']).first()
            default_collection_instance.name = input.get('slug')
            default_collection_instance.save()
        
        return cls(store=store)

class BrandSourceRequestCreateInput(graphene.InputObjectType):
    store = graphene.ID(required=True, description = "Store ID")
    brand = graphene.ID(required=True, description = "Brand ID")
    terms_and_conditions = graphene.String(required=True, description = "terms and conditions for brand source request")
    campaign_name = graphene.String(required = False, description="Brand Source request campaign name")

class BrandSourceRequestBulkCreateInput(graphene.InputObjectType):
    stores = graphene.List(graphene.ID, required=True, description = "Store ID's")
    brand = graphene.ID(required=True, description = "Brand ID")
    terms_and_conditions = graphene.String(required=True, description = "terms and conditions for brand source request")
    campaign_name = graphene.String(required = False, description="Brand Source request campaign name")



class BrandSourceRequestCreate(BaseMutation):

    brand_source_request = graphene.Field(BrandSourceRequest, description="Brand Source Request")

    class Arguments:
        input = BrandSourceRequestCreateInput(
            required=True, description = "input for creating brand source request"
        )

    class Meta:
        description = "Create Brand Source Request."
        model =store_models.BrandSourcingRequest
        exclude = []
        return_field_name = "BrandSourceRequest"

    @classmethod
    def send_mail(cls, brand_source_request_instance, data):
        souring_request_text = brand_sourcing_request_email_context(data)
        cc= data["store_managers"].split(',') + data["brand_managers"].split(',')
        cc = [email for email in cc if email]
        cc.append('branddeals@zaamo.co')
        
        send_brand_sourcing_request_email.delay('New Brand Sourcing Request - {}'.format(brand_source_request_instance.id), 
                                         souring_request_text, cc=cc)
    
    @classmethod
    def perform_mutation(cls, root, info, **data):
        logged_in_user = info.context.user
        input = data['input']
        
        store : store_models.StoreInfo = graphene.Node.get_node_from_global_id(
            info, input.get('store'), only_type=Store
        )
        brand : brand_models.Brand = graphene.Node.get_node_from_global_id(
            info, input.get('brand'), only_type=Brand
        )
        terms_and_conditions = input.get('terms_and_conditions')

        if not store:
            raise ValidationError(message="In-valid store id")

        if not brand:
            raise ValidationError(message="In-valid brand id")
        
        store_managers = ""
        for data in store.staff_store_mappings.all().prefetch_related('user'):
            user = data.user
            
            if user.email:
                store_managers+=(user.email+",")
        
        brand_managers = ""
        for data in brand.staff_brand_mappings.all().prefetch_related('user'):
            user = data.user
            if user.email:
                brand_managers+=(user.email+",")
                
        store_manager_action = store.actions

        barter_guidelines = store.metadata.get('barter_guidelines')
    
        if store_manager_action:
            store_manager_action_status = store_manager_action.status
        else:
            store_manager_action_status = StoreStatus.STILL_EXPLORING

        brand_source_request_data = {
            "brand": brand,
            "store": store,
            "terms_and_conditions": terms_and_conditions,
            "created_by": logged_in_user,
            "brand_managers": brand_managers,
            "store_managers": store_managers,
            "store_bucket":  store_manager_action_status,
            "content": barter_guidelines
        }

        if input.get('campaign_name') is not None:
            brand_source_request_data['campaign_name'] = input.get('campaign_name')

        check = store_models.BrandSourcingRequest.objects.filter(
            brand=brand, 
            store=store,
            state__in = [
                StoreBrandSourcingRequestEnum.REQUEST_RECEIVED
            ]
        )

        if check:
            brand_source_request_instance = check.first()
        else:
            brand_source_request_instance = store_models.BrandSourcingRequest.objects.create(**brand_source_request_data)
            
            cls.send_mail(brand_source_request_instance, brand_source_request_data)
            
            send_notification_brand_interested_in_me([brand_source_request_instance.id])
        
        return cls(brand_source_request=brand_source_request_instance)


class BrandSourceRequestBulkCreate(BaseMutation):
    count = graphene.Int(
        required=True,
        default_value=0,
        description="Returns how many objects were created.",
    )
    sourcing_requests = graphene.List(
        graphene.NonNull(BrandSourceRequest),
        required=True,
        default_value=[],
        description="List of the created BrandSourceRequests.",
    )
    class Arguments:
            input = BrandSourceRequestBulkCreateInput(
            required=True, description = "input for creating brand source requests"
        )

    class Meta:
        description = "Create Brand Source Request in Bulk."
        exclude = []

    @classmethod
    def create_brand_sourcing_requests(cls, info, stores, brand, input):
        instances = []

        logged_in_user = info.context.user
        terms_and_conditions = input.get('terms_and_conditions')

        brand_managers = ""
        for data in brand.staff_brand_mappings.all().prefetch_related('user'):
            user = data.user
            if user.email:
                brand_managers+=(user.email+",")
        
        sourcing_requests = list(
            brand.sourcing_requests.filter(
                state__in = [
                    StoreBrandSourcingRequestEnum.REQUEST_RECEIVED,
                    StoreBrandSourcingRequestEnum.ACCEPT
                ]
            ).values_list("store_id",flat=True).distinct('store_id').order_by()
        )
        
        stores = store_models.StoreInfo.objects.filter(id__in=[store.id for store in stores])
        stores = stores.annotate(store_managers = StringAgg('staff_store_mappings__user__email', delimiter=', '))
        
        for store in stores:
            
            if store.id in sourcing_requests:
                continue
            
            store_manager_action = getattr(store, 'actions', None)
            barter_guidelines = store.metadata.get('barter_guidelines')
            
            if store_manager_action:
                store_manager_action_status = store_manager_action.status
            else:
                store_manager_action_status = StoreStatus.STILL_EXPLORING
            brand_source_request_data = {
            "brand": brand,
            "store": store,
            "terms_and_conditions": terms_and_conditions,
            "created_by": logged_in_user,
            "brand_managers": brand_managers,
            "store_managers": store.store_managers,
            "store_bucket":  store_manager_action_status,
            "content": barter_guidelines,
            }
            if input.get('campaign_name') is not None:
                brand_source_request_data['campaign_name'] = input.get('campaign_name')
       
            instance = store_models.BrandSourcingRequest(**brand_source_request_data)
            
            instances.append(instance)
            
        return instances

    @classmethod
    def perform_mutation(cls, root, info, **data):

        input = data['input']
        stores = get_nodes(input.get('stores'), "Store", store_models.StoreInfo)
        brand : brand_models.Brand = graphene.Node.get_node_from_global_id(
            info, input.get('brand'), only_type=Brand
        )
        sourcing_requests = cls.create_brand_sourcing_requests(info, stores, brand, input)
        sourcing_requests_objects = store_models.BrandSourcingRequest.objects.bulk_create(sourcing_requests, batch_size=500)
        
        send_notification_brand_interested_in_me([object.id for object in sourcing_requests_objects])
        
        return cls(count = len(sourcing_requests), sourcing_requests=sourcing_requests_objects)

class BrandSourceRequestUpdateInput(graphene.InputObjectType):
    id = graphene.ID(required=True, description = "BrandSourceRequest ID")
    store_bucket = StoreStatusEnums(required = False, description="Brand Source request store_bucket enum")
    state = BrandSourceRequestEnums(required = False, description="Brand Source request state enum")
    brand_collab = BrandCollabEnums(required = False, description="Brand Source request brand_collab enum")
    campaign_name = graphene.String(required = False, description="Brand Source request campaign name")
    terms_and_conditions = graphene.String(required=False, description = "terms and conditions for brand source request")

class BrandSourceRequestUpdate(BaseMutation):

    brand_source_request = graphene.Field(BrandSourceRequest, description="Brand Source Request")

    class Arguments:
        input = BrandSourceRequestUpdateInput(
            required=True, description = "input for updating brand source request"
        )

    class Meta:
        description = "Update Brand Source Request."
        model =store_models.BrandSourcingRequest
        exclude = []
        return_field_name = "BrandSourceRequest"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        
        brand_source_request_id = graphene.Node.from_global_id(input.get('id'))[1]
        brand_source_request_instance = store_models.BrandSourcingRequest.objects.filter(id = brand_source_request_id).first()
        
        if input.get('store_bucket'):
            brand_source_request_instance.store_bucket = input.get('store_bucket')

        if input.get('state'):
            brand_source_request_instance.state = input.get('state')
        
        if input.get('brand_collab') is not None:
            brand_source_request_instance.brand_collab = input.get('brand_collab')

        if input.get('campaign_name') is not None:
            brand_source_request_instance.campaign_name = input.get('campaign_name')

        if input.get('terms_and_conditions') is not None:
            brand_source_request_instance.terms_and_conditions = input.get('terms_and_conditions')

        brand_source_request_instance.save()

        return cls(brand_source_request=brand_source_request_instance) 


class StoreManagerCreateInput(graphene.InputObjectType):
    store = graphene.ID(
        required=True, description="ID of the Store for which store manager to be created."
    )

    users = graphene.List(
        graphene.ID, required=True, description="List of user IDs which will be the store manager of the store."
    )


class StoreManagerCreate(BaseMutation):

    store = graphene.Field(Store, description = "Store")
    class Arguments:
        input = StoreManagerCreateInput(
            required=True, description="Fields required to create store Manager of the Store."
        )

    class Meta:
        description = "Store manager create"
        return_field_name = "store"

    @classmethod
    def update_store_managers(cls, store, store_manager_emails):
        SourcingRequest.objects.filter(store=store).update(influencer_managers=store_manager_emails)
        store_models.BrandSourcingRequest.objects.filter(store=store).update(store_managers=store_manager_emails)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        input = data['input']
        store = cls.get_node_or_error(info, input['store'], only_type=Store)
        users = get_nodes(input['users'],"User",models.User)
        
        store_models.StaffStoreMapping.objects.filter(store=store).delete()

        for user in users:
            store_models.StaffStoreMapping.objects.create(
                store = store,
                user = user
            )
        
        store_manager_emails = ",".join(store.staff_store_mappings.all().values_list('user__email', flat=True))
        
        cls.update_store_managers(store, store_manager_emails)

        return cls(store=store)


class IntegrateStoreLinkTreeInput(graphene.InputObjectType):
    linktree = graphene.String(
        required=True, description="Linktree link of the store."
    )


class IntegrateStoreLinkTree(BaseMutation):

    store = graphene.Field(Store, description = "Store")
    class Arguments:
        input = IntegrateStoreLinkTreeInput(
            required=True, description="Fields required to integrate Linktree."
        )

    class Meta:
        description = "Store Linktree integration"
        return_field_name = "store"

    @classmethod
    def start_linktree_crawl(cls, store_id, linktree_link):
        crawl_linktree.delay(store_id, linktree_link)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        input = data['input']
        store_id = RequestUtilities.get_store_id_from_headers(info.context)
        linktree_link = input['linktree']
        
        if linktree_link:
            cls.start_linktree_crawl(store_id, linktree_link)

        store = cls.get_node_or_error(info, graphene.Node.to_global_id('Store', store_id), only_type=Store)

        return cls(store=store)