from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Customer-facing menu
    path("menu/<slug:slug>/", views.hotel_menu, name="hotel_menu"),
    # API endpoints
    path("api/<slug:slug>/order/", views.place_order, name="place_order"),
    path("api/<slug:slug>/waiter-alert/", views.create_waiter_alert, name="waiter_alert"),
    # Kitchen/staff dashboard
    path("kitchen/<slug:slug>/", views.kitchen_dashboard, name="kitchen_dashboard"),
]
