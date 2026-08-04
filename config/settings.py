"""
Django settings for SNSGROWUP.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, True))
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-only-change-before-production")
DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", ".githubpreview.dev", ".app.github.dev"],
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "social_channels",
    "press_accounts",
    "contents",
    "publishing",
    "growth",
    "analytics",
    "shorts",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="snsgrowup"),
        "USER": env("POSTGRES_USER", default="snsgrowup"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="snsgrowup"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

AUTH_USER_MODEL = "accounts.User"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# 기존 META_* 이름과 FACEBOOK_* 이름을 모두 지원한다.
FACEBOOK_APP_ID = env("FACEBOOK_APP_ID", default=env("META_APP_ID", default=""))
FACEBOOK_APP_SECRET = env("FACEBOOK_APP_SECRET", default=env("META_APP_SECRET", default=""))
FACEBOOK_LOGIN_CONFIG_ID = env(
    "FACEBOOK_LOGIN_CONFIG_ID",
    default=env("META_LOGIN_CONFIG_ID", default=""),
)
FACEBOOK_GRAPH_VERSION = env(
    "FACEBOOK_GRAPH_VERSION",
    default=env("META_GRAPH_VERSION", default="v24.0"),
)

# 일반 Facebook Login의 직접 scope 방식은 개발용 최소 권한만 사용한다.
# 비즈니스용 Facebook 로그인에서는 Meta 구성(Configuration)에 권한을 저장하고
# FACEBOOK_LOGIN_CONFIG_ID를 OAuth 요청에 전달한다.
FACEBOOK_OAUTH_SCOPES = env.list(
    "FACEBOOK_OAUTH_SCOPES",
    default=["public_profile"],
)
