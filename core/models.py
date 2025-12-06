import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class Hotel(models.Model):
    """
    Represents a Business tenant in the system (Hotel or Restaurant).
    Each business is a separate entity with its own menus, orders, and settings.
    """

    class BusinessType(models.TextChoices):
        HOTEL = "HOTEL", _("Hotel")
        RESTAURANT = "RESTAURANT", _("Restaurant")
        CAFE = "CAFE", _("Café")
        CLOUD_KITCHEN = "CLOUD_KITCHEN", _("Cloud Kitchen")

    class MenuTheme(models.TextChoices):
        MODERN = "MODERN", _("Modern Light")
        DARK = "DARK", _("Dark Premium")

    name: str = models.CharField(
        _("Business Name"),
        max_length=255,
        help_text=_("The official name of the business."),
    )
    business_type: str = models.CharField(
        _("Business Type"),
        max_length=20,
        choices=BusinessType.choices,
        default=BusinessType.HOTEL,
        help_text=_("The type of food business."),
    )
    slug: str = models.SlugField(
        _("Slug"),
        max_length=255,
        unique=True,
        help_text=_(
            "A unique, URL-friendly identifier (e.g., 'bella-italia-doha')."
        ),
    )
    currency_code: str = models.CharField(
        _("Currency Code"),
        max_length=3,
        help_text=_("The 3-letter ISO currency code (e.g., USD, EUR, QAR)."),
    )
    timezone: str = models.CharField(
        _("Timezone"),
        max_length=63,
        help_text=_("The timezone for the business (e.g., 'Asia/Qatar')."),
        default="UTC",
    )
    logo = models.ImageField(
        _("Logo"),
        upload_to="business_logos/",
        blank=True,
        null=True,
        help_text=_("The business logo image file."),
    )
    is_active: bool = models.BooleanField(
        _("Is Active"),
        default=True,
        help_text=_(
            "Designates whether the business menu is currently active and accessible."
        ),
    )
    # Restaurant-specific settings
    enable_table_management: bool = models.BooleanField(
        _("Enable Table Management"),
        default=False,
        help_text=_("Enable table tracking and status (for restaurants)."),
    )
    enable_waiter_alerts: bool = models.BooleanField(
        _("Enable Waiter Alerts"),
        default=False,
        help_text=_("Allow customers to call waiters (for restaurants)."),
    )
    # Hotel-specific settings
    enable_room_charging: bool = models.BooleanField(
        _("Enable Room Charging"),
        default=False,
        help_text=_("Allow guests to charge orders to their room (for hotels)."),
    )
    # Menu customization
    menu_theme: str = models.CharField(
        _("Menu Theme"),
        max_length=20,
        choices=MenuTheme.choices,
        default=MenuTheme.MODERN,
        help_text=_("The visual theme for the customer-facing menu."),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Business")
        verbose_name_plural = _("Businesses")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_business_type_display()})"

    def get_location_label(self) -> str:
        """Returns the appropriate location label based on business type."""
        if self.business_type == self.BusinessType.RESTAURANT:
            return "Table"
        elif self.business_type == self.BusinessType.HOTEL:
            return "Room"
        else:
            return "Location"

    def get_customer_label(self) -> str:
        """Returns the appropriate customer label based on business type."""
        if self.business_type == self.BusinessType.HOTEL:
            return "Guest"
        else:
            return "Customer"

    def get_service_label(self) -> str:
        """Returns the appropriate service label based on business type."""
        if self.business_type == self.BusinessType.RESTAURANT:
            return "Dine-In"
        elif self.business_type == self.BusinessType.HOTEL:
            return "Room Service"
        else:
            return "Service"


class BusinessOwner(models.Model):
    """
    Links Django User accounts to businesses they own/manage.
    Supports multiple staff members per business with different roles.
    """

    class Role(models.TextChoices):
        OWNER = "OWNER", _("Owner")
        MANAGER = "MANAGER", _("Manager")
        STAFF = "STAFF", _("Staff")

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="business_ownerships",
        verbose_name=_("User"),
    )
    business = models.ForeignKey(
        Hotel,
        on_delete=models.CASCADE,
        related_name="owners",
        verbose_name=_("Business"),
    )
    role = models.CharField(
        _("Role"),
        max_length=20,
        choices=Role.choices,
        default=Role.OWNER,
        help_text=_("User's role in this business."),
    )
    is_primary = models.BooleanField(
        _("Is Primary Owner"),
        default=False,
        help_text=_("Only one primary owner per business. Has full access."),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        verbose_name = _("Business Owner")
        verbose_name_plural = _("Business Owners")
        unique_together = [["user", "business"]]
        ordering = ["-is_primary", "role", "created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.business.name} ({self.get_role_display()})"


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

    class SpiceLevel(models.TextChoices):
        NONE = "NONE", _("No Spice")
        MILD = "MILD", _("🌶️ Mild")
        MEDIUM = "MEDIUM", _("🌶️🌶️ Medium")
        HOT = "HOT", _("🌶️🌶️🌶️ Hot")
        EXTRA_HOT = "EXTRA_HOT", _("🌶️🌶️🌶️🌶️ Extra Hot")

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

    # New Enhancement Fields
    is_featured: bool = models.BooleanField(
        _("Featured Item"),
        default=False,
        help_text=_("Mark as featured/popular item (chef's recommendation)."),
    )
    is_daily_special: bool = models.BooleanField(
        _("Daily Special"),
        default=False,
        help_text=_("Mark as today's special offer."),
    )
    spice_level: str = models.CharField(
        _("Spice Level"),
        max_length=10,
        choices=SpiceLevel.choices,
        default=SpiceLevel.NONE,
        help_text=_("Spiciness level of the dish."),
    )
    allergens: str = models.TextField(
        _("Allergens"),
        blank=True,
        help_text=_("Common allergens (e.g., 'Nuts, Dairy, Shellfish')."),
    )
    prep_time_minutes: int = models.PositiveIntegerField(
        _("Prep Time (minutes)"),
        default=15,
        help_text=_("Estimated preparation time in minutes."),
    )
    popularity_score: int = models.IntegerField(
        _("Popularity Score"),
        default=0,
        help_text=_("Auto-incremented when ordered. Higher = more popular."),
    )
    customization_options: dict = models.JSONField(
        _("Customization Options"),
        blank=True,
        null=True,
        help_text=_("Add-ons, sizes, extras (JSON format)."),
    )
    nutritional_info: dict = models.JSONField(
        _("Nutritional Information"),
        blank=True,
        null=True,
        help_text=_("Calories, protein, carbs, etc. (JSON format)."),
    )

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Menu Item")
        verbose_name_plural = _("Menu Items")
        ordering = ["category", "name"]
        unique_together = [["category", "name"]]

    def __str__(self) -> str:
        return self.name

    def increment_popularity(self):
        """Increment popularity score when item is ordered."""
        self.popularity_score += 1
        self.save(update_fields=["popularity_score"])


class Table(models.Model):
    """
    Represents a table in a restaurant.
    Used for table management and QR code assignment.
    """

    class TableStatus(models.TextChoices):
        AVAILABLE = "AVAILABLE", _("Available")
        OCCUPIED = "OCCUPIED", _("Occupied")
        RESERVED = "RESERVED", _("Reserved")
        CLEANING = "CLEANING", _("Cleaning")

    hotel: Hotel = models.ForeignKey(
        Hotel,
        on_delete=models.CASCADE,
        related_name="tables",
        verbose_name=_("Business"),
    )
    table_number: str = models.CharField(
        _("Table Number"),
        max_length=50,
        help_text=_("Table identifier (e.g., '5', 'A1', 'Patio-3')."),
    )
    capacity: int = models.PositiveIntegerField(
        _("Capacity"),
        default=4,
        help_text=_("Maximum number of guests for this table."),
    )
    status: str = models.CharField(
        _("Status"),
        max_length=20,
        choices=TableStatus.choices,
        default=TableStatus.AVAILABLE,
    )
    qr_code = models.ImageField(
        _("QR Code"),
        upload_to="table_qr_codes/",
        blank=True,
        null=True,
        help_text=_("Generated QR code for this table."),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Table")
        verbose_name_plural = _("Tables")
        ordering = ["hotel", "table_number"]
        unique_together = [["hotel", "table_number"]]

    def __str__(self) -> str:
        return f"Table {self.table_number} at {self.hotel.name}"


class Order(models.Model):
    """
    Represents a customer's order for a specific business.
    """

    class OrderStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        ACCEPTED = "ACCEPTED", _("Accepted")
        PREPARING = "PREPARING", _("Preparing")
        READY = "READY", _("Ready")
        DELIVERED = "DELIVERED", _("Delivered")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", _("Cash")
        CARD = "CARD", _("Card")
        ROOM_CHARGE = "ROOM_CHARGE", _("Charge to Room")
        ONLINE = "ONLINE", _("Online Payment")

    # External-facing Order ID
    id: uuid.UUID = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    hotel: Hotel = models.ForeignKey(
        Hotel,
        on_delete=models.PROTECT,  # Protect orders from business deletion
        related_name="orders",
        verbose_name=_("Business"),
    )
    room_number: str = models.CharField(
        _("Location"),
        max_length=50,
        help_text=_("Room number, table number, or location identifier."),
    )
    table: Table = models.ForeignKey(
        Table,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name=_("Table"),
        help_text=_("Associated table (for restaurants)."),
    )
    status: str = models.CharField(
        _("Status"),
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    payment_method: str = models.CharField(
        _("Payment Method"),
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    payment_status: str = models.CharField(
        _("Payment Status"),
        max_length=20,
        choices=[
            ("PENDING", _("Pending")),
            ("PAID", _("Paid")),
            ("PARTIAL", _("Partially Paid")),
            ("REFUNDED", _("Refunded")),
        ],
        default="PENDING",
    )
    subtotal: Decimal = models.DecimalField(
        _("Subtotal"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Order subtotal before tax and tip."),
    )
    tax_amount: Decimal = models.DecimalField(
        _("Tax Amount"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tip_amount: Decimal = models.DecimalField(
        _("Tip Amount"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_price: Decimal = models.DecimalField(
        _("Total Price"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("The total price including tax and tip."),
    )
    special_requests: str = models.TextField(
        _("Special Requests"),
        blank=True,
        help_text=_("Customer's special requests or notes."),
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

    def calculate_totals(self):
        """Calculate and update order totals."""
        self.subtotal = sum(item.total_price for item in self.items.all())
        # Assuming 5% tax rate - should be configurable per business
        self.tax_amount = self.subtotal * Decimal("0.05")
        self.total_price = self.subtotal + self.tax_amount + self.tip_amount
        self.save()


class WaiterAlert(models.Model):
    """
    Represents a customer request for waiter assistance at a restaurant.
    """

    class AlertType(models.TextChoices):
        ASSISTANCE = "ASSISTANCE", _("General Assistance")
        BILL_REQUEST = "BILL_REQUEST", _("Bill Request")
        COMPLAINT = "COMPLAINT", _("Complaint")
        REFILL = "REFILL", _("Refill Request")

    class AlertStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        ACKNOWLEDGED = "ACKNOWLEDGED", _("Acknowledged")
        RESOLVED = "RESOLVED", _("Resolved")

    hotel: Hotel = models.ForeignKey(
        Hotel,
        on_delete=models.CASCADE,
        related_name="waiter_alerts",
        verbose_name=_("Business"),
    )
    table: Table = models.ForeignKey(
        Table,
        on_delete=models.CASCADE,
        related_name="waiter_alerts",
        verbose_name=_("Table"),
    )
    alert_type: str = models.CharField(
        _("Alert Type"),
        max_length=20,
        choices=AlertType.choices,
        default=AlertType.ASSISTANCE,
    )
    status: str = models.CharField(
        _("Status"),
        max_length=20,
        choices=AlertStatus.choices,
        default=AlertStatus.PENDING,
    )
    note: str = models.TextField(
        _("Note"),
        blank=True,
        help_text=_("Additional details from customer."),
    )
    acknowledged_at = models.DateTimeField(
        _("Acknowledged At"),
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(
        _("Resolved At"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Waiter Alert")
        verbose_name_plural = _("Waiter Alerts")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_alert_type_display()} - {self.table} ({self.get_status_display()})"


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
