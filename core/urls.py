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
    # AI Menu Import
    path("ai-menu-upload/", views.ai_menu_upload, name="ai_menu_upload"),
    path("ai-menu-preview/", views.ai_menu_preview, name="ai_menu_preview"),
    path("ai-menu-confirm/", views.ai_menu_confirm, name="ai_menu_confirm"),
    # CSV Menu Import
    path("csv-menu-upload/", views.csv_menu_upload, name="csv_menu_upload"),
    path("csv-menu-preview/", views.csv_menu_preview, name="csv_menu_preview"),
    path("csv-menu-confirm/", views.csv_menu_confirm, name="csv_menu_confirm"),
    path("csv-template-download/", views.csv_template_download, name="csv_template_download"),
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
    path("track-order/<str:order_id>/", views.track_order, name="track_order"),
    # API endpoints
    path("api/<slug:slug>/order/", views.place_order, name="place_order"),
    path("api/<slug:slug>/waiter-alert/", views.create_waiter_alert, name="waiter_alert"),
    path("api/order/<str:order_id>/status/", views.update_order_status, name="update_order_status"),
    path("api/order/<str:order_id>/status-check/", views.check_order_status, name="check_order_status"),
    path("api/waiter-alert/<int:alert_id>/acknowledge/", views.acknowledge_waiter_alert, name="acknowledge_alert"),
    path("api/<slug:slug>/poll-orders/", views.poll_orders, name="poll_orders"),
    # Recommendation API
    path("api/recommendations/item/<int:item_id>/", views.get_item_recommendations, name="get_item_recommendations"),
    path("api/recommendations/track/", views.track_recommendation_event, name="track_recommendation_event"),
    # Recommendation Analytics Dashboard
    path("dashboard/recommendations/", views.recommendation_dashboard, name="recommendation_dashboard"),
    # Kitchen/staff dashboard
    path("kitchen/<slug:slug>/", views.kitchen_dashboard, name="kitchen_dashboard"),
    # HTMX partials for real-time updates
    path("htmx/kitchen/<slug:slug>/orders/", views.kitchen_orders_partial, name="kitchen_orders_partial"),
    path("htmx/kitchen/<slug:slug>/alerts/", views.kitchen_alerts_partial, name="kitchen_alerts_partial"),
    path("htmx/order/<str:order_id>/status/", views.order_status_partial, name="order_status_partial"),
    # QR code download
    path("qr-codes/<slug:slug>/", views.download_qr_codes, name="download_qr_codes"),
    # Dynamic QR code generation (no file storage needed!)
    path("qr-code/<int:table_id>/", views.serve_qr_code, name="serve_qr_code"),
]
