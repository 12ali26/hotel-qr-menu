"""
Management command to seed realistic order data for testing the recommendation engine.

Usage:
    python manage.py seed_recommendations --orders 50
    python manage.py seed_recommendations --orders 100 --hotel 1
"""

import random
from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Hotel, MenuItem, Order, OrderItem, Category


class Command(BaseCommand):
    help = "Seed realistic order data to test recommendation engine"

    def add_arguments(self, parser):
        parser.add_argument(
            "--orders",
            type=int,
            default=50,
            help="Number of orders to create (default: 50)",
        )
        parser.add_argument(
            "--hotel",
            type=int,
            help="Specific hotel ID to seed (default: first hotel)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Spread orders over N days (default: 30)",
        )

    def handle(self, *args, **options):
        num_orders = options["orders"]
        hotel_id = options["hotel"]
        days_back = options["days"]

        # Get hotel
        if hotel_id:
            try:
                hotel = Hotel.objects.get(id=hotel_id)
            except Hotel.DoesNotExist:
                raise CommandError(f"Hotel with ID {hotel_id} does not exist")
        else:
            hotel = Hotel.objects.first()
            if not hotel:
                raise CommandError("No hotels found. Please create a hotel first.")

        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(self.style.SUCCESS(f"  Seeding recommendation data for: {hotel.name}"))
        self.stdout.write(f"{'='*70}\n")

        # Get all available menu items
        items = list(
            MenuItem.objects.filter(
                category__hotel=hotel, is_available=True
            ).select_related("category")
        )

        if len(items) < 5:
            raise CommandError(
                f"Need at least 5 menu items. Found {len(items)}. "
                "Please add more items to your menu first."
            )

        self.stdout.write(f"Found {len(items)} available menu items\n")

        # Categorize items by type (for realistic pairings)
        mains = []
        sides = []
        drinks = []
        desserts = []
        others = []

        for item in items:
            cat_name = item.category.name.lower()
            if any(
                word in cat_name
                for word in ["main", "entree", "pasta", "pizza", "burger"]
            ):
                mains.append(item)
            elif any(
                word in cat_name
                for word in ["side", "appetizer", "starter", "salad"]
            ):
                sides.append(item)
            elif any(word in cat_name for word in ["drink", "beverage"]):
                drinks.append(item)
            elif any(word in cat_name for word in ["dessert", "sweet"]):
                desserts.append(item)
            else:
                others.append(item)

        # Fallback if categories don't match patterns
        if not mains:
            mains = items[:len(items) // 3]
        if not drinks:
            drinks = items[len(items) // 3 : 2 * len(items) // 3]
        if not sides:
            sides = items[2 * len(items) // 3 :]

        self.stdout.write(
            f"Categorized: {len(mains)} mains, {len(sides)} sides, "
            f"{len(drinks)} drinks, {len(desserts)} desserts\n"
        )

        # Define realistic order patterns
        # Each pattern is (items_list, probability_weight)
        order_patterns = [
            # Common patterns (high weight)
            ([mains, drinks], 30),  # Main + Drink
            ([mains, sides], 25),  # Main + Side
            ([mains, sides, drinks], 20),  # Full meal
            ([mains, drinks, desserts], 15),  # Main + Drink + Dessert
            # Less common patterns
            ([mains], 5),  # Just main course
            ([drinks], 3),  # Just a drink
            ([sides, drinks], 5),  # Appetizer + Drink
            ([mains, sides, drinks, desserts], 7),  # Complete meal
        ]

        # Create orders
        created_orders = []
        total_items = 0
        pair_frequencies = {}

        self.stdout.write(self.style.WARNING(f"\nCreating {num_orders} orders...\n"))

        for i in range(num_orders):
            # Random time in the past N days
            days_ago = random.uniform(0, days_back)
            order_time = timezone.now() - timedelta(days=days_ago)

            # Random table number
            table_num = f"Table {random.randint(1, 20)}"

            # Select order pattern based on weights
            pattern, _ = random.choices(
                order_patterns,
                weights=[weight for _, weight in order_patterns],
                k=1,
            )[0]

            # Create order
            order = Order.objects.create(
                hotel=hotel,
                room_number=table_num,
                status=Order.OrderStatus.COMPLETED,
                payment_method=random.choice(
                    [Order.PaymentMethod.CASH, Order.PaymentMethod.CARD]
                ),
                subtotal=Decimal("0.00"),
            )

            # Manually set created_at to spread orders over time
            order.created_at = order_time
            order.save(update_fields=["created_at"])

            # Add items based on pattern (avoid duplicates)
            order_items = []
            added_items = set()  # Track items already added to this order

            for item_category in pattern:
                if item_category:  # Check if category has items
                    # Try to find an item not already in the order
                    attempts = 0
                    max_attempts = 10
                    item = None

                    while attempts < max_attempts:
                        candidate = random.choice(item_category)
                        if candidate.id not in added_items:
                            item = candidate
                            break
                        attempts += 1

                    # If we found a unique item, add it
                    if item:
                        quantity = random.choices([1, 2], weights=[85, 15])[
                            0
                        ]  # 85% single, 15% double

                        order_item = OrderItem.objects.create(
                            order=order,
                            menu_item=item,
                            quantity=quantity,
                            price_at_order=item.price,
                        )
                        order_items.append(order_item)
                        added_items.add(item.id)
                        total_items += quantity

            # Calculate totals
            order.calculate_totals()

            # Track pair frequencies for summary
            if len(order_items) >= 2:
                for j, item_a in enumerate(order_items):
                    for item_b in order_items[j + 1 :]:
                        pair_key = tuple(
                            sorted([item_a.menu_item.name, item_b.menu_item.name])
                        )
                        pair_frequencies[pair_key] = (
                            pair_frequencies.get(pair_key, 0) + 1
                        )

            created_orders.append(order)

            # Progress indicator
            if (i + 1) % 10 == 0:
                self.stdout.write(f"  Created {i + 1}/{num_orders} orders...")

        self.stdout.write(
            self.style.SUCCESS(f"\n✓ Successfully created {len(created_orders)} orders!")
        )

        # Summary statistics
        self.stdout.write(f"\n{'-'*70}")
        self.stdout.write(self.style.WARNING("SUMMARY STATISTICS"))
        self.stdout.write(f"{'-'*70}")
        self.stdout.write(f"Total orders created:     {len(created_orders)}")
        self.stdout.write(f"Total items ordered:      {total_items}")
        self.stdout.write(
            f"Average items per order:  {total_items / len(created_orders):.1f}"
        )
        self.stdout.write(
            f"Date range:               {days_back} days (spread across timeframe)"
        )

        # Show top item pairs
        if pair_frequencies:
            self.stdout.write(f"\n{'-'*70}")
            self.stdout.write(self.style.WARNING("TOP 10 ITEM COMBINATIONS"))
            self.stdout.write(f"{'-'*70}")

            sorted_pairs = sorted(
                pair_frequencies.items(), key=lambda x: x[1], reverse=True
            )[:10]

            for rank, (pair, count) in enumerate(sorted_pairs, 1):
                item_a, item_b = pair
                self.stdout.write(f"{rank:2d}. {item_a} + {item_b}: {count} times")

        # Trigger recommendation engine update
        self.stdout.write(f"\n{'-'*70}")
        self.stdout.write(self.style.WARNING("UPDATING RECOMMENDATION ENGINE"))
        self.stdout.write(f"{'-'*70}")

        from core.models import ItemPairFrequency

        pair_count_before = ItemPairFrequency.objects.filter(hotel=hotel).count()

        # The signal handlers should have already updated the pairs,
        # but we can verify the count
        pair_count_after = ItemPairFrequency.objects.filter(hotel=hotel).count()

        self.stdout.write(
            f"Item pairs tracked:       {pair_count_after} "
            f"(+{pair_count_after - pair_count_before} new)"
        )

        # Show some statistics
        top_pairs_by_confidence = (
            ItemPairFrequency.objects.filter(hotel=hotel)
            .select_related("item_a", "item_b")
            .order_by("-confidence", "-times_together")[:5]
        )

        if top_pairs_by_confidence.exists():
            self.stdout.write(f"\n{'-'*70}")
            self.stdout.write(self.style.WARNING("TOP 5 PAIRS BY CONFIDENCE"))
            self.stdout.write(f"{'-'*70}")

            for pair in top_pairs_by_confidence:
                confidence_pct = pair.confidence * 100
                self.stdout.write(
                    f"{pair.item_a.name} + {pair.item_b.name}: "
                    f"{confidence_pct:.1f}% confidence ({pair.times_together}x ordered together)"
                )

        # Next steps
        self.stdout.write(f"\n{'-'*70}")
        self.stdout.write(self.style.SUCCESS("✓ SEEDING COMPLETE!"))
        self.stdout.write(f"{'-'*70}\n")

        self.stdout.write(self.style.WARNING("NEXT STEPS:\n"))
        self.stdout.write("1. View analytics dashboard:")
        self.stdout.write("   → http://localhost:8000/dashboard/recommendations/\n")
        self.stdout.write("2. Check customer menu for trending items:")
        self.stdout.write(f"   → http://localhost:8000/menu/{hotel.slug}/\n")
        self.stdout.write("3. Test the recommendation API:")
        self.stdout.write(
            "   → http://localhost:8000/api/recommendations/item/<item_id>/\n"
        )

        self.stdout.write(
            self.style.SUCCESS(
                "\n🎉 Your recommendation engine is now trained with realistic data!"
            )
        )
        self.stdout.write(f"{'='*70}\n")
