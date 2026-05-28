from django.http import JsonResponse
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
import jwt
from saleor.core import models as core_models
from saleor.utilities.time_utilities import TimeUtilities
from saleor.utilities.string_utilities import StringUtilities

def token_creation(api_app_instance):

    prev_token = api_app_instance.token
    curr_time = TimeUtilities.get_current_date_time()

    if api_app_instance.token_expires_at > curr_time:

        return prev_token

    else:     
        payload = {
            "id":api_app_instance.id,
            "app_id":StringUtilities.convert_number_to_string(api_app_instance.app_id),
            "secret_token":api_app_instance.api_secret_key,
            "date_time": StringUtilities.convert_number_to_string(TimeUtilities.get_current_date_time())
        }
        
        encoded_jwt = jwt.encode(payload, "secret", algorithm="HS256")
        api_app_instance.token = encoded_jwt
        api_app_instance.token_expires_at = TimeUtilities.add_time_in_timestamp(TimeUtilities.get_current_date_time(),1)
        api_app_instance.save()

        return encoded_jwt


def validate_auth_token(token_name='Authorization'):
    def decorator(function):
        def wrap(self,request, **kwargs):
            result_data = {}
            curr_datetime = TimeUtilities.get_current_date_time()
   
            token = request.headers.get(token_name,None)
            
            if not token:
                error = {'message': 'a valid token is missing'}
                result_data.update(error)
                
                return JsonResponse(result_data,status=status.HTTP_400_BAD_REQUEST)
            
            
            if token_name == 'Authorization':
                token = token.split(' ')

                if len(token) > 1:
                    token = token[1]
            
            
            if not core_models.ApiApp.objects.filter(token=token , token_expires_at__gt=curr_datetime).exists():

                error = {'message': 'token is invalid'}
                result_data.update(error)
                
                return JsonResponse(result_data,status=status.HTTP_400_BAD_REQUEST)

            return function(self,request,**kwargs)

        wrap.__doc__ = function.__doc__
        wrap.__name__ = function.__name__
        return wrap
    return decorator

def validate_auth_token_without_expiry(token_name='token'):
    def decorator(function):
        def wrap(self,request, **kwargs):
            result_data = {}
            curr_datetime = TimeUtilities.get_current_date_time()
   
            token = request.headers.get(token_name,None)

            if not token:
                error = {'message': 'a valid token is missing'}
                result_data.update(error)
                
                return JsonResponse(result_data,status=status.HTTP_400_BAD_REQUEST)
                
            if not core_models.ApiApp.objects.filter(token=token).exists():

                error = {'message': 'token is invalid'}
                result_data.update(error)
                
                return JsonResponse(result_data,status=status.HTTP_400_BAD_REQUEST)

            return function(self,request,**kwargs)

        wrap.__doc__ = function.__doc__
        wrap.__name__ = function.__name__
        return wrap
    return decorator


class LargeResultsSetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    page = 1
    page_query_param='page_number'
    
