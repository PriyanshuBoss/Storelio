from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage
from storages.backends.s3boto3 import S3Boto3Storage
from storages.backends.azure_storage import AzureStorage
from typing import (
    AnyStr, IO, Iterable, Union,
)
import requests
import io


class S3MediaStorage(S3Boto3Storage):
    def __init__(self, *args, **kwargs):
        self.bucket_name = settings.AWS_MEDIA_BUCKET_NAME
        self.custom_domain = settings.AWS_MEDIA_CUSTOM_DOMAIN
        super().__init__(*args, **kwargs)


class GCSMediaStorage(GoogleCloudStorage):
    def __init__(self, *args, **kwargs):
        self.bucket_name = settings.GS_MEDIA_BUCKET_NAME
        super().__init__(*args, **kwargs)


class AzureMediaStorage(AzureStorage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def upload_blob(self, name: str, data: Union[bytes, str, Iterable[AnyStr], IO[AnyStr]]):
        self._save(name, data)
        return self.url(name)
    
    def upload_blob_from_url(self, name: str, source_url: str):
        obj = io.BytesIO()
        with requests.get(source_url, stream=True) as r:
            obj.write(r.content)
        self._save(name, obj)

        return self.url(name)