"""Contracts that keep the reviewed production TLS ingress in version control."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[3]
NGINX = ROOT / "deploy" / "nginx" / "nginx.conf"


class ProductionNginxContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = NGINX.read_text(encoding="utf-8")

    def test_http_keeps_acme_challenge_route(self):
        self.assertIn("location ^~ /.well-known/acme-challenge/", self.source)
        self.assertIn("root /var/www/static/umanews-acme;", self.source)
        self.assertIn("try_files $uri =404;", self.source)

    def test_https_uses_current_letsencrypt_certificate_and_security_headers(self):
        self.assertIn("listen 443 ssl default_server;", self.source)
        self.assertIn("listen [::]:443 ssl default_server;", self.source)
        self.assertIn(
            "ssl_certificate /etc/nginx/certs/letsencrypt/live/umafans.run/fullchain.pem;",
            self.source,
        )
        self.assertIn(
            "ssl_certificate_key /etc/nginx/certs/letsencrypt/live/umafans.run/privkey.pem;",
            self.source,
        )
        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", self.source)
        self.assertIn(
            'add_header Strict-Transport-Security "max-age=31536000" always;',
            self.source,
        )

    def test_https_preserves_public_routes_and_proxy_headers(self):
        self.assertIn("listen 443 ssl default_server;", self.source)
        https = self.source[self.source.index("listen 443 ssl default_server;") :]
        for fragment in (
            "location /static/",
            "location /media/",
            "location /healthz/",
            "location / {",
            "proxy_set_header X-Forwarded-Proto $scheme;",
        ):
            self.assertIn(fragment, https)

    def test_retired_hipilot_host_remains_gone(self):
        self.assertIn("server_name hipilot.umafans.run", self.source)
        block = self.source[self.source.index("server_name hipilot.umafans.run") :]
        self.assertIn("return 410;", block)
