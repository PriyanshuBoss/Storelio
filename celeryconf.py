import os
from kombu import Queue, Exchange
from celery import Celery
from django.conf import settings

from .plugins import discover_plugins_modules

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saleor.settings")

app = Celery("saleor")
app.conf.task_default_queue = 'default'
default_exchange = Exchange('default', type='direct')
app.conf.task_queues = (
    Queue('default', Exchange('default'), routing_key='default'),
    Queue('priority_queue',  Exchange('priority_queue'),   routing_key='priority_queue'),
    Queue('onboarding_queue',  Exchange('onboarding_queue'),   routing_key='onboarding_queue'),
 )
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.autodiscover_tasks(lambda: discover_plugins_modules(settings.PLUGINS))

