from functools import wraps
from time import monotonic
from saleor.external_services.caching.cache_impl import CacheImpl

CACHE_LOCK_EXPIRE = 15 * 60

def no_simultaneous_execution(f):
    """
    Decorator that prevents a task form being executed with the
    same *args and **kwargs more than one at a time.
    """
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        
        try:
            lock_id = f'{self.name}_{args[-1]}'
        
        except Exception as e:
            arg_name = '_'.join(map(str,args))
            lock_id = f'{self.name}_{arg_name}'

        timeout_at = monotonic() + CACHE_LOCK_EXPIRE - 3

        lock_acquired = CacheImpl.add_cache(lock_id, True, CACHE_LOCK_EXPIRE)
        
        if not lock_acquired:

            self.apply_async(args=args, kwargs=kwargs, countdown=3)
            return

        try:
            f(self, *args, **kwargs)
        finally:
            # Release the lock
            if monotonic() < timeout_at:
                CacheImpl.delete_key(lock_id)
    return wrapper
