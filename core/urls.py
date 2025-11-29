from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("menu/<slug:slug>/", views.hotel_menu, name="hotel_menu"),
]
