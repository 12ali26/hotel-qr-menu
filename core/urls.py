from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Landing page
    path("", views.landing_page, name="landing"),
    # Authentication
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # Business owner dashboard
    path("dashboard/", views.dashboard, name="dashboard"),
    path("onboarding/", views.onboarding, name="onboarding"),
    # Customer-facing menu
    path("menu/<slug:slug>/", views.hotel_menu, name="hotel_menu"),
    # API endpoints
    path("api/<slug:slug>/order/", views.place_order, name="place_order"),
    path("api/<slug:slug>/waiter-alert/", views.create_waiter_alert, name="waiter_alert"),
    # Kitchen/staff dashboard
    path("kitchen/<slug:slug>/", views.kitchen_dashboard, name="kitchen_dashboard"),
    # QR code download
    path("qr-codes/<slug:slug>/", views.download_qr_codes, name="download_qr_codes"),
]
