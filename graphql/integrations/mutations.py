import graphene
from saleor.core.permissions import ProductPermissions
from saleor.graphql.integrations.enums import BarterTypeEnum
from ..core.mutations import BaseMutation
from saleor.graphql.product.types import Product
from saleor.external_services.integrations.base import BaseIntegration
from saleor.graphql.core.scalars import PositiveDecimal
from saleor.product import models as product_models
from saleor.warehouse.models import Warehouse,Stock
from saleor.graphql.product.types import ProductVariant

class BrandVariantZaamomapping(graphene.InputObjectType):
    product_id_brand = graphene.String(description="Product id provided by brand", required=True)
    brand_name = graphene.String(description="Product's Brand name", required=True)
    source = graphene.String(description="Source from which products are being created", required=True)

class ProductFields(graphene.InputObjectType):
    brand =  graphene.ID(description="", required=True)
    name = graphene.String(description="Product name", required=True)
    description_json = graphene.JSONString(description = "json description for product")
    brand_barter = BarterTypeEnum(description=(
                                    "Brand barter status of product"
                                ),)
    minimal_variant_price_amount = graphene.String(description = "minimal price among all variants")
    private_metadata = graphene.JSONString(description="Private meta data for product")
    metadata = graphene.JSONString(description="meta data for product")


class VariantFields(graphene.InputObjectType):
    variant_id_brand = graphene.String(description="Variant Id of the product provided by the brand", required=True)
    private_metadata = graphene.JSONString(description = "Private meta data for  variant")
    metadata = graphene.JSONString(description = "meta data for variant")
    sku_id_brand = graphene.String(description="SKU id provided by brand", required=True)
    name = graphene.String(description="variant name")
    price_amount = graphene.String(description="Price of variant")
    cost_price_amount = graphene.String(description="Cost Price of variant")
    default = graphene.Boolean(description="Set this True for only variant among all variants of product which is having least price")

class VariantStock(graphene.InputObjectType):
    quantity = graphene.Int(description="Quantity of the variant", required=True)

class BaseProductInput(graphene.InputObjectType):
    fields = ProductFields(description="Json for product creation and updation", required=True)

class BaseVariantInput(graphene.InputObjectType):
    attributes = graphene.JSONString(description="Json for Variant attributes and its values", required=True)
    fields = VariantFields(description="Json for Variant creation and updation", required=True)
    stock = VariantStock(description="Json for Variant stock.", required=True)

class BaseProductCreateUpdateInput(graphene.InputObjectType):
    category = graphene.ID(description="Category to which product is being mapped.", required=True)
    product_type = graphene.ID(description="Id of product type to which product is being mapped.", required=True)
    brand = graphene.ID(description="Id of brand", required=True)
    attributes = graphene.JSONString(description="All attributes of products and variants")
    brand_variant_zaamomapping = BrandVariantZaamomapping(description="Details required to maintain mapping between zaamo inventory and brand inventory", required=True)
    product = BaseProductInput(description="Product details for creation and updation of products", required = True)

    productimage = graphene.List(graphene.String, description="Url list for product images")
    upload_images_to_ecom = graphene.Boolean(description="If Set to False if Product images will be uploaded on \
    content service only not on Ecom side")

    productvariant = graphene.List(BaseVariantInput, description="Variant details for creation or updation of variants ", required=True)

class BaseProductCreateUpdateMutation(BaseMutation):
    product_creation_or_updation_status = graphene.Boolean(description = "Describe if Data is created or updated succesfully.") 

    class Arguments:
        input = graphene.List(BaseProductCreateUpdateInput, description="Product and its variants details for creation or updation.", required=True)   

    class Meta:
        description = "Create or Update Products and variants data"
        permissions = (ProductPermissions.MANAGE_PRODUCTS, )

    @classmethod
    def get_from_global_id(cls, global_id):
        try:
            id = graphene.Node.from_global_id(global_id)[1]
        except:
            raise Exception("obj with global id {} does not exists".format(global_id))

        return int(id)

    @classmethod
    def clean_input(cls, data):

        cleaned_data = []

        for item in data:
            item["category"] = cls.get_from_global_id(item.get('category'))
            item["product_type"] = cls.get_from_global_id(item.get('product_type'))
            item["brand"] = cls.get_from_global_id(item.get('brand'))
            item["product"]['fields']['brand'] = item["brand"]

            cleaned_data.append({
                "product.category": item["category"],
                "product.producttype": item["product_type"],
                "brand.brand": item["brand"],
                "product.attribute": item["attributes"],
                "product.brand_variant_zaamomapping": item["brand_variant_zaamomapping"],
                "product.product": item["product"],
                "product.productimage": item["productimage"],
                "upload_images_to_ecom": item.get("upload_images_to_ecom", True),
                "product.productvariant": item["productvariant"]

            })

        return cleaned_data

    @classmethod
    def perform_mutation(cls, root, info, **data):
        data = data.get("input")
        
        cleaned_data = cls.clean_input(data)
        obj = BaseIntegration()
        successfully_pushed_data = obj.push_inventory(json_list=cleaned_data)

        return BaseProductCreateUpdateMutation(product_creation_or_updation_status = successfully_pushed_data)

class VariantInventoryUpdateInput(graphene.InputObjectType):
    variant_id = graphene.ID(description="Variant ID that needs to be updated. " ,required=True)
    stock = graphene.Int(descrption="Quantity of variant that needs to be updated. ", required=True)
    selling_price = PositiveDecimal(description=("Selling price for prodcut. "))
    cost_price =  PositiveDecimal(description=("Cost price for prodcut. ")) 


class VariantInventoryUpdate(BaseMutation):
    success = graphene.Boolean(description = "Updation is successfull or not .")
    class Arguments:
        input = graphene.List(VariantInventoryUpdateInput,description="List of Variant values needs to be updated. ",required=True)

    class Meta:
        description = "Create or Update Products and variants data"
        permissions = (ProductPermissions.MANAGE_PRODUCTS, )


    @classmethod
    def perform_mutation(cls, root, info, **data):
        data = data.get('input')
        try:
            warehouse = Warehouse.objects.get(slug="zaamo-master-warehouse")
        except:
            warehouse = Warehouse.objects.none()

        for item in data:
            variant_id = graphene.Node.from_global_id(item.get('variant_id'))[1]
            variant_instance_filter = product_models.ProductVariant.objects.filter(pk=variant_id)

            if variant_instance_filter.exists():
                variant_instance = variant_instance_filter.first()

                if item.get('selling_price'):
                    variant_instance.price_amount = item.get('selling_price')

                if item.get('cost_price'):    
                    variant_instance.cost_price_amount = item.get('cost_price')

                variant_instance.save()
                variant_stock_instance = Stock.objects.filter(warehouse=warehouse, product_variant=variant_instance).first()
                
                if item.get('stock') >=0:
                    variant_stock_instance.quantity = item.get('stock')

                variant_stock_instance.save()
        
        return cls(success=True)

