"""Implements a data loader that load data into Saleor through graphQL.

Notes
-----
This module is designed and working with Saleor 2.9. Update will be necessary
for futur release if the data models changes.

No tests has been implemented as testing would need to create a fake db, which
requires a lot of dev better redo the project as a django app inside saleor
project for easier testing.

"""
from asyncio.log import logger
import json
import os
import sys
from unicodedata import name
import string
import random
from urllib.parse import urlparse
from django.conf import settings
from django.db import transaction

from django.db.models.options import IMMUTABLE_WARNING
from graphene_federation.entity import key

import requests
from io import StringIO, BytesIO
from saleor.brand.models import Brand
from saleor.order.order_complete import OrderEngineHelper
from saleor.product import models as product_models
import graphene
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils.text import slugify
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities

from saleor.warehouse import models as warehouse_models
from saleor.product import models
from saleor.account.models import User
from saleor.product.utils.bulk_upload import override_dict, handle_errors, get_payload
from saleor.graphql.api import schema
from saleor.plugins.manager import PluginsManager
from saleor.product.models import BrandVariantZaamoMapping, Category, ProductType, Attribute, AttributeValue
from saleor.graphql.core.utils import validate_image_file
from saleor.warehouse import models as warehouse_models
from saleor.warehouse.availability import get_default_warehouse_id

try:
    params = {"user": User.objects.get(email=settings.PRODUCT_IMPORT_USER_EMAIL),
    "plugins": PluginsManager(plugins=settings.PLUGINS), 'app': None}
    schema_context = graphene.types.Context(**params)
except Exception as e:
    print(e)



class ETLDataLoader:
    """abstraction around several graphQL query to load data into Saleor.

    Notes
    -----
    This class requires a valid `auth_token` to be provided during
    initialization. An `app` must be first created for example using django cli

    ```bash
    python manage.py create_app etl --permission account.manage_users \
                                    --permission account.manage_staff \
                                    --permission app.manage_apps \
                                    --permission app.manage_apps \
                                    --permission discount.manage_discounts \
                                    --permission plugins.manage_plugins \
                                    --permission giftcard.manage_gift_card \
                                    --permission menu.manage_menus \
                                    --permission order.manage_orders \
                                    --permission page.manage_pages \
                                    --permission product.manage_products \
                                    --permission shipping.manage_shipping \
                                    --permission site.manage_settings \
                                    --permission site.manage_translations \
                                    --permission webhook.manage_webhooks \
                                    --permission checkout.manage_checkouts
    ```

    Attributes
    ----------
    headers : dict
        the headers used to make graphQL queries.
    endpoint_url : str
        the graphQL endpoint url to query to.

    Methods
    -------

    """

    def __init__(self, auth_token='', endpoint_url="http://localhost:8000/graphql/"):
        """initialize the `DataLoader` with an auth_token and an url endpoint.

        Parameters
        ----------
        auth_token : str
            token used to identify called to the graphQL endpoint.
        endpoint_url : str, optional
            the graphQL endpoint to be used , by default "http://localhost:8000/graphql/"
        """
        self.headers = {"Authorization": "Bearer {}".format(auth_token)}
        self.endpoint_url = endpoint_url

    def update_shop_settings(self, **kwargs):
        """update shop settings.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to update the shop settings refer to the
            ShopSettingsInput graphQL type to know what can be overriden.

        Raises
        ------
        Exception
            when shopErrors is not an empty list
        """

        variables = {
            "input": kwargs
        }

        query = """
            mutation ShopSettingsUpdate($input: ShopSettingsInput!) {
              shopSettingsUpdate(input: $input) {
                shop {
                    headerText
                    description
                    includeTaxesInPrices
                    displayGrossPrices
                    chargeTaxesOnShipping
                    trackInventoryByDefault
                    defaultWeightUnit
                    automaticFulfillmentDigitalProducts
                    defaultDigitalMaxDownloads
                    defaultDigitalUrlValidDays
                    defaultMailSenderName
                    defaultMailSenderAddress
                    customerSetPasswordUrl
                }
                shopErrors {
                    field
                    message
                    code
                }
              }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["shopSettingsUpdate"]["shopErrors"]
        handle_errors(errors)

        return response.data["shopSettingsUpdate"]["shop"]

    def update_shop_domain(self, **kwargs):
        """update shop domain.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to update the shop domain refer to the
            SiteDomainInput graphQL type to know what can be overriden.

        Raises
        ------
        Exception
            when shopErrors is not an empty list
        """

        variables = {
            "siteDomainInput": kwargs
        }

        query = """
            mutation ShopDomainUpdate($siteDomainInput: SiteDomainInput!) {
              shopDomainUpdate(input: $siteDomainInput) {
                shop {
                    domain {
                        host
                        sslEnabled
                        url
                    }
                }
                shopErrors {
                    field
                    message
                    code
                }
              }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["shopDomainUpdate"]["shopErrors"]
        handle_errors(errors)

        return response.data["shopSettingsUpdate"]["shop"]["domain"]

    def update_shop_address(self, **kwargs):
        """update shop address.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to update the shop address refer to the
            AddressInput graphQL type to know what can be overriden.

        Raises
        ------
        Exception
            when shopErrors is not an empty list
        """

        variables = {
            "addressInput": kwargs
        }

        query = """
            mutation ShopAddressUpdate($addressInput: AddressInput!) {
              shopAddressUpdate(input: $addressInput) {
                shop {
                    companyAddress {
                        id
                        firstName
                        lastName
                        companyName
                        streetAddress1
                        streetAddress2
                        city
                        cityArea
                        postalCode
                        country {
                            code
                            country
                        }
                        countryArea
                        phone
                        isDefaultShippingAddress
                        isDefaultBillingAddress
                    }
                }
                shopErrors {
                    field
                    message
                    code
                }
              }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["shopAddressUpdate"]["shopErrors"]
        handle_errors(errors)

        return response.data["shopAddressUpdate"]["shop"]["companyAddress"]


    def create_warehouse(self, **kwargs):
        """create a warehouse.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to create the warehouse refer to the
            WarehouseCreateInput graphQL type to know what can be overriden.

        Returns
        -------
        id : str
            the id of the warehouse created

        Raises
        ------
        Exception
            when warehouseErrors is not an empty list
        """
        default_kwargs = {
            "companyName": "Zaamo Ecom",
            "email": "fake@example.com",
            "name": "Zaamo Master Warehouse",
            "address": {
                "streetAddress1": "a fake street adress",
                "city": "Fake City",
                "postalCode": "124507",
                "country": "IN",
                "countryArea": "Haryana"
            }
        }

        override_dict(default_kwargs, kwargs)

        variables = {
            "input": default_kwargs
        }

        query = """
            mutation createWarehouse($input: WarehouseCreateInput!) {
                createWarehouse(input: $input) {
                    warehouse {
                        id
                    }
                    warehouseErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["createWarehouse"]["warehouseErrors"]
        handle_errors(errors)

        return response.data["createWarehouse"]["warehouse"]["id"]

    def create_shipping_zone(self, **kwargs):
        """create a shippingZone.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to create the shippingzone refer to
            the shippingZoneCreateInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the shippingZone created.

        Raises
        ------
        Exception
            when shippingErrors is not an empty list.
        """
        default_kwargs = {
            "name": "CH",
            "countries": [
                "CH"
            ],
            "default": False,
        }

        override_dict(default_kwargs, kwargs)

        variables = {
            "input": default_kwargs
        }

        query = """
            mutation createShippingZone($input: ShippingZoneCreateInput!) {
                shippingZoneCreate(input: $input) {
                    shippingZone {
                        id
                    }
                    shippingErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["shippingZoneCreate"]["shippingErrors"]
        handle_errors(errors)

        return response.data["shippingZoneCreate"]["shippingZone"]["id"]

    def create_attribute(self, **kwargs):
        """create a product attribute.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to create the attribute refer to
            the AttributeCreateInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the attribute created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        default_kwargs = {
            "inputType": "DROPDOWN",
            "name": "default"
        }

        override_dict(default_kwargs, kwargs)

        variables = {
            "input": default_kwargs
        }

        query = """
            mutation createAttribute($input: AttributeCreateInput!) {
                attributeCreate(input: $input) {
                    attribute {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["attributeCreate"]["productErrors"]
        handle_errors(errors)

        return response.data["attributeCreate"]["attribute"]["id"]

    def create_attribute_value(self, attribute_id, **kwargs):
        """create a product attribute value.

        Parameters
        ----------
        attribute_id : str
            id of the attribute on which to add the value.
        **kwargs : dict, optional
            overrides the default value set to create the attribute refer to
            the AttributeValueCreateInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the attribute on which the value was created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        default_kwargs = {
            "name": "default"
        }

        override_dict(default_kwargs, kwargs)

        variables = {
            "attribute": attribute_id,
            "input": default_kwargs
        }

        query = """
            mutation createAttributeValue($input: AttributeValueCreateInput!, $attribute: ID!) {
                attributeValueCreate(input: $input, attribute: $attribute) {
                    attribute{
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["attributeValueCreate"]["productErrors"]
        handle_errors(errors)

        return response.data["attributeValueCreate"]["attribute"]["id"]

    def create_product_type(self, **kwargs):
        """create a product type.

        Parameters
        ----------
        **kwargs : dict, optional
            overrides the default value set to create the type refer to
            the ProductTypeInput graphQL type to know \ can be
            overriden.

        Returns
        -------
        id : str
            the id of the productType created.

        Raises
        ------
            when productErrors is not an empty list.
        """
        default_kwargs = {
            "name": "default",
            "hasVariants": False,
            "productAttributes": [],
            "variantAttributes": [],
            "isDigital": "false",
        }

        override_dict(default_kwargs, kwargs)

        variables = {
            "input": default_kwargs
        }

        query = """
            mutation createProductType($input: ProductTypeInput!) {
                productTypeCreate(input: $input) {
                    productType {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)
        errors = response.data["productTypeCreate"]["productErrors"]
        handle_errors(errors)

        return response.data["productTypeCreate"]["productType"]["id"]

    def create_category(self, **kwargs):
        """create a category.

        Parameters
        ----------
        **kwargs : dict, optionaldict
            overrides the default value set to create the category refer to
            the productTypeCreateInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the productType created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        parent = kwargs.pop('parent', '')
        default_kwargs = {
            "name": "default"
        }

        override_dict(default_kwargs, kwargs)

        variables = {
            "input": default_kwargs,
            "parent": parent
        }


        query = """
            mutation createCategory($input: CategoryInput!, $parent: ID) {
                categoryCreate(input: $input, parent: $parent) {
                    category {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["categoryCreate"]["productErrors"]
        handle_errors(errors)

        return response.data["categoryCreate"]["category"]["id"]

    def create_product(self, product_type_id, brand_id, **kwargs):

        """create a product.

        Parameters
        ----------
        product_type_id : str
            product type id required to create the product.
        **kwargs : dict, optional
            overrides the default value set to create the product refer to
            the ProductCreateInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the product created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """

        default_kwargs = {
            "productType": product_type_id,
            "brand": brand_id,
            "basePrice": 0.0,
            # "sku": "default"
        }

        override_dict(default_kwargs, kwargs)
        variables = {
            "input": default_kwargs
        }

        query = """
            mutation createProduct($input: ProductCreateInput!) {
                productCreate(input: $input) {
                        product {
                            id
                            category {
                                name
                            }
                            descriptionJson
                            isPublished
                            publicationDate
                            chargeTaxes
                            taxType {
                                taxCode
                                description
                            }
                            name
                            slug
                            productType {
                                name
                            }
                            attributes {
                                attribute {
                                    slug
                                }
                                values {
                                    slug
                                }
                            }
                            visibleInListings
                        }
                        errors {
                                field
                                message
                                }
                        }
                    }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["productCreate"]["errors"]
        handle_errors(errors)

        return response.data["productCreate"]["product"]["id"]

    def create_brand(self, brand_info):
        variables = {
            "input": brand_info
        }
        query = """
            mutation createBrand($input: BrandRegisterInput!) {
                brandCreate(input: $input) {
                    brand {
                        brandName
                        companyName
                        id
                        active
                        address{
                            streetAddress1
                            postalCode
                        }
                    }
                    errors {
                    field
                    message
                    }
                }
            }
        """

        try:
            response = schema.execute(query, variables=variables,
                                    context_value=schema_context)
        except Exception as e:
            print(str(e))
        errors = response.data["brandCreate"]["errors"]
        handle_errors(errors)

        return response.data["brandCreate"]["brand"]["id"]

    def create_brand_zaamo_mapping(self, create_info):

       

        if not create_info.get('product_id_brand') or not create_info.get("sku_id_brand"):
            return
        
        brand_zaamo_mapping_filter = BrandVariantZaamoMapping.objects.filter(product_id_brand=create_info.get('product_id_brand'), sku_id_brand=create_info.get("sku_id_brand"))
        brand_node = graphene.Node.from_global_id(create_info.get('brand_id'))
        brand_instance = Brand.objects.filter(id=brand_node[1]).first()

        product_node= graphene.Node.from_global_id(create_info.get('product_id'))
        product_instance = product_models.Product.objects.filter(id=product_node[1]).first()

        variant_node = graphene.Node.from_global_id(create_info.get('variant_id'))
        variant_instance =  product_models.ProductVariant.objects.filter(id=variant_node[1]).first()

        if not brand_zaamo_mapping_filter:
            brandvarient_zaamo_mapping = BrandVariantZaamoMapping(
                source=create_info.get('source'), 
                brand_name=brand_instance.brand_name, 
                product_name=product_instance.name,
                product_id_brand=create_info.get('product_id_brand'), 
                sku_id_brand = create_info.get('sku_id_brand'),
                product_zaamo =product_instance, 
                variant_id_brand = create_info.get('variant_id_brand'),
                brand_zaamo = brand_instance,
                variant_zaamo=variant_instance)
            brandvarient_zaamo_mapping.save()

    def get_brand_by_name(self, brand_name):
        
        brand_instance = Brand.objects.filter(brand_name=brand_name).first()
        brand_id = None
        
        if brand_instance:
            brand_id = graphene.Node.to_global_id("Brand", brand_instance.id)
        
        return brand_id
    
    def get_brand_by_source_name_in_private_metadata(self, brand_name):
        
        brand_instance = Brand.objects.filter(private_metadata__source_name=brand_name).first()
        brand_id = None
        
        if brand_instance:
            brand_id = graphene.Node.to_global_id("Brand", brand_instance.id)
        
        else:
            brand_id = self.get_brand_by_name(brand_name)
        
        return brand_id
    
    def update_product(self, id, **kwargs):

        """update a product.

        Parameters
        ----------
        id : str
            product id required to update the product.
        **kwargs : dict, optional
            overrides the default value set to update the product refer to
            the ProductInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the product created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        
        variables = {
            "productId": id,
            "input": kwargs
        }

        query = """
            mutation updateProduct($productId: ID!, $input: ProductInput!) {
                productUpdate(id: $productId, input: $input) {
                    product {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """
        
        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["productUpdate"]["productErrors"]
        handle_errors(errors)

        return response.data["productUpdate"]["product"]["id"]

    def update_product_variant(self, id, **kwargs):
        """update a product variant.

        Parameters
        ----------
        id : str
            product variant id required to update the product.
        **kwargs : dict, optional
            overrides the default value set to update the product variant refer to
            the ProductVarientInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the product variant created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        


        variables = {
            "variantId": id,
            "input": kwargs
        }
        
        
        query = """
            mutation updateProductVariant($variantId: ID!, $input: ProductVariantInput!) {
                productVariantUpdate(id: $variantId, input: $input) {
                    productVariant {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """
        
        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["productVariantUpdate"]["productErrors"]
        handle_errors(errors)

        return response.data["productVariantUpdate"]["productVariant"]["id"]

    def update_product_variant_stocks(self, id, stocks):
        """update a product variant stocks.

        Parameters
        ----------
        id : str
            product variant id required to update the product.
        **kwargs : dict, optional
            overrides the default value set to update the product variant refer to
            the ProductVarientInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the product variant created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        
    

        variables = {
            "variantId": id,
            "stocks": stocks
        }
        
        
        query = """
           mutation updateProductVariantStocks($variantId: ID!, $stocks: [StockInput!]!) {
                productVariantStocksUpdate(variantId: $variantId, stocks: $stocks) {
                    productVariant {
                        id
                    }
                    bulkStockErrors {
                        field
                      	message
                    }
                }
            }
        """
        
        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["productVariantStocksUpdate"]["bulkStockErrors"]
        handle_errors(errors)

        return response.data["productVariantStocksUpdate"]["productVariant"]["id"]


    def create_product_variant(self, product_id, **kwargs):

        """create a product variant.

        Parameters
        ----------
        product_id : str
            id for which the product variant will be created.
        **kwargs : dict, optional
            overrides the default value set to create the product variant refer
            to the ProductVariantCreateInput graphQL type to know what can be
            overriden.

        Returns
        -------
        id : str
            the id of the product variant created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        default_kwargs = {
            "product": product_id,
            # "sku": "0",
            "attributes": []
        }

        override_dict(default_kwargs, kwargs)
        variables = {
            "input": default_kwargs
        }
        query = """
            mutation createProductVariant($input: ProductVariantCreateInput!) {
                productVariantCreate(input: $input) {
                    productVariant {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        errors = response.data["productVariantCreate"]["productErrors"]
        handle_errors(errors)

        return response.data["productVariantCreate"]["productVariant"]["id"]

    def create_product_image(self, product_id, file_path):
        """create a product image.

        Parameters
        ----------
        product_id : str
            id for which the product image will be created.
        file_path : str
            path to the image to upload.

        Returns
        -------
        id : str
            the id of the product image created.

        Raises
        ------
        Exception
            when productErrors is not an empty list.
        """
        body = get_payload(product_id, file_path)
        response = {}
        # response = schema.execute(query, variables=variables,
        #                           context_value=schema_context)

        errors = response.data["productImageCreate"]["productErrors"]
        handle_errors(errors)

        return response.data["productImageCreate"]["image"]["id"]

    def update_private_meta(self, item_id, input_list):
        """

        Parameters
        ----------
        item_id: ID of the item to update. Model need to work with private metadata
        input_list: an input dict to which to set the private meta
        Returns
        -------

        """

        variables = {"id": item_id, "input": input_list}

        query = """
                    mutation updatePrivateMetadata($id: ID!, $input: [MetadataInput!]!) {
                        updatePrivateMetadata(id: $id, input: $input) {
                            item {
                                privateMetadata {
                                    key
                                    value
                                }
                            }
                            metadataErrors {
                                field
                                message
                                code
                            }
                        }
                    }
                """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)

        if (
            len(response.data["updatePrivateMetadata"]["item"]["privateMetadata"])
            > 0
        ):
            return item_id
        else:
            return None

    def get_product_from_global_id(self, product_id):
        product_id = graphene.Node.from_global_id(product_id)[1]

        try: 
            product = models.Product.objects.get(pk=product_id)
        except:
            product = None
        return product

    def retrieve_image(self, url):
        try:
            response = requests.get(url)
            fobject = BytesIO(response.content)
            random_string = StringUtilities.convert_number_to_string(
                            TimeUtilities.current_time_in_milliseconds())
                             
            return InMemoryUploadedFile(fobject,'ImageField',
                random_string + '.png',
                'image/png',
                sys.getsizeof(fobject), None) 
        except:
            return None
    
    def upload_product_image(self, product_id, url, file_name, alt=''):
        product = self.get_product_from_global_id(product_id)
        if product and url:
            file_path = urlparse(url).path
            file_name = os.path.splitext(os.path.basename(file_path))[0]
            image_data = self.retrieve_image(url)
            
            if image_data:
                validate_image_file(image_data, "image")
                image = product.images.create(image=image_data, alt=alt)

    def get_catagory(self, name, **kwrgs):
        try:
            category = Category.objects.get(name=name)
        except:
            category = None

        if category:
            category_id = graphene.Node.to_global_id("Category", category.id)
            return  category_id
        return ''

    def get_product_type(self, name, **kwrgs):
        try:
            product_type = ProductType.objects.get(name=name)
        except:
            product_type = None

        if product_type:
            product_type_id = graphene.Node.to_global_id("ProductType", product_type.id)
            return {name: product_type_id}
        return {}
    
    def update_product_type_attributes(self, product_type_id, product_attributes_ids, varient_attributes_ids):
        product_type_pk = graphene.Node.from_global_id(product_type_id)[1]

        try:
            product_type = ProductType.objects.get(id=product_type_pk)
        except:
            product_type = None
 
        if product_type:
            product_attributes = product_type.product_attributes.all()
            public_product_attributes_id = [graphene.Node.to_global_id("Attribute", attr.id) for attr in product_attributes]

            variant_attributes = product_type.variant_attributes.all()
            public_variant_attributes_id = [graphene.Node.to_global_id("Attribute", attr.id) for attr in variant_attributes]
        else:
            public_product_attributes_id=[]
            public_variant_attributes_id=[]

        updated_product_attributes_ids= list(set(public_product_attributes_id) | set(product_attributes_ids))
        updated_variant_attributes_ids= list(set(public_variant_attributes_id) | set(varient_attributes_ids))


        input = {
            "productAttributes": updated_product_attributes_ids,
            "variantAttributes": updated_variant_attributes_ids,
        }

        variables = {
            "id": product_type_id,
            "input": input
        }

        query = """
            mutation updateProductType($id: ID!, $input: ProductTypeInput!) {
                productTypeUpdate(id: $id, input: $input) {
                    productType {
                        id
                    }
                    productErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        response = schema.execute(query, variables=variables,
                                  context_value=schema_context)
        errors = response.data["productTypeUpdate"]["productErrors"]
        handle_errors(errors)

        return response.data["productTypeUpdate"]["productType"]["id"]

    def get_warehouse(self, slug="zaamo-master-warehouse", **kwrgs):
        try:
            warehouse = warehouse_models.Warehouse.objects.get(slug="zaamo-master-warehouse")
        except:
            warehouse = None

        if warehouse:
            warehouse_id = graphene.Node.to_global_id("Warehouse", warehouse.id)
            return {slug: warehouse_id}
        return {}
    
    def get_attribute(self, name, **kwrgs):
        try:
            attribute = Attribute.objects.get(slug=slugify(name))
        except:
            attribute = None
        if attribute:
            attribute_id = graphene.Node.to_global_id("Attribute", attribute.id)
            return {name: attribute_id}
        return {}

    def get_attribute_value(self, attribute_id, value):
        attribute = graphene.Node.from_global_id(attribute_id)
        try: 
            attribute_value = AttributeValue.objects.get(name=value, attribute=attribute[1])
        except:
            attribute_value = None
        if attribute_value:
            attribute_value_id = graphene.Node.to_global_id("AttributeValue", attribute_value.id)
            return {value: attribute_value_id}
        return {}

    @transaction.atomic
    def product_and_variant_create_or_update(self, varients, 
    product_types_name_id_mapping, attribute_name_id_mapping, product_name_id_mappiing
    ):
        product = varients[0]
        product_type_id = product_types_name_id_mapping[
                                            product.get('sub category', '') if product.get('sub category', '') else product.get('category', '')]

        product_type_pk = graphene.Node.from_global_id(product_type_id)[1]

        attributes = []
        product_type_product_attrs = [attr.name for attr in ProductType.objects.get(id=product_type_pk).product_attributes.all()]
        for attribite in product_type_product_attrs:
            
            if product.get(attribite):
                attribute_value_mapping = {'id': attribute_name_id_mapping[attribite],
                'values':  [product.get(attribite)]}
            else:
                attribute_value_mapping = {'id': attribute_name_id_mapping[attribite],
                'values':  ['NA']}

            attributes.append(attribute_value_mapping)
        category = self.get_catagory(product.get('sub category', '') if product.get('sub category', '') else product.get('category', ''))
        
        

        brand_zaamo_mapping = BrandVariantZaamoMapping.objects.filter(product_id_brand=product.get("pid"), brand_name= product.get("brand id"))
        
        
        brand = Brand.objects.get(brand_name=product.get("brand id"))
        brand_id = graphene.Node.to_global_id("Brand", brand.id)
        
        if not brand_zaamo_mapping.count():
            
            product_id = self.create_product(product_type_id,
                                                brand_id,
                                                name=product.get("product name", ''),
                                                descriptionJson=json.dumps({"description_text": product.get("description", '')}),
                                                basePrice=product.get("mrp", '').replace(',', ''),
                                                sku=product.get("sku", ''),
                                                category=category,
                                                attributes=attributes,
                                                isPublished=True,
                                                visibleInListings=True
                                                )

            self.update_private_meta( product_id, [{'key':'hsn', 'value': product.get('hsn', '')}, 
            {'key':'colour', 'value': product.get('colour', '')}, {'key': 'material', 'value': product.get('material', '')}]
            )

            product_name_id_mappiing.update({product.get("product name", ''): product_id})

            self.upload_product_image(product_id, product.get('search image url', ''), 'Search Image')
            self.upload_product_image(product_id, product.get('back image url', ''), 'Back Image')
            self.upload_product_image(product_id, product.get('left image url', ''), 'Left Image')
            self.upload_product_image(product_id, product.get('right image url', ''), 'Right Image')

        else:

            product_id = graphene.Node.to_global_id('Product', brand_zaamo_mapping[0].product_zaamo_id)
            self.update_product(product_id,
                                name=product.get("product name", ''),
                                descriptionJson=json.dumps({"description_text": product.get("description", '')}),
                                basePrice=product.get("mrp", '').replace(',', ''),
                                sku=product.get("sku", ''),
                                category=category,
                                attributes=attributes,
                                brand=brand_id)

            self.update_private_meta( product_id, [{'key':'hsn', 'value': product.get('hsn', '')}, 

            {'key':'colour', 'value': product.get('colour', '')}, {'key': 'material', 'value': product.get('material', '')}]
            )

        warehouse_id_dict = self.get_warehouse()
        warehouse_id = warehouse_id_dict.get("zaamo-master-warehouse")
        
        
        for varient in varients:
            varient_attr = []
            product_type_variant_attrs = [attr.name for attr in ProductType.objects.get(id=product_type_pk).variant_attributes.all()]
            for attribite in product_type_variant_attrs:
                attribute_value_mapping = {'id': attribute_name_id_mapping[attribite],
                'values': [varient.get(attribite)]}
                if varient.get(attribite):
                    varient_attr.append(attribute_value_mapping)
                else:
                    varient_attr.append({'id': attribute_name_id_mapping[attribite],
                'values': ['NA']})
            
            try:

                brand_varient_zaamo_mapping = BrandVariantZaamoMapping.objects.get(product_id_brand=varient.get("pid", ''), sku_id_brand=varient.get("sku", ''),  brand_name = varient.get("brand id"))
            except:

                brand_varient_zaamo_mapping = None

            if not brand_varient_zaamo_mapping:
                varient_id = self.create_product_variant(product_id,
                                                            attributes=varient_attr,
                                                            costPrice=varient.get("mrp", '').replace(',', ''),
                                                            price=varient.get('selling price', '').replace(',', ''),
                                                            stocks=[{"warehouse": warehouse_id, 
                                                            "quantity": varient.get('quantity', '0')}],
                                                            sku=varient.get('sku', ''),
                                                            trackInventory=True
                                                            )
                variant_zaamo_id = graphene.Node.from_global_id(varient_id)
                product_zaamo_id = graphene.Node.from_global_id(product_id)
                brandvarient_zaamo_mapping = BrandVariantZaamoMapping(source='csv', brand_name=varient.get("brand id", ''), product_name=varient.get("product name", ''), 
                                            product_id_brand=varient.get("pid", ''), sku_id_brand=varient.get("sku", ''), brand_zaamo_id = varient.get("brand id", None),
                                            product_zaamo_id =product_zaamo_id[1], 
                                            variant_zaamo_id=variant_zaamo_id[1])
                brandvarient_zaamo_mapping.save()
            else:
                variant_zaamo_id = graphene.Node.to_global_id('ProductVariant', brand_varient_zaamo_mapping.variant_zaamo.id)
                variant_id = self.update_product_variant(variant_zaamo_id,
                                                        attributes=varient_attr,
                                                        costPrice=varient.get("mrp", '').replace(',', ''),
                                                        price=varient.get('selling price', '').replace(',', ''),
                                                        )
                if varient.get('quantity'):
                    self.update_product_variant_stocks(variant_id,
                                                [{"warehouse": warehouse_id, 
                                                "quantity": varient.get('quantity')}]
                                                )


    def read_csv(self, reader_list, product_attribute_list=None, varient_attributes_list=None):
        """
        Objects creation flow:

        create categories
        create sub categories
        create product types
        create attributes
        create products
        create variants

        example row:
        {'product_name': 'CRYSTAL STUD EARRING', 'brand': 'Runway Ritual',
        'VSKU*': 'ER1-28487_NA', 'Pid*': 'ER1-28487', 'Size*': 'NA', 'Quantity*': '10',
         'Selling Price': '926.5', 'MRP*': '1090', 'Category': 'accessories',
         'Sub Category': 'fashion jewellery', 'Search Image URL*': 'https://www.dropbox.com/s/v3a9gqeemb5ckg0/ER1-28487-1.jpg?dl=1',
         'Front Image URL': 'https://www.dropbox.com/s/hjo0c0ebr2ggn75/ER1-28487-2.jpg?dl=1',
         'Back Image URL': '', 'Left Image URL': '', 'Right Image URL': '',
         'Description': 'These always easy-to-style sparkling stud\n earrings are perfect to adorn your ear.            \n  ',
          'Colour': 'Off White', 'Bust(Not needed)': '0', 'Waist(Not needed)': '0',
          'Hips(Not needed)': '0', 'Shoulders(Not needed)': '0', 'Length(Not needed)': '0',
          'Material ': 'Metal/Glass/Pearl', 'HSN': '91021900', '': 'Jewelry'}

        """
        
        if not product_attribute_list:
            product_attribute_list = []
        
        if not varient_attributes_list:
            varient_attributes_list = []

        product_attributes = {product_atttribute: {'values': set() ,'product_type':set()} for product_atttribute in  product_attribute_list}
        varient_attributes = {varient_attribute: {'values': set() ,'product_type':set()} for varient_attribute in  varient_attributes_list}

        products = {}


        # prepare data from csv for all objects creation.
        for row in reader_list:

            for key in product_attributes:

                if key in row:
                    product_attributes[key]['values'].add(row[key])
                    product_type = 'Not Defined'
                    if any([row['sub category'], row['category']]):
                        product_type = row['sub category'] if row['sub category'] else row['category']
                    product_attributes[key]['product_type'].add(product_type)
            for key in varient_attributes:
                
                if key in row:
                    varient_attributes[key]['values'].add(row[key])
                    product_type = 'Not Defined'
                    if any([row['sub category'], row['category']]):
                        product_type = row['sub category'] if row['sub category'] else row['category']
                    varient_attributes[key]['product_type'].add(product_type)
        
            # added remaing data to products dictionary.
            # todo check if missing any case. 

            if 'pid' in row:
                if row['pid'] in products:
                    products[row['pid']].append(row)
                else:
                    products[row['pid']]=[row]
            else:
                products.append(row)

        
        # Initialize name -- id mappings
        attribute_name_id_mapping = {}
        product_types_name_id_mapping = {}
        product_name_id_mappiing = {}


        # check availaible attributes and attribute values if not available then create.
        for attribute in product_attributes:
            attribute_dict = self.get_attribute(attribute)
            if  attribute_dict:
                attribute_id = attribute_dict[attribute]
            else:
                attribute_id = self.create_attribute(name=attribute)
            attribute_name_id_mapping[attribute] = attribute_id

            for attribute_value in product_attributes[attribute]['values']:
                attribite_value_dict = self.get_attribute_value(attribute_id, attribute_value)
                if not attribite_value_dict:
                    try:
                        self.create_attribute_value(attribute_id, name=attribute_value)
                    except:
                        print('attribute value already exist')

        for attribute in varient_attributes:
            attribute_dict = self.get_attribute(attribute)
            if attribute_dict:
                attribute_id = attribute_dict[attribute]
            else:
                attribute_id = self.create_attribute(name=attribute)
            attribute_name_id_mapping[attribute] = attribute_id

            for attribute_value in varient_attributes[attribute]['values']:
                attribite_value_dict = self.get_attribute_value(attribute_id, attribute_value)
                if not attribite_value_dict:
                    try:
                        self.create_attribute_value(attribute_id, name=attribute_value)
                    except:
                        print('attribute value already exist')
        

        # get all product types mapped with product and varients. 
        product_types_from_variants = set()
        product_types_from_products = set()
        for value in varient_attributes.values():
            product_types_from_variants.update(value['product_type'])

        for value in product_attributes.values():
            product_types_from_products.update(value['product_type'])

        product_types = product_types_from_variants.union(product_types_from_products)
        

        # check if product type available and if not then create products types.
        
        for product_type in product_types:
            product_attributes_ids = [attribute_name_id_mapping[product_attribute]  for product_attribute in product_attributes 
            if product_type in product_attributes[product_attribute]['product_type']]

            varient_attributes_ids = [attribute_name_id_mapping[varient_attribute]  for varient_attribute in varient_attributes 
            if product_type in varient_attributes[varient_attribute]['product_type']]
           
            product_type_dict = self.get_product_type(product_type)

            if product_type_dict:
                product_type_id = product_type_dict[product_type]
                self.update_product_type_attributes(product_type_id, product_attributes_ids, varient_attributes_ids)
            else:
                product_type_id = self.create_product_type(name=product_type,
                                                        hasVariants=product_type in product_types_from_variants,
                                                        productAttributes=product_attributes_ids,
                                                        variantAttributes=varient_attributes_ids)
            

            product_types_name_id_mapping.update({product_type: product_type_id})


        #  create products from csv data.
        for pid, varients in products.items():
            self.product_and_variant_create_or_update(varients, product_types_name_id_mapping, 
            attribute_name_id_mapping, product_name_id_mappiing)

    def update_fulfillment_status(self, fulfillment_id,status):
        warehouse_id = get_default_warehouse_id()
        variables = {
            "id": graphene.Node.to_global_id("Fulfillment",fulfillment_id),
            "input":{
                "fulfillmentStatus":status.upper(),
                "warehouseId":warehouse_id
            }
        }
        query = '''
        mutation updatefulfillment($id:ID!,$input:FulfillmentInput!){
        updateFulfillment(id:$id,input:$input){
            order{
                id
            }
            
            orderErrors{
                field
                message
                code
            }


        }
        }

        '''
        try:
            _schema_context = OrderEngineHelper.create_schema_context(**{"META": {"HTTP_X_STORE_ID": None}})
            
            response = schema.execute(query, variables=variables,
                                context_value=_schema_context)
            
            response_json = {
                'success' : True,
                'response' : response.to_dict()
            }

        except Exception as e:

            logger.exception(StringUtilities.convert_object_to_string(e))
            errors = response.data["updateFulfillment"]["orderErrors"]
            handle_errors(errors)
            response_json = {
                'success' : False,
                'response' : errors
            }
        
        finally:
            
            return response_json
