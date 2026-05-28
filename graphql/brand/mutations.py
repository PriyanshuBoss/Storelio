from django.forms import ValidationError
import graphene
from saleor.brand.emails import prepare_email_text_for_barter, prepare_email_text_for_botd_by_brand_manager, prepare_email_text_for_too_many_orders_or_brand_is_active, send_email_for_brand_status_changes
from saleor.brand.states import BrandSourceEnum, BrandEmailStateEnum, BrandStatusEnum
from saleor.core.utils import generate_unique_slug
from saleor.external_services.shopify_service.tasks import change_product_status_with_brand_status_task
from saleor.graphql.core.types.common import BaseBankAccountInput, BaseUpiIdInput
from saleor.graphql.core.types.upload import Upload
from saleor.graphql.core.utils import from_global_id_strict_type
from saleor.utilities.time_utilities import TimeUtilities
from ..core.mutations import ModelMutation
from saleor.graphql.account.types import AddressInput
from graphene.types.generic import GenericScalar
from saleor.brand import models
from saleor.graphql.brand.types import Brand, BrandCommission, BrandEmail, BrandMobile, BrandShippingData
from saleor.product import BarterType, models as product_models
from saleor.graphql.account.types import User
from saleor.account.models import Address, User
from saleor.graphql.brand.enums import BrandMobileTypeEnums, BrandSourceEnums, BrandStatusEnums, PreferedPaymentModeEnums, BrandEmailStateEnums, BrandImportanceEnums
from django.db import transaction
from ..core.mutations import BaseMutation
from saleor.brand.states import BrandMemberStateEnum, BrandEmailStateEnum 
from saleor.graphql.utils import get_nodes
from saleor.store.models import BrandSourcingRequest
from saleor.graphql.meta.mutations import MetadataInput
from saleor.graphql.brand.tasks import explore_content_sync
from saleor.external_services.instagram_shop.tasks import catalog_update_brand_status
from saleor.external_services.google_merchant.tasks import gm_update_catalog_brand_status


class BrandBankAccountInput(BaseBankAccountInput):
    brand = graphene.ID(
        description="ID of the Brand that Bank Account belongs to.",
        name="brand",
        required=True,
    )
    

class BrandUpiIdInput(BaseUpiIdInput):
    brand = graphene.ID(
        description="ID of the Brand that UPI ID belongs to.",
        name="brand",
        required=True,
    )


class DeactivateBrandAccountInput(graphene.InputObjectType):
    brand = graphene.ID(
        description="ID of the Brand that will be deactivated.",
        name="brand",
        required=True,
    )
    user = graphene.ID(
        description="ID of the User that will be deactivated.",
        name="user",
        required=False,
    )

class BrandMobileCreateUpdateInput(graphene.InputObjectType):
    mobile_no = graphene.String(required=True, description="Brand Mobile")
    active = graphene.Boolean(required=False, description = "Brand Mobile State")
    user_name = graphene.String(required=False, description = "name of mobile owner")
    type = BrandMobileTypeEnums(required=False, description = "Brand Mobile Type")


class BrandRegisterInput(graphene.InputObjectType):
    company_name = graphene.String(description="name of Brand's Company", required=True)
    brand_name = graphene.String(description="Name of Brand", required=True)
    brand_contact_name = graphene.String(description="Name of the contact person from brand side.", 
                                         required=True)
    brand_contact_number = graphene.String(description="Brand contact person mobile No.", 
                                           required=True)
    short_description = graphene.String(description="Short discription about brand", required=False)
    size_fit_note = graphene.String(description="size and fit note by brand, can be use to show this to customers", required=False)

    cod = graphene.Boolean(description="COD status of brand", required=False)
    cod_base_price = graphene.Boolean(description="COD base price of brand", required=False)
    active = graphene.Boolean(description="Active status of brand", required=False)

    prefered_payment_mode = PreferedPaymentModeEnums(
                                description=(
                                    "Payment Method that brand prefer to recieve payments."
                                ),
                            )
    brand_source = BrandSourceEnums(
                                description=(
                                    "source of brand"
                                ),
                            )

    address = AddressInput(
        description=(
            "Address of the Brand Company"
        ),required=True
    )

    return_address = AddressInput(
        description=(
            "Address of the Brand Company"
        ), required=True
    )

    pickup_address = AddressInput(
        description=(
            "Address of the Brand Company"
        ), required=False
    )
    shipping_return_policy = GenericScalar(description=("Return and exchange policy JSON"), required=False)
    zaamo_creators_guidelines = GenericScalar(description=("Guidelines for Zaamo creators in Json format"), required=False)
    pan_number = graphene.String(description="Bank account ", required=True) 
    image = Upload(description="image of brand")
    email = graphene.String(description="email of brand", required=False) 
    private_metadata = graphene.JSONString(description="private metadata of brand")
    botd = graphene.Boolean(description = "botd true or false")
    commission  = graphene.Float(description = "Commission of brand")
    too_many_orders = graphene.Boolean(description = "too_many_order true or false")
    brand_order_info = graphene.String(description = "Brand order information ")
    history_notes = graphene.String(description="history notes of brand", required=False) 
    order_processing_days = graphene.Int(description = "Order processing days in integer")
    order_shipping_days = graphene.Int(description = "Order Shipping days in integer")
    brand_barter_guidelines = graphene.String(description = "Brand Barter guidelines ")
    brand_barter = graphene.Boolean(description = "Brand Barter boolean true or false")
    mobiles = graphene.List(BrandMobileCreateUpdateInput, description = "List of mobile no's of a brand")

class BrandUpdateInput(graphene.InputObjectType):
    id = graphene.ID(description="Brand public id.", required=True)

    company_name = graphene.String(description="name of Brand's Company", required=False)
    brand_name = graphene.String(description="Name of Brand", required=False)
    brand_contact_name = graphene.String(description="Name of the contact person from brand side.", 
                                         required=False)
    brand_contact_number = graphene.String(description="Brand contact person mobile No.", 
                                           required=False)
    short_description = graphene.String(description="Short discription about brand", required=False)
    size_fit_note = graphene.String(description="size and fit note by brand, can be use to show this to customers", required=False)

    status = BrandStatusEnums(
                                description=(
                                    "status of brand"
                                ),
                            )
    active = graphene.Boolean(description="Active status of brand", required=False)
    botd = graphene.Boolean(description="botd status of brand", required=False)
    brand_barter = graphene.Boolean(description="barter status of brand", required=False)
    too_many_orders = graphene.Boolean(description="too many orders status of brand", required=False)
    cod = graphene.Boolean(description="COD status of brand", required=False)
    cod_base_price = graphene.Float(description="COD base price of brand", required=False)

    prefered_payment_mode = PreferedPaymentModeEnums(
                                description=(
                                    "Payment Method that brand prefer to recieve payments."
                                ),
                            )
    brand_source = BrandSourceEnums(
                                description=(
                                    "source of brand"
                                ),
                            )

    address = AddressInput(
        description=(
            "Address of the Brand Company"
        ),required=False
    )

    return_address = AddressInput(
        description=(
            "Address of the Brand Company"
        ), required=False
    )
    pickup_address = AddressInput(
        description=(
            "Address of the Brand Company"
        ), required=False
    )
    shipping_return_policy = GenericScalar(description=("Return and exchange policy JSON"), required=False)
    zaamo_creators_guidelines = GenericScalar(description=("Guidelines for Zaamo creators in Json format"), required=False)
    pan_number = graphene.String(description="Bank account ", required=False) 
    image = Upload(description="image of brand")
    email = graphene.String(description="email of brand", required=False)
    brand_order_info = graphene.String(description="brand order info of brand", required=False) 
    history_notes = graphene.String(description="history notes of brand", required=False) 
    brand_barter_guidelines = graphene.String(description="brand barter guidelines of brand", required=False) 
    private_metadata = graphene.JSONString(description="private metadata of brand")
    order_processing_days = graphene.Int(description = "order processing days of brand")
    order_shipping_days = graphene.Int(description = "order processing days of brand")
    metadata = graphene.List(MetadataInput, description="metadata of brand")
    mobiles = graphene.List(BrandMobileCreateUpdateInput, description = "List of mobile no's of a brand")
    importance = BrandImportanceEnums(descriptions='brand importance level')



class BrandCreate(ModelMutation):
    class Arguments:
        input = BrandRegisterInput(
            required=True, description="Fields required to create Brand."
        )

    class Meta:
        description = "Create a new Brand."
        model = models.Brand
        return_field_name = "brand"
        error_type_field = "brand_errors"


    @classmethod
    def save_addresses(cls, data: dict):
        address = Address(**data.get("address"))
        return_address = Address(**data.get("return_address"))
        pickup_address = None
        if data.get("pickup_address"):
            pickup_address = Address(**data.get("pickup_address"))
            pickup_address.save()

        address.save()
        return_address.save()
        
        return address, return_address, pickup_address
    
    @classmethod
    def save_mobile_no(cls, brand_instance, mobiles_data):
        for mobile in mobiles_data:
            mobile_no = mobile.pop('mobile_no')
            mobile_no = '91' + ''.join(mobile_no.strip()[-10:])
            models.BrandMobile.objects.update_or_create(
                brand=brand_instance, mobile_no = mobile_no, 
                defaults=mobile
            )
       
    @classmethod
    def post_save_action(cls, info, instance, cleaned_input):
        
        p_metadata = instance.private_metadata
        p_metadata['source_name'] = instance.brand_name
        instance.private_metadata = p_metadata
        instance.save()

        if cleaned_input.get("commission"):
            models.Commission(brand=instance,commission_percentage=cleaned_input.get("commission")).save()

        if instance.brand_source == BrandSourceEnum.MANUAL:
           user_instance = info.context.user
           models.BrandMemberState(user=user_instance, brand=instance).save()

        if not cleaned_input.get("email"):
            return
        
        if not models.BrandEmail.objects.filter(brand_id=instance,brand_email=cleaned_input.get("email")).exists():
            models.BrandEmail(brand_id=instance,brand_email=cleaned_input.get("email"),state=BrandEmailStateEnum.PRIMARY).save()

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, _root, info, **data):
        address, return_address ,pickup_address = cls.save_addresses(data.get("input"))
        data.get("input")['address'] = address
        data.get("input")['return_address'] = return_address
        data.get("input")['pickup_address'] = pickup_address
        data.get("input")['slug'] = generate_unique_slug(models.Brand(),data.get('brand_name'))
        mobiles = data.get("input", {}).pop('mobiles', [])
        graphql_instance = super().perform_mutation(_root, info, **data)
        brand_instance = models.Brand.objects.filter(**data.get("input")).first()
        
        cls.save_mobile_no(brand_instance, mobiles)
        
        return graphql_instance


    @classmethod
    def get_type_for_model(cls):
        return Brand


class BrandUpdate(BaseMutation):

    brand = graphene.Field(Brand, description = "Brand")
    message = graphene.String(description = "Brand update message")
    class Arguments:
        input = BrandUpdateInput(
            required=True, description="Fields required to create Brand."
        )
    class Meta:
        description = "Update a Brand."
        return_field_name = "brand"
        error_type_field = "brand_errors"
    


    @classmethod
    def update_addresses(cls, brand, data: dict):
        if data.get("address"):
            Address.objects.filter(id=brand.address_id).update(**data.get("address"))
        if data.get("return_address"):
            Address.objects.filter(id=brand.return_address_id).update(**data.get("return_address"))
        if data.get("pickup_address"):
            if brand.pickup_address_id:
                Address.objects.filter(id=brand.pickup_address_id).update(**data.get("pickup_address"))
            else:
                pickup_address = Address.objects.create(**data.get("pickup_address"))
                brand.pickup_address = pickup_address
                brand.save()
    
    @classmethod
    def save_mobile_no(cls, brand_instance, mobiles_data):
        for mobile in mobiles_data:
            mobile_no = mobile.pop('mobile_no')
            mobile_no = '91' + ''.join(mobile_no.strip()[-10:])
            models.BrandMobile.objects.update_or_create(
                brand=brand_instance, mobile_no = mobile_no, 
                defaults=mobile
            )

    @classmethod
    def post_save_action(cls, old_obj, info):
    
        instance = models.Brand.objects.filter(id=old_obj.id).first()
        old_status = old_obj.brand_barter
        old_tmo = old_obj.too_many_orders
        old_active = old_obj.status
        old_botd = old_obj.botd
        user_instance = info.context.user


        if not old_status:
            
            if instance.brand_barter:
                email_text = prepare_email_text_for_barter(instance)
                send_email_for_brand_status_changes.delay("Brand Name - {}(Brand Barter)".format(instance.brand_name),email_text)
                
                var = product_models.Product.objects.filter(brand_id = old_obj.id, brand_barter = BarterType.ACTIVE_BARTER).first()
                if not var:
                    product_models.Product.objects.filter(brand_id = old_obj.id).update(brand_barter = BarterType.ACTIVE_BARTER)

        else:

            if not instance.brand_barter:
                
                email_text = prepare_email_text_for_barter(instance)
                send_email_for_brand_status_changes.delay("Brand Name - {}(Not Brand Barter)".format(instance.brand_name),email_text)

        if not old_botd:

            if instance.botd:
                email_text = prepare_email_text_for_botd_by_brand_manager(instance)
                send_email_for_brand_status_changes.delay("Brand Name - {}(BOTD)".format(instance.brand_name),email_text)

        else:
            
            if not instance.botd:
                email_text = prepare_email_text_for_botd_by_brand_manager(instance)
                send_email_for_brand_status_changes.delay("Brand Name - {}(Not BOTD)".format(instance.brand_name),email_text)
        
        if not old_tmo:

            if instance.too_many_orders:
                email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(instance, old_obj,for_tmo_email=True)
                send_email_for_brand_status_changes.delay("Brand Name - {}(TMO)".format(instance.brand_name),email_text)

        else:

            if not instance.too_many_orders:
                email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(instance, old_obj,for_tmo_email=True)
                send_email_for_brand_status_changes.delay("Brand Name - {}(Not TMO)".format(instance.brand_name),email_text)

        if old_active != instance.status:

            if instance.status == BrandStatusEnum.ACTIVE:

                email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(instance, old_obj,for_tmo_email=False)
                user_email = f"{user_instance.email}"
                email_text += "\n The change is done by {}.".format(user_email)
                send_email_for_brand_status_changes.delay("Brand Name - {}(Active)".format(instance.brand_name),email_text)
        

            if instance.status==BrandStatusEnum.INACTIVE:

                email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(instance, old_obj, for_tmo_email=False)
                user_email = f"{user_instance.email}"
                email_text += "\n The change is done by {}.".format(user_email)
                send_email_for_brand_status_changes.delay("Brand Name - {}(In-Active)".format(instance.brand_name),email_text )
        
    
            if instance.status==BrandStatusEnum.ACTIVE_ONLY_FOR_BARTER:

                email_text = prepare_email_text_for_too_many_orders_or_brand_is_active(instance, old_obj, for_tmo_email=False)
                user_email = f"{user_instance.email}"
                email_text += "\n The change is done by {}.".format(user_email)
                send_email_for_brand_status_changes.delay("Brand Name - {}(Active-Only-For-Barter)".format(instance.brand_name),email_text )

            explore_content_sync.delay(brand_id=instance.id)
            catalog_update_brand_status.delay(brand_ids=[instance.id])
            gm_update_catalog_brand_status.delay(brand_ids=[instance.id])
            change_product_status_with_brand_status_task.delay(instance.id)
    
    @classmethod
    def process_metadata(cls,info, input_data, metadata_dict):
        for field in input_data:
            metadata_dict[field.key] = field.value

        return metadata_dict

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, _root, info, **data):
        id = data.get("input", {}).pop("id")
        brand = graphene.Node.get_node_from_global_id(info, id, Brand)
        message = "Successfully Updated Brand"

    
        if data['input'].get('status') == BrandStatusEnum.ACTIVE and not brand.commission.all():
            message="Can not have Brand status active with no commission."
            return cls(brand=brand, message=message)

        input_metadata = None
        if data['input'].get('metadata'):
            input_metadata = data['input'].get('metadata')
            data.get("input", {}).pop("metadata", None)
    
        old_brand_values = models.Brand.objects.filter(id=brand.id).values(*data['input'].keys()).first()
        cls.update_addresses(brand, data.get("input"))

        mobiles = data.get("input", {}).pop('mobiles', [])
        cls.save_mobile_no(brand, mobiles)

        data.get("input", {}).pop("address", None)
        data.get("input", {}).pop("return_address", None)
        data.get("input", {}).pop("pickup_address", None)
        data["input"]['updated_by'] = info.context.user
        brand.metadata.update({'last_updated_values': old_brand_values})

        if not brand.brand_barter and data.get("input").get("brand_barter"):
             brand.metadata.update({
                'brand_barter_active_date': TimeUtilities.parse_date(
                                                    TimeUtilities.get_current_date_time(), 
                                                    date_format = "%Y/%m/%d %H:%M:%S"
                                                    )
                })

        brand.save()
        
        if input_metadata is not None:
            data["input"]['metadata'] = cls.process_metadata(info,input_metadata, brand.metadata)
                      
        models.Brand.objects.filter(id=brand.id).update(**data.get("input"))
        
        brand_new = models.Brand.objects.filter(id=brand.id).first()
        brand_old = brand
        
        cls.post_save_action(brand_old, info) 
        
        return cls(brand=brand_new, message=message)


    @classmethod
    def get_type_for_model(cls):
        return Brand

class BrandBankAccountCreate(ModelMutation):
    class Arguments:
        input = BrandBankAccountInput(
            required=True, description="Fields required to create Brand's BankAccount."
        )

    class Meta:
        description = "Create a new BankAccount."
        model = models.BrandBankAccount
        return_field_name = "BrandBankAccount"
        error_type_field = "brandAccount_errors"


class BrandUpiIdCreate(ModelMutation):
    class Arguments:
        input = BrandUpiIdInput(
            required=True, description="Fields required to create Brand's UPI ID."
        )

    class Meta:
        description = "Create a new Brand's UPI ID."
        model = models.BrandUpiId
        return_field_name = "BrandUpiId"
        error_type_field = "brandUpiId_errors"


class DeactivateBrandAccount(BaseMutation):
    brand = graphene.Field(Brand, description="Deactivate Brand Account.")
    state = graphene.String()

    class Arguments:
        input = DeactivateBrandAccountInput(
            required=True, description="Fields required to Deactivate Brand Account."
        )
    
    class Meta:
        description = "Deactivate Brand Account."
    
    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data.get("input")
        if input.get('user') is None:

            brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)

            brand_member_state_list = brand.brand_member_states.all()
        
            for brand_member_state in brand_member_state_list:
                brand_member_state.state = BrandMemberStateEnum.INACTIVE
                brand_member_state.save(update_fields=["state"])

                state = brand_member_state.state

            return DeactivateBrandAccount(brand=brand,state=state)

        else:

            brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)
            user = cls.get_node_or_error(info, input['user'], only_type=User)

            brand_member_state = brand.brand_member_states.filter(user=user)[0]
            
            brand_member_state.state = BrandMemberStateEnum.INACTIVE
            brand_member_state.save(update_fields=["state"])

            state = brand_member_state.state

            return DeactivateBrandAccount(brand=brand,state=state)
            
        
        


class BrandManagerCreateInput(graphene.InputObjectType):
    brand = graphene.ID(
        required=True, description="ID of the Brand for which brand manager to be created."
    )

    users = graphene.List(
        graphene.ID, required=True, description="List of user IDs which will be the brand manager of the brand."
    )


class BrandManagerCreate(BaseMutation):

    brand = graphene.Field(Brand, description = "Brand")
    class Arguments:
        input = BrandManagerCreateInput(
            required=True, description="Fields required to create Brand Manager of the Brand."
        )

    class Meta:
        description = "Brand manager create"
        return_field_name = "brand"
        error_type_field = "brand_errors"

    @classmethod
    def update_brand_managers(cls, brand, brand_manager_emails):
        product_models.SourcingRequest.objects.filter(brand=brand).update(brand_managers=brand_manager_emails)
        BrandSourcingRequest.objects.filter(brand=brand).update(brand_managers=brand_manager_emails)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        input = data['input']
        brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)
        users = get_nodes(input['users'],"User",User)
        
        models.StaffBrandMapping.objects.filter(brand=brand).delete()

        for user in users:
            models.StaffBrandMapping.objects.create(
                brand = brand,
                user = user
            )
        
        brand_manager_emails = ",".join(brand.staff_brand_mappings.all().values_list('user__email', flat=True))
        
        cls.update_brand_managers(brand, brand_manager_emails)

        return cls(brand=brand)


class BrandCommissionCreateUpdateInput(graphene.InputObjectType):
    brand = graphene.ID(required=True, description="Brand ID")
    commission_percentage = graphene.Float(required=True, description="Brand Commission Precentage")
    zaamo_commission = graphene.Float(required=False, description="Zaamo Commission Precentage")


class BrandCommissionCreateUpdate(BaseMutation):

    brand_commission = graphene.Field(BrandCommission, description = "Brand Commission Details.")
    
    class Arguments:
        input = BrandCommissionCreateUpdateInput(
            required=True, description = "Brand Commission Create Update Input."
        )

    class Meta:
        description = "Brand Commission Create Update."
        error_type_field = "brand_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        input = data['input']
        brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)
        if not brand:
            raise ValidationError(message="In-valid brand id")

        commission_percentage = input['commission_percentage']
        zaamo_commission = input.get('zaamo_commission', 2.00)

        brand_commission_check = models.Commission.objects.filter(brand=brand)
        
        if brand_commission_check:
            brand_commission = brand_commission_check.first()
            brand_commission.commission_percentage=commission_percentage
            brand_commission.zaamo_commission=zaamo_commission
            brand_commission.save()
        else:
            brand_commission = models.Commission.objects.create(brand = brand, 
                                                        commission_percentage = input['commission_percentage'],
                                                        zaamo_commission = input.get('zaamo_commission', 2.00)
                                                        )
        
        return cls(brand_commission=brand_commission)


class BrandEmailCreateInput(graphene.InputObjectType):
    brand = graphene.ID(required=True, description="Brand ID")
    email = graphene.String(required=True, description="Brand Email")
    state = BrandEmailStateEnums(required=False, description = "Brand Email State")


class BrandEmailCreate(BaseMutation):

    brand_email = graphene.Field(BrandEmail, description = "Brand Email Details.")
    
    class Arguments:
        input = BrandEmailCreateInput(
            required=True, description = "Brand Email Create Input."
        )

    class Meta:
        description = "Brand Email Create."

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        input = data['input']
        brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)
        
        filter_options = {
            'brand_id': brand,
            'brand_email': input['email']
        }
        if input.get('state') is not None:
            filter_options['state'] = input.get('state')
        else:
            filter_options['state'] = BrandEmailStateEnum.SECONDARY
        
        if not brand:
            raise ValidationError(message="In-valid brand id")
        
        brand_email_check = models.BrandEmail.objects.filter(**filter_options)
        
        if brand_email_check:
            brand_email = brand_email_check.first()
        else:
            brand_email = models.BrandEmail.objects.create(**filter_options)
        
        return cls(brand_email=brand_email)


class BrandEmailUpdateInput(graphene.InputObjectType):
    brand_email = graphene.ID(required=True, description="Primary key for BrandEmail Model.")
    email = graphene.String(required=False, description="Brand Email Address.")
    state = BrandEmailStateEnums(required=False, description="Brand Email State.")

class BrandEmailUpdate(BaseMutation):

    brand_email = graphene.Field(BrandEmail, description="Brand Email Details.")

    class Arguments:
        input = BrandEmailUpdateInput(required=True, description="Brand Email Update Input.")

    class Meta:
        description = "Brand Email Update."

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        brand_email = cls.get_node_or_error(info, input['brand_email'], only_type=BrandEmail)
        
        if not brand_email:
            raise ValidationError(message="Invalid BrandEmail ID")

        if input.get('email') is not None:
            brand_email.brand_email = input.get('email')

        if input.get('state') is not None:
            brand_email.state = input.get('state')

        brand_email.save()

        return cls(brand_email=brand_email)

class BrandEmailDeleteInput(graphene.InputObjectType):
    brand_email = graphene.ID(required=True, description="Primary key for BrandEmail Model.")

class BrandEmailDelete(BaseMutation):

    success = graphene.Boolean(description="Brand Email Delete Success.")

    class Arguments:
        input = BrandEmailDeleteInput(required=True, description="Brand Email Delete Input.")

    class Meta:
        description = "Brand Email Delete."

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        brand_email = cls.get_node_or_error(info, input['brand_email'], only_type=BrandEmail)
        
        if not brand_email:
            raise ValidationError(message="Invalid BrandEmail ID")
        
        brand_email.delete()

        return cls(success=True)

class BrandMobileDeleteInput(graphene.InputObjectType):
    brand = graphene.ID(required=True, description="Brand Id")
    mobile_no = graphene.String(required=True, description="mobile no to be deleted")

class BrandMobileDelete(BaseMutation):

    success = graphene.Boolean(description="Brand Email Delete Success.")
    message = graphene.String(description="success or failure message")

    class Arguments:
        input = BrandMobileDeleteInput(required=True, description="Brand Mobile Delete Input.")

    class Meta:
        description = "Brand Mobile Delete."

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)

        brand_mobile = models.BrandMobile.objects.filter(brand=brand, mobile_no=input.get("mobile_no")).first()        
        
        if not brand_mobile:
            success=False
            message = "This mobile_no doesn't exist for the given brand"
        else:
            brand_mobile.delete()
            success=True
            message = "mobile_no deleted for the given brand"

        return cls(success=success, message=message)


class BrandShippingDataCreateInput(graphene.InputObjectType):
    brand = graphene.ID(required=True, description="Brand ID")
    home_state_pincode = graphene.String(required=False, description="Home State Pincode")
    country = graphene.String(required=False, description="Country")
    currency = graphene.String(required=False, description="Currency")
    shipping_cost_same_state_amount = graphene.Float(required=False, description="shipping cost same state amount")
    shipping_cost_other_state_amount = graphene.Float(required=False, description="shipping cost other state amount")
    min_order_value_free_cost_amount = graphene.Float(required=False, description="min order value free cost amount")



class BrandShippingDataCreate(BaseMutation):

    brand_shipping_data = graphene.Field(BrandShippingData, description="Brand Shipping Data.")

    class Arguments:
        input = BrandShippingDataCreateInput(
            required=True, description="Brand Shipping Data Create Input."
        )

    class Meta:
        description = "Brand Shipping Data Create."

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        brand = cls.get_node_or_error(info, input['brand'], only_type=Brand)
        
        if not brand:
            raise ValidationError(message="In-valid brand id")

        input['brand'] = brand

        brand_shipping_data_check = models.BrandShippingData.objects.filter(brand=brand)

        if brand_shipping_data_check:
            brand_shipping_data = brand_shipping_data_check.first()
        else:
            brand_shipping_data = models.BrandShippingData.objects.create(**input)

        return cls(brand_shipping_data=brand_shipping_data)

class BrandShippingDataUpdateInput(graphene.InputObjectType):
    brand_shipping_data = graphene.ID(required=True, description="Primary key for BrandShippingData Model.")
    home_state_pincode = graphene.String(required=False, description="Home State Pincode")
    country = graphene.String(required=False, description="Country")
    currency = graphene.String(required=False, description="Currency")
    shipping_cost_same_state_amount = graphene.Float(required=False, description="shipping cost same state amount")
    shipping_cost_other_state_amount = graphene.Float(required=False, description="shipping cost other state amount")
    min_order_value_free_cost_amount = graphene.Float(required=False, description="min order value free cost amount")



class BrandShippingDataUpdate(BaseMutation):

    brand_shipping_data = graphene.Field(BrandShippingData, description="Brand Shipping Data.")

    class Arguments:
        input = BrandShippingDataUpdateInput(
            required=True, description="Brand Shipping Data Update Input."
        )

    class Meta:
        description = "Brand Shipping Data Update."

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        brand_shipping_data = cls.get_node_or_error(info, input['brand_shipping_data'], only_type=BrandShippingData)
        
        if not brand_shipping_data:
            raise ValidationError(message="In-valid brand_shipping_data id")

        input.pop("brand_shipping_data", None)

        brand_shipping_data.__dict__.update(**input) 
        brand_shipping_data.save()

        return cls(brand_shipping_data=brand_shipping_data)

class BrandShippingDataDeleteInput(graphene.InputObjectType):
    brand_shipping_data = graphene.ID(required=True, description="Primary key for BrandShippingData Model.")


class BrandShippingDataDelete(BaseMutation):

    success = graphene.Boolean(description="success of Brand Shipping Data delete.")

    class Arguments:
        input = BrandShippingDataDeleteInput(
            required=True, description="Brand Shipping Data Delete Input."
        )

    class Meta:
        description = "Brand Shipping Data Delete."

    @classmethod
    def perform_mutation(cls, root, info, **data):
        input = data['input']
        brand_shipping_data = cls.get_node_or_error(info, input['brand_shipping_data'], only_type=BrandShippingData)
        
        if not brand_shipping_data:
            raise ValidationError(message="In-valid brand_shipping_data id")

        brand_shipping_data.delete()

        return cls(success=True)
