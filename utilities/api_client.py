from typing import Union
import json
import requests

class ApiClient:
    params = dict()
    body = dict()
    headers = dict()
    response = None

    def __init__(self, host: str = None, path: str = None, method: str = "GET", schema: str = None, 
    url: str = None):
        self.host = host
        self.path = path
        self.method = method.upper()
        self.schema = schema if schema is not None else "https"
        self.url = url

    def get_host(self):
        return self.host

    def get_request_path(self):
        return self.path

    def get_request_method(self):
        return self.method

    def get_url_params(self):
        return "?" + "&".join(f"{key}={value}" for key, value in self.params.items())

    def get_headers(self):
        return self.headers

    def get_body(self):
        return self.body

    def _fetch_schema(self):
        schema = f"{self.schema}" if self.schema not in self.get_host() else ""
        if schema:
            schema = (schema + "://") if "://" not in schema else schema

        return schema

    def get_request_url(self):

        if self.url:
            return self.url

        return f"{self._fetch_schema()}{self.get_host()}/{self.get_request_path()}{self.get_url_params()}"

    def update_request_url(self, url):
        self.url = url

    def add_url_param(self, key, value):
        self.params.update({key: value})
        return self

    def update_url_params(self, params: dict):
        self.params.update(**params)
        return self

    def update_body(self, data: Union[dict, list]):
        self.body = data
        return self

    def add_header(self, key, value):
        self.headers.update({str(key): str(value)})
        return self

    def update_headers(self, headers: dict):
        self.headers.update(**headers)
        return self

    def request(self):
        url = self.get_request_url()

        self.response = requests.request(method=self.get_request_method(),
                                         url=url,
                                         headers=self.get_headers(),
                                         json=self.get_body())
        return self

    def get(self, send_body=True, verify=True):
        url = self.get_request_url()
        if send_body:
            self.response = requests.request(method="GET",
                                            url=url,
                                            headers=self.get_headers(),
                                            json=self.get_body())
        elif not verify:
            self.response = requests.request(method="GET",
                                            url=url,
                                            headers=self.get_headers(),
                                            verify=False)
            
        else:
            self.response = requests.request(method="GET",
                                            url=url,
                                            headers=self.get_headers())
                                            
        return self

    def post(self,verify=True, timeout=None,body_as_data=False):
        url = self.get_request_url()

        if not verify:
            self.response = requests.request(method="POST",
                                         url=url,
                                         headers=self.get_headers(),
                                         json=self.get_body(),
                                         timeout=timeout,
                                         verify=False)
            
            return self

        if body_as_data:
            
            self.response = requests.request(method="POST",
                                            url=url,
                                            headers=self.get_headers(),
                                            timeout=timeout,
                                            data=self.get_body())
            return self
            

        self.response = requests.request(method="POST",
                                         url=url,
                                         headers=self.get_headers(),
                                         timeout=timeout,
                                         json=self.get_body())
        return self

    def delete(self):
        url = self.get_request_url()

        self.response = requests.request(method="DELETE",
                                         url=url,
                                         headers=self.get_headers(),
                                         json=self.get_body())
        return self

    def patch(self):
        url = self.get_request_url()

        self.response = requests.patch(url=url,
                                       headers=self.get_headers(),
                                       json=self.get_body())
        return self

    def put(self):
        url = self.get_request_url()

        self.response = requests.put(url=url,
                                       headers=self.get_headers(),
                                       json=self.get_body())
        return self

    def fetch_response_code(self):
        return self.response.status_code

    def fetch_response(self):

        if self.response.status_code in [200, 201]:

            try:

                try: 
                    return self.response.json()
                
                except Exception as e:
                    
                    if 'utf-8' in str(e).lower() and 'bom' in str(e).lower():
                        res = self.response.text.encode('utf-8').decode('utf-8-sig')
                        return json.loads(res)
                    
                    return {}

            except Exception as e:
                return {}
        else:
            
            return {}
