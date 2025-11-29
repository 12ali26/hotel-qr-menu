from django.shortcuts import get_object_or_404, render

from .models import Category, Hotel


def hotel_menu(request, slug: str):
    """
    Displays the public menu for a specific hotel.

    Args:
        request: The HTTP request object.
        slug: The unique slug of the hotel.

    Returns:
        A rendered HTML page of the hotel's menu.
    """
    hotel = get_object_or_404(Hotel, slug=slug, is_active=True)

    # Prefetch related menu items for each category to avoid N+1 queries.
    # We only fetch categories that have at least one available menu item.
    categories = (
        Category.objects.filter(hotel=hotel)
        .prefetch_related(
            "menu_items"
        )
        .order_by("sort_order")
    )

    context = {
        "hotel": hotel,
        "categories": categories,
    }
    return render(request, "core/menu.html", context)