"""固定导航 URL；不得导入业务 views。"""
from django.urls import path


def synthetic_endpoint(request):
    raise AssertionError('C021 renders templates directly; HTTP is forbidden')


urlpatterns = [
    path('races/', synthetic_endpoint, name='public-race-calendar'),
    path('horses/', synthetic_endpoint, name='public-horse-index'),
    path('horses/follows/', synthetic_endpoint, name='public-horse-follows'),
]
