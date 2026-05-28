class InvalidRequestError(Exception):
    def __init__(self, message=None, *args, **kwargs):
        super(InvalidRequestError, self).__init__(message)


class ServerError(Exception):
    def __init__(self, message=None, *args, **kwargs):
        super(ServerError, self).__init__(message)

class BadRequestError(Exception):
    def __init__(self, message=None,*args,**kwargs):
        super(RateLimitError,self).__init__(message)


class RateLimitError(Exception):
    def __init__(self, message=None,*args,**kwargs):
        super(RateLimitError,self).__init__(message)

