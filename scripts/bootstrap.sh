#!/usr/bin/env bash
set -euo pipefail

if [ -f manage.py ]; then
  echo "SNSGROWUP project already initialized."
  exit 0
fi

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install "Django>=5.2,<6.1" psycopg[binary] django-environ feedparser Pillow djangorestframework celery redis gunicorn whitenoise

cat > requirements.txt <<'REQ'
Django>=5.2,<6.1
psycopg[binary]
django-environ
feedparser
Pillow
djangorestframework
celery
redis
gunicorn
whitenoise
REQ

django-admin startproject config .
for app in accounts social_channels press_accounts contents publishing growth analytics shorts dashboard; do
  python manage.py startapp "$app"
done

mkdir -p templates/{accounts,dashboard,includes} static/{css,js,icons,images} media/{profiles,press_logos,article_images,generated_shorts} tests

cat > .env.example <<'ENV'
DEBUG=True
SECRET_KEY=change-me
DATABASE_URL=postgresql://snsgrowup:snsgrowup@db:5432/snsgrowup
REDIS_URL=redis://redis:6379/0
ALLOWED_HOSTS=localhost,127.0.0.1,.githubpreview.dev,.app.github.dev
ENV

cat > docker-compose.yml <<'YAML'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: snsgrowup
      POSTGRES_USER: snsgrowup
      POSTGRES_PASSWORD: snsgrowup
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U snsgrowup"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

volumes:
  postgres_data:
YAML

cat > Dockerfile <<'DOCKER'
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
DOCKER

cat > accounts/models.py <<'PY'
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class AccountType(models.TextChoices):
        GENERAL = "general", "일반 계정 사용자"
        PRESS = "press", "신문사 사용자"

    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "display_name", "account_type"]
PY

cat > press_accounts/models.py <<'PY'
from django.conf import settings
from django.db import models


class PressProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="press_profile")
    press_name = models.CharField(max_length=150)
    homepage_url = models.URLField()
    rss_url = models.URLField()
    rss_verified = models.BooleanField(default=False)
    logo = models.ImageField(upload_to="press_logos/", blank=True)
    auto_collect = models.BooleanField(default=True)
    last_collected_at = models.DateTimeField(null=True, blank=True)
    collection_status = models.CharField(max_length=30, default="pending")

    def __str__(self):
        return self.press_name
PY

cat > social_channels/models.py <<'PY'
from django.conf import settings
from django.db import models


class SocialPlatform(models.Model):
    name = models.CharField(max_length=50)
    code = models.SlugField(unique=True)
    icon = models.CharField(max_length=255, blank=True)
    supports_oauth = models.BooleanField(default=False)
    supports_publish = models.BooleanField(default=False)
    supports_analytics = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class SocialAccount(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_accounts")
    platform = models.ForeignKey(SocialPlatform, on_delete=models.PROTECT)
    profile_name = models.CharField(max_length=120)
    profile_url = models.URLField()
    external_account_id = models.CharField(max_length=255, blank=True)
    connection_status = models.CharField(max_length=30, default="url_only")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "platform", "profile_url")
PY

cat > contents/models.py <<'PY'
from django.conf import settings
from django.db import models


class ContentItem(models.Model):
    class SourceType(models.TextChoices):
        DIRECT = "direct", "직접 등록"
        RSS = "rss", "RSS 기사"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contents")
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    representative_image = models.ImageField(upload_to="article_images/", blank=True)
    external_guid = models.CharField(max_length=500, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "external_guid"], condition=~models.Q(external_guid=""), name="unique_owner_guid")
        ]
PY

cat > accounts/admin.py <<'PY'
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("SNSGROWUP", {"fields": ("display_name", "account_type")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("SNSGROWUP", {"fields": ("email", "display_name", "account_type")}),)
    list_display = ("email", "display_name", "account_type", "is_staff", "is_active")
PY

cat > press_accounts/admin.py <<'PY'
from django.contrib import admin
from .models import PressProfile
admin.site.register(PressProfile)
PY

cat > social_channels/admin.py <<'PY'
from django.contrib import admin
from .models import SocialPlatform, SocialAccount
admin.site.register(SocialPlatform)
admin.site.register(SocialAccount)
PY

cat > contents/admin.py <<'PY'
from django.contrib import admin
from .models import ContentItem
admin.site.register(ContentItem)
PY

python - <<'PY'
from pathlib import Path
p = Path('config/settings.py')
s = p.read_text()
s = s.replace('from pathlib import Path', 'from pathlib import Path\nimport os\nimport environ')
s = s.replace('BASE_DIR = Path(__file__).resolve().parent.parent', 'BASE_DIR = Path(__file__).resolve().parent.parent\nenv = environ.Env(DEBUG=(bool, True))\nif (BASE_DIR / ".env").exists():\n    environ.Env.read_env(BASE_DIR / ".env")')
s = s.replace("SECRET_KEY = 'django-insecure-", "SECRET_KEY = env('SECRET_KEY', default='django-insecure-")
s = s.replace("DEBUG = True", "DEBUG = env.bool('DEBUG', default=True)")
s = s.replace("ALLOWED_HOSTS = []", "ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '.githubpreview.dev', '.app.github.dev'])")
s = s.replace("'django.contrib.staticfiles',", "'django.contrib.staticfiles',\n    'rest_framework',\n    'accounts',\n    'social_channels',\n    'press_accounts',\n    'contents',\n    'publishing',\n    'growth',\n    'analytics',\n    'shorts',\n    'dashboard',")
s = s.replace("'ENGINE': 'django.db.backends.sqlite3',\n        'NAME': BASE_DIR / 'db.sqlite3',", "'ENGINE': 'django.db.backends.postgresql',\n        'NAME': env('POSTGRES_DB', default='snsgrowup'),\n        'USER': env('POSTGRES_USER', default='snsgrowup'),\n        'PASSWORD': env('POSTGRES_PASSWORD', default='snsgrowup'),\n        'HOST': env('POSTGRES_HOST', default='db'),\n        'PORT': env('POSTGRES_PORT', default='5432'),")
s += "\nAUTH_USER_MODEL = 'accounts.User'\nLOGIN_REDIRECT_URL = '/'\nLOGOUT_REDIRECT_URL = '/'\nSTATIC_URL = 'static/'\nSTATIC_ROOT = BASE_DIR / 'staticfiles'\nMEDIA_URL = 'media/'\nMEDIA_ROOT = BASE_DIR / 'media'\n"
p.write_text(s)
PY

cat > .env <<'ENV'
DEBUG=True
SECRET_KEY=dev-only-change-before-production
POSTGRES_DB=snsgrowup
POSTGRES_USER=snsgrowup
POSTGRES_PASSWORD=snsgrowup
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/0
ALLOWED_HOSTS=localhost,127.0.0.1,.githubpreview.dev,.app.github.dev
ENV

cat > dashboard/views.py <<'PY'
from django.shortcuts import render


def home(request):
    return render(request, "dashboard/index.html")
PY

cat > dashboard/urls.py <<'PY'
from django.urls import path
from .views import home

urlpatterns = [path("", home, name="home")]
PY

cat > templates/dashboard/index.html <<'HTML'
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SNSGROWUP</title>
  <style>
    body{margin:0;font-family:system-ui,sans-serif;background:#f5f7fb;color:#162033}.wrap{max-width:1100px;margin:auto;padding:24px}.hero{background:white;border-radius:24px;padding:36px;box-shadow:0 16px 50px rgba(20,32,51,.08)}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:24px}.card{background:#fff;border:1px solid #e7ebf2;border-radius:18px;padding:22px}@media(max-width:720px){.wrap{padding:14px}.hero{padding:24px}.grid{grid-template-columns:1fr}}
  </style>
</head>
<body><main class="wrap"><section class="hero"><strong>SNSGROWUP</strong><h1>콘텐츠를 만들고, 채널을 키우는 통합 운영 플랫폼</h1><p>일반 계정 사용자와 신문사 사용자를 구분해 가입시키고 SNS 발행·성장활동·통계·RSS·AI 쇼츠를 관리합니다.</p><div class="grid"><article class="card"><h2>일반 계정 사용자</h2><p>직접 콘텐츠 등록, SNS 채널 연결, 성장활동 및 성과분석</p></article><article class="card"><h2>신문사 사용자</h2><p>신문사 정보와 RSS 등록, 기사수집, 다중채널 발행 및 쇼츠 제작</p></article></div></section></main></body>
</html>
HTML

python - <<'PY'
from pathlib import Path
p=Path('config/urls.py')
s=p.read_text()
s=s.replace('from django.urls import path', 'from django.urls import include, path')
s=s.replace('urlpatterns = [', "urlpatterns = [\n    path('', include('dashboard.urls')),")
p.write_text(s)
PY

python manage.py makemigrations accounts social_channels press_accounts contents

git add .
git commit -m "Initialize Django full-stack foundation"
git push

echo
echo "Bootstrap complete."
echo "Run: docker compose up --build"
echo "Then open forwarded port 8000."
