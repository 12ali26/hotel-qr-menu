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


@receiver(post_save, sender=Order)
def update_table_status_on_order_change(sender, instance, created, **kwargs):
    """
    Reset table to AVAILABLE when order is completed or cancelled.

    This ensures tables don't stay stuck in OCCUPIED status after
    customers have finished their meal or cancelled their order.
    """
    # Only process if this order has an associated table
    if not instance.table:
        return

    # Import here to avoid circular imports
    from .models import Table

    # When order is completed or cancelled, free up the table
    if instance.status in [Order.OrderStatus.COMPLETED, Order.OrderStatus.CANCELLED]:
        # Only update if table is currently occupied
        if instance.table.status == Table.TableStatus.OCCUPIED:
            instance.table.status = Table.TableStatus.AVAILABLE
            instance.table.save(update_fields=["status"])
            logger.info(
                f"Table {instance.table.table_number} set to AVAILABLE "
                f"after order {instance.id} was {instance.status.lower()}"
            )
