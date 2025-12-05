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
    path("switch-business/<int:business_id>/", views.switch_business, name="switch_business"),
    path("add-business/", views.add_business, name="add_business"),
    # Menu management
    path("menu-management/", views.menu_management, name="menu_management"),
    path("menu-management/add-category/", views.add_category, name="add_category"),
    path("menu-management/add-item/", views.add_menu_item, name="add_menu_item"),
    path("menu-management/add-item/<int:category_id>/", views.add_menu_item, name="add_menu_item_to_category"),
    path("menu-management/edit-item/<int:item_id>/", views.edit_menu_item, name="edit_menu_item"),
    path("menu-management/delete-item/<int:item_id>/", views.delete_menu_item, name="delete_menu_item"),
    # Table management
    path("table-management/", views.table_management, name="table_management"),
    path("table-management/add/", views.add_table, name="add_table"),
    path("table-management/generate-qr-codes/", views.generate_all_qr_codes, name="generate_all_qr_codes"),
    # Customer-facing menu
    path("menu/<slug:slug>/", views.hotel_menu, name="hotel_menu"),
    # API endpoints
    path("api/<slug:slug>/order/", views.place_order, name="place_order"),
    path("api/<slug:slug>/waiter-alert/", views.create_waiter_alert, name="waiter_alert"),
    # Kitchen/staff dashboard
    path("kitchen/<slug:slug>/", views.kitchen_dashboard, name="kitchen_dashboard"),
    # QR code download
    path("qr-codes/<slug:slug>/", views.download_qr_codes, name="download_qr_codes"),
    # Dynamic QR code generation (no file storage needed!)
    path("qr-code/<int:table_id>/", views.serve_qr_code, name="serve_qr_code"),
]
