import io
import json
import logging
import traceback
from decimal import Decimal

import qrcode
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files import File
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import BusinessOwner, Category, Hotel, MenuItem, Order, OrderItem, Table, WaiterAlert
from .ai_menu_extractor import extract_menu_from_image, validate_menu_data, estimate_extraction_confidence
from .csv_menu_importer import import_menu_from_csv, validate_csv_data, generate_csv_template

logger = logging.getLogger(__name__)


def get_current_business(request):
    """
    Get the current business for the logged-in user.
    Supports multi-business accounts with session-based switching.
    Returns (business, ownership) tuple or (None, None) if no business found.
    """
    try:
        logger.debug(f"get_current_business called for user: {request.user}")

        if not request.user.is_authenticated:
            logger.debug("User not authenticated")
            return None, None

        # Get all businesses this user owns/manages
        logger.debug("Fetching BusinessOwner records...")
        ownerships = BusinessOwner.objects.filter(user=request.user).select_related("business")
        ownership_count = ownerships.count()
        logger.debug(f"Found {ownership_count} BusinessOwner records for user {request.user.username}")

        if not ownerships.exists():
            logger.warning(f"No BusinessOwner records found for user {request.user.username}")
            return None, None

        # Check if user has selected a specific business
        selected_business_id = request.session.get("selected_business_id")
        logger.debug(f"Session selected_business_id: {selected_business_id}")

        if selected_business_id:
            # Try to get the selected business
            logger.debug(f"Looking for ownership with business_id={selected_business_id}")
            ownership = ownerships.filter(business_id=selected_business_id).first()
            if ownership:
                logger.debug(f"Found selected business: {ownership.business.name} (id={ownership.business.id})")
                return ownership.business, ownership
            else:
                logger.warning(f"Could not find business_id={selected_business_id} in user's ownerships")

        # Default to first business (or primary owner if exists)
        logger.debug("Looking for primary ownership or first ownership...")
        ownership = ownerships.filter(is_primary=True).first() or ownerships.first()

        # Store in session for next time
        if ownership:
            logger.debug(f"Using business: {ownership.business.name} (id={ownership.business.id})")
            request.session["selected_business_id"] = ownership.business.id
            return ownership.business, ownership

        logger.warning("No ownership found (should not happen if ownerships.exists() was True)")
        return None, None

    except Exception as e:
        logger.error(f"ERROR in get_current_business: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
        raise


def generate_qr_code_for_table(table, request):
    """
    Helper function to generate a QR code for a specific table.
    Embeds the business logo in the center if available.
    Returns True if successful, False otherwise.
    """
    try:
        # Get the site URL from request
        site_url = f"{request.scheme}://{request.get_host()}"

        # Generate QR code URL - this URL shows the menu dynamically
        qr_url = f"{site_url}/menu/{table.hotel.slug}/?location={table.table_number}"

        logger.info(f"Generating QR code for {table} with URL: {qr_url}")

        # Create QR code with high error correction (allows logo overlay)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction for logo
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.convert('RGB')  # Convert to RGB for logo overlay

        # Embed logo if available
        if table.hotel.logo:
            try:
                from PIL import Image, ImageDraw

                # Open logo
                logo = Image.open(table.hotel.logo)

                # Calculate logo size (20% of QR code size)
                qr_width, qr_height = img.size
                logo_size = int(qr_width * 0.2)

                # Resize logo maintaining aspect ratio
                logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)

                # Create white background for logo (better contrast)
                logo_bg_size = int(logo_size * 1.1)
                logo_bg = Image.new('RGB', (logo_bg_size, logo_bg_size), 'white')

                # Paste logo on white background
                logo_pos = ((logo_bg_size - logo.size[0]) // 2, (logo_bg_size - logo.size[1]) // 2)
                if logo.mode == 'RGBA':
                    logo_bg.paste(logo, logo_pos, logo)
                else:
                    logo_bg.paste(logo, logo_pos)

                # Calculate position to center logo on QR code
                pos = ((qr_width - logo_bg_size) // 2, (qr_height - logo_bg_size) // 2)

                # Paste logo background onto QR code
                img.paste(logo_bg, pos)

                logger.info(f"Successfully embedded logo for {table.hotel.name}")
            except Exception as logo_error:
                logger.warning(f"Could not embed logo for {table.hotel.name}: {str(logo_error)}")
                # Continue without logo if embedding fails

        # Save to BytesIO
        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)

        # Save to model
        filename = f"table_{table.table_number}_qr.png"
        table.qr_code.save(filename, File(img_io), save=True)

        logger.info(f"Successfully generated QR code for {table}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate QR code for {table}: {str(e)}")
        logger.error(traceback.format_exc())
        return False


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
    try:
        logger.info(f"Loading menu for slug: {slug}")
        hotel = get_object_or_404(Hotel, slug=slug, is_active=True)
        logger.info(f"Found hotel: {hotel.name} (id={hotel.id})")

        # Get location from query parameter (table number or room number)
        location = request.GET.get("location", "")
        logger.info(f"Location: {location}")

        # Prefetch related menu items for each category to avoid N+1 queries.
        categories = (
            Category.objects.filter(hotel=hotel)
            .prefetch_related("menu_items")
            .order_by("sort_order")
        )
        logger.info(f"Found {categories.count()} categories")

        # Get popular items for recommendations
        from .recommendation_engine import SimpleRecommendationEngine
        from datetime import timedelta
        from django.utils import timezone

        # Get trending items (ordered recently)
        seven_days_ago = timezone.now() - timedelta(days=7)
        trending_items = (
            MenuItem.objects.filter(
                category__hotel=hotel,
                is_available=True,
                order_items__order__created_at__gte=seven_days_ago,
            )
            .annotate(recent_orders=Count("order_items"))
            .filter(recent_orders__gte=2)
            .order_by("-recent_orders")[:5]
        )

        context = {
            "hotel": hotel,
            "categories": categories,
            "location": location,
            "trending_items": trending_items,
        }

        # Select template based on menu theme
        template_name = "core/menu_dark.html" if hotel.menu_theme == "DARK" else "core/menu.html"
        return render(request, template_name, context)

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"ERROR in hotel_menu view!")
        logger.error(f"Slug: {slug}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Full traceback:")
        logger.error(traceback.format_exc())
        logger.error("=" * 80)
        raise


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

            # Increment popularity score for analytics
            menu_item.increment_popularity()

            subtotal += menu_item.price * quantity

        # Calculate totals
        order.subtotal = subtotal
        order.tax_amount = subtotal * Decimal("0.05")
        order.total_price = order.subtotal + order.tax_amount
        order.save()

        # Build tracking URL
        tracking_url = f"{request.scheme}://{request.get_host()}/track-order/{order.id}/"

        return JsonResponse(
            {
                "success": True,
                "order_id": str(order.id),
                "total": float(order.total_price),
                "tracking_url": tracking_url,
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


@require_http_methods(["POST"])
@csrf_exempt
def update_order_status(request, order_id: str):
    """
    API endpoint to update order status (kitchen dashboard).
    """
    try:
        order = get_object_or_404(Order, id=order_id)
        data = json.loads(request.body)
        new_status = data.get("status")

        # Validate status
        valid_statuses = [choice[0] for choice in Order.OrderStatus.choices]
        if new_status not in valid_statuses:
            return JsonResponse({"error": "Invalid status"}, status=400)

        order.status = new_status
        order.save()

        return JsonResponse({"success": True, "status": new_status})

    except Exception as e:
        logger.error(f"Failed to update order status: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def acknowledge_waiter_alert(request, alert_id: int):
    """
    API endpoint to acknowledge a waiter alert (kitchen dashboard).
    """
    try:
        alert = get_object_or_404(WaiterAlert, id=alert_id)
        alert.status = WaiterAlert.AlertStatus.ACKNOWLEDGED
        alert.save()

        return JsonResponse({"success": True})

    except Exception as e:
        logger.error(f"Failed to acknowledge alert: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def poll_orders(request, slug: str):
    """
    API endpoint for polling new orders (kitchen dashboard real-time updates).
    Returns count of pending orders.
    """
    try:
        hotel = get_object_or_404(Hotel, slug=slug, is_active=True)

        pending_count = Order.objects.filter(
            hotel=hotel,
            status__in=[Order.OrderStatus.PENDING, Order.OrderStatus.ACCEPTED]
        ).count()

        return JsonResponse({
            "success": True,
            "pending_count": pending_count
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def check_order_status(request, order_id: str):
    """
    API endpoint for checking individual order status (customer tracking page).
    """
    try:
        order = get_object_or_404(Order, id=order_id)

        return JsonResponse({
            "success": True,
            "status": order.status,
            "status_display": order.get_status_display()
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def track_order(request, order_id: str):
    """
    Customer order tracking page - shows real-time order status.
    """
    order = get_object_or_404(Order, id=order_id)

    context = {
        "order": order,
        "hotel": order.hotel,
    }

    return render(request, "core/track_order.html", context)


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


@require_http_methods(["GET"])
def kitchen_orders_partial(request, slug: str):
    """
    HTMX endpoint - Returns just the orders section for kitchen dashboard.
    Used for auto-refreshing without full page reload.
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

    context = {
        "hotel": hotel,
        "orders": orders,
    }

    return render(request, "core/partials/kitchen_orders.html", context)


@require_http_methods(["GET"])
def kitchen_alerts_partial(request, slug: str):
    """
    HTMX endpoint - Returns just the waiter alerts section for kitchen dashboard.
    Used for auto-refreshing without full page reload.
    """
    hotel = get_object_or_404(Hotel, slug=slug, is_active=True)

    # Get pending waiter alerts
    waiter_alerts = []
    if hotel.enable_waiter_alerts:
        waiter_alerts = WaiterAlert.objects.filter(
            hotel=hotel, status=WaiterAlert.AlertStatus.PENDING
        ).select_related("table")[:20]

    context = {
        "hotel": hotel,
        "waiter_alerts": waiter_alerts,
    }

    return render(request, "core/partials/kitchen_alerts.html", context)


@require_http_methods(["GET"])
def order_status_partial(request, order_id: str):
    """
    HTMX endpoint - Returns just the order status section for tracking page.
    Used for auto-refreshing without full page reload.
    """
    order = get_object_or_404(Order, id=order_id)

    context = {
        "order": order,
        "hotel": order.hotel,
    }

    return render(request, "core/partials/order_status.html", context)


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
    business, ownership = get_current_business(request)

    if not business:
        messages.warning(request, "You don't have any businesses set up yet.")
        return redirect("core:signup")

    # Get all user's businesses for the switcher
    all_ownerships = BusinessOwner.objects.filter(user=request.user).select_related("business")

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
        "all_ownerships": all_ownerships,
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
    business, ownership = get_current_business(request)

    if not business:
        return redirect("core:signup")

    context = {
        "business": business,
        "ownership": ownership,
    }

    return render(request, "core/onboarding.html", context)


@login_required
def ai_menu_upload(request):
    """
    Upload a photo of existing menu for AI extraction.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    if request.method == "POST":
        menu_photo = request.FILES.get("menu_photo")

        if not menu_photo:
            messages.error(request, "Please upload a menu photo.")
            return redirect("core:ai_menu_upload")

        # Validate file type
        if not menu_photo.content_type.startswith("image/"):
            messages.error(request, "Please upload a valid image file (JPG, PNG, etc.)")
            return redirect("core:ai_menu_upload")

        try:
            # Extract menu data using AI Vision
            logger.info(f"Starting AI menu extraction for business: {business.name}")
            menu_data = extract_menu_from_image(menu_photo, business.business_type)

            if not menu_data:
                messages.error(request, "Failed to extract menu data. Please ensure the image is clear and try again.")
                return redirect("core:ai_menu_upload")

            # Validate extracted data
            if not validate_menu_data(menu_data):
                messages.error(request, "Extracted menu data is invalid. Please try again with a clearer photo.")
                return redirect("core:ai_menu_upload")

            # Calculate confidence
            confidence = estimate_extraction_confidence(menu_data)
            logger.info(f"Menu extraction confidence: {confidence:.2%}")

            # Store extracted data in session for preview
            request.session["extracted_menu_data"] = menu_data
            request.session["menu_extraction_confidence"] = confidence

            messages.success(request, f"Menu extracted successfully! Found {len(menu_data['categories'])} categories. Please review and confirm.")
            return redirect("core:ai_menu_preview")

        except Exception as e:
            logger.error(f"Error during AI menu extraction: {str(e)}")
            messages.error(request, f"An error occurred while processing your menu. Please try again.")
            return redirect("core:ai_menu_upload")

    context = {
        "business": business,
    }
    return render(request, "core/ai_menu_upload.html", context)


@login_required
def ai_menu_preview(request):
    """
    Preview and edit AI-extracted menu data before saving.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    # Get extracted menu data from session
    menu_data = request.session.get("extracted_menu_data")
    confidence = request.session.get("menu_extraction_confidence", 0.0)

    if not menu_data:
        messages.warning(request, "No menu data to preview. Please upload a menu photo first.")
        return redirect("core:ai_menu_upload")

    context = {
        "business": business,
        "menu_data": menu_data,
        "confidence": confidence,
        "confidence_percent": int(confidence * 100),
    }
    return render(request, "core/ai_menu_preview.html", context)


@login_required
def ai_menu_confirm(request):
    """
    Confirm and save AI-extracted menu data to database.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    if request.method != "POST":
        return redirect("core:ai_menu_preview")

    # Get extracted menu data from session
    menu_data = request.session.get("extracted_menu_data")

    if not menu_data:
        messages.error(request, "No menu data found. Please upload a menu photo first.")
        return redirect("core:ai_menu_upload")

    try:
        with transaction.atomic():
            categories_created = 0
            items_created = 0

            # Create categories and menu items
            for cat_data in menu_data.get("categories", []):
                # Create or get category
                category, created = Category.objects.get_or_create(
                    hotel=business,
                    name=cat_data["name"],
                    defaults={"sort_order": cat_data.get("sort_order", 0)}
                )

                if created:
                    categories_created += 1

                # Create menu items
                for item_data in cat_data.get("items", []):
                    # Check if item already exists
                    if MenuItem.objects.filter(category=category, name=item_data["name"]).exists():
                        logger.info(f"Skipping duplicate item: {item_data['name']}")
                        continue

                    MenuItem.objects.create(
                        category=category,
                        name=item_data["name"],
                        description=item_data.get("description", ""),
                        price=Decimal(str(item_data["price"])),
                        is_available=True,
                        is_vegetarian=item_data.get("is_vegetarian", False),
                        is_vegan=item_data.get("is_vegan", False),
                        is_gluten_free=item_data.get("is_gluten_free", False),
                        spice_level=item_data.get("spice_level", "NONE"),
                        allergens=item_data.get("allergens", ""),
                        prep_time_minutes=item_data.get("prep_time_minutes", 15),
                    )
                    items_created += 1

            # Clear session data
            del request.session["extracted_menu_data"]
            if "menu_extraction_confidence" in request.session:
                del request.session["menu_extraction_confidence"]

            messages.success(
                request,
                f"🎉 Menu imported successfully! Created {categories_created} categories and {items_created} items."
            )
            return redirect("core:menu_management")

    except Exception as e:
        logger.error(f"Error saving AI-extracted menu: {str(e)}")
        messages.error(request, f"An error occurred while saving your menu. Please try again.")
        return redirect("core:ai_menu_preview")


@login_required
def csv_menu_upload(request):
    """
    Upload CSV file for bulk menu import.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "Please upload a CSV file.")
            return redirect("core:csv_menu_upload")

        # Validate file size (max 5MB)
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, "File too large. Maximum size is 5MB.")
            return redirect("core:csv_menu_upload")

        try:
            # Import menu data from CSV
            logger.info(f"Starting CSV menu import for business: {business.name}")
            menu_data, errors = import_menu_from_csv(csv_file)

            if not menu_data:
                # Show all errors
                for error in errors:
                    messages.error(request, error)
                return redirect("core:csv_menu_upload")

            # Validate imported data
            if not validate_csv_data(menu_data):
                messages.error(request, "CSV data is invalid. Please check your file and try again.")
                return redirect("core:csv_menu_upload")

            # Store imported data in session for preview
            request.session["csv_menu_data"] = menu_data
            request.session["csv_import_errors"] = errors

            messages.success(
                request,
                f"CSV parsed successfully! Found {menu_data['stats']['total_items']} items in {menu_data['stats']['total_categories']} categories. Please review and confirm."
            )
            return redirect("core:csv_menu_preview")

        except Exception as e:
            logger.error(f"Error during CSV import: {str(e)}")
            messages.error(request, f"An error occurred while processing your CSV. Please try again.")
            return redirect("core:csv_menu_upload")

    context = {
        "business": business,
    }
    return render(request, "core/csv_menu_upload.html", context)


@login_required
def csv_menu_preview(request):
    """
    Preview CSV-imported menu data before saving.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    # Get imported menu data from session
    menu_data = request.session.get("csv_menu_data")
    errors = request.session.get("csv_import_errors", [])

    if not menu_data:
        messages.warning(request, "No menu data to preview. Please upload a CSV file first.")
        return redirect("core:csv_menu_upload")

    context = {
        "business": business,
        "menu_data": menu_data,
        "errors": errors,
    }
    return render(request, "core/csv_menu_preview.html", context)


@login_required
def csv_menu_confirm(request):
    """
    Confirm and save CSV-imported menu data to database.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    if request.method != "POST":
        return redirect("core:csv_menu_preview")

    # Get imported menu data from session
    menu_data = request.session.get("csv_menu_data")

    if not menu_data:
        messages.error(request, "No menu data found. Please upload a CSV file first.")
        return redirect("core:csv_menu_upload")

    try:
        with transaction.atomic():
            categories_created = 0
            items_created = 0

            # Create categories and menu items
            for category_name, items in menu_data.get("categories", {}).items():
                # Create or get category
                category, created = Category.objects.get_or_create(
                    hotel=business,
                    name=category_name,
                )

                if created:
                    categories_created += 1

                # Create menu items
                for item_data in items:
                    # Check if item already exists
                    if MenuItem.objects.filter(category=category, name=item_data["name"]).exists():
                        logger.info(f"Skipping duplicate item: {item_data['name']}")
                        continue

                    MenuItem.objects.create(
                        category=category,
                        name=item_data["name"],
                        description=item_data.get("description", ""),
                        price=Decimal(str(item_data["price"])),
                        is_available=item_data.get("is_available", True),
                        is_vegetarian=item_data.get("is_vegetarian", False),
                        is_vegan=item_data.get("is_vegan", False),
                        is_featured=item_data.get("is_featured", False),
                        is_daily_special=item_data.get("is_daily_special", False),
                        spice_level=item_data.get("spice_level", "NONE"),
                        allergens=item_data.get("allergens", ""),
                        prep_time_minutes=item_data.get("prep_time_minutes", 15),
                    )
                    items_created += 1

            # Clear session data
            del request.session["csv_menu_data"]
            if "csv_import_errors" in request.session:
                del request.session["csv_import_errors"]

            messages.success(
                request,
                f"🎉 Menu imported successfully! Created {categories_created} categories and {items_created} items."
            )
            return redirect("core:menu_management")

    except Exception as e:
        logger.error(f"Error saving CSV menu: {str(e)}")
        messages.error(request, f"An error occurred while saving your menu. Please try again.")
        return redirect("core:csv_menu_preview")


@login_required
def csv_template_download(request):
    """
    Download CSV template with example data.
    """
    # Generate CSV template
    template_content = generate_csv_template()

    # Create HTTP response with CSV content
    response = HttpResponse(template_content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="menu_import_template.csv"'

    return response


@login_required
def menu_management(request):
    """
    Menu management page - view all categories and menu items.
    """
    try:
        logger.info(f"menu_management called by user: {request.user.username} (id={request.user.id})")

        # Get current business
        logger.info("Calling get_current_business...")
        business, ownership = get_current_business(request)
        logger.info(f"get_current_business returned: business={business}, ownership={ownership}")

        if not business:
            logger.warning(f"No business found for user {request.user.username}")
            messages.warning(request, "Please create a business first.")
            return redirect("core:signup")

        logger.info(f"Working with business: {business.name} (id={business.id})")

        # Get all categories with their menu items
        logger.info("Fetching categories...")
        categories = Category.objects.filter(hotel=business).prefetch_related("menu_items").order_by("sort_order")
        logger.info(f"Found {categories.count()} categories")

        # Get all user's businesses for the switcher
        logger.info("Fetching all ownerships...")
        all_ownerships = BusinessOwner.objects.filter(user=request.user).select_related("business")
        logger.info(f"Found {all_ownerships.count()} ownerships")

        context = {
            "business": business,
            "ownership": ownership,
            "all_ownerships": all_ownerships,
            "categories": categories,
        }

        logger.info("Rendering template...")
        return render(request, "core/menu_management.html", context)

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"ERROR in menu_management view!")
        logger.error(f"User: {request.user.username} (id={request.user.id})")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Full traceback:")
        logger.error(traceback.format_exc())
        logger.error("=" * 80)

        # Re-raise to get Django's normal error handling
        raise


@login_required
def add_category(request):
    """
    Add a new category.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

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
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")
    categories = Category.objects.filter(hotel=business).order_by("sort_order")

    if request.method == "POST":
        category_id = request.POST.get("category")
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        price = request.POST.get("price")
        image = request.FILES.get("image")  # Handle image upload
        is_available = request.POST.get("is_available") == "on"
        is_vegetarian = request.POST.get("is_vegetarian") == "on"
        is_vegan = request.POST.get("is_vegan") == "on"
        is_gluten_free = request.POST.get("is_gluten_free") == "on"
        # New fields
        is_featured = request.POST.get("is_featured") == "on"
        is_daily_special = request.POST.get("is_daily_special") == "on"
        spice_level = request.POST.get("spice_level", "NONE")
        allergens = request.POST.get("allergens", "").strip()
        prep_time_minutes = request.POST.get("prep_time_minutes", 15)

        if category_id and name and price:
            try:
                category = Category.objects.get(id=category_id, hotel=business)
                MenuItem.objects.create(
                    category=category,
                    name=name,
                    description=description,
                    price=Decimal(price),
                    image=image,  # Save uploaded image
                    is_available=is_available,
                    is_vegetarian=is_vegetarian,
                    is_vegan=is_vegan,
                    is_gluten_free=is_gluten_free,
                    is_featured=is_featured,
                    is_daily_special=is_daily_special,
                    spice_level=spice_level,
                    allergens=allergens,
                    prep_time_minutes=int(prep_time_minutes) if prep_time_minutes else 15,
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
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")
    menu_item = get_object_or_404(MenuItem, id=item_id, category__hotel=business)

    if request.method == "POST":
        menu_item.name = request.POST.get("name", "").strip()
        menu_item.description = request.POST.get("description", "").strip()
        menu_item.price = Decimal(request.POST.get("price", "0"))

        # Handle image upload
        if "image" in request.FILES:
            menu_item.image = request.FILES["image"]

        menu_item.is_available = request.POST.get("is_available") == "on"
        menu_item.is_vegetarian = request.POST.get("is_vegetarian") == "on"
        menu_item.is_vegan = request.POST.get("is_vegan") == "on"
        menu_item.is_gluten_free = request.POST.get("is_gluten_free") == "on"
        # New fields
        menu_item.is_featured = request.POST.get("is_featured") == "on"
        menu_item.is_daily_special = request.POST.get("is_daily_special") == "on"
        menu_item.spice_level = request.POST.get("spice_level", "NONE")
        menu_item.allergens = request.POST.get("allergens", "").strip()
        prep_time = request.POST.get("prep_time_minutes", 15)
        menu_item.prep_time_minutes = int(prep_time) if prep_time else 15
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
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")
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
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    if not business.enable_table_management:
        messages.warning(request, "Table management is not enabled for your business type.")
        return redirect("core:dashboard")

    # Get all user's businesses for the switcher
    all_ownerships = BusinessOwner.objects.filter(user=request.user).select_related("business")

    tables = Table.objects.filter(hotel=business).order_by("table_number")

    # Count tables without QR codes
    tables_without_qr_count = tables.filter(qr_code='').count()

    context = {
        "business": business,
        "ownership": ownership,
        "all_ownerships": all_ownerships,
        "tables": tables,
        "tables_without_qr_count": tables_without_qr_count,
    }

    return render(request, "core/table_management.html", context)


def serve_qr_code(request, table_id):
    """
    Generate and serve QR code on-the-fly with embedded logo (no disk storage needed).
    Works perfectly on Render's ephemeral filesystem!
    """
    from django.http import HttpResponse

    try:
        # Get the table
        table = get_object_or_404(Table, id=table_id)

        # Get the site URL from request
        site_url = f"{request.scheme}://{request.get_host()}"

        # Generate QR code URL
        qr_url = f"{site_url}/menu/{table.hotel.slug}/?location={table.table_number}"

        logger.info(f"Generating dynamic QR code for {table} with URL: {qr_url}")

        # Create QR code with high error correction (allows logo overlay)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction for logo
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.convert('RGB')  # Convert to RGB for logo overlay

        # Embed logo if available
        if table.hotel.logo:
            try:
                from PIL import Image

                # Open logo
                logo = Image.open(table.hotel.logo)

                # Calculate logo size (20% of QR code size)
                qr_width, qr_height = img.size
                logo_size = int(qr_width * 0.2)

                # Resize logo maintaining aspect ratio
                logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)

                # Create white background for logo (better contrast)
                logo_bg_size = int(logo_size * 1.1)
                logo_bg = Image.new('RGB', (logo_bg_size, logo_bg_size), 'white')

                # Paste logo on white background
                logo_pos = ((logo_bg_size - logo.size[0]) // 2, (logo_bg_size - logo.size[1]) // 2)
                if logo.mode == 'RGBA':
                    logo_bg.paste(logo, logo_pos, logo)
                else:
                    logo_bg.paste(logo, logo_pos)

                # Calculate position to center logo on QR code
                pos = ((qr_width - logo_bg_size) // 2, (qr_height - logo_bg_size) // 2)

                # Paste logo background onto QR code
                img.paste(logo_bg, pos)

                logger.info(f"Successfully embedded logo for {table.hotel.name}")
            except Exception as logo_error:
                logger.warning(f"Could not embed logo for {table.hotel.name}: {str(logo_error)}")
                # Continue without logo if embedding fails

        # Save to BytesIO
        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)

        # Return as HTTP response (dynamically generated, no file storage!)
        return HttpResponse(img_io.getvalue(), content_type="image/png")

    except Exception as e:
        logger.error(f"Failed to serve QR code: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({"error": "QR code generation failed"}, status=500)


@login_required
def add_table(request):
    """
    Add a new table.
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    if request.method == "POST":
        table_number = request.POST.get("table_number", "").strip()
        capacity = request.POST.get("capacity", 4)

        if table_number:
            # Create the table
            table = Table.objects.create(
                hotel=business,
                table_number=table_number,
                capacity=capacity,
                status=Table.TableStatus.AVAILABLE,
            )

            # Auto-generate QR code for this table
            if generate_qr_code_for_table(table, request):
                messages.success(request, f"Table {table_number} created successfully with QR code!")
            else:
                messages.warning(request, f"Table {table_number} created, but QR code generation failed. You can generate it later.")

            return redirect("core:table_management")
        else:
            messages.error(request, "Table number is required.")

    context = {"business": business}
    return render(request, "core/add_table.html", context)


@login_required
def generate_all_qr_codes(request):
    """
    Generate QR codes for all tables that don't have one yet.
    Accessible via web button - no code required!
    """
    business, ownership = get_current_business(request)
    if not business:
        return redirect("core:signup")

    # Get all tables without QR codes
    tables = Table.objects.filter(hotel=business, qr_code='')

    if not tables.exists():
        messages.info(request, "All tables already have QR codes!")
        return redirect("core:table_management")

    # Generate QR codes for all tables
    generated_count = 0
    failed_count = 0

    for table in tables:
        if generate_qr_code_for_table(table, request):
            generated_count += 1
        else:
            failed_count += 1

    # Show success message
    if generated_count > 0:
        messages.success(request, f"Successfully generated {generated_count} QR code(s)!")

    if failed_count > 0:
        messages.warning(request, f"Failed to generate {failed_count} QR code(s). Please try again.")

    return redirect("core:table_management")


@login_required
def switch_business(request, business_id):
    """
    Switch to a different business owned by the user.
    """
    # Verify user owns this business
    ownership = BusinessOwner.objects.filter(
        user=request.user,
        business_id=business_id
    ).select_related("business").first()

    if ownership:
        request.session["selected_business_id"] = business_id
        messages.success(request, f"Switched to {ownership.business.name}")
    else:
        messages.error(request, "You don't have access to that business.")

    return redirect("core:dashboard")


@login_required
def add_business(request):
    """
    Add a new business to the user's account.
    """
    if request.method == "POST":
        business_name = request.POST.get("business_name", "").strip()
        business_type = request.POST.get("business_type", "RESTAURANT")

        if not business_name:
            messages.error(request, "Business name is required.")
            return render(request, "core/add_business.html")

        try:
            with transaction.atomic():
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
                    user=request.user,
                    business=business,
                    role=BusinessOwner.Role.OWNER,
                    is_primary=False,  # Not primary since they already have a business
                )

                # Switch to the new business
                request.session["selected_business_id"] = business.id

                messages.success(request, f"Business '{business_name}' created successfully!")
                return redirect("core:onboarding")

        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return render(request, "core/add_business.html")

    return render(request, "core/add_business.html")


# ============================================================================
# RECOMMENDATION ENGINE VIEWS
# ============================================================================


@require_http_methods(["GET"])
def get_item_recommendations(request, item_id):
    """
    API endpoint to get recommendations for a specific menu item.

    Returns:
        JSON response with recommended items
    """
    try:
        menu_item = get_object_or_404(MenuItem, id=item_id, is_available=True)
        hotel = menu_item.category.hotel

        from .recommendation_engine import SimpleRecommendationEngine

        engine = SimpleRecommendationEngine(hotel)
        recommendations = engine.get_recommendations(menu_item, limit=3)

        # Track impressions for these recommendations
        for rec in recommendations:
            engine.track_impression(
                source_item=menu_item, recommended_item=rec["item"]
            )

        # Format response
        rec_data = []
        for rec in recommendations:
            item = rec["item"]
            rec_data.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "price": str(item.price),
                    "image": item.image.url if item.image else None,
                    "reason": rec["reason"],
                    "confidence": rec["confidence"],
                }
            )

        return JsonResponse({"recommendations": rec_data})

    except Exception as e:
        logger.error(f"Error getting recommendations: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def track_recommendation_event(request):
    """
    API endpoint to track recommendation events (impressions, clicks, conversions).

    Expected POST data:
    {
        "event_type": "impression" | "click" | "conversion",
        "hotel_slug": "restaurant-slug",
        "source_item_id": 123,  # optional
        "recommended_item_id": 456,
        "revenue": "12.50"  # optional, for conversions
    }
    """
    try:
        data = json.loads(request.body)

        event_type = data.get("event_type")
        hotel_slug = data.get("hotel_slug")
        source_item_id = data.get("source_item_id")
        recommended_item_id = data.get("recommended_item_id")

        if not event_type or not recommended_item_id:
            return JsonResponse(
                {"error": "event_type and recommended_item_id are required"},
                status=400,
            )

        # Get hotel
        hotel = get_object_or_404(Hotel, slug=hotel_slug)

        # Get items
        source_item = None
        if source_item_id:
            source_item = get_object_or_404(MenuItem, id=source_item_id)

        recommended_item = get_object_or_404(MenuItem, id=recommended_item_id)

        # Import models
        from .models import RecommendationEvent

        # Create event
        event = RecommendationEvent.objects.create(
            hotel=hotel,
            source_item=source_item,
            recommended_item=recommended_item,
            event_type=event_type.upper(),
            revenue=Decimal(data.get("revenue", "0.00")),
        )

        logger.info(f"Tracked {event_type} event for {recommended_item.name}")

        return JsonResponse({"status": "success", "event_id": str(event.id)})

    except Exception as e:
        logger.error(f"Error tracking recommendation event: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def recommendation_dashboard(request):
    """
    Analytics dashboard showing recommendation performance and ROI.
    """
    try:
        business, ownership = get_current_business(request)

        if not business:
            messages.error(request, "No business found. Please complete onboarding first.")
            return redirect("core:onboarding")

        # Date range filter (default 30 days)
        days = int(request.GET.get("days", 30))

        from datetime import timedelta
        from django.utils import timezone
        from .recommendation_engine import RecommendationAnalytics
        from .models import RecommendationEvent, ItemPairFrequency

        start_date = timezone.now() - timedelta(days=days)

        # Get performance summary
        analytics = RecommendationAnalytics(business)
        performance = analytics.get_performance_summary(days)

        # Get top performing pairs
        top_pairs = analytics.get_top_performing_pairs(limit=10)

        # Get total revenue for comparison
        total_revenue = (
            Order.objects.filter(
                hotel=business,
                created_at__gte=start_date,
                status__in=[Order.OrderStatus.COMPLETED, Order.OrderStatus.DELIVERED],
            ).aggregate(total=Sum("total_price"))["total"]
            or Decimal("0.00")
        )

        # Calculate percentage
        rec_revenue_percentage = 0.0
        if total_revenue > 0:
            rec_revenue_percentage = (
                float(performance["total_revenue"]) / float(total_revenue) * 100
            )

        # Get daily trend data
        from django.db.models import Count as CountAgg, Sum as SumAgg

        daily_trends = []
        for i in range(days):
            date = (timezone.now() - timedelta(days=days - i)).date()
            day_revenue = (
                RecommendationEvent.objects.filter(
                    hotel=business,
                    created_at__date=date,
                    event_type=RecommendationEvent.EventType.CONVERSION,
                ).aggregate(revenue=SumAgg("revenue"))["revenue"]
                or Decimal("0.00")
            )
            daily_trends.append(
                {"date": date.strftime("%b %d"), "revenue": float(day_revenue)}
            )

        # Calculate estimated monthly impact
        daily_avg = performance["total_revenue"] / days if days > 0 else Decimal("0.00")
        monthly_estimate = daily_avg * 30

        context = {
            "business": business,
            "days": days,
            "total_rec_revenue": performance["total_revenue"],
            "rec_revenue_percentage": round(rec_revenue_percentage, 1),
            "total_revenue": total_revenue,
            "total_conversions": performance["total_conversions"],
            "total_impressions": performance["total_impressions"],
            "conversion_rate": performance["conversion_rate"],
            "top_pairs": top_pairs,
            "daily_trends": daily_trends,
            "monthly_estimate": monthly_estimate,
        }

        return render(request, "core/recommendation_dashboard.html", context)

    except Exception as e:
        logger.error(f"Error in recommendation dashboard: {str(e)}\n{traceback.format_exc()}")
        messages.error(request, f"Error loading dashboard: {str(e)}")
        return redirect("core:dashboard")