"""
WSGI configuration for the Restaurant Portal project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "restaurant_portal.settings.production"
)

application = get_wsgi_application()