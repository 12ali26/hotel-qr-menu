from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import BusinessOwner, Category, Hotel, MenuItem, Order, OrderItem, Table, WaiterAlert


@admin.register(BusinessOwner)
class BusinessOwnerAdmin(admin.ModelAdmin):
    """Admin configuration for the BusinessOwner model."""

    list_display = ("user", "business", "role", "is_primary", "created_at")
    list_filter = ("role", "is_primary")
    search_fields = ("user__username", "user__email", "business__name")
    raw_id_fields = ("user", "business")


@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    """Admin configuration for the Business model."""

    list_display = (
        "name",
        "business_type",
        "slug",
        "currency_code",
        "is_active",
    )
    list_filter = ("business_type", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "name",
                    "business_type",
                    "slug",
                    "currency_code",
                    "timezone",
                    "logo",
                    "is_active",
                )
            },
        ),
        (
            "Feature Settings",
            {
                "fields": (
                    "enable_table_management",
                    "enable_waiter_alerts",
                    "enable_room_charging",
                ),
                "description": "Enable specific features based on your business type.",
            },
        ),
    )


class MenuItemInline(admin.TabularInline):
    """
    Inline admin descriptor for MenuItems.
    Allows for editing MenuItems directly within the Category admin page.
    """

    model = MenuItem
    extra = 1  # Show one extra form for adding a new menu item
    fields = (
        "name",
        "description",
        "price",
        "is_available",
        "is_vegetarian",
        "is_vegan",
        "is_gluten_free",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin configuration for the Category model."""

    list_display = ("name", "hotel", "sort_order")
    list_filter = ("hotel",)
    search_fields = ("name",)
    inlines = [MenuItemInline]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    """Admin configuration for the MenuItem model."""

    list_display = ("name", "get_hotel", "category", "price", "is_available")
    list_filter = ("is_available", "category__hotel", "category")
    search_fields = ("name", "description")

    @admin.display(description="Hotel")
    def get_hotel(self, obj: MenuItem) -> str:
        """Returns the name of the hotel for the menu item."""
        return obj.category.hotel.name


class OrderItemInline(admin.TabularInline):
    """
    Inline admin descriptor for OrderItems.
    Shows the items within an order in a read-only format.
    """

    model = OrderItem
    extra = 0
    readonly_fields = ("menu_item", "quantity", "price_at_order", "total_price")
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    """Admin configuration for the Table model."""

    list_display = ("table_number", "hotel", "capacity", "status", "updated_at")
    list_filter = ("status", "hotel")
    search_fields = ("table_number", "hotel__name")
    list_editable = ("status",)


@admin.register(WaiterAlert)
class WaiterAlertAdmin(admin.ModelAdmin):
    """Admin configuration for the WaiterAlert model."""

    list_display = (
        "table",
        "hotel",
        "alert_type",
        "status",
        "created_at",
        "acknowledged_at",
    )
    list_filter = ("status", "alert_type", "hotel")
    search_fields = ("table__table_number", "note")
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("status",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin configuration for the Order model."""

    list_display = (
        "id",
        "hotel",
        "room_number",
        "table",
        "status",
        "payment_method",
        "total_price",
        "created_at",
    )
    list_filter = ("status", "payment_method", "payment_status", "hotel")
    search_fields = ("id", "room_number", "table__table_number")
    readonly_fields = (
        "id",
        "hotel",
        "room_number",
        "table",
        "subtotal",
        "tax_amount",
        "total_price",
        "items_snapshot",
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline]
    fieldsets = (
        (
            "Order Information",
            {
                "fields": (
                    "id",
                    "hotel",
                    "room_number",
                    "table",
                    "status",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Payment",
            {
                "fields": (
                    "payment_method",
                    "payment_status",
                    "subtotal",
                    "tax_amount",
                    "tip_amount",
                    "total_price",
                )
            },
        ),
        (
            "Additional Information",
            {"fields": ("special_requests", "items_snapshot")},
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Orders should be created through the front-end, not the admin.
        return False

    def has_change_permission(self, request: HttpRequest, obj: Order = None) -> bool:
        # Allow changing the status, but not other fields for integrity.
        return True

    def get_readonly_fields(self, request, obj=None):
        if obj:  # For existing objects
            # Allow editing status, payment_status, and tip_amount
            editable_fields = ["status", "payment_status", "tip_amount"]
            return [
                field.name
                for field in self.model._meta.fields
                if field.name not in editable_fields
            ]
        return super().get_readonly_fields(request, obj)
