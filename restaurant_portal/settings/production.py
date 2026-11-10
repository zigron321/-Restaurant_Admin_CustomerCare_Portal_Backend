"""
Production-specific settings (Railway).

- DEBUG = False
- Security hardened
- Database comes from DATABASE_URL (set in base.py)
- Sentry error tracking (optional)
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403
from .base import env, LOGGING, REST_FRAMEWORK, SECRET_KEY

# ====================================================
# Safety check: refuse to start with the placeholder key
# ====================================================
if SECRET_KEY.startswith("unsafe-default"):
    raise ImproperlyConfigured(
        "SECRET_KEY environment variable is not set. "
        "Add SECRET_KEY in Railway Variables."
    )

# ====================================================
# Debug Mode - STRICTLY False
# ====================================================
DEBUG = False

# ====================================================
# Allowed Hosts (Railway domains + localhost)
# ====================================================
ALLOWED_HOSTS = list(env.list("ALLOWED_HOSTS", default=[]))
for _host in [".up.railway.app", "localhost", "127.0.0.1"]:
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

# ====================================================
# CSRF Trusted Origins
# Wildcard covers every Railway subdomain. Extra origins can be added
# in the CSRF_TRUSTED_ORIGINS variable (comma separated, with https://).
# ====================================================
CSRF_TRUSTED_ORIGINS = list(env.list("CSRF_TRUSTED_ORIGINS", default=[]))
if "https://*.up.railway.app" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append("https://*.up.railway.app")

# ====================================================
# Security Configuration
# Railway terminates HTTPS at its proxy and forwards the protocol header.
# ====================================================
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ====================================================
# CORS Configuration (strict)
# Add your Vercel URL to CORS_ALLOWED_ORIGINS once the frontend is deployed.
# ====================================================
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# ====================================================
# Email Configuration
# ====================================================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# ====================================================
# Logging - more conservative in production
# ====================================================
LOGGING["loggers"]["django"]["level"] = "WARNING"
LOGGING["loggers"]["apps"]["level"] = "INFO"

# ====================================================
# Sentry Integration (optional, only if SENTRY_DSN is set)
# ====================================================
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment="production",
    )

# ====================================================
# Throttle limits for production
# ====================================================
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": "60/hour",
    "user": "1000/hour",
}


# AWS S3 Configuration
AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = 'restaurant-portal-media-bucket' # REPLACE WITH YOUR BUCKET NAME
AWS_S3_REGION_NAME = 'ap-southeast-2' # REPLACE WITH YOUR REGION
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = 'public-read'
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'