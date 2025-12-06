"""
CSV Menu Importer - Bulk import menu items from CSV/Excel files
Supports CSV, TSV, and Excel formats with flexible column mapping
"""
import csv
import io
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Column mapping - flexible column names that map to our fields
COLUMN_MAPPING = {
    'category': ['category', 'category_name', 'section', 'type'],
    'name': ['name', 'item_name', 'dish', 'dish_name', 'item'],
    'description': ['description', 'desc', 'details', 'info'],
    'price': ['price', 'cost', 'amount'],
    'is_available': ['available', 'is_available', 'in_stock', 'active'],
    'is_vegetarian': ['vegetarian', 'is_vegetarian', 'veg'],
    'is_vegan': ['vegan', 'is_vegan'],
    'is_featured': ['featured', 'is_featured', 'highlight'],
    'is_daily_special': ['special', 'daily_special', 'is_daily_special', 'today_special'],
    'spice_level': ['spice', 'spice_level', 'heat', 'heat_level'],
    'allergens': ['allergens', 'allergen', 'allergies'],
    'prep_time_minutes': ['prep_time', 'prep_time_minutes', 'cooking_time', 'time'],
    'customization_options': ['customization', 'options', 'custom_options'],
}


def normalize_column_name(column: str) -> str:
    """Normalize column name for matching."""
    return column.lower().strip().replace(' ', '_').replace('-', '_')


def map_columns(headers: List[str]) -> Dict[str, int]:
    """
    Map CSV headers to MenuItem fields.

    Returns dict like: {'name': 0, 'price': 1, 'category': 2, ...}
    where values are column indices.
    """
    mapped = {}
    normalized_headers = [normalize_column_name(h) for h in headers]

    for field, possible_names in COLUMN_MAPPING.items():
        for idx, header in enumerate(normalized_headers):
            if header in possible_names:
                mapped[field] = idx
                break

    return mapped


def parse_boolean(value: str) -> bool:
    """Parse various boolean representations."""
    if not value:
        return False

    value = str(value).lower().strip()
    return value in ['true', 'yes', 'y', '1', 'on', 'x', '✓', '✔']


def parse_price(value: str) -> Optional[Decimal]:
    """Parse price from string, handling currency symbols."""
    if not value:
        return None

    # Remove common currency symbols and whitespace
    cleaned = str(value).strip().replace('$', '').replace('€', '').replace('£', '')
    cleaned = cleaned.replace(',', '').replace(' ', '')

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def parse_spice_level(value: str) -> str:
    """Parse spice level from various formats."""
    if not value:
        return "NONE"

    value = str(value).lower().strip()

    # Map common variations
    mapping = {
        'none': 'NONE',
        'no': 'NONE',
        '0': 'NONE',
        'mild': 'MILD',
        'low': 'MILD',
        '1': 'MILD',
        'medium': 'MEDIUM',
        'med': 'MEDIUM',
        '2': 'MEDIUM',
        'hot': 'HOT',
        'spicy': 'HOT',
        'high': 'HOT',
        '3': 'HOT',
        'extra_hot': 'EXTRA_HOT',
        'extra hot': 'EXTRA_HOT',
        'very_hot': 'EXTRA_HOT',
        'very hot': 'EXTRA_HOT',
        '4': 'EXTRA_HOT',
    }

    return mapping.get(value, 'NONE')


def parse_prep_time(value: str) -> int:
    """Parse prep time in minutes."""
    if not value:
        return 15  # Default

    try:
        # Extract just the number
        cleaned = str(value).strip().split()[0]
        return int(float(cleaned))
    except (ValueError, IndexError):
        return 15


def detect_delimiter(file_content: str) -> str:
    """Detect CSV delimiter (comma, semicolon, or tab)."""
    # Try to detect based on first line
    first_line = file_content.split('\n')[0]

    if '\t' in first_line:
        return '\t'
    elif ';' in first_line and first_line.count(';') > first_line.count(','):
        return ';'
    else:
        return ','


def import_menu_from_csv(csv_file, encoding: str = 'utf-8') -> Tuple[Optional[Dict], List[str]]:
    """
    Import menu data from CSV file.

    Args:
        csv_file: Django UploadedFile object
        encoding: File encoding (default: utf-8)

    Returns:
        Tuple of (menu_data, errors)
        menu_data structure:
        {
            "categories": {
                "Appetizers": [
                    {
                        "name": "Spring Rolls",
                        "description": "Crispy vegetable rolls",
                        "price": 8.99,
                        "is_vegetarian": True,
                        ...
                    }
                ]
            },
            "stats": {
                "total_items": 25,
                "total_categories": 5,
                "skipped_rows": 2
            }
        }
    """
    errors = []
    categories = {}
    total_items = 0
    skipped_rows = 0

    try:
        # Read file content
        content = csv_file.read()

        # Try to decode with specified encoding, fallback to utf-8-sig (handles BOM)
        try:
            text_content = content.decode(encoding)
        except UnicodeDecodeError:
            text_content = content.decode('utf-8-sig')

        # Detect delimiter
        delimiter = detect_delimiter(text_content)

        # Parse CSV
        csv_reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)

        # Read headers
        try:
            headers = next(csv_reader)
        except StopIteration:
            errors.append("CSV file is empty")
            return None, errors

        # Map columns
        column_map = map_columns(headers)

        # Validate required columns
        if 'name' not in column_map:
            errors.append("Required column 'name' not found. Please include a column for item names.")
            return None, errors

        if 'price' not in column_map:
            errors.append("Required column 'price' not found. Please include a column for prices.")
            return None, errors

        # Process rows
        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (header is row 1)
            if not row or not any(row):  # Skip empty rows
                continue

            try:
                # Get category (default to "Uncategorized")
                category_idx = column_map.get('category')
                category_name = row[category_idx].strip() if category_idx is not None and len(row) > category_idx else "Uncategorized"
                if not category_name:
                    category_name = "Uncategorized"

                # Get name (required)
                name_idx = column_map['name']
                name = row[name_idx].strip() if len(row) > name_idx else ""
                if not name:
                    skipped_rows += 1
                    errors.append(f"Row {row_num}: Missing item name, skipped")
                    continue

                # Get price (required)
                price_idx = column_map['price']
                price_str = row[price_idx].strip() if len(row) > price_idx else ""
                price = parse_price(price_str)
                if price is None:
                    skipped_rows += 1
                    errors.append(f"Row {row_num} ({name}): Invalid price '{price_str}', skipped")
                    continue

                # Parse other fields
                item_data = {
                    'name': name,
                    'price': float(price),
                    'description': '',
                    'is_available': True,
                    'is_vegetarian': False,
                    'is_vegan': False,
                    'is_featured': False,
                    'is_daily_special': False,
                    'spice_level': 'NONE',
                    'allergens': '',
                    'prep_time_minutes': 15,
                }

                # Optional: description
                if 'description' in column_map:
                    desc_idx = column_map['description']
                    if len(row) > desc_idx:
                        item_data['description'] = row[desc_idx].strip()

                # Optional: boolean fields
                for field in ['is_available', 'is_vegetarian', 'is_vegan', 'is_featured', 'is_daily_special']:
                    if field in column_map:
                        idx = column_map[field]
                        if len(row) > idx:
                            item_data[field] = parse_boolean(row[idx])

                # Optional: spice level
                if 'spice_level' in column_map:
                    idx = column_map['spice_level']
                    if len(row) > idx:
                        item_data['spice_level'] = parse_spice_level(row[idx])

                # Optional: allergens
                if 'allergens' in column_map:
                    idx = column_map['allergens']
                    if len(row) > idx:
                        item_data['allergens'] = row[idx].strip()

                # Optional: prep time
                if 'prep_time_minutes' in column_map:
                    idx = column_map['prep_time_minutes']
                    if len(row) > idx:
                        item_data['prep_time_minutes'] = parse_prep_time(row[idx])

                # Add to categories
                if category_name not in categories:
                    categories[category_name] = []

                categories[category_name].append(item_data)
                total_items += 1

            except Exception as e:
                skipped_rows += 1
                errors.append(f"Row {row_num}: Error processing - {str(e)}")
                continue

        # Check if we got any items
        if total_items == 0:
            errors.append("No valid menu items found in CSV file")
            return None, errors

        # Build result
        menu_data = {
            'categories': categories,
            'stats': {
                'total_items': total_items,
                'total_categories': len(categories),
                'skipped_rows': skipped_rows,
            }
        }

        return menu_data, errors

    except Exception as e:
        logger.error(f"CSV import failed: {str(e)}")
        errors.append(f"Failed to parse CSV file: {str(e)}")
        return None, errors


def validate_csv_data(menu_data: Dict) -> bool:
    """Validate the structure of imported menu data."""
    if not menu_data:
        return False

    if 'categories' not in menu_data:
        return False

    if not menu_data['categories']:
        return False

    # Check at least one category has items
    for items in menu_data['categories'].values():
        if items and len(items) > 0:
            return True

    return False


def generate_csv_template() -> str:
    """Generate a CSV template with example data."""
    template = """category,name,description,price,is_vegetarian,is_vegan,spice_level,allergens,prep_time_minutes,is_featured,is_daily_special
Appetizers,Spring Rolls,Crispy vegetable spring rolls with sweet chili sauce,8.99,yes,yes,mild,Soy,10,no,no
Appetizers,Caesar Salad,Fresh romaine lettuce with parmesan and croutons,12.50,yes,no,none,Dairy; Eggs; Gluten,5,no,no
Main Course,Grilled Salmon,Atlantic salmon with lemon butter sauce,24.99,no,no,none,Fish,25,yes,no
Main Course,Vegetable Curry,Mixed vegetables in coconut curry sauce,16.99,yes,yes,medium,none,20,no,yes
Main Course,Beef Burger,Angus beef burger with fries,18.50,no,no,none,Gluten; Dairy,15,no,no
Desserts,Chocolate Cake,Rich chocolate cake with vanilla ice cream,8.99,yes,no,none,Dairy; Eggs; Gluten,5,no,no
Beverages,Fresh Orange Juice,Freshly squeezed orange juice,5.99,yes,yes,none,none,2,no,no
Beverages,Cappuccino,Italian espresso with steamed milk,4.50,yes,no,none,Dairy,3,no,no"""

    return template
