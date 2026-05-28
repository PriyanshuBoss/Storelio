from rest_framework import serializers
from saleor.brand import models as brand_models


class UpdateInventorySerializer(serializers.Serializer):
    product_id = serializers.CharField(required=True)
    variant_id = serializers.CharField(required=True)
    quantity = serializers.IntegerField(required=True)

class CustomUpdateInventorySerializer(serializers.Serializer):
    product_id = serializers.CharField(required=True)
    variant_id = serializers.CharField(required=True)
    sku_code = serializers.CharField(required=True)
    in_stock = serializers.IntegerField(required=True)


class AppAuthTokenGenerationSerializer(serializers.Serializer):

    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True)

class BrandImageUploadSerializer(serializers.Serializer):

    category_type = serializers.CharField(required=True)
    brand_id = serializers.CharField(required=True)
    image = serializers.ImageField(required=True)


class GroupingImageUploadSerializer(serializers.Serializer):

    grouping_id = serializers.CharField(required=True)
    image = serializers.ImageField(required=True)

class VoucherImageUploadSerializer(serializers.Serializer):

    voucher_id = serializers.CharField(required=True)
    image = serializers.ImageField(required=True)