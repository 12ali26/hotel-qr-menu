from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import Category, Hotel, MenuItem, Order, OrderItem


@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    """Admin configuration for the Hotel model."""

    list_display = ("name", "slug", "currency_code", "timezone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin configuration for the Order model."""

    list_display = (
        "id",
        "hotel",
        "room_number",
        "status",
        "total_price",
        "created_at",
    )
    list_filter = ("status", "hotel")
    search_fields = ("id", "room_number")
    readonly_fields = (
        "id",
        "hotel",
        "room_number",
        "total_price",
        "items_snapshot",
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline]

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Orders should be created through the front-end, not the admin.
        return False

    def has_change_permission(self, request: HttpRequest, obj: Order = None) -> bool:
        # Allow changing the status, but not other fields for integrity.
        # More granular control can be achieved by overriding get_readonly_fields.
        return True

    def get_readonly_fields(self, request, obj=None):
        if obj:  # For existing objects
            # All fields are readonly except for 'status'
            return [
                field.name
                for field in self.model._meta.fields
                if field.name != "status"
            ]
        return super().get_readonly_fields(request, obj)
