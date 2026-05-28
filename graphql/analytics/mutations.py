import graphene
from saleor.external_services.shopify_service.tasks import update_product_status_shopify_product_zaamo_task
from saleor.graphql.analytics.resolvers import update_brand_collection_mapping_from_to_publish
from saleor.graphql.core.mutations import BaseMutation
from saleor.product import models as models
from django.core.exceptions import ValidationError
from saleor.graphql.analytics.tasks import create_product_for_pdp_mutations
from saleor.brand.models import Brand
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from saleor.graphql.brand.tasks import explore_content_sync

class pdpPublishProduct(BaseMutation):
    
    class Arguments:
        product_id_brand = graphene.String(description="brand product id")
        variant_id_brands = graphene.List(graphene.String, description="list of brand variant ids")
        brand_id = graphene.ID(description="id of brand")
        to_publish = graphene.Boolean(description = "publish or unpublish product")
        category_id = graphene.ID(description="id of category")
        commission = graphene.Float(description = 'product commission')
        value_deal = graphene.Boolean(description = "toggle for product value bool in product private metadata")
        
    
    class Meta:
        description = "Publish or unpublish a product and Creates a product in postgres if it is not created"

    success = graphene.Boolean(description="Mutation result after call")
    message = graphene.String(description="Error message if any occurs")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        product_id_brand = data.get('product_id_brand')
        variant_id_brands = data.get('variant_id_brands')
        brand_id_global = data.get('brand_id')
        to_publish = data.get('to_publish', False)
        category_id_global = data.get('category_id')
        commission = data.get('commission')
        value_deal = data.get('value_deal')

        if not product_id_brand or not brand_id_global:
            return cls(success=False, message='product_id or brand_id not provided')

        brand_id_int = graphene.Node.from_global_id(brand_id_global)[-1]
        brand = Brand.objects.filter(id=brand_id_int).first()
        brand_name = brand.private_metadata.get('source_name')

        category_id = None
        if category_id_global:
            category_id = graphene.Node.from_global_id(category_id_global)[-1]

        if not brand_name:
            brand_name = brand.brand_name

        if not variant_id_brands or None in variant_id_brands:
            product_mapping = models.BrandVariantZaamoMapping.objects.filter(product_id_brand=product_id_brand, brand_name=brand_name).first()

        else:
            product_mapping = models.BrandVariantZaamoMapping.objects.filter(product_id_brand=product_id_brand,variant_id_brand__in=variant_id_brands, brand_name=brand_name).first()

        if product_mapping:
            product_zaamo = product_mapping.product_zaamo
            prev_published = product_zaamo.is_published
            product_zaamo.is_published = to_publish


            if commission:
                product_zaamo.commission_percentage=commission
                product_zaamo.has_custom_commission=True
                
            if value_deal:
                product_zaamo.metadata['value_deal'] = value_deal
                product_zaamo.metadata['value_updated_at'] = TimeUtilities.get_current_date_time()

            product_zaamo.save()

            if to_publish!=prev_published and product_zaamo.metadata.get('shopify')!=None:
                update_product_status_shopify_product_zaamo_task.delay(product_zaamo.id,to_publish)
                
            update_brand_collection_mapping_from_to_publish(to_publish, product_zaamo)
            explore_content_sync.delay(product_id=product_zaamo.id)
            return cls(success=True, message='')
        
        else:
            arg_data = dict()
            arg_data['brand_id'] = brand_id_int
            arg_data['product_id_brand'] = product_id_brand
            arg_data['variant_id_brands'] = variant_id_brands
            arg_data['to_publish'] = to_publish

            if not category_id:
                return cls(success=False, message='category_id not available')

            category = models.Category.objects.filter(id=category_id).first()

            if category:

                if not 'uncategorized' in category.name:
                    create_product_for_pdp_mutations.delay(arg_data,category_id,commission,value_deal)
                    return cls(success=True, message='')
                    
                else:
                    raise ValidationError(message="selected category isn't allowed.")
            
            return cls(success=False, message="selected category isn't allowed.")

