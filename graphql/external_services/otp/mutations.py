import graphene
from saleor.external_services.otp.otp_impl import OtpImpl
from saleor.graphql.core.types.common import AccountError
from django.core.exceptions import ValidationError
from saleor.graphql.core.mutations import BaseMutation

class GenerateOtp(BaseMutation):
    
    class Arguments:
        mobile_no = graphene.String(description="mobile no. of user")
    
    class Meta:
        description = "generates otp for given mobile number"
        error_type_class = AccountError
        error_type_field = "account_errors"

    success = graphene.Boolean(description="Otp generation status")

    @classmethod
    def perform_mutation(cls, root, info, **data):
        mobile_no = data.get('mobile_no')
        
        if not mobile_no:
            raise ValidationError(message="Invalid mobile number")
        
        otp_dict = OtpImpl.generate_otp(mobile_no=mobile_no)
    
        if otp_dict.get('error_message'):
            raise ValidationError(message=otp_dict.get('error_message'))
        
        return cls(success=otp_dict.get('success'))


class VerifyOtp(BaseMutation):
    
    class Arguments:
        mobile_no = graphene.String(description="mobile no of user")
        otp = graphene.Int(description="otp sent for the mobile no.")
    
    class Meta:
        description = "verify otp for given mobile number"
        error_type_class = AccountError
        error_type_field = "account_errors"

    success = graphene.Boolean(description="Is otp valid")
    
    @classmethod
    def perform_mutation(cls, root, info, **data):
        mobile_no = data.get('mobile_no')
        otp = data.get('otp')

        if not mobile_no or not otp:
            raise ValidationError(message="Invalid credentials")
        
        otp_dict = OtpImpl.verify_otp(mobile_no=mobile_no, otp=otp)

        if otp_dict.get('error_message'):
            raise ValidationError(message=otp_dict.get('error_message'))
        
        return cls(success=otp_dict.get('success'))
