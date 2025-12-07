# Smart Recommendation Engine - Technical Architecture

## Executive Summary

This document outlines the technical architecture for a data-driven recommendation system that creates a defensible competitive moat through:
- **Direct Revenue Impact**: Increase average order value by 15-35%
- **Data Moat**: Gets smarter with every order (competitors can't copy without data)
- **Proven ROI**: Clear analytics showing "You made $X extra this week"
- **Network Effects**: Better with more restaurants on the platform

---

## Phase 1: Foundation (Weeks 1-2)

### 1.1 New Database Models

#### RecommendationEvent (Core Tracking)
Tracks every recommendation shown and its outcome for learning.

```python
class RecommendationEvent(models.Model):
    """Tracks recommendation displays and conversions for algorithm learning."""

    class EventType(models.TextChoices):
        IMPRESSION = "IMPRESSION", _("Shown to customer")
        CLICK = "CLICK", _("Customer clicked/viewed")
        CONVERSION = "CONVERSION", _("Customer added to cart")

    class RecommendationType(models.TextChoices):
        FREQUENTLY_TOGETHER = "FREQUENTLY_TOGETHER", _("Bought Together")
        SIMILAR_ITEMS = "SIMILAR_ITEMS", _("Similar Items")
        CATEGORY_POPULAR = "CATEGORY_POPULAR", _("Popular in Category")
        TRENDING = "TRENDING", _("Trending Now")
        PERSONALIZED = "PERSONALIZED", _("For You")
        UPSELL = "UPSELL", _("Premium Upgrade")
        COMPLEMENT = "COMPLEMENT", _("Complete Your Meal")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='recommendation_events')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True)

    # What was recommended
    source_item = models.ForeignKey(
        MenuItem,
        on_delete=models.SET_NULL,
        null=True,
        related_name='recommendations_triggered',
        help_text="Item that triggered recommendation (e.g., user viewing pasta)"
    )
    recommended_item = models.ForeignKey(
        MenuItem,
        on_delete=models.SET_NULL,
        null=True,
        related_name='times_recommended',
        help_text="Item that was recommended"
    )

    recommendation_type = models.CharField(max_length=30, choices=RecommendationType.choices)
    event_type = models.CharField(max_length=20, choices=EventType.choices)

    # A/B Testing
    algorithm_version = models.CharField(
        max_length=20,
        default="v1",
        help_text="Which algorithm version generated this (for A/B testing)"
    )
    test_group = models.CharField(
        max_length=10,
        blank=True,
        help_text="A/B test group (A, B, control, etc.)"
    )

    # Context
    position = models.IntegerField(help_text="Position in recommendation list (1-5)")
    context = models.JSONField(
        default=dict,
        help_text="Additional context: time_of_day, cart_items, session_duration, etc."
    )

    # Revenue tracking
    revenue_generated = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Revenue if recommendation converted"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['hotel', '-created_at']),
            models.Index(fields=['recommendation_type', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
            models.Index(fields=['recommended_item', 'event_type']),
        ]
```

#### ItemPairFrequency (Collaborative Filtering Core)
Pre-computed "bought together" associations.

```python
class ItemPairFrequency(models.Model):
    """Tracks how often two items are ordered together."""

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='item_pairs')
    item_a = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='paired_with_a')
    item_b = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='paired_with_b')

    # Frequency metrics
    times_ordered_together = models.IntegerField(default=1)
    last_ordered_together = models.DateTimeField(auto_now=True)

    # Confidence metrics
    confidence_score = models.FloatField(
        default=0.0,
        help_text="P(B|A) - probability of B given A was ordered"
    )
    support = models.FloatField(
        default=0.0,
        help_text="Overall frequency in all orders"
    )
    lift = models.FloatField(
        default=1.0,
        help_text="How much more likely B is ordered when A is ordered (vs baseline)"
    )

    # Performance tracking
    times_recommended = models.IntegerField(default=0)
    times_clicked = models.IntegerField(default=0)
    times_converted = models.IntegerField(default=0)
    total_revenue_generated = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['hotel', 'item_a', 'item_b']]
        indexes = [
            models.Index(fields=['hotel', '-confidence_score']),
            models.Index(fields=['item_a', '-confidence_score']),
        ]

    @property
    def conversion_rate(self) -> float:
        """How often this recommendation converts."""
        if self.times_recommended == 0:
            return 0.0
        return (self.times_converted / self.times_recommended) * 100
```

#### RecommendationPerformance (Analytics Aggregation)
Daily/weekly performance summaries for dashboard.

```python
class RecommendationPerformance(models.Model):
    """Daily aggregated performance metrics for analytics dashboard."""

    class Period(models.TextChoices):
        DAILY = "DAILY", _("Daily")
        WEEKLY = "WEEKLY", _("Weekly")
        MONTHLY = "MONTHLY", _("Monthly")

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='recommendation_performance')
    period = models.CharField(max_length=10, choices=Period.choices, default=Period.DAILY)
    date = models.DateField(help_text="Start date of period")

    # Volume metrics
    total_impressions = models.IntegerField(default=0)
    total_clicks = models.IntegerField(default=0)
    total_conversions = models.IntegerField(default=0)

    # Revenue metrics
    revenue_from_recommendations = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total revenue from recommended items that were purchased"
    )
    baseline_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Revenue from non-recommended purchases for comparison"
    )

    # Calculated metrics
    click_through_rate = models.FloatField(default=0.0, help_text="CTR %")
    conversion_rate = models.FloatField(default=0.0, help_text="Conversion %")
    average_order_lift = models.FloatField(default=0.0, help_text="% increase in order value")

    # Top performers
    top_recommended_item = models.ForeignKey(
        MenuItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Most successful recommended item this period"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['hotel', 'period', 'date']]
        indexes = [
            models.Index(fields=['hotel', 'period', '-date']),
        ]
```

---

## Phase 2: Algorithms (Weeks 2-4)

### 2.1 Algorithm #1: Frequently Bought Together (Collaborative Filtering)

**Best for**: "Customers who ordered Margherita Pizza also ordered Garlic Bread"

#### Data Collection (Real-time on Order Creation)

```python
# In Order.save() or order creation signal
from core.recommendation_engine import RecommendationEngine

@receiver(post_save, sender=Order)
def update_item_associations(sender, instance, created, **kwargs):
    """When order is created, update item pair frequencies."""
    if created and instance.status == Order.OrderStatus.COMPLETED:
        engine = RecommendationEngine(instance.hotel)
        engine.update_item_pairs(instance)
```

#### Core Algorithm Logic

```python
# core/recommendation_engine.py

class RecommendationEngine:
    """Main recommendation engine with multiple algorithm strategies."""

    def __init__(self, hotel):
        self.hotel = hotel

    def update_item_pairs(self, order):
        """Update association rules when order completes."""
        items = list(order.items.values_list('menu_item_id', flat=True))

        # Generate all pairs (combinations)
        from itertools import combinations
        for item_a_id, item_b_id in combinations(items, 2):
            # Ensure consistent ordering (smaller ID first)
            if item_a_id > item_b_id:
                item_a_id, item_b_id = item_b_id, item_a_id

            pair, created = ItemPairFrequency.objects.get_or_create(
                hotel=self.hotel,
                item_a_id=item_a_id,
                item_b_id=item_b_id,
            )
            pair.times_ordered_together += 1
            pair.save()

        # Recalculate confidence scores (run async for performance)
        self.recalculate_confidence_scores.delay(self.hotel.id)

    @staticmethod
    @shared_task
    def recalculate_confidence_scores(hotel_id):
        """Batch update confidence/support/lift for all pairs."""
        hotel = Hotel.objects.get(id=hotel_id)
        total_orders = Order.objects.filter(hotel=hotel).count()

        for pair in ItemPairFrequency.objects.filter(hotel=hotel):
            # How many times was item_a ordered?
            item_a_orders = OrderItem.objects.filter(
                order__hotel=hotel,
                menu_item=pair.item_a
            ).values('order').distinct().count()

            # Confidence: P(B|A) = orders_with_both / orders_with_a
            if item_a_orders > 0:
                pair.confidence_score = pair.times_ordered_together / item_a_orders

            # Support: overall frequency
            pair.support = pair.times_ordered_together / total_orders if total_orders > 0 else 0

            # Lift: how much more likely vs random
            item_b_orders = OrderItem.objects.filter(
                order__hotel=hotel,
                menu_item=pair.item_b
            ).values('order').distinct().count()

            baseline_prob = item_b_orders / total_orders if total_orders > 0 else 0
            if baseline_prob > 0:
                pair.lift = pair.confidence_score / baseline_prob

            pair.save()

    def get_frequently_bought_together(self, item, limit=5):
        """Get top recommendations based on collaborative filtering."""
        # Get pairs where this item appears
        pairs = ItemPairFrequency.objects.filter(
            models.Q(item_a=item) | models.Q(item_b=item),
            hotel=self.hotel,
            confidence_score__gte=0.2,  # Minimum 20% confidence
            lift__gte=1.2,  # 20% lift over baseline
            times_ordered_together__gte=3  # Minimum 3 co-occurrences
        ).order_by('-confidence_score', '-times_ordered_together')[:limit]

        # Extract the "other" item from each pair
        recommendations = []
        for pair in pairs:
            other_item = pair.item_b if pair.item_a == item else pair.item_a
            recommendations.append({
                'item': other_item,
                'reason': f"Often ordered with {item.name}",
                'confidence': pair.confidence_score,
                'social_proof': f"{pair.times_ordered_together} customers ordered both"
            })

        return recommendations
```

---

### 2.2 Algorithm #2: Category-Based Popular Items

**Best for**: "Popular appetizers" when user is browsing appetizers

```python
def get_category_popular(self, category, exclude_items=None, limit=5):
    """Get most popular items in a category."""
    queryset = MenuItem.objects.filter(
        category=category,
        is_available=True
    ).exclude(
        id__in=exclude_items or []
    )

    # Weighted popularity (recent orders count more)
    from django.db.models import Count, Q, F
    from datetime import timedelta
    from django.utils import timezone

    thirty_days_ago = timezone.now() - timedelta(days=30)
    seven_days_ago = timezone.now() - timedelta(days=7)

    popular_items = queryset.annotate(
        recent_orders_7d=Count(
            'order_items',
            filter=Q(order_items__order__created_at__gte=seven_days_ago)
        ),
        recent_orders_30d=Count(
            'order_items',
            filter=Q(order_items__order__created_at__gte=thirty_days_ago)
        ),
        # Weighted score: 7-day orders * 3 + 30-day orders * 1 + all-time popularity
        popularity_weighted=F('recent_orders_7d') * 3 + F('recent_orders_30d') + F('popularity_score')
    ).order_by('-popularity_weighted')[:limit]

    return [{
        'item': item,
        'reason': f"Popular {category.name}",
        'orders_last_week': item.recent_orders_7d,
    } for item in popular_items]
```

---

### 2.3 Algorithm #3: Complement Your Meal (Rule-Based)

**Best for**: Smart upsells based on order composition

```python
def get_meal_complements(self, current_cart_items, limit=3):
    """Suggest items to complete the meal based on what's missing."""

    # Analyze current cart
    cart_categories = set(
        item.category.name.lower()
        for item in current_cart_items
    )

    recommendations = []

    # Rule 1: No drink? Suggest popular drinks
    if not any(cat in ['drinks', 'beverages'] for cat in cart_categories):
        drinks_category = Category.objects.filter(
            hotel=self.hotel,
            name__icontains='drink'
        ).first()

        if drinks_category:
            popular_drink = MenuItem.objects.filter(
                category=drinks_category,
                is_available=True
            ).order_by('-popularity_score').first()

            if popular_drink:
                recommendations.append({
                    'item': popular_drink,
                    'reason': "Complete your meal with a drink",
                    'type': 'complement'
                })

    # Rule 2: No dessert? Suggest if main course present
    if any(cat in ['main', 'entrees', 'pasta', 'pizza'] for cat in cart_categories):
        if not any(cat in ['dessert', 'sweets'] for cat in cart_categories):
            desserts = Category.objects.filter(
                hotel=self.hotel,
                name__icontains='dessert'
            ).first()

            if desserts:
                popular_dessert = MenuItem.objects.filter(
                    category=desserts,
                    is_available=True
                ).order_by('-popularity_score').first()

                if popular_dessert:
                    recommendations.append({
                        'item': popular_dessert,
                        'reason': "Save room for dessert!",
                        'type': 'complement'
                    })

    # Rule 3: No appetizer? Suggest if cart is small
    if len(current_cart_items) <= 2:
        if not any(cat in ['appetizer', 'starters', 'sides'] for cat in cart_categories):
            appetizers = Category.objects.filter(
                hotel=self.hotel,
                name__icontains='appetizer'
            ).first() or Category.objects.filter(
                hotel=self.hotel,
                name__icontains='starter'
            ).first()

            if appetizers:
                recommendations.append({
                    'item': MenuItem.objects.filter(
                        category=appetizers,
                        is_available=True,
                        price__lte=Decimal('15.00')  # Affordable upsell
                    ).order_by('-popularity_score').first(),
                    'reason': "Start with an appetizer",
                    'type': 'complement'
                })

    return recommendations[:limit]
```

---

### 2.4 Algorithm #4: Time-Based Trending

**Best for**: "Popular right now" during lunch rush

```python
def get_trending_now(self, limit=5):
    """Items that are trending in the last 2 hours."""
    from django.utils import timezone
    from datetime import timedelta

    two_hours_ago = timezone.now() - timedelta(hours=2)

    trending = MenuItem.objects.filter(
        category__hotel=self.hotel,
        is_available=True
    ).annotate(
        recent_orders=Count(
            'order_items',
            filter=Q(
                order_items__order__created_at__gte=two_hours_ago,
                order_items__order__status__in=[
                    Order.OrderStatus.ACCEPTED,
                    Order.OrderStatus.PREPARING,
                    Order.OrderStatus.READY,
                ]
            )
        )
    ).filter(
        recent_orders__gte=3  # At least 3 orders in last 2 hours
    ).order_by('-recent_orders')[:limit]

    return [{
        'item': item,
        'reason': "Trending right now",
        'orders_count': item.recent_orders,
        'badge': '🔥 Hot'
    } for item in trending]
```

---

## Phase 3: UI Integration (Week 4-5)

### 3.1 Recommendation Display Components

**Location 1: Menu Item Detail View**

```html
<!-- In menu.html when viewing item details -->
{% if frequently_bought_together %}
<div class="mt-6 border-t pt-4">
    <h3 class="text-lg font-semibold mb-3">Frequently Bought Together</h3>
    <div class="grid grid-cols-2 gap-3">
        {% for rec in frequently_bought_together %}
        <div class="border rounded-lg p-3 cursor-pointer hover:shadow-md transition"
             data-rec-type="frequently_together"
             data-rec-item="{{ rec.item.id }}"
             data-rec-source="{{ current_item.id }}"
             onclick="trackRecommendationClick(this); addToCart({{ rec.item.id }})">
            <img src="{{ rec.item.image.url }}" class="w-16 h-16 rounded object-cover mb-2">
            <p class="font-medium text-sm">{{ rec.item.name }}</p>
            <p class="text-xs text-gray-500">{{ rec.social_proof }}</p>
            <p class="font-bold text-green-600">+${{ rec.item.price }}</p>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}
```

**Location 2: Cart Page (Upsells)**

```html
<!-- In cart.html -->
{% if cart_recommendations %}
<div class="bg-yellow-50 rounded-lg p-4 mb-4">
    <h3 class="font-semibold mb-2">✨ Complete Your Order</h3>
    <div class="flex gap-3 overflow-x-auto">
        {% for rec in cart_recommendations %}
        <div class="min-w-[150px] bg-white rounded border p-3"
             data-rec-type="{{ rec.type }}"
             data-rec-item="{{ rec.item.id }}">
            <img src="{{ rec.item.image.url }}" class="w-full h-20 object-cover rounded mb-2">
            <p class="text-sm font-medium">{{ rec.item.name }}</p>
            <p class="text-xs text-gray-600">{{ rec.reason }}</p>
            <button onclick="addToCartFromRecommendation({{ rec.item.id }}, '{{ rec.type }}')"
                    class="mt-2 w-full bg-green-500 text-white text-xs py-1 rounded">
                Add ${{ rec.item.price }}
            </button>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}
```

**Location 3: "Trending Now" Banner**

```html
<!-- At top of menu.html -->
{% if trending_items %}
<div class="bg-gradient-to-r from-orange-500 to-red-500 text-white p-4 rounded-lg mb-4">
    <h3 class="font-bold mb-2">🔥 Trending Right Now</h3>
    <div class="flex gap-3 overflow-x-auto">
        {% for item in trending_items %}
        <div class="min-w-[120px] bg-white/20 backdrop-blur rounded p-2 cursor-pointer"
             onclick="viewItem({{ item.id }})">
            <img src="{{ item.image.url }}" class="w-20 h-20 rounded object-cover mx-auto mb-1">
            <p class="text-xs text-center font-medium">{{ item.name }}</p>
            <p class="text-xs text-center">{{ item.orders_count }} recent orders</p>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}
```

### 3.2 Tracking JavaScript

```javascript
// In menu.html <script> section

function trackRecommendationImpression(recType, itemId, sourceItem = null, position = 0) {
    fetch('/api/recommendations/track/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            event_type: 'impression',
            recommendation_type: recType,
            recommended_item_id: itemId,
            source_item_id: sourceItem,
            position: position,
            context: {
                time_of_day: new Date().getHours(),
                cart_size: getCartSize(),
                session_duration: getSessionDuration()
            }
        })
    });
}

function trackRecommendationClick(element) {
    const recType = element.dataset.recType;
    const itemId = element.dataset.recItem;
    const sourceItem = element.dataset.recSource;

    fetch('/api/recommendations/track/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            event_type: 'click',
            recommendation_type: recType,
            recommended_item_id: itemId,
            source_item_id: sourceItem
        })
    });
}

function addToCartFromRecommendation(itemId, recType) {
    // Track conversion
    fetch('/api/recommendations/track/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            event_type: 'conversion',
            recommendation_type: recType,
            recommended_item_id: itemId
        })
    });

    // Add to cart
    addToCart(itemId);
}

// Track impressions when recommendations are shown
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[data-rec-item]').forEach((el, index) => {
        trackRecommendationImpression(
            el.dataset.recType,
            el.dataset.recItem,
            el.dataset.recSource || null,
            index + 1
        );
    });
});
```

---

## Phase 4: Analytics Dashboard (Week 5-6)

### 4.1 Business Owner Dashboard View

```python
# core/views.py

@login_required
def recommendation_analytics(request):
    """Analytics dashboard showing recommendation performance and ROI."""
    hotel = get_user_hotel(request.user)

    # Date range filter
    from datetime import timedelta
    from django.utils import timezone

    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)

    # Aggregate performance
    performance = RecommendationPerformance.objects.filter(
        hotel=hotel,
        period=RecommendationPerformance.Period.DAILY,
        date__gte=start_date.date()
    ).aggregate(
        total_revenue=Sum('revenue_from_recommendations'),
        total_conversions=Sum('total_conversions'),
        total_impressions=Sum('total_impressions'),
        avg_conversion_rate=Avg('conversion_rate'),
        avg_order_lift=Avg('average_order_lift')
    )

    # Revenue comparison
    total_revenue_all = Order.objects.filter(
        hotel=hotel,
        created_at__gte=start_date,
        status__in=[Order.OrderStatus.COMPLETED, Order.OrderStatus.DELIVERED]
    ).aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')

    rec_revenue = performance['total_revenue'] or Decimal('0.00')
    rec_revenue_percentage = (rec_revenue / total_revenue_all * 100) if total_revenue_all > 0 else 0

    # Top performing recommendations
    top_recommendations = RecommendationEvent.objects.filter(
        hotel=hotel,
        created_at__gte=start_date,
        event_type=RecommendationEvent.EventType.CONVERSION
    ).values(
        'recommended_item__name',
        'recommended_item__id'
    ).annotate(
        conversions=Count('id'),
        revenue=Sum('revenue_generated')
    ).order_by('-revenue')[:10]

    # Daily trend data for chart
    daily_trends = RecommendationPerformance.objects.filter(
        hotel=hotel,
        period=RecommendationPerformance.Period.DAILY,
        date__gte=start_date.date()
    ).values('date').annotate(
        revenue=Sum('revenue_from_recommendations'),
        conversions=Sum('total_conversions')
    ).order_by('date')

    # Recommendation type breakdown
    type_breakdown = RecommendationEvent.objects.filter(
        hotel=hotel,
        created_at__gte=start_date,
        event_type=RecommendationEvent.EventType.CONVERSION
    ).values('recommendation_type').annotate(
        count=Count('id'),
        revenue=Sum('revenue_generated')
    ).order_by('-revenue')

    context = {
        'hotel': hotel,
        'days': days,
        'total_rec_revenue': rec_revenue,
        'rec_revenue_percentage': round(rec_revenue_percentage, 1),
        'total_conversions': performance['total_conversions'] or 0,
        'avg_conversion_rate': round(performance['avg_conversion_rate'] or 0, 2),
        'avg_order_lift': round(performance['avg_order_lift'] or 0, 1),
        'top_recommendations': top_recommendations,
        'daily_trends': list(daily_trends),
        'type_breakdown': list(type_breakdown),
    }

    return render(request, 'core/recommendation_analytics.html', context)
```

### 4.2 Dashboard Template

```html
<!-- core/templates/core/recommendation_analytics.html -->

{% extends "base.html" %}

{% block content %}
<div class="max-w-7xl mx-auto p-6">
    <h1 class="text-3xl font-bold mb-2">Recommendation Performance</h1>
    <p class="text-gray-600 mb-6">Last {{ days }} days</p>

    <!-- Key Metrics Cards -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <!-- Revenue Generated -->
        <div class="bg-gradient-to-br from-green-500 to-green-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-1">Revenue from Recommendations</div>
            <div class="text-4xl font-bold">${{ total_rec_revenue|floatformat:0 }}</div>
            <div class="text-sm mt-2">{{ rec_revenue_percentage }}% of total revenue</div>
        </div>

        <!-- Conversions -->
        <div class="bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-1">Items Added from Recommendations</div>
            <div class="text-4xl font-bold">{{ total_conversions }}</div>
            <div class="text-sm mt-2">{{ avg_conversion_rate }}% conversion rate</div>
        </div>

        <!-- Order Value Lift -->
        <div class="bg-gradient-to-br from-purple-500 to-purple-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-1">Average Order Lift</div>
            <div class="text-4xl font-bold">+{{ avg_order_lift }}%</div>
            <div class="text-sm mt-2">Higher than baseline</div>
        </div>

        <!-- Estimated Monthly Impact -->
        <div class="bg-gradient-to-br from-orange-500 to-orange-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-1">Estimated Monthly Impact</div>
            <div class="text-4xl font-bold">${{ total_rec_revenue|multiply:30|divide:days|floatformat:0 }}</div>
            <div class="text-sm mt-2">Based on current rate</div>
        </div>
    </div>

    <!-- Revenue Trend Chart -->
    <div class="bg-white rounded-lg shadow p-6 mb-8">
        <h2 class="text-xl font-bold mb-4">Daily Revenue from Recommendations</h2>
        <canvas id="revenueTrendChart" height="80"></canvas>
    </div>

    <!-- Two Column Layout -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- Top Performing Items -->
        <div class="bg-white rounded-lg shadow p-6">
            <h2 class="text-xl font-bold mb-4">Top Recommended Items</h2>
            <table class="w-full">
                <thead>
                    <tr class="border-b">
                        <th class="text-left py-2">Item</th>
                        <th class="text-right py-2">Conversions</th>
                        <th class="text-right py-2">Revenue</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in top_recommendations %}
                    <tr class="border-b">
                        <td class="py-2">{{ item.recommended_item__name }}</td>
                        <td class="text-right">{{ item.conversions }}</td>
                        <td class="text-right font-bold text-green-600">${{ item.revenue|floatformat:2 }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- Recommendation Type Breakdown -->
        <div class="bg-white rounded-lg shadow p-6">
            <h2 class="text-xl font-bold mb-4">Performance by Type</h2>
            <div class="space-y-3">
                {% for type in type_breakdown %}
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded">
                    <div>
                        <div class="font-medium">{{ type.recommendation_type|title|replace:'_',' ' }}</div>
                        <div class="text-sm text-gray-600">{{ type.count }} conversions</div>
                    </div>
                    <div class="text-right">
                        <div class="font-bold text-green-600">${{ type.revenue|floatformat:0 }}</div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// Revenue trend chart
const ctx = document.getElementById('revenueTrendChart').getContext('2d');
new Chart(ctx, {
    type: 'line',
    data: {
        labels: {{ daily_trends|map:'date'|list|safe }},
        datasets: [{
            label: 'Revenue from Recommendations',
            data: {{ daily_trends|map:'revenue'|list|safe }},
            borderColor: 'rgb(34, 197, 94)',
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            fill: true,
            tension: 0.4
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            }
        },
        scales: {
            y: {
                beginAtZero: true,
                ticks: {
                    callback: function(value) {
                        return '$' + value;
                    }
                }
            }
        }
    }
});
</script>
{% endblock %}
```

---

## Phase 5: A/B Testing Framework (Week 6)

### 5.1 A/B Test Configuration Model

```python
class RecommendationABTest(models.Model):
    """A/B test configuration for recommendation algorithms."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        RUNNING = "RUNNING", _("Running")
        PAUSED = "PAUSED", _("Paused")
        COMPLETED = "COMPLETED", _("Completed")

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='ab_tests')
    name = models.CharField(max_length=200, help_text="Test name (e.g., 'Confidence threshold test')")
    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Test configuration
    control_algorithm = models.CharField(max_length=50, default="v1")
    variant_algorithm = models.CharField(max_length=50, help_text="Algorithm variant to test")
    traffic_split = models.IntegerField(
        default=50,
        help_text="% of traffic to variant (0-100, remaining goes to control)"
    )

    # Duration
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()

    # Results (auto-calculated)
    control_conversions = models.IntegerField(default=0)
    variant_conversions = models.IntegerField(default=0)
    control_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    variant_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Winner
    winner = models.CharField(
        max_length=20,
        blank=True,
        choices=[('control', 'Control'), ('variant', 'Variant'), ('no_difference', 'No Significant Difference')]
    )
    statistical_significance = models.FloatField(
        default=0.0,
        help_text="P-value from statistical test"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 5.2 Traffic Assignment Logic

```python
# In RecommendationEngine class

def assign_test_group(self, session_id):
    """Assign user to A/B test group consistently."""
    import hashlib

    active_test = RecommendationABTest.objects.filter(
        hotel=self.hotel,
        status=RecommendationABTest.Status.RUNNING,
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    ).first()

    if not active_test:
        return 'control', 'v1'

    # Consistent hashing for user assignment
    hash_value = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
    assignment = hash_value % 100

    if assignment < active_test.traffic_split:
        return 'variant', active_test.variant_algorithm
    else:
        return 'control', active_test.control_algorithm
```

---

## Implementation Roadmap

### Week 1-2: Foundation
- [ ] Create new models (RecommendationEvent, ItemPairFrequency, RecommendationPerformance)
- [ ] Run migrations
- [ ] Set up Celery task for confidence score calculation
- [ ] Create RecommendationEngine class skeleton

### Week 3-4: Core Algorithms
- [ ] Implement "Frequently Bought Together" algorithm
- [ ] Implement "Category Popular" algorithm
- [ ] Implement "Complete Your Meal" algorithm
- [ ] Implement "Trending Now" algorithm
- [ ] Add signal handlers for order completion

### Week 4-5: UI Integration
- [ ] Add recommendation sections to menu.html
- [ ] Add recommendation sections to cart page
- [ ] Implement tracking JavaScript
- [ ] Create recommendation API endpoints
- [ ] Test recommendation display and tracking

### Week 5-6: Analytics
- [ ] Create analytics view and template
- [ ] Implement daily aggregation task
- [ ] Build Chart.js visualizations
- [ ] Add export functionality (CSV/PDF reports)

### Week 6+: Advanced Features
- [ ] A/B testing framework
- [ ] Personalized recommendations (user history)
- [ ] Email/SMS campaigns for returning customers
- [ ] Cross-restaurant recommendations (network effect)

---

## Success Metrics

### Technical Metrics
- **Click-Through Rate (CTR)**: Target 15-25%
- **Conversion Rate**: Target 8-15%
- **API Response Time**: < 200ms for recommendation generation

### Business Metrics
- **Order Value Lift**: Target 15-35% increase
- **Items per Order**: Target +0.5 to +1.5 items
- **Revenue from Recommendations**: Track $ and % of total
- **Customer Satisfaction**: No negative impact on ratings

---

## Technology Stack

- **Backend**: Django + PostgreSQL
- **Async Tasks**: Celery + Redis
- **ML Libraries**: scikit-learn (for advanced collaborative filtering later)
- **Frontend**: HTMX + Chart.js
- **Caching**: Redis (for frequently accessed recommendations)

---

## Cost Estimate

**Development**: 6 weeks @ $5k/week = $30k

**OR**

**DIY with this architecture**: ~150 hours of focused development

**Infrastructure**:
- Redis instance: $10-20/month
- Additional database storage: ~$5/month per 1000 restaurants
- Minimal compute overhead (existing Django server can handle it)

**ROI Example** (for 1 restaurant):
- Average 50 orders/day
- Average order value $25
- 20% order lift from recommendations = +$5/order
- Revenue impact: 50 × $5 × 30 days = **$7,500/month**
- Even at 5% commission = **$375/month per restaurant**

With 100 restaurants on platform = **$37,500/month recurring revenue**

---

## Competitive Moat Analysis

| Feature | Easy to Copy? | Data Moat? | Switching Cost? |
|---------|---------------|------------|-----------------|
| Basic QR menu | ✅ Very easy | ❌ No | ❌ None |
| Recommendations | ⚠️ Moderate (needs expertise) | ✅ Yes (6+ months data) | ✅ High (lose performance) |
| Analytics dashboard | ⚠️ Moderate | ✅ Yes (historical data) | ✅ High (lose insights) |
| A/B testing | ❌ Hard | ✅ Yes | ✅ Very high |

**Conclusion**: Recommendation engine creates a **6-12 month moat** that grows stronger over time.

---

## Next Steps

1. **Review this architecture** with technical team
2. **Validate assumptions** with 2-3 pilot restaurants
3. **Start with Phase 1** (foundation + simple collaborative filtering)
4. **Measure results** after 2 weeks with pilot restaurants
5. **Iterate** based on data before building advanced features

**Questions to address**:
- Should we start with collaborative filtering or rule-based recommendations first?
- What's the minimum order volume needed for meaningful recommendations?
- How do we handle cold start problem (new restaurants with no data)?

