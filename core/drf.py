import re
from uuid import UUID
from saleor.core.models import ApiApp
from rest_framework import exceptions

from rest_framework.viewsets import ViewSetMixin
from rest_framework.views import APIView

APP_SECRET_REGEX_LIST = [
    re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}\Z', flags=re.I),
    re.compile('[a-fA-z0-9]{32}\Z', flags=re.I)
]

class RestrictedViewSet(ViewSetMixin, APIView):
    message = "Send the correct api-keys to access the endpoints"
    app_id_message = "Send a valid app-id to access endpoints"
    api_secret_key_message = "Send a valid api-secret-key to access endpoints"


    def _validate_app_id(self, app_id):
        """
        will check the app_id is a valid or not
        """
        try:
            uuid_hex = UUID(app_id)
            regex = APP_SECRET_REGEX_LIST[0]
            m = regex.search(app_id)
            if not m:
                return False
            elif uuid_hex or m:
                return True
        except ValueError:
            return False

    def _validate_api_secret_key(self, api_secret_key):
        """
        will check the api_secret_key is a valid or not
        """
        regex = APP_SECRET_REGEX_LIST[1]
        m = regex.search(api_secret_key)
        if not m:
            return False
        else:
            return True

    def check_api_keys(self, request):
        """
        It will take the request object. Checks the api keys present in those request or not.
        If keys present then give access to the Zaamo API Endpoint otherwise it raises the
        permission denied.

        :param request
        :param HTTP_APP_ID
        :param HTTP_API_SECRET_KEY
        :returns True or False
        """
        app_id, api_obj = request.META.get("HTTP_APP_ID"), None
        api_secret_key = request.META.get("HTTP_API_SECRET_KEY")
        if app_id and api_secret_key:
            # validate app_id and api_secret_key
            app_id_bool = self._validate_app_id(app_id)
            if not app_id_bool:
                return False, self.app_id_message
            # api_secret_key_bool = self._validate_api_secret_key(api_secret_key)
            if not api_secret_key:
                return False, self.api_secret_key_message
            try:
                api_obj = ApiApp.objects.get(app_id=app_id, api_secret_key=api_secret_key, active=True)
                if api_obj:
                    return True, ''
            except ApiApp.DoesNotExist:
                return False, self.message
        else:
            return False, self.message

    def initial(self, request, *args, **kwargs):
        """
        Runs anything that needs to occur prior to calling the method handler.
        """

        # It's checks the permissions for the third party endpoint or not
        bool_value, message = self.check_api_keys(request)
        if bool_value:
            super(RestrictedViewSet, self).initial(request, *args, **kwargs)
        else:
            raise exceptions.PermissionDenied(detail=message)

