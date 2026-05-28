from enum import Enum


class ProductAvailabilityStatus(str, Enum):
    NOT_PUBLISHED = "not-published"
    VARIANTS_MISSSING = "variants-missing"
    OUT_OF_STOCK = "out-of-stock"
    LOW_STOCK = "low-stock"
    NOT_YET_AVAILABLE = "not-yet-available"
    READY_FOR_PURCHASE = "ready-for-purchase"

    @staticmethod
    def get_display(status):
        status_mapping = {
            ProductAvailabilityStatus.NOT_PUBLISHED: "not published",
            ProductAvailabilityStatus.VARIANTS_MISSSING: "variants missing",
            ProductAvailabilityStatus.OUT_OF_STOCK: "out of stock",
            ProductAvailabilityStatus.LOW_STOCK: "stock running low",
            ProductAvailabilityStatus.NOT_YET_AVAILABLE: "not yet available",
            ProductAvailabilityStatus.READY_FOR_PURCHASE: "ready for purchase",
        }

        if status in status_mapping:
            return status_mapping[status]
        else:
            raise NotImplementedError(f"Unknown status: {status}")


class VariantAvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out-of-stock"

    @staticmethod
    def get_display(status):
        status_mapping = {
            VariantAvailabilityStatus.AVAILABLE: "available",
            VariantAvailabilityStatus.OUT_OF_STOCK: "out of stock",
        }

        if status in status_mapping:
            return status_mapping[status]
        else:
            raise NotImplementedError(f"Unknown status: {status}")


class AttributeInputType:
    """The type that we expect to render the attribute's values as."""

    DROPDOWN = "dropdown"
    MULTISELECT = "multiselect"

    CHOICES = [
        (DROPDOWN, "Dropdown"),
        (MULTISELECT, "Multi Select"),
    ]
    # list the input types that cannot be assigned to a variant
    NON_ASSIGNABLE_TO_VARIANTS = [MULTISELECT]

class SourcingRequestStatus:
    
    REQUEST_RECIEVED = "request received"
    BRAND_SHARED_DELIVERABLES = "brand shared deliverables"
    BRAND_CONTACT_INFLUENCER = "brand will contact the influencer"
    BRAND_COLLAB_APPROVED = "brand collaboration approved"
    BRAND_COUPON_CREATED =  "brand coupon created"
    BRAND_NOT_INTERESTED = "brand not interested"
    ZAAMO_FULFILL_REQUEST = "zaamo will fulfill request"
    ZAAMO_COUPON_CREATED = "zaamo coupon created"
    ZAAMO_NOT_INTERESTED = "zaamo not interested"
    INFLUENCER_CONTENT_CREATED_FOR_ZAAMO = "influencer content created for Zaamo"
    INFLUENCER_CONTENT_CREATED_FOR_BRAND = "influencer content created for Brand"
    PRODUCT_EXCHANGE_RETURN_REQUESTED = "product exchange or return requested"
    REQUEST_CANCELLED_INFLUENCER = "request cancelled by influencer"
    BRAND_COUPON_CLUBBED = "brand coupon clubbed"
    INFLUENCER_HOLD = "influencer hold"
    BRAND_HOLD = "brand hold"
    INFLUENCER_HAS_SHARED_THE_DELIVERABLES = "influencer has shared the deliverables"
    REQUEST_CLUBBED = "request clubbed"
    COUPON_CANCELLED_BY_INFLUENCER = "coupon cancelled by influencer"
    COUPON_CANCELLED_BY_BRAND = "coupon cancelled by brand"
    REQUEST_EXPIRED = "request expired"



    CHOICES = [
        (REQUEST_RECIEVED , "Request Received"),
        (BRAND_SHARED_DELIVERABLES,"Brand Shared Deliverables"),
        (BRAND_CONTACT_INFLUENCER,"Brand Will Contact the Influencer"),
        (BRAND_COLLAB_APPROVED,"Brand Collaboration Approved"),
        (BRAND_COUPON_CREATED , "Brand Coupon Created"),
        (BRAND_NOT_INTERESTED ,"Brand Not Interested"),
        (ZAAMO_FULFILL_REQUEST, "Zaamo Will Fulfill Request"),
        (ZAAMO_COUPON_CREATED, "Zaamo Coupon Created"),
        (ZAAMO_NOT_INTERESTED, "Zaamo Not Interested"),
        (INFLUENCER_CONTENT_CREATED_FOR_ZAAMO, "Influencer Content Created For Zaamo"),
        (INFLUENCER_CONTENT_CREATED_FOR_BRAND, "Influencer Content Created For Brand"),
        (PRODUCT_EXCHANGE_RETURN_REQUESTED, "Product exchange or return Requested"),
        (REQUEST_CANCELLED_INFLUENCER, "Request Cancelled By Influencer"),
        (BRAND_COUPON_CLUBBED, "Brand Coupon Clubbed"),
        (INFLUENCER_HOLD, "Influencer Hold"),
        (BRAND_HOLD, "Brand Hold"),
        (INFLUENCER_HAS_SHARED_THE_DELIVERABLES, "Influencer Has Shared The Deliverables"),
        (REQUEST_CLUBBED, "Request Clubbed"),
        (COUPON_CANCELLED_BY_INFLUENCER, "coupon cancelled by influencer"),
        (COUPON_CANCELLED_BY_BRAND, "coupon cancelled by brand"),
        (REQUEST_EXPIRED, "request expired"),
        
    ]

class BrandCollabStatusForSouringRequest:

    YES = "YES"
    NO = "NO"
    NA = "NA"

    CHOICES = [
        (YES ,"YES"),
        (NO ,"NO"),
        (NA , "NA"),
    ]

class BarterType:
    
    ACTIVE_BARTER = "ACTIVE_BARTER"
    ACTIVE_ONLY_BARTER = "ACTIVE_ONLY_BARTER"
    NO_BARTER = "NO_BARTER"

    CHOICES = [
        (ACTIVE_BARTER ,"ACTIVE_BARTER"),
        (ACTIVE_ONLY_BARTER ,"ACTIVE_ONLY_BARTER"),
        (NO_BARTER , "NO_BARTER"),
    ]

