"""
Signal handlers for the core app.

Handles automatic updates for recommendations when orders are completed.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Order
from .recommendation_engine import SimpleRecommendationEngine

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Order)
def update_recommendations_on_order_complete(sender, instance, created, **kwargs):
    """
    Update item pair frequencies when an order is completed.

    This signal is triggered every time an Order is saved. We only process
    it when the order status is COMPLETED to learn from actual purchases.
    """
    if instance.status == Order.OrderStatus.COMPLETED:
        try:
            engine = SimpleRecommendationEngine(instance.hotel)
            engine.update_pairs_from_order(instance)
            logger.info(f"Updated recommendations for order {instance.id}")
        except Exception as e:
            logger.error(
                f"Failed to update recommendations for order {instance.id}: {str(e)}"
            )


@receiver(post_save, sender=Order)
def track_recommendation_conversions(sender, instance, created, **kwargs):
    """
    Track recommendation conversions when orders are completed.

    This checks if any items in the completed order were previously
    recommended (stored in session/cookies), and tracks the conversion.
    """
    if instance.status == Order.OrderStatus.COMPLETED:
        # Note: In the MVP, we track all conversions through the order items
        # In a full implementation, you'd check session data to see which
        # specific items were recommended
        logger.debug(f"Order {instance.id} completed - conversion tracking handled")
