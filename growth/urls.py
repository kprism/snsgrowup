from django.urls import path

from . import instagram_discovery, reel_views, views

app_name = "growth"

urlpatterns = [
    path("", views.action_center, name="action_center"),
    path("generate/", views.generate_actions, name="generate_actions"),
    path("<int:pk>/prepare/", views.prepare_action, name="prepare_action"),
    path("<int:pk>/instagram-discover/", instagram_discovery.instagram_discover, name="instagram_discover"),
    path("<int:pk>/content/<int:content_pk>/post/", views.use_content_for_post, name="use_content_for_post"),
    path("<int:pk>/content/<int:content_pk>/instagram-news-reel/", reel_views.generate_instagram_news_reel, name="generate_instagram_news_reel"),
    path("<int:pk>/content/<int:content_pk>/story-video/", views.generate_story_video, name="generate_story_video"),
    path("<int:pk>/start/", views.start_action, name="start_action"),
    path("<int:pk>/complete/", views.complete_action, name="complete_action"),
    path("<int:pk>/skip/", views.skip_action, name="skip_action"),
]
