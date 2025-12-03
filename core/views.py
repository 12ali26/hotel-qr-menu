import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import BusinessOwner, Category, Hotel, MenuItem, Order, OrderItem, Table, WaiterAlert


def landing_page(request):
    """
    Landing page for the platform.
    """
    return render(request, "core/landing.html")


def hotel_menu(request, slug: str):
    """
    Displays the public menu for a specific business (hotel/restaurant).

    Args:
        request: The HTTP request object.
        slug: The unique slug of the business.

    Returns:
        A rendered HTML page of the business menu.
    """
    hotel = get_object_or_404(Hotel, slug=slug, is_active=True)

    # Get location from query parameter (table number or room number)
    location = request.GET.get("location", "")

    # Prefetch related menu items for each category to avoid N+1 queries.
    categories = (
        Category.objects.filter(hotel=hotel)
        .prefetch_related("menu_items")
        .order_by("sort_order")
    )

    context = {
        "hotel": hotel,
        "categories": categories,
        "location": location,
    }
    return render(request, "core/menu.html", context)


@require_http_methods(["POST"])
@csrf_exempt  # Remove this in production and implement proper CSRF protection
def place_order(request, slug: str):
    """
    API endpoint to place an order.
    """
    try:
        hotel = get_object_or_404(Hotel, slug=slug, is_active=True)
        data = json.loads(request.body)

        location = data.get("location", "")
        items_data = data.get("items", [])
        special_requests = data.get("special_requests", "")
        payment_method = data.get("payment_method", "CARD")

        if not location:
            return JsonResponse({"error": "Location is required"}, status=400)

        if not items_data:
            return JsonResponse({"error": "No items in order"}, status=400)

        # Find associated table if it exists
        table = None
        if hotel.enable_table_management:
            try:
                table = Table.objects.get(hotel=hotel, table_number=location)
                table.status = Table.TableStatus.OCCUPIED
                table.save()
            except Table.DoesNotExist:
                pass

        # Create order
        order = Order.objects.create(
            hotel=hotel,
            room_number=location,
            table=table,
            special_requests=special_requests,
            payment_method=payment_method,
            status=Order.OrderStatus.PENDING,
        )

        # Add order items
        subtotal = Decimal("0.00")
        for item_data in items_data:
            menu_item = get_object_or_404(MenuItem, id=item_data["id"])
            quantity = int(item_data["quantity"])

            OrderItem.objects.create(
                order=order,
                menu_item=menu_item,
                quantity=quantity,
                price_at_order=menu_item.price,
            )

            subtotal += menu_item.price * quantity

        # Calculate totals
        order.subtotal = subtotal
        order.tax_amount = subtotal * Decimal("0.05")
        order.total_price = order.subtotal + order.tax_amount
        order.save()

        return JsonResponse(
            {
                "success": True,
                "order_id": str(order.id),
                "total": float(order.total_price),
            }
        )

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt  # Remove this in production
def create_waiter_alert(request, slug: str):
    """
    API endpoint to create a waiter alert (restaurant feature).
    """
    try:
        hotel = get_object_or_404(Hotel, slug=slug, is_active=True)

        if not hotel.enable_waiter_alerts:
            return JsonResponse(
                {"error": "Waiter alerts not enabled for this business"}, status=400
            )

        data = json.loads(request.body)
        location = data.get("location", "")

        if not location:
            return JsonResponse({"error": "Location is required"}, status=400)

        # Find the table
        try:
            table = Table.objects.get(hotel=hotel, table_number=location)
        except Table.DoesNotExist:
            return JsonResponse({"error": "Table not found"}, status=404)

        # Create waiter alert
        alert = WaiterAlert.objects.create(
            hotel=hotel,
            table=table,
            alert_type=WaiterAlert.AlertType.ASSISTANCE,
            status=WaiterAlert.AlertStatus.PENDING,
        )

        return JsonResponse({"success": True, "alert_id": alert.id})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def kitchen_dashboard(request, slug: str):
    """
    Kitchen dashboard for viewing and managing orders.
    """
    hotel = get_object_or_404(Hotel, slug=slug, is_active=True)

    # Get recent orders
    orders = (
        Order.objects.filter(hotel=hotel)
        .exclude(status=Order.OrderStatus.COMPLETED)
        .exclude(status=Order.OrderStatus.CANCELLED)
        .prefetch_related("items__menu_item")
        .order_by("-created_at")[:50]
    )

    # Get pending waiter alerts
    waiter_alerts = []
    if hotel.enable_waiter_alerts:
        waiter_alerts = WaiterAlert.objects.filter(
            hotel=hotel, status=WaiterAlert.AlertStatus.PENDING
        ).select_related("table")[:20]

    context = {
        "hotel": hotel,
        "orders": orders,
        "waiter_alerts": waiter_alerts,
    }

    return render(request, "core/kitchen_dashboard.html", context)


def download_qr_codes(request, slug: str):
    """
    View to download all QR codes for a business.
    Returns an HTML page with all QR codes for easy printing.
    """
    hotel = get_object_or_404(Hotel, slug=slug)

    # Get all tables with QR codes
    tables = Table.objects.filter(hotel=hotel).exclude(qr_code='').order_by('table_number')

    context = {
        "hotel": hotel,
        "tables": tables,
    }

    return render(request, "core/download_qr_codes.html", context)


def signup_view(request):
    """
    Business owner signup form.
    Creates a user account and their first business in one step.
    """
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        # Get form data
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password")
        password_confirm = request.POST.get("password_confirm")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        business_name = request.POST.get("business_name", "").strip()
        business_type = request.POST.get("business_type", "RESTAURANT")
        phone = request.POST.get("phone", "").strip()

        # Validation
        errors = []
        if not email or not password or not business_name:
            errors.append("Email, password, and business name are required.")
        if password != password_confirm:
            errors.append("Passwords do not match.")
        if User.objects.filter(username=email).exists():
            errors.append("An account with this email already exists.")
        if User.objects.filter(email=email).exists():
            errors.append("An account with this email already exists.")

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, "core/signup.html", {"post_data": request.POST})

        # Create user and business in a transaction
        try:
            with transaction.atomic():
                # Create user
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )

                # Create business
                base_slug = slugify(business_name)
                slug = base_slug
                counter = 1
                while Hotel.objects.filter(slug=slug).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                business = Hotel.objects.create(
                    name=business_name,
                    business_type=business_type,
                    slug=slug,
                    currency_code="QAR",
                    timezone="Asia/Qatar",
                    is_active=True,
                    enable_table_management=(business_type in ["RESTAURANT", "CAFE"]),
                    enable_waiter_alerts=(business_type in ["RESTAURANT", "CAFE"]),
                    enable_room_charging=(business_type == "HOTEL"),
                )

                # Link user to business
                BusinessOwner.objects.create(
                    user=user,
                    business=business,
                    role=BusinessOwner.Role.OWNER,
                    is_primary=True,
                )

                # Log the user in
                login(request, user)
                messages.success(
                    request,
                    f"Welcome! Your account has been created. Let's set up your menu.",
                )
                return redirect("core:onboarding")

        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return render(request, "core/signup.html", {"post_data": request.POST})

    return render(request, "core/signup.html")


def login_view(request):
    """
    Business owner login form.
    """
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password")

        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect("core:dashboard")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "core/login.html")


def logout_view(request):
    """
    Log out the current user.
    """
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("core:landing")


@login_required
def dashboard(request):
    """
    Business owner dashboard.
    Shows overview of their business, orders, and quick actions.
    """
    # Get user's businesses
    ownerships = BusinessOwner.objects.filter(user=request.user).select_related("business")

    if not ownerships.exists():
        messages.warning(request, "You don't have any businesses set up yet.")
        return redirect("core:signup")

    # For now, use the first business (later we can add business switcher)
    ownership = ownerships.first()
    business = ownership.business

    # Get recent orders
    recent_orders = Order.objects.filter(hotel=business).order_by("-created_at")[:10]

    # Get stats
    total_orders = Order.objects.filter(hotel=business).count()
    pending_orders = Order.objects.filter(
        hotel=business, status=Order.OrderStatus.PENDING
    ).count()

    context = {
        "business": business,
        "ownership": ownership,
        "recent_orders": recent_orders,
        "total_orders": total_orders,
        "pending_orders": pending_orders,
    }

    return render(request, "core/dashboard.html", context)


@login_required
def onboarding(request):
    """
    Onboarding wizard for new business owners.
    Guides them through menu setup and QR code generation.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business

    context = {
        "business": business,
        "ownership": ownership,
    }

    return render(request, "core/onboarding.html", context)


@login_required
def menu_management(request):
    """
    Menu management page - view all categories and menu items.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business

    # Get all categories with their menu items
    categories = Category.objects.filter(hotel=business).prefetch_related("menuitem_set").order_by("sort_order")

    context = {
        "business": business,
        "ownership": ownership,
        "categories": categories,
    }

    return render(request, "core/menu_management.html", context)


@login_required
def add_category(request):
    """
    Add a new category.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        sort_order = request.POST.get("sort_order", 0)

        if name:
            Category.objects.create(
                hotel=business,
                name=name,
                sort_order=sort_order or 0,
            )
            messages.success(request, f"Category '{name}' created successfully!")
            return redirect("core:menu_management")
        else:
            messages.error(request, "Category name is required.")

    return render(request, "core/add_category.html", {"business": business})


@login_required
def add_menu_item(request, category_id=None):
    """
    Add a new menu item.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business
    categories = Category.objects.filter(hotel=business).order_by("sort_order")

    if request.method == "POST":
        category_id = request.POST.get("category")
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        price = request.POST.get("price")
        is_available = request.POST.get("is_available") == "on"
        is_vegetarian = request.POST.get("is_vegetarian") == "on"
        is_vegan = request.POST.get("is_vegan") == "on"
        is_gluten_free = request.POST.get("is_gluten_free") == "on"

        if category_id and name and price:
            try:
                category = Category.objects.get(id=category_id, hotel=business)
                MenuItem.objects.create(
                    category=category,
                    name=name,
                    description=description,
                    price=Decimal(price),
                    is_available=is_available,
                    is_vegetarian=is_vegetarian,
                    is_vegan=is_vegan,
                    is_gluten_free=is_gluten_free,
                )
                messages.success(request, f"Menu item '{name}' added successfully!")
                return redirect("core:menu_management")
            except (Category.DoesNotExist, ValueError) as e:
                messages.error(request, f"Error adding menu item: {str(e)}")
        else:
            messages.error(request, "Category, name, and price are required.")

    selected_category = None
    if category_id:
        selected_category = categories.filter(id=category_id).first()

    context = {
        "business": business,
        "categories": categories,
        "selected_category": selected_category,
    }

    return render(request, "core/add_menu_item.html", context)


@login_required
def edit_menu_item(request, item_id):
    """
    Edit an existing menu item.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business
    menu_item = get_object_or_404(MenuItem, id=item_id, category__hotel=business)

    if request.method == "POST":
        menu_item.name = request.POST.get("name", "").strip()
        menu_item.description = request.POST.get("description", "").strip()
        menu_item.price = Decimal(request.POST.get("price", "0"))
        menu_item.is_available = request.POST.get("is_available") == "on"
        menu_item.is_vegetarian = request.POST.get("is_vegetarian") == "on"
        menu_item.is_vegan = request.POST.get("is_vegan") == "on"
        menu_item.is_gluten_free = request.POST.get("is_gluten_free") == "on"
        menu_item.save()

        messages.success(request, f"Menu item '{menu_item.name}' updated successfully!")
        return redirect("core:menu_management")

    context = {
        "business": business,
        "menu_item": menu_item,
    }

    return render(request, "core/edit_menu_item.html", context)


@login_required
def delete_menu_item(request, item_id):
    """
    Delete a menu item.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business
    menu_item = get_object_or_404(MenuItem, id=item_id, category__hotel=business)

    if request.method == "POST":
        name = menu_item.name
        menu_item.delete()
        messages.success(request, f"Menu item '{name}' deleted successfully!")
        return redirect("core:menu_management")

    context = {
        "business": business,
        "menu_item": menu_item,
    }

    return render(request, "core/delete_menu_item.html", context)


@login_required
def table_management(request):
    """
    Table management page - view all tables.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business

    if not business.enable_table_management:
        messages.warning(request, "Table management is not enabled for your business type.")
        return redirect("core:dashboard")

    tables = Table.objects.filter(hotel=business).order_by("table_number")

    context = {
        "business": business,
        "ownership": ownership,
        "tables": tables,
    }

    return render(request, "core/table_management.html", context)


@login_required
def add_table(request):
    """
    Add a new table.
    """
    ownership = BusinessOwner.objects.filter(user=request.user).first()
    if not ownership:
        return redirect("core:signup")

    business = ownership.business

    if request.method == "POST":
        table_number = request.POST.get("table_number", "").strip()
        capacity = request.POST.get("capacity", 4)

        if table_number:
            Table.objects.create(
                hotel=business,
                table_number=table_number,
                capacity=capacity,
                status=Table.TableStatus.AVAILABLE,
            )
            messages.success(request, f"Table {table_number} created successfully!")
            return redirect("core:table_management")
        else:
            messages.error(request, "Table number is required.")

    context = {"business": business}
    return render(request, "core/add_table.html", context)