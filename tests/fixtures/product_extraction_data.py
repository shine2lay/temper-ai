"""Product extraction test dataset for M5 validation.

This module provides 50 realistic product descriptions with ground truth JSON
for testing product information extraction quality metrics.

Each test case includes:
- description: Natural language product description
- ground_truth: Expected structured JSON output
"""

from typing import Any, Dict, List

# Product extraction test dataset (50 test cases)
PRODUCT_TEST_CASES: List[Dict[str, Any]] = [
    # Electronics
    {
        "description": "Apple MacBook Pro 16-inch with M3 Max chip, 36GB RAM, 1TB SSD, Space Black. Features Liquid Retina XDR display, 140W USB-C Power Adapter, and up to 22 hours battery life. Price: $3,499.00",
        "ground_truth": {
            "name": "Apple MacBook Pro 16-inch",
            "brand": "Apple",
            "category": "Electronics",
            "specifications": {
                "processor": "M3 Max chip",
                "ram": "36GB",
                "storage": "1TB SSD",
                "display": "Liquid Retina XDR",
                "battery_life": "22 hours"
            },
            "color": "Space Black",
            "price": 3499.00,
            "currency": "USD"
        }
    },
    {
        "description": "Samsung 65\" QLED 4K Smart TV QN90C with Quantum HDR, Neural Quantum Processor 4K, 120Hz refresh rate. Includes Alexa and Google Assistant. $1,799.99.",
        "ground_truth": {
            "name": "Samsung 65\" QLED 4K Smart TV QN90C",
            "brand": "Samsung",
            "category": "Electronics",
            "specifications": {
                "screen_size": "65 inches",
                "resolution": "4K",
                "refresh_rate": "120Hz",
                "processor": "Neural Quantum Processor 4K",
                "hdr": "Quantum HDR"
            },
            "features": ["Alexa", "Google Assistant"],
            "price": 1799.99,
            "currency": "USD"
        }
    },
    {
        "description": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones - Black. 30-hour battery, LDAC/DSEE Extreme support, multipoint connection. $399.99",
        "ground_truth": {
            "name": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
            "brand": "Sony",
            "category": "Electronics",
            "specifications": {
                "battery_life": "30 hours",
                "audio_codecs": ["LDAC", "DSEE Extreme"],
                "connectivity": "Wireless"
            },
            "color": "Black",
            "features": ["Noise Cancelling", "Multipoint Connection"],
            "price": 399.99,
            "currency": "USD"
        }
    },

    # Home & Kitchen
    {
        "description": "Ninja Foodi 8-Quart 9-in-1 Deluxe XL Pressure Cooker. Stainless steel. Pressure cook, air fry, steam, slow cook. $179.99",
        "ground_truth": {
            "name": "Ninja Foodi 8-Quart 9-in-1 Deluxe XL Pressure Cooker",
            "brand": "Ninja",
            "category": "Home & Kitchen",
            "specifications": {
                "capacity": "8 quarts",
                "material": "Stainless steel",
                "functions": 9
            },
            "features": ["Pressure cook", "Air fry", "Steam", "Slow cook"],
            "price": 179.99,
            "currency": "USD"
        }
    },
    {
        "description": "Dyson V15 Detect Cordless Vacuum - Nickel/Iron. 60-minute runtime, laser dust detection, HEPA filtration. Includes 6 attachments. $699.99",
        "ground_truth": {
            "name": "Dyson V15 Detect Cordless Vacuum",
            "brand": "Dyson",
            "category": "Home & Kitchen",
            "specifications": {
                "runtime": "60 minutes",
                "filtration": "HEPA",
                "attachments": 6
            },
            "color": "Nickel/Iron",
            "features": ["Laser dust detection", "Cordless"],
            "price": 699.99,
            "currency": "USD"
        }
    },

    # Clothing
    {
        "description": "Levi's 501 Original Fit Men's Jeans - Dark Stonewash, size 32x32. 100% cotton denim. Button fly. $69.50",
        "ground_truth": {
            "name": "Levi's 501 Original Fit Men's Jeans",
            "brand": "Levi's",
            "category": "Clothing",
            "specifications": {
                "material": "100% cotton denim",
                "fit": "Original Fit",
                "closure": "Button fly"
            },
            "color": "Dark Stonewash",
            "size": "32x32",
            "gender": "Men",
            "price": 69.50,
            "currency": "USD"
        }
    },
    {
        "description": "Patagonia Women's Better Sweater Fleece Jacket - Navy Blue, Medium. 100% recycled polyester fleece. Full-zip, stand-up collar. $139.00",
        "ground_truth": {
            "name": "Patagonia Women's Better Sweater Fleece Jacket",
            "brand": "Patagonia",
            "category": "Clothing",
            "specifications": {
                "material": "100% recycled polyester fleece",
                "closure": "Full-zip",
                "collar": "Stand-up collar"
            },
            "color": "Navy Blue",
            "size": "Medium",
            "gender": "Women",
            "price": 139.00,
            "currency": "USD"
        }
    },

    # Books
    {
        "description": "The Pragmatic Programmer: Your Journey To Mastery (20th Anniversary Edition) by David Thomas and Andrew Hunt. Paperback, 352 pages. Published by Addison-Wesley. $34.99",
        "ground_truth": {
            "name": "The Pragmatic Programmer: Your Journey To Mastery (20th Anniversary Edition)",
            "brand": "Addison-Wesley",
            "category": "Books",
            "specifications": {
                "format": "Paperback",
                "pages": 352,
                "edition": "20th Anniversary Edition"
            },
            "authors": ["David Thomas", "Andrew Hunt"],
            "publisher": "Addison-Wesley",
            "price": 34.99,
            "currency": "USD"
        }
    },
    {
        "description": "Atomic Habits by James Clear. Hardcover, 320 pages. Self-help/Psychology. ISBN: 978-0735211292. $27.00",
        "ground_truth": {
            "name": "Atomic Habits",
            "brand": "Avery",
            "category": "Books",
            "specifications": {
                "format": "Hardcover",
                "pages": 320,
                "isbn": "978-0735211292"
            },
            "authors": ["James Clear"],
            "genre": ["Self-help", "Psychology"],
            "price": 27.00,
            "currency": "USD"
        }
    },

    # Sports & Outdoors
    {
        "description": "REI Co-op Half Dome SL 2+ Tent. 3-season, sleeps 2, weighs 4 lbs 2 oz. Includes footprint and gear loft. Color: Green. $349.00",
        "ground_truth": {
            "name": "REI Co-op Half Dome SL 2+ Tent",
            "brand": "REI Co-op",
            "category": "Sports & Outdoors",
            "specifications": {
                "capacity": "2 people",
                "weight": "4 lbs 2 oz",
                "seasons": "3-season"
            },
            "color": "Green",
            "includes": ["Footprint", "Gear loft"],
            "price": 349.00,
            "currency": "USD"
        }
    },
    {
        "description": "Hydro Flask 32 oz Wide Mouth Water Bottle with Flex Cap. Stainless steel, vacuum insulated. Keeps cold 24hrs, hot 12hrs. Pacific blue. $44.95",
        "ground_truth": {
            "name": "Hydro Flask 32 oz Wide Mouth Water Bottle",
            "brand": "Hydro Flask",
            "category": "Sports & Outdoors",
            "specifications": {
                "capacity": "32 oz",
                "material": "Stainless steel",
                "insulation": "Vacuum insulated",
                "cold_retention": "24 hours",
                "hot_retention": "12 hours"
            },
            "color": "Pacific blue",
            "cap_type": "Flex Cap",
            "price": 44.95,
            "currency": "USD"
        }
    },

    # Complex/Edge Cases
    {
        "description": "Professional camera bundle: Canon EOS R5 mirrorless body ($3,899), RF 24-70mm f/2.8 lens ($2,299), 2x 64GB CFexpress cards ($299 each), battery grip ($349). Total package: $7,145",
        "ground_truth": {
            "name": "Canon EOS R5 Professional Bundle",
            "brand": "Canon",
            "category": "Electronics",
            "specifications": {
                "camera_body": "EOS R5 mirrorless",
                "lens": "RF 24-70mm f/2.8",
                "memory_cards": "2x 64GB CFexpress"
            },
            "includes": ["Camera body", "Lens", "Memory cards", "Battery grip"],
            "price": 7145.00,
            "currency": "USD"
        }
    },
    {
        "description": "Organic Fair Trade Colombian Coffee - Medium Roast. Whole bean, 2 lb bag. Notes of chocolate and caramel. Rainforest Alliance Certified. $24.99",
        "ground_truth": {
            "name": "Organic Fair Trade Colombian Coffee - Medium Roast",
            "brand": "Generic",
            "category": "Food & Beverage",
            "specifications": {
                "roast": "Medium",
                "form": "Whole bean",
                "weight": "2 lb",
                "flavor_notes": ["Chocolate", "Caramel"]
            },
            "certifications": ["Organic", "Fair Trade", "Rainforest Alliance"],
            "origin": "Colombia",
            "price": 24.99,
            "currency": "USD"
        }
    },
    {
        "description": "IKEA KALLAX 4x4 Shelf Unit - White. 57 7/8x57 7/8\". Made of particleboard with paper foil finish. Assembly required. $139.00",
        "ground_truth": {
            "name": "IKEA KALLAX 4x4 Shelf Unit",
            "brand": "IKEA",
            "category": "Furniture",
            "specifications": {
                "dimensions": "57 7/8 x 57 7/8 inches",
                "material": "Particleboard with paper foil finish",
                "configuration": "4x4"
            },
            "color": "White",
            "assembly_required": True,
            "price": 139.00,
            "currency": "USD"
        }
    },
    {
        "description": "Xbox Series X 1TB Console Bundle with 3 months Game Pass Ultimate and extra controller. Black. $549.99",
        "ground_truth": {
            "name": "Xbox Series X 1TB Console Bundle",
            "brand": "Microsoft",
            "category": "Electronics",
            "specifications": {
                "storage": "1TB",
                "subscription_included": "3 months Game Pass Ultimate"
            },
            "color": "Black",
            "includes": ["Console", "Extra controller", "Game Pass Ultimate"],
            "price": 549.99,
            "currency": "USD"
        }
    },
    {
        "description": "Blue Apron meal kit: 3 meals for 2 people per week. Organic ingredients, chef-designed recipes. Delivered weekly. $69.95/week",
        "ground_truth": {
            "name": "Blue Apron Meal Kit - 3 Meals Plan",
            "brand": "Blue Apron",
            "category": "Food & Beverage",
            "specifications": {
                "meals_per_week": 3,
                "servings_per_meal": 2,
                "ingredients": "Organic",
                "delivery": "Weekly"
            },
            "price": 69.95,
            "currency": "USD",
            "pricing_period": "per week"
        }
    },

    # Minimal information cases
    {
        "description": "Red Nike running shoes, size 10, $85",
        "ground_truth": {
            "name": "Nike Running Shoes",
            "brand": "Nike",
            "category": "Footwear",
            "specifications": {
                "type": "Running"
            },
            "color": "Red",
            "size": "10",
            "price": 85.00,
            "currency": "USD"
        }
    },
    {
        "description": "Stainless steel chef's knife, 8 inch, Wüsthof, $149.95",
        "ground_truth": {
            "name": "Wüsthof Chef's Knife",
            "brand": "Wüsthof",
            "category": "Home & Kitchen",
            "specifications": {
                "material": "Stainless steel",
                "length": "8 inches",
                "type": "Chef's knife"
            },
            "price": 149.95,
            "currency": "USD"
        }
    },

    # Additional diverse cases
    {
        "description": "Casper Original Mattress - Queen size. 11\" foam layers with zoned support. 100-night trial, 10-year warranty. $1,095",
        "ground_truth": {
            "name": "Casper Original Mattress",
            "brand": "Casper",
            "category": "Furniture",
            "specifications": {
                "size": "Queen",
                "thickness": "11 inches",
                "material": "Foam",
                "support_type": "Zoned support"
            },
            "warranty": "10 years",
            "trial_period": "100 nights",
            "price": 1095.00,
            "currency": "USD"
        }
    },
    {
        "description": "The North Face Borealis Backpack - 28L, laptop sleeve fits 15\", FlexVent suspension system. TNF Black. $99.00",
        "ground_truth": {
            "name": "The North Face Borealis Backpack",
            "brand": "The North Face",
            "category": "Sports & Outdoors",
            "specifications": {
                "capacity": "28L",
                "laptop_size": "15 inches",
                "suspension": "FlexVent"
            },
            "color": "TNF Black",
            "price": 99.00,
            "currency": "USD"
        }
    },
    {
        "description": "Dell UltraSharp 27\" 4K USB-C Monitor (U2723DE). IPS panel, 99% sRGB, 60Hz, height-adjustable stand. VESA mount compatible. $679.99",
        "ground_truth": {
            "name": "Dell UltraSharp 27\" 4K USB-C Monitor (U2723DE)",
            "brand": "Dell",
            "category": "Electronics",
            "specifications": {
                "screen_size": "27 inches",
                "resolution": "4K",
                "panel_type": "IPS",
                "color_gamut": "99% sRGB",
                "refresh_rate": "60Hz"
            },
            "features": ["USB-C", "Height-adjustable stand", "VESA mount compatible"],
            "price": 679.99,
            "currency": "USD"
        }
    },
    {
        "description": "KitchenAid Artisan Stand Mixer 5-Quart - Empire Red. 10-speed, tilt-head design. Includes flat beater, dough hook, wire whip. $429.99",
        "ground_truth": {
            "name": "KitchenAid Artisan Stand Mixer 5-Quart",
            "brand": "KitchenAid",
            "category": "Home & Kitchen",
            "specifications": {
                "capacity": "5 quarts",
                "speeds": 10,
                "design": "Tilt-head"
            },
            "color": "Empire Red",
            "includes": ["Flat beater", "Dough hook", "Wire whip"],
            "price": 429.99,
            "currency": "USD"
        }
    },
    {
        "description": "Instant Pot Duo 7-in-1 Electric Pressure Cooker, 6 Qt. Stainless steel. Pressure cook, slow cook, rice cooker, steamer, sauté, yogurt maker, warmer. $89.99",
        "ground_truth": {
            "name": "Instant Pot Duo 7-in-1 Electric Pressure Cooker",
            "brand": "Instant Pot",
            "category": "Home & Kitchen",
            "specifications": {
                "capacity": "6 quarts",
                "functions": 7,
                "material": "Stainless steel"
            },
            "features": ["Pressure cook", "Slow cook", "Rice cooker", "Steamer", "Sauté", "Yogurt maker", "Warmer"],
            "price": 89.99,
            "currency": "USD"
        }
    },
    {
        "description": "Anker PowerCore 20000mAh Portable Charger. Dual USB-A ports, PowerIQ 2.0. Charges iPhone 13 4.5 times. Black. $49.99",
        "ground_truth": {
            "name": "Anker PowerCore 20000mAh Portable Charger",
            "brand": "Anker",
            "category": "Electronics",
            "specifications": {
                "capacity": "20000mAh",
                "ports": "Dual USB-A",
                "technology": "PowerIQ 2.0",
                "charging_capacity": "iPhone 13 4.5 times"
            },
            "color": "Black",
            "price": 49.99,
            "currency": "USD"
        }
    },
    {
        "description": "Bose QuietComfort 45 Wireless Headphones. Active noise cancellation, 24-hour battery, Bluetooth 5.1. Triple Black. $329.00",
        "ground_truth": {
            "name": "Bose QuietComfort 45 Wireless Headphones",
            "brand": "Bose",
            "category": "Electronics",
            "specifications": {
                "battery_life": "24 hours",
                "bluetooth": "5.1",
                "connectivity": "Wireless"
            },
            "color": "Triple Black",
            "features": ["Active noise cancellation"],
            "price": 329.00,
            "currency": "USD"
        }
    },
    {
        "description": "Lodge Cast Iron Skillet 12-inch. Pre-seasoned, oven safe to 500°F. Made in USA. $34.90",
        "ground_truth": {
            "name": "Lodge Cast Iron Skillet",
            "brand": "Lodge",
            "category": "Home & Kitchen",
            "specifications": {
                "size": "12 inches",
                "material": "Cast iron",
                "oven_safe_temp": "500°F",
                "seasoning": "Pre-seasoned"
            },
            "country_of_origin": "USA",
            "price": 34.90,
            "currency": "USD"
        }
    },
    {
        "description": "Kindle Paperwhite Signature Edition (32 GB) - Ad-Free. 6.8\" display, wireless charging, auto-adjusting front light. $189.99",
        "ground_truth": {
            "name": "Kindle Paperwhite Signature Edition",
            "brand": "Amazon",
            "category": "Electronics",
            "specifications": {
                "storage": "32 GB",
                "display_size": "6.8 inches",
                "ad_free": True
            },
            "features": ["Wireless charging", "Auto-adjusting front light"],
            "price": 189.99,
            "currency": "USD"
        }
    },
    {
        "description": "GoPro HERO11 Black Action Camera. 5.3K60 video, 27MP photos, HyperSmooth 5.0 stabilization. Waterproof to 33ft. $399.99",
        "ground_truth": {
            "name": "GoPro HERO11 Black Action Camera",
            "brand": "GoPro",
            "category": "Electronics",
            "specifications": {
                "video_resolution": "5.3K60",
                "photo_resolution": "27MP",
                "stabilization": "HyperSmooth 5.0",
                "waterproof_depth": "33 feet"
            },
            "price": 399.99,
            "currency": "USD"
        }
    },
    {
        "description": "Herman Miller Aeron Chair Size B. Fully adjustable, PostureFit SL lumbar support, tilt limiter. Graphite/Carbon. $1,695.00",
        "ground_truth": {
            "name": "Herman Miller Aeron Chair",
            "brand": "Herman Miller",
            "category": "Furniture",
            "specifications": {
                "size": "B",
                "adjustability": "Fully adjustable",
                "lumbar_support": "PostureFit SL",
                "tilt_limiter": True
            },
            "color": "Graphite/Carbon",
            "price": 1695.00,
            "currency": "USD"
        }
    },
    {
        "description": "Vitamix 5200 Blender - Black. 64 oz container, variable speed control, 2 HP motor. 7-year warranty. $449.95",
        "ground_truth": {
            "name": "Vitamix 5200 Blender",
            "brand": "Vitamix",
            "category": "Home & Kitchen",
            "specifications": {
                "capacity": "64 oz",
                "motor_power": "2 HP",
                "speed_control": "Variable"
            },
            "color": "Black",
            "warranty": "7 years",
            "price": 449.95,
            "currency": "USD"
        }
    },
    {
        "description": "Peloton Bike+ with 24\" HD touchscreen. Auto-follow resistance, rotating screen, Dolby Atmos speakers. Requires All-Access membership ($44/mo). $2,495",
        "ground_truth": {
            "name": "Peloton Bike+",
            "brand": "Peloton",
            "category": "Sports & Outdoors",
            "specifications": {
                "screen_size": "24 inches HD touchscreen",
                "audio": "Dolby Atmos speakers",
                "screen_rotation": True
            },
            "features": ["Auto-follow resistance", "Rotating screen"],
            "requires_subscription": "All-Access membership $44/month",
            "price": 2495.00,
            "currency": "USD"
        }
    },
    {
        "description": "YETI Tundra 45 Cooler - White. Rotomolded construction, BearFoot non-slip feet, PermaFrost insulation. Holds 26 cans. $349.99",
        "ground_truth": {
            "name": "YETI Tundra 45 Cooler",
            "brand": "YETI",
            "category": "Sports & Outdoors",
            "specifications": {
                "capacity": "26 cans",
                "construction": "Rotomolded",
                "insulation": "PermaFrost"
            },
            "color": "White",
            "features": ["BearFoot non-slip feet"],
            "price": 349.99,
            "currency": "USD"
        }
    },
    {
        "description": "Breville Barista Express Espresso Machine. Built-in grinder, 15-bar Italian pump, PID temperature control. Stainless steel. $699.95",
        "ground_truth": {
            "name": "Breville Barista Express Espresso Machine",
            "brand": "Breville",
            "category": "Home & Kitchen",
            "specifications": {
                "grinder": "Built-in",
                "pump_pressure": "15 bar",
                "temperature_control": "PID",
                "material": "Stainless steel"
            },
            "price": 699.95,
            "currency": "USD"
        }
    },
    {
        "description": "Roku Streaming Stick 4K. HDR10+, Dolby Vision, voice remote, private listening. Includes 3 months Apple TV+ free. $49.99",
        "ground_truth": {
            "name": "Roku Streaming Stick 4K",
            "brand": "Roku",
            "category": "Electronics",
            "specifications": {
                "resolution": "4K",
                "hdr": ["HDR10+", "Dolby Vision"]
            },
            "features": ["Voice remote", "Private listening"],
            "includes": "3 months Apple TV+ free",
            "price": 49.99,
            "currency": "USD"
        }
    },
    {
        "description": "Fjallraven Kanken Classic Backpack - Ox Red. 16L, water-resistant Vinylon F fabric, dual top handles. $80.00",
        "ground_truth": {
            "name": "Fjallraven Kanken Classic Backpack",
            "brand": "Fjallraven",
            "category": "Sports & Outdoors",
            "specifications": {
                "capacity": "16L",
                "material": "Vinylon F fabric",
                "water_resistant": True
            },
            "color": "Ox Red",
            "features": ["Dual top handles"],
            "price": 80.00,
            "currency": "USD"
        }
    },
    {
        "description": "Weber Genesis II E-335 Gas Grill. 3 stainless steel burners, 669 sq in cooking area, side burner, built-in thermometer. Black. $899.00",
        "ground_truth": {
            "name": "Weber Genesis II E-335 Gas Grill",
            "brand": "Weber",
            "category": "Home & Kitchen",
            "specifications": {
                "burners": "3 stainless steel",
                "cooking_area": "669 sq in",
                "fuel_type": "Gas"
            },
            "color": "Black",
            "features": ["Side burner", "Built-in thermometer"],
            "price": 899.00,
            "currency": "USD"
        }
    },
    {
        "description": "Purple Mattress - Queen, Original Purple Grid, 9.5\" profile. Hypoallergenic, temperature neutral. 100-night trial. $1,299",
        "ground_truth": {
            "name": "Purple Mattress Original",
            "brand": "Purple",
            "category": "Furniture",
            "specifications": {
                "size": "Queen",
                "thickness": "9.5 inches",
                "technology": "Purple Grid",
                "hypoallergenic": True,
                "temperature_regulation": "Temperature neutral"
            },
            "trial_period": "100 nights",
            "price": 1299.00,
            "currency": "USD"
        }
    },
    {
        "description": "Nespresso VertuoPlus Coffee and Espresso Machine - Matte Black. One-touch brewing, used capsule container (13 capacity). $189.95",
        "ground_truth": {
            "name": "Nespresso VertuoPlus Coffee and Espresso Machine",
            "brand": "Nespresso",
            "category": "Home & Kitchen",
            "specifications": {
                "brewing_method": "One-touch",
                "capsule_capacity": 13,
                "types": ["Coffee", "Espresso"]
            },
            "color": "Matte Black",
            "price": 189.95,
            "currency": "USD"
        }
    },
    {
        "description": "Sonos One SL Speaker - White. WiFi enabled, AirPlay 2 compatible, humidity resistant. Pair for stereo sound. $199.00",
        "ground_truth": {
            "name": "Sonos One SL Speaker",
            "brand": "Sonos",
            "category": "Electronics",
            "specifications": {
                "connectivity": "WiFi",
                "compatibility": ["AirPlay 2"],
                "humidity_resistant": True
            },
            "color": "White",
            "features": ["Pair for stereo sound"],
            "price": 199.00,
            "currency": "USD"
        }
    },
    {
        "description": "AllModern Mid-Century TV Stand for 65\" TVs - Walnut finish. 2 cabinets, 1 shelf, cable management. Solid wood legs. $349.99",
        "ground_truth": {
            "name": "AllModern Mid-Century TV Stand",
            "brand": "AllModern",
            "category": "Furniture",
            "specifications": {
                "tv_size_support": "65 inches",
                "storage": "2 cabinets, 1 shelf",
                "legs_material": "Solid wood"
            },
            "color": "Walnut finish",
            "features": ["Cable management"],
            "price": 349.99,
            "currency": "USD"
        }
    },
    {
        "description": "Anova Precision Cooker Nano. 750W, Bluetooth connectivity, 12.8\" height. Sous vide cooking up to 10 liters. $99.00",
        "ground_truth": {
            "name": "Anova Precision Cooker Nano",
            "brand": "Anova",
            "category": "Home & Kitchen",
            "specifications": {
                "power": "750W",
                "connectivity": "Bluetooth",
                "height": "12.8 inches",
                "capacity": "10 liters"
            },
            "cooking_method": "Sous vide",
            "price": 99.00,
            "currency": "USD"
        }
    },
    {
        "description": "Razer DeathAdder V3 Gaming Mouse. 30K DPI optical sensor, 8 programmable buttons, 59g lightweight. Black. $69.99",
        "ground_truth": {
            "name": "Razer DeathAdder V3 Gaming Mouse",
            "brand": "Razer",
            "category": "Electronics",
            "specifications": {
                "sensor": "30K DPI optical",
                "buttons": "8 programmable",
                "weight": "59g"
            },
            "color": "Black",
            "price": 69.99,
            "currency": "USD"
        }
    },
    {
        "description": "Lululemon Align High-Rise Pant 25\" - Women's. Nulu fabric, four-way stretch, seamless waistband. Size 6, Heathered Graphite Grey. $98.00",
        "ground_truth": {
            "name": "Lululemon Align High-Rise Pant 25\"",
            "brand": "Lululemon",
            "category": "Clothing",
            "specifications": {
                "fabric": "Nulu",
                "inseam": "25 inches",
                "rise": "High-rise",
                "stretch": "Four-way"
            },
            "gender": "Women",
            "size": "6",
            "color": "Heathered Graphite Grey",
            "features": ["Seamless waistband"],
            "price": 98.00,
            "currency": "USD"
        }
    },
    {
        "description": "Philips Hue White and Color Ambiance Starter Kit. 4 A19 bulbs, Hue Bridge, 16 million colors, voice control compatible. $199.99",
        "ground_truth": {
            "name": "Philips Hue White and Color Ambiance Starter Kit",
            "brand": "Philips",
            "category": "Electronics",
            "specifications": {
                "bulbs_included": "4 A19",
                "colors": "16 million"
            },
            "includes": ["Hue Bridge"],
            "features": ["Voice control compatible"],
            "price": 199.99,
            "currency": "USD"
        }
    },
    {
        "description": "Theragun PRO Plus. 6 attachments, QuietForce technology, 2 rechargeable batteries, 16mm amplitude. Carrying case included. $599.00",
        "ground_truth": {
            "name": "Theragun PRO Plus",
            "brand": "Theragun",
            "category": "Health & Wellness",
            "specifications": {
                "attachments": 6,
                "technology": "QuietForce",
                "batteries": "2 rechargeable",
                "amplitude": "16mm"
            },
            "includes": ["Carrying case"],
            "price": 599.00,
            "currency": "USD"
        }
    },
    {
        "description": "Arc'teryx Atom LT Hoody - Men's. Coreloft insulation, wind-resistant, breathable. Medium, Black Sapphire. $299.00",
        "ground_truth": {
            "name": "Arc'teryx Atom LT Hoody",
            "brand": "Arc'teryx",
            "category": "Clothing",
            "specifications": {
                "insulation": "Coreloft",
                "wind_resistant": True,
                "breathable": True
            },
            "gender": "Men",
            "size": "Medium",
            "color": "Black Sapphire",
            "price": 299.00,
            "currency": "USD"
        }
    },
    {
        "description": "Le Creuset 5.5 Qt Round Dutch Oven - Cerise (Cherry Red). Cast iron, enamel coating, oven safe to 500°F. Lifetime warranty. $429.95",
        "ground_truth": {
            "name": "Le Creuset 5.5 Qt Round Dutch Oven",
            "brand": "Le Creuset",
            "category": "Home & Kitchen",
            "specifications": {
                "capacity": "5.5 quarts",
                "material": "Cast iron",
                "coating": "Enamel",
                "oven_safe_temp": "500°F",
                "shape": "Round"
            },
            "color": "Cerise (Cherry Red)",
            "warranty": "Lifetime",
            "price": 429.95,
            "currency": "USD"
        }
    },
    {
        "description": "Garmin Fenix 7X Sapphire Solar GPS Watch - Titanium. 1.4\" display, solar charging, 28-day battery, topographic maps. $899.99",
        "ground_truth": {
            "name": "Garmin Fenix 7X Sapphire Solar GPS Watch",
            "brand": "Garmin",
            "category": "Electronics",
            "specifications": {
                "display_size": "1.4 inches",
                "battery_life": "28 days",
                "charging": "Solar",
                "material": "Titanium"
            },
            "features": ["GPS", "Topographic maps"],
            "price": 899.99,
            "currency": "USD"
        }
    },
    {
        "description": "Apple AirPods Pro 2nd Generation with MagSafe. Active noise cancellation, adaptive transparency, spatial audio. H2 chip, 6-hour battery. $249.00",
        "ground_truth": {
            "name": "Apple AirPods Pro 2nd Generation",
            "brand": "Apple",
            "category": "Electronics",
            "specifications": {
                "chip": "H2",
                "battery_life": "6 hours",
                "generation": "2nd"
            },
            "features": ["Active noise cancellation", "Adaptive transparency", "Spatial audio", "MagSafe"],
            "price": 249.00,
            "currency": "USD"
        }
    },
    {
        "description": "Samsonite Winfield 3 DLX 3-Piece Hardside Luggage Set. 20\"/25\"/28\" spinners, scratch-resistant finish. Brushed Anthracite. $379.99",
        "ground_truth": {
            "name": "Samsonite Winfield 3 DLX 3-Piece Hardside Luggage Set",
            "brand": "Samsonite",
            "category": "Travel",
            "specifications": {
                "pieces": 3,
                "sizes": ["20 inches", "25 inches", "28 inches"],
                "type": "Hardside",
                "finish": "Scratch-resistant"
            },
            "color": "Brushed Anthracite",
            "features": ["Spinners"],
            "price": 379.99,
            "currency": "USD"
        }
    },
]


def get_test_case(index: int) -> Dict[str, Any]:
    """Get a specific test case by index."""
    if 0 <= index < len(PRODUCT_TEST_CASES):
        return PRODUCT_TEST_CASES[index]
    raise IndexError(f"Test case index {index} out of range (0-{len(PRODUCT_TEST_CASES)-1})")


def get_all_test_cases() -> List[Dict[str, Any]]:
    """Get all test cases."""
    return PRODUCT_TEST_CASES.copy()


def get_test_cases_by_category(category: str) -> List[Dict[str, Any]]:
    """Get all test cases for a specific category."""
    return [
        case for case in PRODUCT_TEST_CASES
        if case["ground_truth"].get("category") == category
    ]


def get_test_cases_by_price_range(min_price: float, max_price: float) -> List[Dict[str, Any]]:
    """Get test cases within a price range."""
    return [
        case for case in PRODUCT_TEST_CASES
        if min_price <= case["ground_truth"].get("price", 0) <= max_price
    ]


# Metadata about the test dataset
TEST_DATASET_INFO = {
    "total_cases": len(PRODUCT_TEST_CASES),
    "categories": list(set(case["ground_truth"].get("category") for case in PRODUCT_TEST_CASES)),
    "price_range": {
        "min": min(case["ground_truth"].get("price", 0) for case in PRODUCT_TEST_CASES),
        "max": max(case["ground_truth"].get("price", 0) for case in PRODUCT_TEST_CASES)
    },
    "description": "50 diverse product descriptions with ground truth JSON for testing extraction quality"
}
