from rest_framework import serializers

class UpdateInventorySerializer(serializers.Serializer):
    productId = serializers.CharField(required=True)
    variantId = serializers.CharField(required=True)
    inventory = serializers.IntegerField(required=True)
    hsnCode = serializers.CharField(required=False)

class OrderItemSerializer(serializers.Serializer):
    orderItemId = serializers.CharField(required=True)
    quantity = serializers.IntegerField(required=True)
    taxRate = serializers.DecimalField(required=False,max_digits=5 , decimal_places=3)

class ShippingSerializer(serializers.Serializer):
    deliveryPartner = serializers.CharField(required=True)
    dispatchDate = serializers.DateTimeField(required=True)
    invoiceDate = serializers.DateField(required=True)
    invoiceNumber = serializers.CharField(required=True)
    tentativeDeliveryDate = serializers.DateTimeField(required=True)
    trackingId = serializers.CharField(required=True)

class PostOrderDispatchSerializer(serializers.Serializer):

    orderItems = serializers.ListField(
        child = OrderItemSerializer()
    )
    selfShipping = ShippingSerializer()

class PostStatusNotificationSerializer(serializers.Serializer):
    orderItemId = serializers.CharField(required=True)
    status = serializers.CharField(required=True)
    IsReverse = serializers.BooleanField(required=True)
    courier_status = serializers.CharField(required=False)
    updated = serializers.DateTimeField(input_formats=["%b %d, %Y %I:%M:%S %p"] ,required=True)

class PostOrderCancelOrderItemSerializer(serializers.Serializer):
    orderItemId = serializers.CharField(required=True)
    productId = serializers.CharField(required=True)
    variantId = serializers.CharField(required=True)
    quantity = serializers.IntegerField(required=True)

class PostOrderCancelSerializer(serializers.Serializer):
    orderId = serializers.CharField(required=True)
    orderItems = serializers.ListField( child = PostOrderCancelOrderItemSerializer() )
