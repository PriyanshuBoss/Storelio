from django.urls import path
from .view_impl import page_load_time
urlpatterns = [
    path('page_load_time', page_load_time, name="page_load_time"),

]
