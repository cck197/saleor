# pylint: disable=W0401, W0614
# flake8: noqa
from saleor.settings import *  # noqa

CELERY_TASK_ALWAYS_EAGER = True

SECRET_KEY = "NOTREALLY"

ALLOWED_CLIENT_HOSTS = ["www.example.com"]

DEFAULT_CURRENCY = "USD"

TIME_ZONE = "America/Chicago"
LANGUAGE_CODE = "en"

ES_URL = None
SEARCH_BACKEND = "saleor.search.backends.postgresql"
INSTALLED_APPS = [a for a in INSTALLED_APPS if a != "django_elasticsearch_dsl"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

RECAPTCHA_PUBLIC_KEY = ""
RECAPTCHA_PRIVATE_KEY = ""

VATLAYER_ACCESS_KEY = ""

if "sqlite" in DATABASES["default"]["ENGINE"]:  # noqa
    DATABASES["default"]["TEST"] = {  # noqa
        "SERIALIZE": False,
        "NAME": ":memory:",
        "MIRROR": None,
    }
#DATABASES = {'default': {'NAME': 'saleor', 'USER': 'saleor', 'PASSWORD': 'saleor', 'HOST': 'localhost', 'PORT': 5432, 'CONN_MAX_AGE': 600, 'ENGINE': 'django.db.backends.postgresql_psycopg2'}}

COUNTRIES_ONLY = None

MEDIA_ROOT = None
MAX_CHECKOUT_LINE_QUANTITY = 50

USE_JSON_CONTENT = False

AUTH_PASSWORD_VALIDATORS = []

PASSWORD_HASHERS = ["tests.dummy_password_hasher.DummyHasher"]
EXTENSIONS_MANAGER = "saleor.extensions.manager.ExtensionsManager"

PLUGINS = []
