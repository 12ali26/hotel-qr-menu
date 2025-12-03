import json
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Category, Hotel, MenuItem, Order, OrderItem, Table, WaiterAlert


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