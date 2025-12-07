# Recommendation Engine MVP - Quick Start Guide

## Goal: Ship Revenue-Generating Recommendations in 2 Weeks

This guide focuses on the **minimum viable product** that delivers immediate value:
- ✅ "Frequently Bought Together" recommendations
- ✅ Basic conversion tracking
- ✅ Simple ROI dashboard showing "You made $X this week"

Skip: Complex ML, A/B testing, personalization (add later when you have data)

---

## Week 1: Foundation & Data Collection

### Day 1-2: Database Models

Add these three models to `core/models.py`:

#### 1. ItemPairFrequency (Core Data)

```python
class ItemPairFrequency(models.Model):
    """Tracks items ordered together."""
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='item_pairs')
    item_a = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='paired_with_a')
    item_b = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='paired_with_b')

    times_together = models.IntegerField(default=1)
    confidence = models.FloatField(default=0.0)  # P(B|A)

    times_recommended = models.IntegerField(default=0)
    times_converted = models.IntegerField(default=0)
    revenue_generated = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['hotel', 'item_a', 'item_b']]
        indexes = [models.Index(fields=['hotel', '-confidence'])]
```

#### 2. RecommendationEvent (Tracking)

```python
class RecommendationEvent(models.Model):
    """Track recommendation shown → clicked → purchased."""

    IMPRESSION = 'IMPRESSION'
    CLICK = 'CLICK'
    CONVERSION = 'CONVERSION'

    EVENT_CHOICES = [
        (IMPRESSION, 'Shown'),
        (CLICK, 'Clicked'),
        (CONVERSION, 'Purchased'),
    ]

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)

    source_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, related_name='triggered_recs')
    recommended_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, related_name='was_recommended')

    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    revenue = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=['hotel', '-created_at'])]
```

**Run migration:**
```bash
python manage.py makemigrations
python manage.py migrate
```

---

### Day 3-4: Simple Recommendation Engine

Create `core/recommendation_engine.py`:

```python
from django.db.models import Q, F
from decimal import Decimal
from .models import ItemPairFrequency, MenuItem, Order, OrderItem, RecommendationEvent

class SimpleRecommendationEngine:
    """MVP recommendation engine - just collaborative filtering."""

    def __init__(self, hotel):
        self.hotel = hotel

    def update_pairs_from_order(self, order):
        """
        When order completes, record all item pairs.
        Call this from Order save or signal.
        """
        if order.status != Order.OrderStatus.COMPLETED:
            return

        item_ids = list(order.items.values_list('menu_item_id', flat=True))

        # Generate all pairs
        from itertools import combinations
        for item_a_id, item_b_id in combinations(item_ids, 2):
            # Keep consistent ordering (smaller ID first)
            if item_a_id > item_b_id:
                item_a_id, item_b_id = item_b_id, item_a_id

            pair, created = ItemPairFrequency.objects.get_or_create(
                hotel=self.hotel,
                item_a_id=item_a_id,
                item_b_id=item_b_id,
            )
            pair.times_together += 1
            pair.save()

        # Update confidence scores (run in background for production)
        self._update_confidence_scores()

    def _update_confidence_scores(self):
        """Calculate P(B|A) for all pairs."""
        from django.db.models import Count

        for pair in ItemPairFrequency.objects.filter(hotel=self.hotel):
            # How many orders contained item_a?
            item_a_count = OrderItem.objects.filter(
                order__hotel=self.hotel,
                menu_item=pair.item_a
            ).values('order').distinct().count()

            if item_a_count > 0:
                pair.confidence = pair.times_together / item_a_count
                pair.save(update_fields=['confidence'])

    def get_recommendations(self, item, limit=3):
        """
        Get top N items frequently bought with this item.
        Returns list of MenuItem objects.
        """
        pairs = ItemPairFrequency.objects.filter(
            Q(item_a=item) | Q(item_b=item),
            hotel=self.hotel,
            confidence__gte=0.15,  # At least 15% confidence
            times_together__gte=2  # At least 2 co-occurrences
        ).select_related('item_a', 'item_b').order_by('-confidence', '-times_together')[:limit]

        recommendations = []
        for pair in pairs:
            # Get the "other" item
            other_item = pair.item_b if pair.item_a == item else pair.item_a

            # Make sure it's available
            if other_item.is_available:
                recommendations.append({
                    'item': other_item,
                    'reason': f"{pair.times_together} customers bought both",
                    'pair': pair  # For tracking later
                })

        return recommendations

    def track_impression(self, source_item, recommended_item):
        """Track when recommendation is shown to customer."""
        RecommendationEvent.objects.create(
            hotel=self.hotel,
            source_item=source_item,
            recommended_item=recommended_item,
            event_type=RecommendationEvent.IMPRESSION
        )

    def track_conversion(self, recommended_item, order):
        """Track when recommended item is purchased."""
        # Get item price from order
        order_item = order.items.filter(menu_item=recommended_item).first()
        if not order_item:
            return

        revenue = order_item.total_price

        # Record conversion event
        RecommendationEvent.objects.create(
            hotel=self.hotel,
            order=order,
            recommended_item=recommended_item,
            event_type=RecommendationEvent.CONVERSION,
            revenue=revenue
        )

        # Update pair performance (if this was from a pair)
        # Note: In production, you'd track which pair triggered this via session
        # For MVP, we'll update all pairs containing this item
        pairs = ItemPairFrequency.objects.filter(
            Q(item_a=recommended_item) | Q(item_b=recommended_item),
            hotel=self.hotel
        )
        for pair in pairs:
            pair.times_converted += 1
            pair.revenue_generated += revenue
            pair.save(update_fields=['times_converted', 'revenue_generated'])
```

---

### Day 5: Hook into Order Flow

Add signal to update pairs when order completes:

```python
# In core/signals.py (create if doesn't exist)

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Order
from .recommendation_engine import SimpleRecommendationEngine

@receiver(post_save, sender=Order)
def update_recommendations_on_order(sender, instance, created, **kwargs):
    """Update item pair frequencies when order completes."""
    if instance.status == Order.OrderStatus.COMPLETED:
        engine = SimpleRecommendationEngine(instance.hotel)
        engine.update_pairs_from_order(instance)
```

Register signals in `core/apps.py`:

```python
class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        import core.signals  # Register signals
```

---

## Week 2: UI & Analytics

### Day 6-7: Display Recommendations

Update menu item detail view in `core/views.py`:

```python
def menu_item_detail(request, hotel_slug, item_id):
    """Show item details with recommendations."""
    hotel = get_object_or_404(Hotel, slug=hotel_slug)
    item = get_object_or_404(MenuItem, id=item_id, category__hotel=hotel)

    # Get recommendations
    from .recommendation_engine import SimpleRecommendationEngine
    engine = SimpleRecommendationEngine(hotel)
    recommendations = engine.get_recommendations(item, limit=3)

    # Track impressions
    for rec in recommendations:
        engine.track_impression(item, rec['item'])

    context = {
        'hotel': hotel,
        'item': item,
        'recommendations': recommendations,
    }
    return render(request, 'core/menu_item_detail.html', context)
```

Add to template `core/templates/core/menu.html` (in item detail section):

```html
{% if recommendations %}
<div class="mt-6 border-t pt-4">
    <h3 class="text-lg font-semibold mb-3">Frequently Bought Together</h3>
    <div class="space-y-3">
        {% for rec in recommendations %}
        <div class="flex items-center gap-3 p-3 border rounded-lg hover:bg-gray-50 cursor-pointer"
             onclick="addRecommendedItem({{ rec.item.id }}, '{{ rec.item.name }}', {{ rec.item.price }})">
            {% if rec.item.image %}
            <img src="{{ rec.item.image.url }}" class="w-16 h-16 rounded object-cover">
            {% endif %}
            <div class="flex-1">
                <p class="font-medium">{{ rec.item.name }}</p>
                <p class="text-xs text-gray-600">{{ rec.reason }}</p>
            </div>
            <div class="text-right">
                <p class="font-bold text-green-600">+${{ rec.item.price }}</p>
                <button class="mt-1 px-3 py-1 bg-green-500 text-white text-xs rounded">
                    Add
                </button>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}

<script>
function addRecommendedItem(itemId, itemName, price) {
    // Your existing addToCart logic
    addToCart(itemId);

    // Track conversion (when order completes)
    // Store in session that this item was recommended
    sessionStorage.setItem('rec_item_' + itemId, 'true');
}
</script>
```

---

### Day 8-9: Simple ROI Dashboard

Create analytics view in `core/views.py`:

```python
from django.db.models import Sum, Count
from datetime import timedelta
from django.utils import timezone

@login_required
def recommendation_dashboard(request):
    """Simple dashboard showing $ made from recommendations."""
    hotel = get_user_hotel(request.user)

    # Last 30 days
    start_date = timezone.now() - timedelta(days=30)

    # Revenue from recommendations
    stats = RecommendationEvent.objects.filter(
        hotel=hotel,
        created_at__gte=start_date,
        event_type=RecommendationEvent.CONVERSION
    ).aggregate(
        total_revenue=Sum('revenue'),
        total_conversions=Count('id')
    )

    # Top performing pairs
    top_pairs = ItemPairFrequency.objects.filter(
        hotel=hotel,
        times_converted__gt=0
    ).select_related('item_a', 'item_b').order_by('-revenue_generated')[:10]

    # Conversion rate
    impressions = RecommendationEvent.objects.filter(
        hotel=hotel,
        created_at__gte=start_date,
        event_type=RecommendationEvent.IMPRESSION
    ).count()

    conversion_rate = 0
    if impressions > 0:
        conversion_rate = (stats['total_conversions'] / impressions) * 100

    context = {
        'hotel': hotel,
        'total_revenue': stats['total_revenue'] or Decimal('0.00'),
        'total_conversions': stats['total_conversions'] or 0,
        'conversion_rate': round(conversion_rate, 1),
        'top_pairs': top_pairs,
        'days': 30,
    }

    return render(request, 'core/recommendation_dashboard.html', context)
```

Simple template `core/templates/core/recommendation_dashboard.html`:

```html
{% extends "base.html" %}

{% block content %}
<div class="max-w-6xl mx-auto p-6">
    <h1 class="text-3xl font-bold mb-6">Recommendation Performance</h1>

    <!-- Big Number: Revenue -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div class="bg-gradient-to-br from-green-500 to-green-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-2">Revenue from Recommendations</div>
            <div class="text-5xl font-bold">${{ total_revenue|floatformat:0 }}</div>
            <div class="text-sm mt-2">Last {{ days }} days</div>
        </div>

        <div class="bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-2">Items Added</div>
            <div class="text-5xl font-bold">{{ total_conversions }}</div>
            <div class="text-sm mt-2">From recommendations</div>
        </div>

        <div class="bg-gradient-to-br from-purple-500 to-purple-600 text-white rounded-lg p-6 shadow-lg">
            <div class="text-sm opacity-90 mb-2">Conversion Rate</div>
            <div class="text-5xl font-bold">{{ conversion_rate }}%</div>
            <div class="text-sm mt-2">Customers who clicked</div>
        </div>
    </div>

    <!-- Top Performing Pairs -->
    <div class="bg-white rounded-lg shadow p-6">
        <h2 class="text-xl font-bold mb-4">Top Performing Combinations</h2>
        <table class="w-full">
            <thead>
                <tr class="border-b">
                    <th class="text-left py-2">Item A</th>
                    <th class="text-left py-2">Item B</th>
                    <th class="text-right py-2">Times Sold Together</th>
                    <th class="text-right py-2">Revenue Generated</th>
                </tr>
            </thead>
            <tbody>
                {% for pair in top_pairs %}
                <tr class="border-b">
                    <td class="py-2">{{ pair.item_a.name }}</td>
                    <td class="py-2">{{ pair.item_b.name }}</td>
                    <td class="text-right">{{ pair.times_converted }}</td>
                    <td class="text-right font-bold text-green-600">${{ pair.revenue_generated|floatformat:2 }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
{% endblock %}
```

Add URL in `core/urls.py`:

```python
path('dashboard/recommendations/', views.recommendation_dashboard, name='recommendation_dashboard'),
```

---

### Day 10: Test with Real Data

#### Seed Test Data (Development)

Create management command `core/management/commands/seed_recommendation_data.py`:

```python
from django.core.management.base import BaseCommand
from core.models import Hotel, MenuItem, Order, OrderItem
from decimal import Decimal
import random

class Command(BaseCommand):
    help = 'Seed test orders for recommendation testing'

    def handle(self, *args, **options):
        hotel = Hotel.objects.first()
        if not hotel:
            self.stdout.write(self.style.ERROR('No hotel found'))
            return

        items = list(MenuItem.objects.filter(category__hotel=hotel, is_available=True))
        if len(items) < 5:
            self.stdout.write(self.style.ERROR('Need at least 5 menu items'))
            return

        # Common pairs (simulate patterns)
        common_pairs = [
            (items[0], items[1]),  # e.g., Pizza + Garlic Bread
            (items[0], items[2]),  # e.g., Pizza + Coke
            (items[3], items[4]),  # e.g., Pasta + Wine
        ]

        # Create 50 test orders
        for i in range(50):
            order = Order.objects.create(
                hotel=hotel,
                room_number=f"Table {random.randint(1, 20)}",
                status=Order.OrderStatus.COMPLETED,
                subtotal=Decimal('0.00')
            )

            # 70% chance to order a common pair
            if random.random() < 0.7:
                pair = random.choice(common_pairs)
                for item in pair:
                    OrderItem.objects.create(
                        order=order,
                        menu_item=item,
                        quantity=1,
                        price_at_order=item.price
                    )
            else:
                # Random items
                selected_items = random.sample(items, random.randint(1, 3))
                for item in selected_items:
                    OrderItem.objects.create(
                        order=order,
                        menu_item=item,
                        quantity=1,
                        price_at_order=item.price
                    )

            order.calculate_totals()
            order.save()

        self.stdout.write(self.style.SUCCESS(f'Created 50 test orders with patterns'))
```

Run:
```bash
python manage.py seed_recommendation_data
```

---

## Launch Checklist

### Before Going Live:

- [ ] Models migrated to production database
- [ ] Signal handlers registered (check `apps.py`)
- [ ] Recommendation engine tested with real menu items
- [ ] UI displays recommendations correctly
- [ ] Tracking events are being recorded
- [ ] Dashboard shows accurate numbers
- [ ] Test on mobile (most users will be on phones)

### Performance Checks:

- [ ] Page load time < 2 seconds (recommendations shouldn't slow down menu)
- [ ] Database indexes in place (`hotel`, `created_at`, `confidence`)
- [ ] Consider caching popular recommendations (Redis) if needed

---

## What You'll See After 1 Week of Real Data:

**Day 1-2**: Almost no recommendations (not enough data)
- **Action**: Manually mark a few items as "is_featured" to show something

**Day 3-7**: Patterns start emerging
- Popular combinations begin showing up
- Track which ones customers actually click

**Week 2-4**: Algorithm gets smarter
- Confidence scores stabilize
- You can increase minimum confidence threshold
- Dashboard shows real revenue impact

**Month 2+**: Defensible moat
- Competitor can't replicate your recommendation quality
- Restaurant owners see clear value: "Made $847 extra this month!"

---

## Next Steps After MVP:

Once this is working and generating revenue:

1. **Add "Complete Your Meal" upsells** (Week 3)
   - "No drink in cart? Suggest Coke"
   - Rule-based, easy to implement

2. **Add "Trending Now"** (Week 4)
   - Items popular in last 2 hours
   - Great for lunch/dinner rush

3. **Personalization** (Month 2)
   - Remember what customer ordered before
   - "Welcome back! You loved the Pizza last time"

4. **A/B Testing** (Month 3)
   - Test different confidence thresholds
   - Test different UI placements
   - Optimize conversion rates

---

## Common Issues & Solutions:

### "No recommendations showing"
- Check: Do you have at least 10 completed orders?
- Check: Are multiple items being ordered together?
- Lower `confidence__gte` threshold temporarily (from 0.15 to 0.05)

### "Recommendations not tracking conversions"
- Check: Is the signal handler registered in apps.py?
- Check: Are orders reaching COMPLETED status?
- Check: Browser console for JavaScript errors

### "Dashboard showing $0 revenue"
- Check: Are RecommendationEvent CONVERSION events being created?
- Check: Is the revenue field being populated from OrderItem.total_price?
- Check: Date range filter (default 30 days)

---

## Success Metrics for MVP:

After 2 weeks with 5 pilot restaurants:

- ✅ At least 20 recommendations shown per restaurant per day
- ✅ CTR > 10% (customers clicking recommendations)
- ✅ Conversion rate > 5% (clicks turning into purchases)
- ✅ $100-500 additional revenue per restaurant per week

**If you hit these numbers, you have product-market fit for recommendations!**

---

## Cost to Build This MVP:

- **Development Time**: 60-80 hours (2 weeks full-time)
- **Infrastructure**: $0 additional (runs on existing Django server)
- **External Services**: None needed for MVP

**ROI**:
- 1 restaurant with $7,500/month extra revenue
- You take 5% commission = $375/month
- Pays for development in 3-4 months
- Scales linearly with more restaurants

---

## Questions? Stuck?

Common debugging commands:

```bash
# Check if pairs are being created
python manage.py shell
>>> from core.models import ItemPairFrequency
>>> ItemPairFrequency.objects.count()

# Check if events are being tracked
>>> from core.models import RecommendationEvent
>>> RecommendationEvent.objects.filter(event_type='CONVERSION').count()

# Manually trigger confidence calculation
>>> from core.recommendation_engine import SimpleRecommendationEngine
>>> from core.models import Hotel
>>> hotel = Hotel.objects.first()
>>> engine = SimpleRecommendationEngine(hotel)
>>> engine._update_confidence_scores()

# Test recommendations for an item
>>> from core.models import MenuItem
>>> item = MenuItem.objects.first()
>>> engine.get_recommendations(item, limit=5)
```

---

**Ready to build? Start with Day 1 and ship incrementally. Don't overthink it - the algorithm will improve as you get real data!**
