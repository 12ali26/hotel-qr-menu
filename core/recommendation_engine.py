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
