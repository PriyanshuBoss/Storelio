from collections import defaultdict
from django.conf import settings
from django.db import transaction
import graphene
import re
from django.core.exceptions import ValidationError
from saleor.graphql.meta.mutations import MetadataInput
from decimal import Decimal
from saleor.product import SourcingRequestStatus
from saleor.warehouse.models import Stock
from django.db.models import F, Sum, Case, When
from django.db.models.functions import Coalesce
from saleor.store.store_utilities import get_instance_for_store, get_store_instances_by_ids,get_default_zaamo_store
from saleor.utilities.number_utilities import NumberUtilities
from saleor.discount.emails import send_email_for_voucher_creation , get_voucher_creation_context ,get_voucher_creation_context_for_brand,send_email_for_brand_on_voucher_creation
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.string_utilities import StringUtilities
from ...core.permissions import DiscountPermissions
from ...core.utils.promo_code import generate_promo_code, is_available_promo_code
from ...discount import VoucherType, DiscountValueType , VoucherOwner , models
from ...discount.error_codes import DiscountErrorCode
from ...product.tasks import (
    update_products_minimal_variant_prices_of_catalogues_task,
    update_products_minimal_variant_prices_of_discount_task,
)
from ..core.mutations import BaseMutation, ModelDeleteMutation, ModelMutation
from ..core.scalars import PositiveDecimal
from ..core.types.common import DiscountError
from ..core.validators import validate_price_precision
from ..product.types import Category, Collection, Product
from .enums import DiscountValueTypeEnum, VoucherOwnerEnum, VoucherTypeEnum,DealTypeEnum
from .types import Sale, Voucher, VoucherStoreDeal
from saleor.external_services.messaging.messaging_impl import MessagingImpl
from saleor.account.models import User
from saleor.utilities.request_utilities import RequestUtilities
from saleor.store.models import StoreInfo
from saleor.discount.tasks import product_value_deal_update,update_value_deal_voucher_task
from saleor.product.models import SourcingRequest

class CatalogueInput(graphene.InputObjectType):
    products = graphene.List(
        graphene.ID, description="Products related to the discount.", name="products"
    )
    categories = graphene.List(
        graphene.ID,
        description="Categories related to the discount.",
        name="categories",
    )
    collections = graphene.List(
        graphene.ID,
        description="Collections related to the discount.",
        name="collections",
    )


class BaseDiscountCatalogueMutation(BaseMutation):
    class Meta:
        abstract = True

    @classmethod
    def recalculate_minimal_prices(cls, products, categories, collections):
        update_products_minimal_variant_prices_of_catalogues_task.delay(
            product_ids=[p.pk for p in products],
            category_ids=[c.pk for c in categories],
            collection_ids=[c.pk for c in collections],
        )

    @classmethod
    def add_catalogues_to_node(cls, node, input):
        products = input.get("products", [])
        if products:
            products = cls.get_nodes_or_error(products, "products", Product)
            node.products.add(*products)
        categories = input.get("categories", [])
        if categories:
            categories = cls.get_nodes_or_error(categories, "categories", Category)
            node.categories.add(*categories)
        collections = input.get("collections", [])
        if collections:
            collections = cls.get_nodes_or_error(collections, "collections", Collection)
            node.collections.add(*collections)
        # Updated the db entries, recalculating discounts of affected products
        cls.recalculate_minimal_prices(products, categories, collections)

    @classmethod
    def remove_catalogues_from_node(cls, node, input):
        products = input.get("products", [])
        if products:
            products = cls.get_nodes_or_error(products, "products", Product)
            node.products.remove(*products)
        categories = input.get("categories", [])
        if categories:
            categories = cls.get_nodes_or_error(categories, "categories", Category)
            node.categories.remove(*categories)
        collections = input.get("collections", [])
        if collections:
            collections = cls.get_nodes_or_error(collections, "collections", Collection)
            node.collections.remove(*collections)
        # Updated the db entries, recalculating discounts of affected products
        cls.recalculate_minimal_prices(products, categories, collections)


class VoucherInput(graphene.InputObjectType):
    type = VoucherTypeEnum(
        description=("Voucher type: PRODUCT, CATEGORY SHIPPING or ENTIRE_ORDER."),
        required=True
    )
    name = graphene.String(description="Voucher name.")
    code = graphene.String(description="Code to use the voucher.")
    start_date = graphene.types.datetime.DateTime(
        description="Start date of the voucher in ISO 8601 format."
    )
    end_date = graphene.types.datetime.DateTime(
        description="End date of the voucher in ISO 8601 format."
    )
    discount_value_type = DiscountValueTypeEnum(
        description="Choices: fixed or percentage."
    )
    discount_value = PositiveDecimal(description="Value of the voucher.")
    products = graphene.List(
        graphene.ID, description="Products discounted by the voucher.", name="products"
    )
    collections = graphene.List(
        graphene.ID,
        description="Collections discounted by the voucher.",
        name="collections",
    )
    categories = graphene.List(
        graphene.ID,
        description="Categories discounted by the voucher.",
        name="categories",
    )
    brands = graphene.List(graphene.ID, description="brands discounted by the voucher",
    name="brands")
    min_amount_spent = PositiveDecimal(
        description="Min purchase amount required to apply the voucher."
    )
    min_checkout_items_quantity = graphene.Int(
        description="Minimal quantity of checkout items required to apply the voucher."
    )
    countries = graphene.List(
        graphene.String,
        description="Country codes that can be used with the shipping voucher.",
    )
    apply_once_per_order = graphene.Boolean(
        description="Voucher should be applied to the cheapest item or entire order."
    )
    apply_once_per_customer = graphene.Boolean(
        description="Voucher should be applied once per customer."
    )
    usage_limit = graphene.Int(
        description="Limit number of times this voucher can be used in total."
    )
    max_discount_value = PositiveDecimal(description="maximum discount value that can be applied")
    metadata = graphene.List(MetadataInput, description="stores the metadata on vouchar")
    private_metadata = graphene.List(MetadataInput, description="stores the private metadta of voucher")
    owner = VoucherOwnerEnum(
        description="Choices: fixed or percentage."
    )
        
class VoucherCreate(ModelMutation):
    class Arguments:
        input = VoucherInput(
            required=True, description="Fields required to create a voucher."
        )
        store_id = graphene.String(description="store id for coupon", required=True)

    class Meta:
        description = "Creates a new voucher."
        model = models.Voucher
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def process_metadata(cls, input_data):
        metadata_dict = {field.key: field.value for field in input_data}

        return metadata_dict

    @classmethod
    def clean_input(cls, info, instance, data):
        code = data.get("code", None)
        if not code:
            data["code"] = generate_promo_code()
        elif not is_available_promo_code(code):
            raise ValidationError(
                {
                    "code": ValidationError(
                        "Promo code already exists.",
                        code=DiscountErrorCode.ALREADY_EXISTS,
                    )
                }
            )
        cleaned_input = super().clean_input(info, instance, data)
        min_spent_amount = cleaned_input.pop("min_amount_spent", None)
        
        if min_spent_amount is not None:
            try:
                validate_price_precision(min_spent_amount, instance.currency)
            except ValidationError as error:
                error.code = DiscountErrorCode.INVALID.value
                raise ValidationError({"min_spent_amount": error})
            cleaned_input["min_spent_amount"] = min_spent_amount
        
        max_discount_value = cleaned_input.pop('max_discount_value', None)

        if max_discount_value is not None:
            try:
                validate_price_precision(max_discount_value, instance.currency)
            except ValidationError as error:
                raise ValidationError({"max_discount_value": error})
            
            cleaned_input['max_discount_value'] = max_discount_value
        
        cleaned_input['user'] = info.context.user
        store_instance = get_instance_for_store(cleaned_input.get('store_id'))
        
        if not store_instance:
            raise ValidationError({'error':"In-valid store id"})

        cleaned_input['store'] = store_instance
        cleaned_input['metadata'] = cls.process_metadata(data.get('metadata', []))
        cleaned_input['private_metadata'] = cls.process_metadata(data.get('private_metadata', []))

        return cleaned_input

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        store_id = data.get('store_id')
        data['input']['store_id'] = store_id

        return super().perform_mutation(_root, info, **data)


class VoucherUpdate(VoucherCreate):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a voucher to update.")
        input = VoucherInput(
            required=True, description="Fields required to update a voucher."
        )

        
    class Meta:
        description = "Updates a voucher."
        model = models.Voucher
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def prev_code_input(cls,info,data):
        voucher_id = data.get("id")
        voucher_instance = cls.get_node_or_error(info,voucher_id)
        if voucher_instance:
            data['input']['code'] = voucher_instance.code
        
    @classmethod
    def clean_input(cls, info, instance, data):
        cleaned_input = {}
        cleaned_input.update(data)       
        min_spent_amount = cleaned_input.pop("min_amount_spent", None)
        
        if min_spent_amount is not None:
            try:
                validate_price_precision(min_spent_amount, instance.currency)
            except ValidationError as error:
                error.code = DiscountErrorCode.INVALID.value
                raise ValidationError({"min_spent_amount": error})
            cleaned_input["min_spent_amount"] = min_spent_amount
        
        max_discount_value = cleaned_input.pop('max_discount_value', None)

        if max_discount_value is not None:
            try:
                validate_price_precision(max_discount_value, instance.currency)
            except ValidationError as error:
                raise ValidationError({"max_discount_value": error})
            
            cleaned_input['max_discount_value'] = max_discount_value

        cleaned_input['metadata'] = cls.process_metadata(data.get('metadata', []))
        cleaned_input['private_metadata'] = cls.process_metadata(data.get('private_metadata', []))

        return cleaned_input

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        cls.prev_code_input(info,data)
        return super().perform_mutation(_root, info, **data)


class VoucherDelete(ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a voucher to delete.")

    class Meta:
        description = "Deletes a voucher."
        model = models.Voucher
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"


class VoucherBaseCatalogueMutation(BaseDiscountCatalogueMutation):
    voucher = graphene.Field(
        Voucher, description="Voucher of which catalogue IDs will be modified."
    )

    class Arguments:
        id = graphene.ID(required=True, description="ID of a voucher.")
        input = CatalogueInput(
            required=True,
            description=("Fields required to modify catalogue IDs of voucher."),
        )

    class Meta:
        abstract = True


class VoucherAddCatalogues(VoucherBaseCatalogueMutation):
    class Meta:
        description = "Adds products, categories, collections to a voucher."
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        voucher = cls.get_node_or_error(
            info, data.get("id"), only_type=Voucher, field="voucher_id"
        )
        cls.add_catalogues_to_node(voucher, data.get("input"))
        return VoucherAddCatalogues(voucher=voucher)


class VoucherRemoveCatalogues(VoucherBaseCatalogueMutation):
    class Meta:
        description = "Removes products, categories, collections from a voucher."
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        voucher = cls.get_node_or_error(
            info, data.get("id"), only_type=Voucher, field="voucher_id"
        )
        cls.remove_catalogues_from_node(voucher, data.get("input"))
        return VoucherRemoveCatalogues(voucher=voucher)


class SaleInput(graphene.InputObjectType):
    name = graphene.String(description="Voucher name.")
    type = DiscountValueTypeEnum(description="Fixed or percentage.")
    value = PositiveDecimal(description="Value of the voucher.")
    products = graphene.List(
        graphene.ID, description="Products related to the discount.", name="products"
    )
    categories = graphene.List(
        graphene.ID,
        description="Categories related to the discount.",
        name="categories",
    )
    collections = graphene.List(
        graphene.ID,
        description="Collections related to the discount.",
        name="collections",
    )
    start_date = graphene.types.datetime.DateTime(
        description="Start date of the voucher in ISO 8601 format."
    )
    end_date = graphene.types.datetime.DateTime(
        description="End date of the voucher in ISO 8601 format."
    )


class SaleUpdateMinimalVariantPriceMixin:
    @classmethod
    def success_response(cls, instance):
        # Update the "minimal_variant_prices" of the associated, discounted
        # products (including collections and categories).
        update_products_minimal_variant_prices_of_discount_task.delay(instance.pk)
        return super().success_response(instance)


class SaleCreate(SaleUpdateMinimalVariantPriceMixin, ModelMutation):
    class Arguments:
        input = SaleInput(
            required=True, description="Fields required to create a sale."
        )

    class Meta:
        description = "Creates a new sale."
        model = models.Sale
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"


class SaleUpdate(SaleUpdateMinimalVariantPriceMixin, ModelMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a sale to update.")
        input = SaleInput(
            required=True, description="Fields required to update a sale."
        )

    class Meta:
        description = "Updates a sale."
        model = models.Sale
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"


class SaleDelete(SaleUpdateMinimalVariantPriceMixin, ModelDeleteMutation):
    class Arguments:
        id = graphene.ID(required=True, description="ID of a sale to delete.")

    class Meta:
        description = "Deletes a sale."
        model = models.Sale
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"


class SaleBaseCatalogueMutation(BaseDiscountCatalogueMutation):
    sale = graphene.Field(
        Sale, description="Sale of which catalogue IDs will be modified."
    )

    class Arguments:
        id = graphene.ID(required=True, description="ID of a sale.")
        input = CatalogueInput(
            required=True,
            description="Fields required to modify catalogue IDs of sale.",
        )

    class Meta:
        abstract = True


class SaleAddCatalogues(SaleBaseCatalogueMutation):
    class Meta:
        description = "Adds products, categories, collections to a voucher."
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        sale = cls.get_node_or_error(
            info, data.get("id"), only_type=Sale, field="sale_id"
        )
        cls.add_catalogues_to_node(sale, data.get("input"))
        return SaleAddCatalogues(sale=sale)


class SaleRemoveCatalogues(SaleBaseCatalogueMutation):
    class Meta:
        description = "Removes products, categories, collections from a sale."
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        sale = cls.get_node_or_error(
            info, data.get("id"), only_type=Sale, field="sale_id"
        )
        cls.remove_catalogues_from_node(sale, data.get("input"))
        return SaleRemoveCatalogues(sale=sale)


class VoucherBulkCreate(BaseMutation):

    success = graphene.Boolean(description="status for voucher bulk creation")
    voucher_object_list = graphene.List(Voucher,description ="Voucher object  list")

    class Arguments:
        input = VoucherInput(
            required=True, description="Fields required to create multiple voucher."
        )
        stores = graphene.List(graphene.String, description="store ids for coupon", required=False)
        is_shipping = graphene.Boolean(description="Is shipping for Voucher" , required = False)
        mixed_coupon_card_name = graphene.String(description="mixed coupon card name",required = False)
        deal_type = DealTypeEnum(description=("Deal Type : BUY_M_GET_N_FREE ,BUY_M_GET_Y_OFF ,BUY_M_GET_X_PERC_OFF_N_PROD "),
        required=False)
        buy_m_products = graphene.Int(description = "Number of products to buy for offer" , required = False)  
        discount_n_products  = graphene.Int(description = "Number of products to get offer on" , required = False)
        y_percent_discount = graphene.Int(description="Value of the voucher.")
        max_products_allowed = graphene.Int(description = "Maximum products allowed in checkout for discount")


    class Meta:
        description = "Creates new vouchers for stores"
        model = models.Voucher
        permissions = (DiscountPermissions.MANAGE_DISCOUNTS,)
        error_type_class = DiscountError
        error_type_field = "discount_errors"

    @classmethod
    def generate_code_for_voucher(cls, data):
        code = data.get("input").get('code', None)
        if not code:   
            code = generate_promo_code()
        elif not is_available_promo_code(code):
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
    def process_metadata(cls, input_data):
        metadata_dict = {field.key: field.value for field in input_data}

        return metadata_dict

    @classmethod
    def process_data_for_many_to_many_save(cls, info, cleaned_input, key):

       data_list = cleaned_input.get(key, [])
       instance_id_list = [cls.get_node_or_error(info, data).id for data in data_list]
       cleaned_input.pop(key, [])
       
       return instance_id_list

    @classmethod
    def clean_input_util(cls, info, data):
        
        cleaned_input = {}
        cleaned_input.update(data.get('input'))

        min_spent_amount = cleaned_input.pop("min_amount_spent", None)
        
        if not cleaned_input.get('discount_value'):
            cleaned_input["discount_value"] = 0
        
        if min_spent_amount is not None:
            # try:
            #     validate_price_precision(min_spent_amount, settings.DEFAULT_CURRENCY)
            # except ValidationError as error:
            #     error.code = DiscountErrorCode.INVALID.value
            #     raise ValidationError({"min_spent_amount": error})
            min_spent_amount = round(min_spent_amount,2)
            cleaned_input["min_spent_amount"] = min_spent_amount
        
        max_discount_value = cleaned_input.pop('max_discount_value', None)

        if max_discount_value is not None:
            # try:
            #     validate_price_precision(max_discount_value, settings.DEFAULT_CURRENCY)
            # except ValidationError as error:
            #     raise ValidationError({"max_discount_value": error})
            max_discount_value = round(max_discount_value,2)
            cleaned_input['max_discount_value'] = max_discount_value
        
        cleaned_input['user'] = info.context.user
        cleaned_input['metadata'] = cls.process_metadata(cleaned_input.get('metadata', []))
        cleaned_input['private_metadata'] = cls.process_metadata(cleaned_input.get('private_metadata', []))
        
        return cleaned_input

    @classmethod
    def fetch_variant_stock_lists_from_voucher(cls,voucher):
        try:
            in_stock_dict = defaultdict(list)
            out_of_stock_dict = defaultdict(list)
            in_stock = []
            out_of_stock = []
            stocks = (Stock.objects.select_related("product_variant",'product_variant__product')
                    .values("product_variant__name",'product_variant__product__name')
                    .annotate(
                        total_quantity_allocated=Coalesce(Sum("allocations__quantity_allocated"), 0)
                    )
                    .annotate(total_quantity=Coalesce(Sum("quantity",distinct=True), 0))
                    .annotate(total_available=Case(When(product_variant__track_inventory=False, then=1), 
                    default=(F("total_quantity") - F("total_quantity_allocated"))))
                    .filter(product_variant__product_id__in=voucher.products.all().values('id')))

            for stock in stocks:
                
                if stock['total_available']>0:
                    in_stock_dict[stock['product_variant__product__name']].append(stock['product_variant__name'])
                else:
                    out_of_stock_dict[stock['product_variant__product__name']].append(stock['product_variant__name'])
            
            for product_name,v_names in in_stock_dict.items():
                in_stock.append(f"{product_name} ({', '.join(v_names)})")
                
            for product_name,v_names in out_of_stock_dict.items():
                out_of_stock.append(f"{product_name} ({', '.join(v_names)})")
                
            return ', '.join(in_stock),', '.join(out_of_stock)
        
        except Exception as e:
            return None,None
        
    @classmethod
    def send_mail_for_voucher_creation_to_managers(cls, temp, voucher_instance):
        temp['created_at'] = voucher_instance.created_at
        voucher_text=get_voucher_creation_context(temp)
        store_instance = temp['store']
        cc = []
        if voucher_instance.owner == VoucherOwner.BRAND:

            if voucher_instance.type == VoucherType.SPECIFIC_PRODUCT:

                voucher_products = voucher_instance.products.all()
                if voucher_products:
                    brand_manager_emails = list(voucher_products[0].brand.staff_brand_mappings.all().values_list('user__email', flat=True))
                    cc.extend(brand_manager_emails)
        
        influence_managers = list(store_instance.staff_store_mappings.all().values_list('user__email', flat=True))
        cc.extend(influence_managers)

        subject = temp.get('code')
        if voucher_instance.owner == VoucherOwner.BRAND and voucher_instance.code.startswith('SZ'):
            brand_name = ''

            if voucher_instance.products.first():
                brand_name = voucher_instance.products.first().brand.brand_name

            elif voucher_instance.brands.first():
                brand_name = voucher_instance.brands.first().brand_name

            subject = ' - '.join([temp.get('code'), brand_name, store_instance.store_name])

            in_stock,out_of_stock = cls.fetch_variant_stock_lists_from_voucher(voucher_instance)
            voucher_text = f"{voucher_text}\n\nIn stock: {in_stock}\nOut of Stock: {out_of_stock}"

        send_email_for_voucher_creation.delay(subject, voucher_text, cc=cc)

    @classmethod
    def send_message_for_voucher_creation_to_influencer(cls, voucher_instance):
        voucher_name = voucher_instance.name
        user_mobile_number_list = list(voucher_instance.store.store_members.filter(store_id=voucher_instance.store_id).values_list('user__mobile_no', flat=True))
        MessagingImpl.send_message_to_influencer_for_coupon_creation.delay(voucher_name, user_mobile_number_list)  
       
    @classmethod
    def clean_input_for_entire_cart_discount(cls, info, data):

        cleaned_input = cls.clean_input_util(info, data)
        store_list =  data.get('stores', [])
        store_list = [graphene.Node.from_global_id(store_id)[1] for store_id in store_list]
        stores_dict = get_store_instances_by_ids(store_list)
        data.pop('stores')
        bulk_create_list = []

        for store in store_list:
            temp = {}
            temp.update(cleaned_input)
            store_id = NumberUtilities.convert_string_to_number(store)
            
            if not stores_dict.get(store_id):
                raise ValidationError(
                    {
                        'error': "In-valid store_id: " + store
                    }
                )
            
            store_instance = stores_dict.get(store_id)
            temp['store'] = store_instance
            temp['code'] = cls.generate_code_for_voucher(data)
            temp['is_shipping'] = data.get('is_shipping',False)
            instance = models.Voucher(**temp)

            bulk_create_list.append(instance)

            cls.send_mail_for_voucher_creation_to_managers(temp, instance)
            cls.send_message_for_voucher_creation_to_influencer(instance)

        return bulk_create_list
    
    @classmethod
    def check_sourcing_coupon_creation(cls,info,data):
        name = data.get('input').get('name')
        owner = data.get('input').get('owner')
        start_date = TimeUtilities.get_current_date_time()
        end_date = TimeUtilities.add_time_in_timestamp(TimeUtilities.get_current_date_time(),7)
        if owner == VoucherOwnerEnum.BRAND and name.startswith('SZ'):
            
            data['input']['start_date'] = start_date
            data['input']['end_date'] =  end_date
            
            all_ids = re.findall('[0-9]+',name)

            for sourcing_id in all_ids:

                sourcing_id = NumberUtilities.convert_string_to_number(sourcing_id)
                if not SourcingRequest.objects.filter(id=sourcing_id).exists():
                    continue
                global_sourcing_id = graphene.Node.to_global_id("SourcingRequest",sourcing_id)
                sourcing_request_instance = cls.get_node_or_error(info,global_sourcing_id)
                store_instance = cls.get_node_or_error(info,data.get('stores')[0])
                mapped_store = sourcing_request_instance.store_id
                if mapped_store!=store_instance.id:
                    raise ValidationError(
                    {
                        "SouringRequestId": ValidationError(
                            "Sourcing Request Id is not mapped with the Store Id",
                            code=DiscountErrorCode.INVALID,
                        )
                    }
            )

    @classmethod
    def update_sourcing_request_status(cls,info,data):
        name = data.get('input').get('name')
        owner = data.get('input').get('owner')
        
        if owner == VoucherOwnerEnum.BRAND and name.startswith('SZ'):
            
            all_ids = re.findall('[0-9]+',name)

            for sourcing_id in all_ids:

                sourcing_id = NumberUtilities.convert_string_to_number(sourcing_id)
                if not SourcingRequest.objects.filter(id=sourcing_id).exists():
                    continue
                global_sourcing_id = graphene.Node.to_global_id("SourcingRequest",sourcing_id)
                sourcing_request_instance = cls.get_node_or_error(info,global_sourcing_id)
                sourcing_request_instance.status = SourcingRequestStatus.BRAND_COUPON_CREATED
                sourcing_request_instance.save()


    @classmethod
    def mail_for_brand(cls,info,cleaned_input,stores_dict,products_instance,brands=None):
        owner = cleaned_input.get('owner')
        name = cleaned_input.get('name')
        if owner == VoucherOwnerEnum.BRAND and name.startswith('SZ') and len(brands)==0:

            try:
                all_ids = re.findall('[0-9]+',name)
                variant_instance_dict = {}
                for sourcing_id in all_ids:
                    sourcing_id = NumberUtilities.convert_string_to_number(sourcing_id)
                    global_sourcing_id = graphene.Node.to_global_id("SourcingRequest",sourcing_id)
                    sourcing_request_instance = cls.get_node_or_error(info,global_sourcing_id)
                    product_id = sourcing_request_instance.product_id
                    variant_instance_dict[product_id] = sourcing_request_instance.variant

                product = products_instance[0]
                store_id = list(stores_dict.keys())[0]
                store_instance = stores_dict.get(store_id)
                brand = product.brand
                brand_email_instance = brand.brand_emails.filter(state='primary').first()
                
                if brand_email_instance:
                    brand_email = brand_email_instance.brand_email
                    voucher_context = get_voucher_creation_context_for_brand(cleaned_input,store_instance,products_instance,variant_instance_dict)
                    send_email_for_brand_on_voucher_creation.delay(voucher_context,mail_type='brand_voucher_creation',recipient_email=brand_email)
            
            except Exception as e:
                pass

    @classmethod
    def voucher_with_deal_type(cls,voucher_instance,data):
        updated_data = {
            'deal_type':data.get('deal_type'),
            'rule':{
                'n_products':data.get('discount_n_products'),
                'y_percent_discount':data.get('y_percent_discount')
            }
        }
        m_products = data.get('buy_m_products')
        if data.get('deal_type') == DealTypeEnum.BUY_M_GET_N_FREE or data.get('deal_type') == DealTypeEnum.BUY_M_GET_X_PERC_OFF_N_PROD:
            voucher_instance.min_checkout_items_quantity = m_products+1
        elif data.get('deal_type') == DealTypeEnum.BUY_M_GET_Y_OFF or data.get('deal_type') == DealTypeEnum.BUY_M_GET_X_PERC_OFF_BUY_N_GET_Y_PERC_OFF:
            voucher_instance.min_checkout_items_quantity = m_products
            
        voucher_instance.discount_rule.update(updated_data)
        voucher_instance.metadata['Brand_discount'] = '100'
        voucher_instance.save()



    @classmethod
    def clean_input_for_specific_discount(cls, info, data):
        
        cls.check_sourcing_coupon_creation(info,data)
        cleaned_input = cls.clean_input_util(info, data)
        store_list =  data.get('stores', [])
        store_list = [graphene.Node.from_global_id(store_id)[1] for store_id in store_list]
        stores_dict = get_store_instances_by_ids(store_list)
        data.pop('stores')
        products_instance = [cls.get_node_or_error(info, data) for data in cleaned_input.get('products',[])]
        products = cls.process_data_for_many_to_many_save(info, cleaned_input, 'products')
        categories = cls.process_data_for_many_to_many_save(info, cleaned_input, 'categories')
        collections = cls.process_data_for_many_to_many_save(info, cleaned_input, 'collections')
        brands = cls.process_data_for_many_to_many_save(info, cleaned_input, 'brands')
        voucher_object_list = []
        for store in store_list:
            temp = {}
            temp.update(cleaned_input)
            store_id = NumberUtilities.convert_string_to_number(store)
            
            if not stores_dict.get(store_id):
                raise ValidationError(  
                    {
                        'error': "In-valid store_id: " + store
                    }
                )
            store_instance = stores_dict.get(store_id)
            temp['store'] = store_instance
            temp['code'] = cls.generate_code_for_voucher(data)
            temp['is_shipping'] = data.get('is_shipping',False)
            instance = models.Voucher(**temp)
            if data.get('mixed_coupon_card_name'):
                instance.metadata['mixed_coupon_card_name'] = data.get('mixed_coupon_card_name')
            if data.get('max_products_allowed'):
                instance.metadata['max_products_allowed'] = data.get('max_products_allowed')
            instance.save()
            
            instance.products.set(products)
            instance.collections.set(collections)
            instance.categories.set(categories)
            instance.brands.set(brands)
            voucher_object_list.append(instance)

            # try:
            #     product_value_deal_update(products,categories,collections,brands,True)
            #     trigger_date =  TimeUtilities.subtract_time_from_timestamp(instance.end_date,0,5,30)
            #     update_value_deal_voucher_task.apply_async(([instance.id]),eta =trigger_date)
            # except:
            #     pass
            #TODO: Commented to not update value_deal key in product metadata

            if data.get('deal_type') and data.get('deal_type') != DealTypeEnum.NORMAL:
                cls.voucher_with_deal_type(instance,data)

            cls.send_mail_for_voucher_creation_to_managers(temp, instance)

            if data.get('input').get('type') != VoucherType.SPECIFIC_BRAND_PRODUCTS:

                cls.send_message_for_voucher_creation_to_influencer(instance)

        cls.mail_for_brand(info,cleaned_input,stores_dict,products_instance,brands)

        return True,voucher_object_list
    
    @classmethod
    def postprocess_cotd_voucher_creation(cls,created,**data):
        store_id = data.get('input').get('store_id')
        name = data.get('input').get('name')

        if name == 'COTD':
            new_coupon = models.Voucher.objects.filter(store_id=store_id,name = name).first()
            if new_coupon:

                collection_instance = new_coupon.collections.first()
                collection_instance.metadata['cotd_coupon_code']=new_coupon.code
                collection_instance.metadata['cotd_coupon_expiry_time'] = new_coupon.end_date
                collection_instance.save()
        
                if created:
                    old_code = new_coupon.code
                    new_coupon.code = 'COTD_'+old_code
                    new_coupon.metadata['collection_queue'] = [{"collection_id":collection_instance.id , "datetime":TimeUtilities.get_current_date_time()}]
                    new_coupon.save()
                
                else:
                    collection_queue  = new_coupon.metadata.get('collection_queue',[])

                    if len(collection_queue)>=6:
                        new_coupon.metadata["collection_queue"].pop(0)

                    collection_queue.append({"collection_id":collection_instance.id , "datetime":TimeUtilities.get_current_date_time()})
                    new_coupon.metadata['collection_queue'] = collection_queue
                    new_coupon.save()
            
            return True

        return False

    @classmethod
    def preprocess_cotd_voucher_creation(cls,root,info,**data):
        
        store_list =  data.get('stores', [])
        name = data.get('input').get('name')
        start_date = TimeUtilities.get_current_date_time()
        end_date = TimeUtilities.add_time_in_timestamp(TimeUtilities.get_current_date_time(),1)
        data['input']['discount_value_type'] = DiscountValueType.PERCENTAGE
        data['input']['discount_value'] = Decimal("25.0")
        data['input']['owner'] = VoucherOwner.ZAAMO
        data['input']['max_discount_value'] = Decimal("500.0")
        data['input']['min_amount_spent'] = Decimal("2000.0")
        data['input']['start_date'] = start_date
        data['input']['end_date'] =  end_date
        collection_list  = [cls.get_node_or_error(info,collection_id).id for collection_id in data.get('input').get('collections',[])]
        store_id = graphene.Node.from_global_id(store_list[0])[1]
        data['input']['store_id'] = store_id
        last_coupon = models.Voucher.objects.filter(store_id=store_id,name = name).first()

        if last_coupon:
            collection_instance = last_coupon.collections.first()

            if collection_instance.metadata.get('cotd'):
                collection_instance.metadata.pop('cotd')

            if collection_instance.metadata.get('cotd_coupon_code'):    
                collection_instance.metadata.pop('cotd_coupon_code')
            
            if collection_instance.metadata.get('cotd_coupon_expiry_time'):
                collection_instance.metadata.pop('cotd_coupon_expiry_time')
                
            collection_instance.save()
            last_coupon.discount_value = data['input']['discount_value'] 
            last_coupon.max_discount_value = data['input']['max_discount_value']
            last_coupon.min_spent_amount = data['input']['min_amount_spent']
            last_coupon.collections.set(collection_list)
            last_coupon.start_date = data.get('input').get('start_date')
            last_coupon.end_date = data.get('input').get('end_date')
            last_coupon.save()
            
            return False,[]
        
        else:

            return cls.core_function(root,info,**data)
      
    @classmethod
    def core_function(cls,root,info,**data):
        created = False
        voucher_object_list = None
        if data.get('input').get('type') == VoucherType.ENTIRE_ORDER:
            bulk_create_list = cls.clean_input_for_entire_cart_discount(info, data)
            voucher_object_list = bulk_create_list
            created = models.Voucher.objects.bulk_create(bulk_create_list)
        elif data.get('input').get('type') == VoucherType.SPECIFIC_PRODUCT:
            created,voucher_object_list = cls.clean_input_for_specific_discount(info, data)
        elif data.get('input').get('type') == VoucherType.SPECIFIC_BRAND_PRODUCTS:
            default_store = get_default_zaamo_store()
            store_id = None
            if default_store:
                store_id = graphene.Node.to_global_id("Store",default_store.id)
            data['stores'] = [store_id]
            created,voucher_object_list = cls.clean_input_for_specific_discount(info,data)
        
        cls.update_sourcing_request_status(info,data)
        cls.add_product_links_in_tnc(voucher_object_list)
        return created,voucher_object_list

    @classmethod
    def add_product_links_in_tnc(cls, vouchers):
        if not vouchers:
            return
        for voucher in vouchers:
            if voucher.owner == VoucherOwner.BRAND and voucher.code.startswith('SZ'):
                links = ''
                store_url = settings.DEFAULT_STORE_URL
                if voucher.store:
                    if voucher.store.store_url:
                        store_url = voucher.store.store_url
                    else:
                        store_url = 'https://zaamo.co/' + voucher.store.slug
                if store_url.endswith('/'):
                    store_url = store_url[:-1]
                for product in voucher.products.all().only('slug', 'name'):
                    links += f"<br><a href={store_url}/products/{product.slug} target=_blank style='color: blue; text-decoration: underline;'>{product.name}</a>"
                if links:
                    links = '<br>Share these links to earn Affiliate commission:' + links
                    metadata = voucher.metadata
                    metadata['conditions'] += links
                    models.Voucher.objects.filter(code=voucher.code).update(metadata=metadata)

    @classmethod
    @transaction.atomic
    def perform_mutation(cls, root, info, **data):
        
        created = False
      
        name = data.get('input').get('name')

        # if name == 'COTD':
        #     voucher_created,voucher_object_list = cls.preprocess_cotd_voucher_creation(root,info,**data)
        #     success=cls.postprocess_cotd_voucher_creation(voucher_created,**data)
        #     return cls(success=success,voucher_object_list = voucher_object_list)

        if name == 'COTD':
            return cls(success=False,voucher_object_list=[])
        
        created,voucher_object_list = cls.core_function(root,info,**data)
        return cls(success= created,voucher_object_list = voucher_object_list)


class AttachDealCardToStore(BaseMutation):

    voucher_store_deal = graphene.Field(VoucherStoreDeal, description="Voucher Store Deal details.")

    class Arguments:
        voucher_id = graphene.ID(required=True, description="ID of a voucher.")

    class Meta:
        description = "Attach dealcard to store."
    
    @classmethod
    def perform_mutation(cls, root, info, **data):
        voucher = cls.get_node_or_error(
            info, data.get("voucher_id"), only_type=Voucher, field="voucher_id"
        )
        if not voucher:
            raise ValidationError("In-valid VoucherID.")
        
        store_id=RequestUtilities.get_store_id_from_headers(info.context)
        store_instance = get_instance_for_store(store_id)
        
        if not store_instance:
            raise ValidationError("In-valid StoreID.")
        
        check_existance = models.VoucherStoreDealMapping.objects.filter(voucher=voucher, store=store_instance)
        if check_existance:
            voucher_store_deal = check_existance.first()
        else:
            voucher_store_deal = models.VoucherStoreDealMapping.objects.create(
                voucher=voucher, 
                store=store_instance
            )
        return cls(voucher_store_deal=voucher_store_deal)


