import json
import mimetypes
import os
from typing import Union
import graphene
from django.http import FileResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404
from saleor.brand.models import Commission
from saleor.core.utils import build_absolute_uri
from saleor.product.templatetags.product_images import get_product_image_thumbnail

from .models import BrandVariantZaamoMapping, DigitalContentUrl, ProductImage
from .utils.digital_products import (
    digital_content_url_is_valid,
    increment_download_count,
)
from collections import defaultdict
from saleor.graphql.product.filters import filter_products_by_stock_availability
from saleor.product.models import Product, ProductGrouping, ProductGroupingMapping
from django.db.models import When,Case,F
from saleor.graphql.product.resolvers import clean_product_grouping_details_to_check



def digital_product(request, token: str) -> Union[FileResponse, HttpResponseNotFound]:
    """Return the direct download link to content if given token is still valid."""

    qs = DigitalContentUrl.objects.prefetch_related("line__order__user")
    content_url = get_object_or_404(qs, token=token)  # type: DigitalContentUrl
    if not digital_content_url_is_valid(content_url):
        return HttpResponseNotFound("Url is not valid anymore")

    digital_content = content_url.content
    digital_content.content_file.open()
    opened_file = digital_content.content_file.file
    filename = os.path.basename(digital_content.content_file.name)
    file_expr = 'filename="{}"'.format(filename)

    content_type = mimetypes.guess_type(str(filename))[0]
    response = FileResponse(opened_file)
    response["Content-Length"] = digital_content.content_file.size

    response["Content-Type"] = str(content_type)
    response["Content-Disposition"] = "attachment; {}".format(file_expr)

    increment_download_count(content_url)
    return response


def product_groups_from_id(to_check,groupings_by_name):

    name_list = []


    for name,rule in groupings_by_name.items():
        
        if (
            (rule.get('valueDeal')==to_check['valueDeal'] or rule.get('valueDeal')==None or rule.get('valueDeal')==False) and 
            (to_check['brand'] in rule.get('brands') or rule.get('brands')==[]) and (to_check['category'] in
             rule.get('categories') or rule.get('categories')==[]) and 
            (len(set(rule.get('productTags')).intersection(set(to_check['productTags']))) == len(rule.get('productTags')) 
            or rule.get('productTags')==[]) and
            (len(set(rule.get('brandCollection')).intersection(set(to_check['brandCollection']))) > 0 
            or rule.get('brandCollection')==[]) and
            (rule.get('price').get('gtequal',0)<=to_check.get('price',0)<=rule.get('price').get('ltequal',10000)) and 
            (rule.get('discount').get('gtequal',0)<=to_check.get('discount',0)<=rule.get('discount').get('ltequal',10000))
            ):
            
            name_list.append(name)

                
    return name_list


def mark_less_than_10(less_than_10_product_group):
    
    groupings = ProductGrouping.objects.all()
    for gr in groupings:
        if gr.name in less_than_10_product_group:
            gr.private_metadata['less_than_10_products']=True
        else:
            gr.private_metadata['less_than_10_products']=False
        
        gr.save()

def structure_product_data(product,url,brand_comm):

    return {
              "id":graphene.Node.to_global_id('Product',product.id),
              "name":product.name,
              "slug":product.slug,
              "too_many_orders":product.brand.too_many_orders or False,
              "metadata": [{"key":key,"value":value} for key,value in product.metadata.items()],
              "brand": {
                            "id":graphene.Node.to_global_id('Brand',product.brand_id),
                            "brand_name": product.brand.brand_name,
                            "commission_percentage":product.commission_percentage or brand_comm
                        },
              "thumbnail": {
                            "url":url
                        },
              "default_variant": {
                            "id": graphene.Node.to_global_id('ProductVariant',product.default_variant_id),

                            "cost_price": {
                                    "amount": product.default_variant.cost_price_amount
                                    },

                            "pricing": {
                                    "price_undiscounted": {
                                                    "gross": {
                                                        "amount":product.default_variant.price_amount
                                                        }
                                                }
                                    }
                        }
            }

def create_productsgroupingmapping(new_grouping_id=None):
    
    p = filter_products_by_stock_availability(Product.objects.all(),'AVAILABLE')
    products = Product.objects.filter(is_published=True, brand__status__in=['active'],id__in=p.values('id')).select_related('brand','category').values('id','name','brand__brand_name','category_id','category__name',
                'brand_id','default_variant__price_amount','is_published','default_variant__cost_price_amount',
                'through_product_tag_product__product_tag_id','through_product_tag_product__product_tag__name','metadata__value_deal','through_brand_collection_product__brand_collection_id').annotate(discount = Case(When(default_variant=None, then=0), 
                When(default_variant__cost_price_amount=0, then=0), default = 
                (F('default_variant__cost_price_amount') - F('default_variant__price_amount'))*100/F("default_variant__cost_price_amount")))
    
    products_dict = defaultdict(list)
    
    for product in products:
        products_dict[product.get('id')].append(product)
    
    product_instances = Product.objects.filter(is_published=True, brand__status__in=['active'],
                        id__in=p.values('id')).select_related('brand','default_variant').only(
                            'id',
                            'name',
                            'slug',
                            'metadata',
                            'commission_percentage',
                            'brand__id',
                            'brand__brand_name',
                            'brand__too_many_orders',
                            'default_variant__price_amount',
                            'default_variant__cost_price_amount'
                            )

    brand_commission = Commission.objects.all().values('brand_id','commission_percentage')
    brand_commission_dict = defaultdict(float)

    for comm in brand_commission:
        brand_commission_dict[comm['brand_id']]=comm['commission_percentage']
    
    products_inst_dict = dict()
    
    for product in product_instances:
        products_inst_dict[product.id] = product

    images = ProductImage.objects.filter(product_id__in=product_instances.values('id'))
    
    images_product_dict = defaultdict(str)
    
    for image in images:

        if not images_product_dict.get(image.product_id):
            
            try:
                url = image.url
                url = url.replace('.png','')
                url = url.replace('media/','media/__sized__/')
                image_url = f'{url}-thumbnail-1080x1080.png'
            
            except Exception as e:
                url = get_product_image_thumbnail(image, 1080, method="thumbnail")

                image_url = build_absolute_uri(url)

            finally:
                images_product_dict[image.product_id]=image_url
                
    if new_grouping_id:
        groupings = ProductGrouping.objects.filter(id=new_grouping_id)

    else:
        groupings = ProductGrouping.objects.all()

    grouping_by_name = {g.name: g.rule for g in groupings}
    grouping_inst_by_name = {g.name: g for g in groupings}
    
    group_name_dict = defaultdict(list)
    
    for id, product in products_dict.items():

        to_check = clean_product_grouping_details_to_check(product)
        name_list = product_groups_from_id(to_check,grouping_by_name)
        
        for i in name_list:
            if id in group_name_dict[i]:
                continue
            group_name_dict[i].append(id)

    from saleor.graphql.product.sorters import ProductOrderField
    less_than_10_product_group = []

    groups_with_no_product = set(grouping_by_name.keys()).difference(set(group_name_dict))
    less_than_10_product_group.extend(list(groups_with_no_product))
    
    irrelevant_groups = list(set(grouping_inst_by_name).difference(set(group_name_dict.keys())))
    
    ProductGroupingMapping.objects.filter(product_grouping__name__in=irrelevant_groups).delete()
    for name,product_ids in group_name_dict.items():
        
        mapping_inst = []
        grouping = grouping_inst_by_name.get(name)
        
        if not grouping:
            continue

        ProductGroupingMapping.objects.filter(product_grouping_id=grouping.id).delete()

        
        rule = grouping_by_name.get(name)
        sorting_field = rule.get('field')
        sorting_direction = rule.get('direction')
        
        if sorting_field:
            fields_to_sort = getattr(ProductOrderField,sorting_field).value.copy()
            
            if sorting_direction=='DESC':

                for i in range(len(fields_to_sort)):
                    fields_to_sort[i] = '-'+fields_to_sort[i]
            
            try:
                sorting_func = getattr(ProductOrderField,f'qs_with_{sorting_field.lower()}')
                
                products = sorting_func(Product.objects.filter(id__in=product_ids)).order_by(*fields_to_sort).values_list('id',flat=True)
                products = list(products)
            
            except AttributeError as e:
                
                products = Product.objects.filter(id__in=product_ids).order_by(*fields_to_sort).values_list('id',flat=True)
                products = list(products)
            
        if len(products)<10:
            less_than_10_product_group.append(name)
            continue

        to_add = products
        
        weight = 0

        for p_id in to_add:

            inst = ProductGroupingMapping()
            inst.product_id = p_id
            inst.product_grouping_id = grouping.id
            inst.weight=weight
            weight+=1
            product_insts = products_inst_dict[p_id]
            inst.metadata['query_data'] = structure_product_data(product_insts,images_product_dict[p_id],brand_commission_dict[product_insts.brand_id])
            mapping_inst.append(inst)
        
        ProductGroupingMapping.objects.bulk_create(mapping_inst,batch_size=10000)
    
    if new_grouping_id:

        for g_name in less_than_10_product_group:
            grouping = grouping_inst_by_name.get(g_name)
            grouping.private_metadata['less_than_10_products']=True
            grouping.save()

    else:
        mark_less_than_10(less_than_10_product_group)
