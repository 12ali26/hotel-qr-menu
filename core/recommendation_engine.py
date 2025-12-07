"""
Simple Recommendation Engine - MVP Implementation

Provides collaborative filtering ("Frequently Bought Together") recommendations
based on actual order patterns.
"""

import logging
from decimal import Decimal
from itertools import combinations
from typing import List, Dict, Any

from django.db.models import Q, Count

from .models import (
    ItemPairFrequency,
    MenuItem,
    Order,
    OrderItem,
    RecommendationEvent,
)

logger = logging.getLogger(__name__)


class SimpleRecommendationEngine:
    """
    MVP recommendation engine using collaborative filtering.

    Algorithm: Track which items are frequently ordered together,
    then recommend based on confidence scores (P(B|A)).
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def update_pairs_from_order(self, order: Order) -> None:
        """
        When an order completes, record all item pairs.

        This is the core data collection step - every completed order
        teaches the algorithm about which items go well together.

        Args:
            order: Completed Order instance
        """
        if order.status != Order.OrderStatus.COMPLETED:
            logger.debug(
                f"Skipping pair update for order {order.id} - status is {order.status}"
            )
            return

        # Get all menu items in this order
        item_ids = list(order.items.values_list("menu_item_id", flat=True))

        if len(item_ids) < 2:
            logger.debug(
                f"Skipping pair update for order {order.id} - only {len(item_ids)} item(s)"
            )
            return

        # Generate all possible pairs (combinations, not permutations)
        pair_count = 0
        for item_a_id, item_b_id in combinations(item_ids, 2):
            # Keep consistent ordering (smaller ID first) to avoid duplicates
            if item_a_id > item_b_id:
                item_a_id, item_b_id = item_b_id, item_a_id

            # Get or create the pair record
            pair, created = ItemPairFrequency.objects.get_or_create(
                hotel=self.hotel,
                item_a_id=item_a_id,
                item_b_id=item_b_id,
            )

            # Increment the counter
            if not created:
                pair.times_together += 1
                pair.save(update_fields=["times_together", "updated_at"])

            pair_count += 1

        logger.info(
            f"Updated {pair_count} item pairs from order {order.id} "
            f"({len(item_ids)} items)"
        )

        # Recalculate confidence scores
        self._update_confidence_scores()

    def _update_confidence_scores(self) -> None:
        """
        Calculate P(B|A) for all pairs.

        Confidence = times_together / total_times_item_a_was_ordered

        This tells us: "When someone orders item A, what's the probability
        they'll also order item B?"
        """
        pairs_updated = 0

        for pair in ItemPairFrequency.objects.filter(hotel=self.hotel):
            # Count how many orders contained item_a
            item_a_order_count = (
                OrderItem.objects.filter(
                    order__hotel=self.hotel,
                    order__status=Order.OrderStatus.COMPLETED,
                    menu_item=pair.item_a,
                )
                .values("order")
                .distinct()
                .count()
            )

            if item_a_order_count > 0:
                # Confidence = P(B|A) = orders_with_both / orders_with_a
                new_confidence = pair.times_together / item_a_order_count

                if pair.confidence != new_confidence:
                    pair.confidence = new_confidence
                    pair.save(update_fields=["confidence", "updated_at"])
                    pairs_updated += 1

        if pairs_updated > 0:
            logger.info(f"Updated confidence scores for {pairs_updated} pairs")

    def get_recommendations(
        self, item: MenuItem, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get top N items frequently bought with this item.

        Args:
            item: The menu item to get recommendations for
            limit: Maximum number of recommendations to return

        Returns:
            List of dicts containing recommended items and metadata:
            [
                {
                    'item': MenuItem,
                    'reason': "5 customers bought both",
                    'confidence': 0.35,
                    'pair': ItemPairFrequency (for tracking)
                },
                ...
            ]
        """
        # Find pairs where this item appears
        pairs = (
            ItemPairFrequency.objects.filter(
                Q(item_a=item) | Q(item_b=item),
                hotel=self.hotel,
                confidence__gte=0.15,  # Minimum 15% confidence
                times_together__gte=2,  # At least 2 co-occurrences
            )
            .select_related("item_a", "item_b")
            .order_by("-confidence", "-times_together")[:limit]
        )

        recommendations = []
        for pair in pairs:
            # Get the "other" item in the pair
            other_item = pair.item_b if pair.item_a == item else pair.item_a

            # Only recommend available items
            if not other_item.is_available:
                continue

            recommendations.append(
                {
                    "item": other_item,
                    "reason": f"{pair.times_together} customers bought both",
                    "confidence": round(pair.confidence * 100, 1),  # As percentage
                    "pair": pair,
                }
            )

        logger.debug(
            f"Generated {len(recommendations)} recommendations for {item.name}"
        )
        return recommendations

    def track_impression(
        self, source_item: MenuItem = None, recommended_item: MenuItem = None
    ) -> None:
        """
        Track when a recommendation is shown to a customer.

        Args:
            source_item: Item that triggered the recommendation (optional)
            recommended_item: Item that was recommended
        """
        if not recommended_item:
            logger.warning("Cannot track impression without recommended_item")
            return

        RecommendationEvent.objects.create(
            hotel=self.hotel,
            source_item=source_item,
            recommended_item=recommended_item,
            event_type=RecommendationEvent.EventType.IMPRESSION,
        )

        # Update pair stats
        if source_item:
            self._update_pair_stats(source_item, recommended_item, "impression")

    def track_conversion(
        self, recommended_item: MenuItem, order: Order, revenue: Decimal = None
    ) -> None:
        """
        Track when a recommended item is actually purchased.

        Args:
            recommended_item: Item that was recommended and purchased
            order: The order containing the purchased item
            revenue: Revenue from this item (defaults to item price * quantity)
        """
        # Get the revenue if not provided
        if revenue is None:
            order_item = order.items.filter(menu_item=recommended_item).first()
            if order_item:
                revenue = order_item.total_price
            else:
                revenue = Decimal("0.00")

        # Record conversion event
        RecommendationEvent.objects.create(
            hotel=self.hotel,
            order=order,
            recommended_item=recommended_item,
            event_type=RecommendationEvent.EventType.CONVERSION,
            revenue=revenue,
        )

        # Update all pairs containing this item
        # (In a full implementation, we'd track which specific pair triggered this)
        pairs = ItemPairFrequency.objects.filter(
            Q(item_a=recommended_item) | Q(item_b=recommended_item), hotel=self.hotel
        )

        for pair in pairs:
            pair.times_converted += 1
            pair.revenue_generated += revenue
            pair.save(update_fields=["times_converted", "revenue_generated", "updated_at"])

        logger.info(
            f"Tracked conversion for {recommended_item.name} in order {order.id} "
            f"(revenue: ${revenue})"
        )

    def _update_pair_stats(
        self, item_a: MenuItem, item_b: MenuItem, stat_type: str
    ) -> None:
        """
        Update recommendation statistics for a specific pair.

        Args:
            item_a: First item in pair
            item_b: Second item in pair
            stat_type: 'impression' or 'click'
        """
        # Ensure consistent ordering
        if item_a.id > item_b.id:
            item_a, item_b = item_b, item_a

        try:
            pair = ItemPairFrequency.objects.get(
                hotel=self.hotel, item_a=item_a, item_b=item_b
            )

            if stat_type == "impression":
                pair.times_recommended += 1
                pair.save(update_fields=["times_recommended", "updated_at"])

        except ItemPairFrequency.DoesNotExist:
            # Pair doesn't exist yet (no orders with both items)
            logger.debug(f"Pair {item_a.name} + {item_b.name} doesn't exist yet")


class RecommendationAnalytics:
    """
    Helper class for analytics and reporting on recommendation performance.
    """

    def __init__(self, hotel):
        self.hotel = hotel

    def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """
        Get aggregate performance metrics for the last N days.

        Args:
            days: Number of days to look back

        Returns:
            Dict with metrics: total_revenue, conversion_rate, etc.
        """
        from datetime import timedelta
        from django.utils import timezone
        from django.db.models import Sum, Count

        start_date = timezone.now() - timedelta(days=days)

        # Get conversion events
        conversions = RecommendationEvent.objects.filter(
            hotel=self.hotel,
            created_at__gte=start_date,
            event_type=RecommendationEvent.EventType.CONVERSION,
        ).aggregate(total_revenue=Sum("revenue"), total_conversions=Count("id"))

        # Get impressions
        impressions = RecommendationEvent.objects.filter(
            hotel=self.hotel,
            created_at__gte=start_date,
            event_type=RecommendationEvent.EventType.IMPRESSION,
        ).count()

        # Calculate conversion rate
        conversion_rate = 0.0
        if impressions > 0:
            conversion_rate = (
                conversions["total_conversions"] / impressions
            ) * 100

        return {
            "total_revenue": conversions["total_revenue"] or Decimal("0.00"),
            "total_conversions": conversions["total_conversions"] or 0,
            "total_impressions": impressions,
            "conversion_rate": round(conversion_rate, 2),
            "days": days,
        }

    def get_top_performing_pairs(self, limit: int = 10) -> List[ItemPairFrequency]:
        """
        Get the most successful recommendation pairs by revenue.

        Args:
            limit: Max number of pairs to return

        Returns:
            List of ItemPairFrequency objects ordered by revenue
        """
        return (
            ItemPairFrequency.objects.filter(
                hotel=self.hotel, times_converted__gt=0
            )
            .select_related("item_a", "item_b")
            .order_by("-revenue_generated", "-times_converted")[:limit]
        )


class CrossNetworkInsights:
    """
    Provides insights from across the entire restaurant network.

    This creates powerful network effects - as more restaurants join the platform,
    recommendations get better for everyone. This is a key competitive moat.
    """

    def __init__(self, hotel=None):
        self.hotel = hotel

    def get_network_size(self) -> Dict[str, int]:
        """Get the size of the network for credibility."""
        from .models import Hotel, Order

        return {
            "total_restaurants": Hotel.objects.filter(is_active=True).count(),
            "total_orders": Order.objects.filter(
                status=Order.OrderStatus.COMPLETED
            ).count(),
            "total_pairs": ItemPairFrequency.objects.count(),
        }

    def get_similar_restaurants(self, limit: int = 10) -> List[Any]:
        """
        Find restaurants similar to this one (by business type, category overlap, etc.).

        Args:
            limit: Max number of similar restaurants

        Returns:
            List of similar Hotel objects
        """
        from .models import Hotel

        if not self.hotel:
            return []

        # Find restaurants with same business type
        similar = Hotel.objects.filter(
            business_type=self.hotel.business_type, is_active=True
        ).exclude(id=self.hotel.id)[:limit]

        return list(similar)

    def get_cross_network_trending_patterns(
        self, business_type: str = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get trending item combinations across the entire network.

        This shows what's working well across all restaurants, providing
        inspiration and validation for new restaurants.

        Args:
            business_type: Filter by business type (RESTAURANT, CAFE, etc.)
            limit: Number of patterns to return

        Returns:
            List of trending patterns with aggregate statistics
        """
        from django.db.models import Avg, Sum, Count
        from .models import Hotel

        # Build query to aggregate across network
        query = ItemPairFrequency.objects.select_related(
            "item_a__category", "item_b__category", "hotel"
        )

        # Filter by business type if specified
        if business_type:
            query = query.filter(hotel__business_type=business_type)
        elif self.hotel:
            query = query.filter(hotel__business_type=self.hotel.business_type)

        # Group by item name patterns (normalize similar items across restaurants)
        # For MVP, we'll just show top pairs by frequency
        top_patterns = (
            query.values(
                "item_a__name",
                "item_b__name",
                "item_a__category__name",
                "item_b__category__name",
            )
            .annotate(
                total_orders=Sum("times_together"),
                avg_confidence=Avg("confidence"),
                restaurant_count=Count("hotel", distinct=True),
                total_conversions=Sum("times_converted"),
                total_revenue=Sum("revenue_generated"),
            )
            .filter(total_orders__gte=5)  # Minimum 5 occurrences across network
            .order_by("-total_orders")[:limit]
        )

        return [
            {
                "item_a": pattern["item_a__name"],
                "item_b": pattern["item_b__name"],
                "category_a": pattern["item_a__category__name"],
                "category_b": pattern["item_b__category__name"],
                "total_orders": pattern["total_orders"],
                "avg_confidence": round(pattern["avg_confidence"] * 100, 1)
                if pattern["avg_confidence"]
                else 0,
                "restaurant_count": pattern["restaurant_count"],
                "total_conversions": pattern["total_conversions"] or 0,
                "total_revenue": pattern["total_revenue"] or Decimal("0.00"),
            }
            for pattern in top_patterns
        ]

    def get_network_benchmarks(self) -> Dict[str, Any]:
        """
        Get platform-wide benchmarks for comparison.

        Shows how this restaurant compares to the network average.
        Useful for identifying improvement opportunities.

        Returns:
            Dict with network-wide statistics
        """
        from django.db.models import Avg, Count
        from .models import Order, Hotel
        from datetime import timedelta
        from django.utils import timezone

        thirty_days_ago = timezone.now() - timedelta(days=30)

        # Network-wide metrics
        network_stats = Hotel.objects.filter(is_active=True).aggregate(
            avg_items_per_order=Avg("orders__items__quantity"),
            avg_order_value=Avg("orders__total_price"),
        )

        # Recommendation performance across network
        rec_performance = RecommendationEvent.objects.filter(
            created_at__gte=thirty_days_ago
        ).aggregate(
            total_impressions=Count("id", filter=Q(event_type="IMPRESSION")),
            total_conversions=Count("id", filter=Q(event_type="CONVERSION")),
            avg_revenue=Avg("revenue", filter=Q(event_type="CONVERSION")),
        )

        network_conversion_rate = 0.0
        if rec_performance["total_impressions"]:
            network_conversion_rate = (
                rec_performance["total_conversions"]
                / rec_performance["total_impressions"]
                * 100
            )

        return {
            "avg_items_per_order": round(
                network_stats["avg_items_per_order"] or 0, 1
            ),
            "avg_order_value": network_stats["avg_order_value"] or Decimal("0.00"),
            "recommendation_conversion_rate": round(network_conversion_rate, 2),
            "avg_recommendation_revenue": rec_performance["avg_revenue"]
            or Decimal("0.00"),
        }

    def get_inspiration_for_new_restaurant(self) -> Dict[str, Any]:
        """
        Provides data-driven insights for restaurants just starting out.

        This is incredibly valuable for new restaurants with no data - they can
        see what's working across the network and start with proven patterns.

        Returns:
            Dict with actionable insights for new restaurants
        """
        # Get top trending patterns
        trending = self.get_cross_network_trending_patterns(
            business_type=self.hotel.business_type if self.hotel else None, limit=5
        )

        # Get network benchmarks
        benchmarks = self.get_network_benchmarks()

        # Get network size for credibility
        network_size = self.get_network_size()

        return {
            "trending_patterns": trending,
            "benchmarks": benchmarks,
            "network_size": network_size,
            "message": f"Based on insights from {network_size['total_restaurants']} restaurants "
            f"and {network_size['total_orders']} completed orders",
        }

    def compare_to_network(
        self, hotel_analytics: "RecommendationAnalytics"
    ) -> Dict[str, Any]:
        """
        Compare a specific restaurant's performance to network averages.

        Args:
            hotel_analytics: RecommendationAnalytics instance for the restaurant

        Returns:
            Dict with comparison metrics
        """
        hotel_performance = hotel_analytics.get_performance_summary(days=30)
        network_benchmarks = self.get_network_benchmarks()

        # Calculate differences
        conversion_diff = (
            hotel_performance["conversion_rate"]
            - network_benchmarks["recommendation_conversion_rate"]
        )

        return {
            "your_conversion_rate": hotel_performance["conversion_rate"],
            "network_avg_conversion_rate": network_benchmarks[
                "recommendation_conversion_rate"
            ],
            "conversion_diff": round(conversion_diff, 2),
            "performing_above_average": conversion_diff > 0,
            "network_size": self.get_network_size(),
        }
