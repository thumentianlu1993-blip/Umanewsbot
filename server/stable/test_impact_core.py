"""每次局部业务改动保留公开健康入口的装载检查。"""
from django.test import SimpleTestCase


class PublicHealthSmokeTests(SimpleTestCase):
    def test_anonymous_health_route_loads_without_database_access(self):
        response=self.client.get('/healthz/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'status':'ok'})
