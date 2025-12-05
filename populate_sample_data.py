"""
Script to populate the database with sample data for testing.
Run this with: python populate_sample_data.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_qr_menu_project.settings')
django.setup()

from decimal import Decimal
from core.models import Hotel, Category, MenuItem, Table

# Check if data already exists - if so, skip creation
if Hotel.objects.exists():
    print("✅ Sample data already exists. Skipping creation.")
    print(f"   • {Hotel.objects.count()} Businesses")
    print(f"   • {Category.objects.count()} Categories")
    print(f"   • {MenuItem.objects.count()} Menu items")
    print(f"   • {Table.objects.count()} Tables")
    sys.exit(0)

print("\n" + "="*60)
print("CREATING SAMPLE DATA FOR MULTI-MARKET PLATFORM")
print("="*60 + "\n")

# ============================================================================
# 1. CREATE RESTAURANT: Bella Italia
# ============================================================================
print("1️⃣ Creating RESTAURANT: Bella Italia...")

bella_italia = Hotel.objects.create(
    name="Bella Italia",
    business_type=Hotel.BusinessType.RESTAURANT,
    slug="bella-italia-doha",
    currency_code="QAR",
    timezone="Asia/Qatar",
    is_active=True,
    enable_table_management=True,
    enable_waiter_alerts=True,
    enable_room_charging=False,
)
print(f"   ✓ Created: {bella_italia}")

# Create tables for the restaurant
print("   Creating tables...")
for i in range(1, 21):  # 20 tables
    Table.objects.create(
        hotel=bella_italia,
        table_number=str(i),
        capacity=4 if i <= 15 else 6,  # Larger tables for 16-20
        status=Table.TableStatus.AVAILABLE,
    )
print("   ✓ Created 20 tables")

# Create categories
print("   Creating menu categories...")
antipasti = Category.objects.create(
    hotel=bella_italia,
    name="Antipasti",
    sort_order=1
)
pasta = Category.objects.create(
    hotel=bella_italia,
    name="Pasta",
    sort_order=2
)
pizza = Category.objects.create(
    hotel=bella_italia,
    name="Pizza",
    sort_order=3
)
desserts = Category.objects.create(
    hotel=bella_italia,
    name="Desserts",
    sort_order=4
)
drinks = Category.objects.create(
    hotel=bella_italia,
    name="Drinks",
    sort_order=5
)

# Create menu items
print("   Creating menu items...")

# Antipasti
MenuItem.objects.create(
    category=antipasti,
    name="Bruschetta",
    description="Toasted bread topped with fresh tomatoes, garlic, and basil",
    price=Decimal("28.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=antipasti,
    name="Caprese Salad",
    description="Fresh mozzarella, tomatoes, and basil with olive oil",
    price=Decimal("32.00"),
    is_available=True,
    is_vegetarian=True,
)

# Pasta
MenuItem.objects.create(
    category=pasta,
    name="Spaghetti Carbonara",
    description="Classic Roman pasta with eggs, cheese, and pancetta",
    price=Decimal("45.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=pasta,
    name="Fettuccine Alfredo",
    description="Creamy pasta with parmesan cheese",
    price=Decimal("48.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=pasta,
    name="Penne Arrabbiata",
    description="Spicy tomato sauce with garlic and chili",
    price=Decimal("42.00"),
    is_available=True,
    is_vegetarian=True,
    is_vegan=True,
)

# Pizza
MenuItem.objects.create(
    category=pizza,
    name="Margherita",
    description="Classic pizza with tomato, mozzarella, and basil",
    price=Decimal("55.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=pizza,
    name="Pepperoni",
    description="Tomato sauce, mozzarella, and pepperoni",
    price=Decimal("62.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=pizza,
    name="Quattro Formaggi",
    description="Four cheese pizza",
    price=Decimal("58.00"),
    is_available=True,
    is_vegetarian=True,
)

# Desserts
MenuItem.objects.create(
    category=desserts,
    name="Tiramisu",
    description="Classic Italian coffee-flavored dessert",
    price=Decimal("28.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=desserts,
    name="Panna Cotta",
    description="Italian vanilla custard with berry compote",
    price=Decimal("25.00"),
    is_available=True,
    is_vegetarian=True,
)

# Drinks
MenuItem.objects.create(
    category=drinks,
    name="Coca-Cola",
    description="Classic soft drink",
    price=Decimal("8.00"),
    is_available=True,
    is_vegan=True,
)
MenuItem.objects.create(
    category=drinks,
    name="Sparkling Water",
    description="San Pellegrino",
    price=Decimal("10.00"),
    is_available=True,
    is_vegan=True,
)

print("   ✓ Created menu items")
print(f"   ✅ Restaurant complete!\n")

# ============================================================================
# 2. CREATE HOTEL: Grand Plaza Hotel
# ============================================================================
print("2️⃣ Creating HOTEL: Grand Plaza Hotel...")

grand_plaza = Hotel.objects.create(
    name="Grand Plaza Hotel",
    business_type=Hotel.BusinessType.HOTEL,
    slug="grand-plaza-doha",
    currency_code="QAR",
    timezone="Asia/Qatar",
    is_active=True,
    enable_table_management=False,
    enable_waiter_alerts=False,
    enable_room_charging=True,
)
print(f"   ✓ Created: {grand_plaza}")

# Create categories
print("   Creating menu categories...")
breakfast = Category.objects.create(
    hotel=grand_plaza,
    name="Breakfast",
    sort_order=1
)
sandwiches = Category.objects.create(
    hotel=grand_plaza,
    name="Sandwiches",
    sort_order=2
)
main_courses = Category.objects.create(
    hotel=grand_plaza,
    name="Main Courses",
    sort_order=3
)
hotel_desserts = Category.objects.create(
    hotel=grand_plaza,
    name="Desserts",
    sort_order=4
)
hotel_drinks = Category.objects.create(
    hotel=grand_plaza,
    name="Beverages",
    sort_order=5
)

# Create menu items
print("   Creating menu items...")

# Breakfast
MenuItem.objects.create(
    category=breakfast,
    name="Continental Breakfast",
    description="Fresh pastries, fruit, yogurt, and juice",
    price=Decimal("65.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=breakfast,
    name="American Breakfast",
    description="Eggs, bacon, toast, and hashbrowns",
    price=Decimal("75.00"),
    is_available=True,
)

# Sandwiches
MenuItem.objects.create(
    category=sandwiches,
    name="Club Sandwich",
    description="Triple-decker with chicken, bacon, lettuce, and tomato",
    price=Decimal("55.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=sandwiches,
    name="Grilled Cheese",
    description="Classic grilled cheese sandwich",
    price=Decimal("38.00"),
    is_available=True,
    is_vegetarian=True,
)

# Main Courses
MenuItem.objects.create(
    category=main_courses,
    name="Grilled Salmon",
    description="Atlantic salmon with seasonal vegetables",
    price=Decimal("95.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=main_courses,
    name="Beef Burger",
    description="Angus beef burger with fries",
    price=Decimal("68.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=main_courses,
    name="Chicken Tikka Masala",
    description="Indian-style chicken curry with rice",
    price=Decimal("72.00"),
    is_available=True,
)

# Desserts
MenuItem.objects.create(
    category=hotel_desserts,
    name="Chocolate Cake",
    description="Rich chocolate layer cake",
    price=Decimal("32.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=hotel_desserts,
    name="Ice Cream Sundae",
    description="Three scoops with toppings",
    price=Decimal("28.00"),
    is_available=True,
    is_vegetarian=True,
)

# Beverages
MenuItem.objects.create(
    category=hotel_drinks,
    name="Fresh Orange Juice",
    description="Freshly squeezed",
    price=Decimal("15.00"),
    is_available=True,
    is_vegan=True,
)
MenuItem.objects.create(
    category=hotel_drinks,
    name="Coffee",
    description="Freshly brewed",
    price=Decimal("12.00"),
    is_available=True,
    is_vegan=True,
)

print("   ✓ Created menu items")
print(f"   ✅ Hotel complete!\n")

# ============================================================================
# 3. CREATE CAFÉ: Morning Brew Café
# ============================================================================
print("3️⃣ Creating CAFÉ: Morning Brew Café...")

morning_brew = Hotel.objects.create(
    name="Morning Brew Café",
    business_type=Hotel.BusinessType.CAFE,
    slug="morning-brew-cafe",
    currency_code="QAR",
    timezone="Asia/Qatar",
    is_active=True,
    enable_table_management=True,
    enable_waiter_alerts=True,
    enable_room_charging=False,
)
print(f"   ✓ Created: {morning_brew}")

# Create tables
print("   Creating tables...")
for i in range(1, 11):  # 10 tables
    Table.objects.create(
        hotel=morning_brew,
        table_number=str(i),
        capacity=2 if i <= 6 else 4,
        status=Table.TableStatus.AVAILABLE,
    )
print("   ✓ Created 10 tables")

# Create categories
print("   Creating menu categories...")
coffee_cat = Category.objects.create(
    hotel=morning_brew,
    name="Coffee",
    sort_order=1
)
pastries_cat = Category.objects.create(
    hotel=morning_brew,
    name="Pastries",
    sort_order=2
)
light_bites = Category.objects.create(
    hotel=morning_brew,
    name="Light Bites",
    sort_order=3
)

# Create menu items
print("   Creating menu items...")

# Coffee
MenuItem.objects.create(
    category=coffee_cat,
    name="Espresso",
    description="Strong Italian coffee",
    price=Decimal("12.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=coffee_cat,
    name="Cappuccino",
    description="Espresso with steamed milk foam",
    price=Decimal("15.00"),
    is_available=True,
)
MenuItem.objects.create(
    category=coffee_cat,
    name="Latte",
    description="Espresso with steamed milk",
    price=Decimal("16.00"),
    is_available=True,
)

# Pastries
MenuItem.objects.create(
    category=pastries_cat,
    name="Croissant",
    description="Buttery French pastry",
    price=Decimal("18.00"),
    is_available=True,
    is_vegetarian=True,
)
MenuItem.objects.create(
    category=pastries_cat,
    name="Chocolate Muffin",
    description="Rich chocolate muffin",
    price=Decimal("20.00"),
    is_available=True,
    is_vegetarian=True,
)

# Light Bites
MenuItem.objects.create(
    category=light_bites,
    name="Avocado Toast",
    description="Smashed avocado on sourdough",
    price=Decimal("32.00"),
    is_available=True,
    is_vegetarian=True,
    is_vegan=True,
)
MenuItem.objects.create(
    category=light_bites,
    name="Greek Yogurt Bowl",
    description="Yogurt with granola and berries",
    price=Decimal("28.00"),
    is_available=True,
    is_vegetarian=True,
)

print("   ✓ Created menu items")
print(f"   ✅ Café complete!\n")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*60)
print("✅ SAMPLE DATA CREATION COMPLETE!")
print("="*60)
print("\n📊 Summary:")
print(f"   • {Hotel.objects.count()} Businesses created")
print(f"   • {Category.objects.count()} Categories created")
print(f"   • {MenuItem.objects.count()} Menu items created")
print(f"   • {Table.objects.count()} Tables created")

print("\n🔗 Access URLs:")
print(f"   Restaurant Menu: http://localhost:8000/menu/bella-italia-doha/?location=5")
print(f"   Restaurant Kitchen: http://localhost:8000/kitchen/bella-italia-doha/")
print(f"   Hotel Menu: http://localhost:8000/menu/grand-plaza-doha/?location=305")
print(f"   Hotel Kitchen: http://localhost:8000/kitchen/grand-plaza-doha/")
print(f"   Café Menu: http://localhost:8000/menu/morning-brew-cafe/?location=3")
print(f"   Café Kitchen: http://localhost:8000/kitchen/morning-brew-cafe/")
print(f"   Admin Panel: http://localhost:8000/admin/")

print("\n💡 Next Steps:")
print("   1. Create a superuser: python manage.py createsuperuser")
print("   2. Run the server: python manage.py runserver")
print("   3. Visit the URLs above to test the system!")
print("   4. Use the admin panel to manage businesses and orders")
print("\n" + "="*60 + "\n")
