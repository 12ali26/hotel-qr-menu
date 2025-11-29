import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class Hotel(models.Model):
    """
    Represents a Hotel tenant in the system.
    Each hotel is a separate entity with its own menus, orders, and settings.
    """

    name: str = models.CharField(
        _("Hotel Name"),
        max_length=255,
        help_text=_("The official name of the hotel."),
    )
    slug: str = models.SlugField(
        _("Slug"),
        max_length=255,
        unique=True,
        help_text=_(
            "A unique, URL-friendly identifier for the hotel (e.g., 'hilton-london')."
        ),
    )
    currency_code: str = models.CharField(
        _("Currency Code"),
        max_length=3,
        help_text=_("The 3-letter ISO currency code (e.g., USD, EUR)."),
    )
    timezone: str = models.CharField(
        _("Timezone"),
        max_length=63,
        help_text=_("The timezone for the hotel (e.g., 'Europe/London')."),
        default="UTC",
    )
    logo = models.ImageField(
        _("Logo"),
        upload_to="hotel_logos/",
        blank=True,
        null=True,
        help_text=_("The hotel's logo image file."),
    )
    is_active: bool = models.BooleanField(
        _("Is Active"),
        default=True,
        help_text=_(
            "Designates whether the hotel's menu is currently active and accessible."
        ),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Hotel")
        verbose_name_plural = _("Hotels")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Category(models.Model):
    """
    A category for menu items within a hotel's menu (e.g., Starters, Main Courses, Drinks).
    """

    hotel: Hotel = models.ForeignKey(
        Hotel,
        on_delete=models.CASCADE,
        related_name="categories",
        verbose_name=_("Hotel"),
    )
    name: str = models.CharField(
        _("Category Name"),
        max_length=100,
        help_text=_("The name of the category (e.g., 'Starters', 'Desserts')."),
    )
    sort_order: int = models.PositiveIntegerField(
        _("Sort Order"),
        default=0,
        help_text=_("The order in which this category appears on the menu."),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Category")
        verbose_name_plural = _("Categories")
        ordering = ["hotel", "sort_order", "name"]
        unique_together = [["hotel", "name"]]

    def __str__(self) -> str:
        return f"{self.name} ({self.hotel.name})"


class MenuItem(models.Model):
    """
    An individual item on the menu (e.g., a specific dish or drink).
    """

    category: Category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="menu_items",
        verbose_name=_("Category"),
    )
    name: str = models.CharField(_("Name"), max_length=255)
    description: str = models.TextField(_("Description"), blank=True)
    price: Decimal = models.DecimalField(
        _("Price"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    image = models.ImageField(
        _("Image"),
        upload_to="menu_item_images/",
        blank=True,
        null=True,
        help_text=_("An image of the menu item."),
    )
    is_available: bool = models.BooleanField(
        _("Is Available"),
        default=True,
        help_text=_("Toggle for out-of-stock items."),
    )
    # Dietary Flags
    is_vegetarian: bool = models.BooleanField(_("Vegetarian"), default=False)
    is_vegan: bool = models.BooleanField(_("Vegan"), default=False)
    is_gluten_free: bool = models.BooleanField(_("Gluten-Free"), default=False)

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Menu Item")
        verbose_name_plural = _("Menu Items")
        ordering = ["category", "name"]
        unique_together = [["category", "name"]]

    def __str__(self) -> str:
        return self.name


class Order(models.Model):
    """
    Represents a customer's order for a specific hotel.
    """

    class OrderStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        PREPARING = "PREPARING", _("Preparing")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    # External-facing Order ID
    id: uuid.UUID = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    hotel: Hotel = models.ForeignKey(
        Hotel,
        on_delete=models.PROTECT,  # Protect orders from hotel deletion
        related_name="orders",
        verbose_name=_("Hotel"),
    )
    room_number: str = models.CharField(
        _("Room Number / Location"),
        max_length=50,
        help_text=_("Room number or table identifier."),
    )
    status: str = models.CharField(
        _("Status"),
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    total_price: Decimal = models.DecimalField(
        _("Total Price"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("The total price of the order at the time of creation."),
    )
    # Snapshot of items for historical accuracy, in case item details change later.
    items_snapshot: dict = models.JSONField(
        _("Items Snapshot"),
        blank=True,
        null=True,
        help_text=_("A JSON snapshot of the items and prices at the time of order."),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Order {self.id} for {self.hotel.name}"


class OrderItem(models.Model):
    """
    An intermediate model representing a menu item within a specific order,
    including its quantity and the price at the time of ordering.
    """

    order: Order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Order"),
    )
    menu_item: MenuItem = models.ForeignKey(
        MenuItem,
        on_delete=models.SET_NULL,  # Keep order history even if menu item is deleted
        null=True,
        related_name="order_items",
        verbose_name=_("Menu Item"),
    )
    quantity: int = models.PositiveIntegerField(
        _("Quantity"),
        validators=[MinValueValidator(1)],
        default=1,
    )
    price_at_order: Decimal = models.DecimalField(
        _("Price at Order"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Price of a single item at the time the order was placed."),
    )

    class Meta:
        verbose_name = _("Order Item")
        verbose_name_plural = _("Order Items")
        ordering = ["order"]
        unique_together = [["order", "menu_item"]]

    def __str__(self) -> str:
        return (
            f"{self.quantity} x {self.menu_item.name or 'N/A'} in Order {self.order.id}"
        )

    @property
    def total_price(self) -> Decimal:
        """Calculates the total price for this line item."""
        return self.quantity * self.price_at_order
