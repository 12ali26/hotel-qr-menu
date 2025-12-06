"""
AI Menu Extractor - Uses Vision AI to extract menu data from photos
Supports OpenAI GPT-4 Vision and Anthropic Claude 3.5 Sonnet
"""
import base64
import json
import logging
import os
from io import BytesIO
from typing import Dict, List, Optional

from PIL import Image

logger = logging.getLogger(__name__)


def extract_menu_from_image(image_file, business_type: str = "RESTAURANT") -> Optional[Dict]:
    """
    Extract menu data from an uploaded image using AI Vision.

    Args:
        image_file: Django UploadedFile object (menu photo)
        business_type: Type of business (RESTAURANT, CAFE, HOTEL, etc.)

    Returns:
        Dictionary with structure:
        {
            "categories": [
                {
                    "name": "Starters",
                    "sort_order": 0,
                    "items": [
                        {
                            "name": "Caesar Salad",
                            "description": "Fresh romaine lettuce with parmesan",
                            "price": 12.99,
                            "is_vegetarian": True,
                            "spice_level": "NONE",
                            "allergens": "Dairy, Eggs",
                            "prep_time_minutes": 10
                        }
                    ]
                }
            ]
        }
    """
    try:
        # Get OpenAI API key from environment
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not set. AI menu extraction unavailable.")
            return None

        # Import OpenAI library
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("OpenAI library not installed. Run: pip install openai")
            return None

        # Initialize OpenAI client
        client = OpenAI(api_key=api_key)

        # Convert image to base64
        image_bytes = image_file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')

        # Reset file pointer for potential future use
        image_file.seek(0)

        # Construct prompt for AI
        prompt = f"""
You are a menu digitization expert. Analyze this {business_type.lower()} menu photo and extract ALL menu items with their details.

Extract the following information in JSON format:

{{
  "categories": [
    {{
      "name": "Category Name",
      "sort_order": 0,
      "items": [
        {{
          "name": "Item Name",
          "description": "Brief description if available",
          "price": 12.99,
          "is_vegetarian": true/false,
          "is_vegan": true/false,
          "is_gluten_free": true/false,
          "spice_level": "NONE" | "MILD" | "MEDIUM" | "HOT" | "EXTRA_HOT",
          "allergens": "Comma-separated allergens if mentioned",
          "prep_time_minutes": 15
        }}
      ]
    }}
  ]
}}

Important guidelines:
1. Identify ALL categories (Starters, Mains, Desserts, Drinks, etc.)
2. Extract ALL items under each category
3. Include prices (convert to decimal format)
4. Infer dietary tags from item names/descriptions (e.g., "Veggie Burger" = vegetarian)
5. Guess spice level from indicators like 🌶️, "spicy", "hot"
6. List common allergens if mentioned (nuts, dairy, gluten, shellfish, eggs)
7. Estimate prep_time_minutes based on dish complexity (10-60 minutes)
8. If description is not visible, create a brief one based on the item name
9. Sort categories logically (Starters → Mains → Sides → Desserts → Drinks)
10. Return ONLY valid JSON, no other text

Be thorough and extract every single item visible in the menu.
"""

        # Call GPT-4 Vision API
        response = client.chat.completions.create(
            model="gpt-4o",  # GPT-4 Vision model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"  # High detail for better extraction
                            }
                        }
                    ]
                }
            ],
            max_tokens=4096,
            temperature=0.1,  # Low temperature for consistent output
        )

        # Extract response
        ai_response = response.choices[0].message.content
        logger.info(f"AI Vision response received: {len(ai_response)} characters")

        # Parse JSON response
        # Remove markdown code blocks if present
        if ai_response.startswith("```json"):
            ai_response = ai_response.replace("```json", "").replace("```", "").strip()
        elif ai_response.startswith("```"):
            ai_response = ai_response.replace("```", "").strip()

        menu_data = json.loads(ai_response)

        logger.info(f"Successfully extracted {len(menu_data.get('categories', []))} categories from menu image")
        return menu_data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        logger.error(f"AI Response: {ai_response[:500]}...")
        return None
    except Exception as e:
        logger.error(f"Error extracting menu from image: {type(e).__name__}: {str(e)}")
        return None


def validate_menu_data(menu_data: Dict) -> bool:
    """
    Validate the structure of extracted menu data.

    Args:
        menu_data: Dictionary from extract_menu_from_image()

    Returns:
        True if valid, False otherwise
    """
    if not isinstance(menu_data, dict):
        return False

    if "categories" not in menu_data:
        return False

    if not isinstance(menu_data["categories"], list):
        return False

    for category in menu_data["categories"]:
        if not isinstance(category, dict):
            return False
        if "name" not in category or "items" not in category:
            return False
        if not isinstance(category["items"], list):
            return False

        for item in category["items"]:
            if not isinstance(item, dict):
                return False
            if "name" not in item or "price" not in item:
                return False

    return True


def estimate_extraction_confidence(menu_data: Dict) -> float:
    """
    Estimate the confidence level of the extraction (0.0 to 1.0).

    Args:
        menu_data: Dictionary from extract_menu_from_image()

    Returns:
        Confidence score between 0.0 and 1.0
    """
    if not validate_menu_data(menu_data):
        return 0.0

    confidence = 0.5  # Base confidence

    # More categories = higher confidence
    num_categories = len(menu_data.get("categories", []))
    if num_categories >= 3:
        confidence += 0.1
    if num_categories >= 5:
        confidence += 0.1

    # Check for descriptions
    total_items = 0
    items_with_descriptions = 0

    for category in menu_data.get("categories", []):
        for item in category.get("items", []):
            total_items += 1
            if item.get("description"):
                items_with_descriptions += 1

    if total_items > 0:
        description_ratio = items_with_descriptions / total_items
        confidence += description_ratio * 0.2

    # More items = higher confidence (up to a point)
    if total_items >= 10:
        confidence += 0.1

    return min(confidence, 1.0)
