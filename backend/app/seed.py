from . import repo

SEED_ITEMS = [
    # Unit spectrum: pcs = bought/consumed as whole packages or pieces,
    # l = liquid containers, kg = bulk goods (small packs as fractional kg).
    # Quantities are rounded estimates; low-vs-min drives the "running low" signal.
    {"id": "salz", "name": "Salz", "category": "Pantry", "quantity": 0.2, "unit": "kg", "min_quantity": 0.5, "package_size": 0.5, "barcode": "4006434000937"},
    {"id": "milch", "name": "Milch", "category": "Dairy", "quantity": 0.4, "unit": "l", "min_quantity": 1, "package_size": 1, "barcode": "4013165000110"},
    {"id": "eier", "name": "Eier", "category": "Dairy", "quantity": 3, "unit": "pcs", "min_quantity": 6, "package_size": 10},
    {"id": "kaffee", "name": "Kaffee", "category": "Pantry", "quantity": 0, "unit": "kg", "min_quantity": 0.25, "package_size": 0.5, "barcode": "4006400400222"},
    {"id": "spuelmittel", "name": "Spülmittel", "category": "Household", "quantity": 0.1, "unit": "l", "min_quantity": 0.3, "package_size": 0.5},
    {"id": "olivenoel", "name": "Olivenöl", "category": "Pantry", "quantity": 0.7, "unit": "l", "min_quantity": 0.25, "package_size": 0.5},
    {"id": "reis", "name": "Reis", "category": "Pantry", "quantity": 0.8, "unit": "kg", "min_quantity": 0.5, "package_size": 1},
    {"id": "butter", "name": "Butter", "category": "Dairy", "quantity": 1, "unit": "pcs", "min_quantity": 1, "package_size": 1, "barcode": "4013165000111", "uncertain": 1},
    {"id": "klopapier", "name": "Toilettenpapier", "category": "Household", "quantity": 2, "unit": "pcs", "min_quantity": 4, "package_size": 10},
    {"id": "apfelsaft", "name": "Apfelsaft", "category": "Drinks", "quantity": 3, "unit": "l", "min_quantity": 2, "package_size": 1},
    {"id": "mehl", "name": "Mehl", "category": "Pantry", "quantity": 1.5, "unit": "kg", "min_quantity": 0.5, "package_size": 1},
    {"id": "zucker", "name": "Zucker", "category": "Pantry", "quantity": 0.9, "unit": "kg", "min_quantity": 0.5, "package_size": 1},
    {"id": "spaghetti", "name": "Spaghetti", "category": "Pantry", "quantity": 1, "unit": "kg", "min_quantity": 0.5, "package_size": 0.5},
    # Produce: pieces and nets/2 kg packs
    {"id": "kartoffeln", "name": "Kartoffeln", "category": "Produce", "quantity": 1.5, "unit": "kg", "min_quantity": 1, "package_size": 2},
    {"id": "zwiebeln", "name": "Zwiebeln", "category": "Produce", "quantity": 5, "unit": "pcs", "min_quantity": 2, "package_size": 1},
    {"id": "knoblauch", "name": "Knoblauch", "category": "Produce", "quantity": 2, "unit": "pcs", "min_quantity": 1, "package_size": 1},
    {"id": "tomaten", "name": "Tomaten", "category": "Produce", "quantity": 4, "unit": "pcs", "min_quantity": 3, "package_size": 1},
    {"id": "bananen", "name": "Bananen", "category": "Produce", "quantity": 4, "unit": "pcs", "min_quantity": 2, "package_size": 1},
    {"id": "avocado", "name": "Avocado", "category": "Produce", "quantity": 1, "unit": "pcs", "min_quantity": 1, "package_size": 1},
    # Dairy: cups and pieces, plus a block of cheese in kg
    {"id": "naturjoghurt", "name": "Naturjoghurt", "category": "Dairy", "quantity": 1, "unit": "pcs", "min_quantity": 2, "package_size": 1},
    {"id": "gouda", "name": "Gouda", "category": "Dairy", "quantity": 0.25, "unit": "kg", "min_quantity": 0.1, "package_size": 0.25},
    # Meat: filets by piece, minced in 500 g packs
    {"id": "haehnchenbrust", "name": "Hähnchenbrust", "category": "Meat", "quantity": 3, "unit": "pcs", "min_quantity": 2, "package_size": 1},
    {"id": "hackfleisch", "name": "Hackfleisch", "category": "Meat", "quantity": 0.5, "unit": "kg", "min_quantity": 0.5, "package_size": 0.5},
    # Pantry additions: cans as pieces, gram-world goods as rounded fractional kg
    {"id": "haferflocken", "name": "Haferflocken", "category": "Pantry", "quantity": 0.2, "unit": "kg", "min_quantity": 0.5, "package_size": 0.5},
    {"id": "honig", "name": "Honig", "category": "Pantry", "quantity": 0.35, "unit": "kg", "min_quantity": 0.25, "package_size": 0.5},
    {"id": "parmesan", "name": "Parmesan", "category": "Pantry", "quantity": 0.1, "unit": "kg", "min_quantity": 0.05, "package_size": 0.1},
    {"id": "paprikapulver", "name": "Paprikapulver", "category": "Pantry", "quantity": 1, "unit": "pcs", "min_quantity": 1, "package_size": 1},
    {"id": "kichererbsen", "name": "Kichererbsen", "category": "Pantry", "quantity": 4, "unit": "pcs", "min_quantity": 2, "package_size": 1},
    {"id": "kokosmilch", "name": "Kokosmilch", "category": "Pantry", "quantity": 3, "unit": "pcs", "min_quantity": 1, "package_size": 1},
    # Drinks
    {"id": "orangensaft", "name": "Orangensaft", "category": "Drinks", "quantity": 1.5, "unit": "l", "min_quantity": 1, "package_size": 1},
    {"id": "haferdrink", "name": "Haferdrink", "category": "Drinks", "quantity": 0.5, "unit": "l", "min_quantity": 1, "package_size": 1},
    {"id": "mineralwasser", "name": "Mineralwasser", "category": "Drinks", "quantity": 3, "unit": "l", "min_quantity": 1.5, "package_size": 1.5},
    # Household: bottles and tubes as pieces (matches the pending Duschgel receipt line)
    {"id": "duschgel", "name": "Duschgel", "category": "Household", "quantity": 1, "unit": "pcs", "min_quantity": 1, "package_size": 1},
    {"id": "zahnpasta", "name": "Zahnpasta", "category": "Household", "quantity": 1, "unit": "pcs", "min_quantity": 1, "package_size": 1},
]

SEED_RECIPES = [
    {
        "title": "Pancakes",
        "source": "pasted",
        "base_portions": 4,
        "ingredients": [
            {"raw": "500 g Mehl", "amount": 0.5, "item": "mehl", "tracked": True},
            {"raw": "500 ml Milch", "amount": 0.5, "item": "milch", "tracked": True},
            {"raw": "3 Eier", "amount": 3, "item": "eier", "tracked": True},
            {"raw": "60 g Butter", "amount": 0.24, "item": "butter", "tracked": True},
            {"raw": "2 EL Zucker", "amount": 0.05, "item": "zucker", "tracked": True},
            {"raw": "1 Prise Salz", "tracked": False},
        ],
        "steps": [
            "Whisk flour, eggs, milk and sugar into a smooth batter.",
            "Let the batter rest for 15 minutes.",
            "Fry thin pancakes in butter until golden on both sides.",
        ],
    },
    {
        "title": "Spaghetti Aglio e Olio",
        "source": "https://www.chefkoch.de/rezepte/aglio-e-olio",
        "base_portions": 2,
        "ingredients": [
            {"raw": "250 g Spaghetti", "amount": 0.25, "item": "spaghetti", "tracked": True},
            {"raw": "6 EL Olivenöl", "amount": 0.09, "item": "olivenoel", "tracked": True},
            {"raw": "3 Zehen Knoblauch", "amount": 3, "item": "knoblauch", "tracked": True},
            {"raw": "1 Handvoll Petersilie", "tracked": True},
            {"raw": "Salz", "tracked": False},
        ],
        "steps": [
            "Cook the spaghetti in salted water until al dente.",
            "Slowly warm sliced garlic in olive oil until golden.",
            "Toss pasta with the garlic oil and parsley.",
        ],
    },
    {
        "title": "Rührei",
        "source": "pasted",
        "base_portions": 2,
        "ingredients": [
            {"raw": "4 Eier", "amount": 4, "item": "eier", "tracked": True},
            {"raw": "20 g Butter", "amount": 0.08, "item": "butter", "tracked": True},
            {"raw": "Schuss Milch", "amount": 0.05, "item": "milch", "tracked": True},
            {"raw": "Salz, Pfeffer", "tracked": False},
        ],
        "steps": [
            "Beat the eggs with a splash of milk and salt.",
            "Melt butter in a pan over medium heat.",
            "Scramble slowly, removing from heat while still glossy.",
        ],
    },
    {
        "title": "Ofengemüse mit Kartoffeln",
        "source": "pasted",
        "base_portions": 4,
        "ingredients": [
            {"raw": "1 kg Kartoffeln", "amount": 1, "item": "kartoffeln", "tracked": True},
            {"raw": "2 Zwiebeln", "amount": 2, "item": "zwiebeln", "tracked": True},
            {"raw": "2 Zehen Knoblauch", "amount": 2, "item": "knoblauch", "tracked": True},
            {"raw": "50 ml Olivenöl", "amount": 0.05, "item": "olivenoel", "tracked": True},
            {"raw": "4 Tomaten", "amount": 4, "item": "tomaten", "tracked": True},
            {"raw": "1 TL Paprikapulver", "tracked": True},
        ],
        "steps": [
            "Dice potatoes, onions and tomatoes, slice the garlic.",
            "Toss everything with olive oil and paprika on a tray.",
            "Roast at 200 °C for 35 minutes until browned at the edges.",
        ],
    },
    {
        "title": "Kichererbsen-Curry",
        "source": "pasted",
        "base_portions": 4,
        "ingredients": [
            {"raw": "2 Dosen Kichererbsen", "amount": 2, "item": "kichererbsen", "tracked": True},
            {"raw": "2 Dosen Kokosmilch", "amount": 2, "item": "kokosmilch", "tracked": True},
            {"raw": "1 Zwiebel", "amount": 1, "item": "zwiebeln", "tracked": True},
            {"raw": "1 TL Paprikapulver", "tracked": True},
            # and/or alternative: served with rice or naan, pick what to buy
            {"raw": "Basmatireis", "item": "reis", "tracked": True, "alt_group": "curry-side"},
            {"raw": "Naan", "tracked": True, "alt_group": "curry-side"},
        ],
        "steps": [
            "Sauté diced onion, add paprika and curry spices.",
            "Add coconut milk and chickpeas, simmer for 15 minutes.",
            "Serve with basmati rice or naan.",
        ],
    },
    {
        "title": "Bauernfrühstück",
        "source": "pasted",
        "base_portions": 2,
        "ingredients": [
            {"raw": "500 g Kartoffeln", "amount": 0.5, "item": "kartoffeln", "tracked": True},
            {"raw": "3 Eier", "amount": 3, "item": "eier", "tracked": True},
            {"raw": "1 Zwiebel", "amount": 1, "item": "zwiebeln", "tracked": True},
            {"raw": "30 g Butter", "amount": 0.12, "item": "butter", "tracked": True},
            {"raw": "100 ml Milch", "amount": 0.1, "item": "milch", "tracked": True},
            {"raw": "Salz, Pfeffer", "tracked": False},
        ],
        "steps": [
            "Fry diced potatoes and onion in butter until golden.",
            "Beat eggs with milk, salt and pepper.",
            "Pour over the potatoes and cook until just set.",
        ],
    },
]

SEED_RECEIPTS = [
    {
        "store": "REWE",
        "date": "2025-06-14",
        "total": 23.47,
        "status": "done",
        "items": [
            {"raw_name": "Bad Reichenhaller Jodarmes Salz", "quantity": 1, "suggestion": "Salz", "status": "matched"},
            {"raw_name": "Weidemilch 3,8% 1l", "quantity": 2, "suggestion": "Milch", "status": "matched"},
        ],
    },
    {
        "store": "Lidl",
        "date": "2025-06-16",
        "total": 14.98,
        "status": "review",
        "items": [
            {"raw_name": "Bellmer Kartoffeln 2kg", "quantity": 1, "suggestion": "Kartoffeln", "status": "pending"},
            {"raw_name": "Milbona Haltbarmilch 1,5%", "quantity": 3, "suggestion": "Milch", "status": "pending"},
            {"raw_name": "Cien Duschgel", "quantity": 1, "status": "pending"},
        ],
    },
]


def seed_if_empty():
    from .db import get_db
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if count > 0:
        return False

    for item in SEED_ITEMS:
        repo.create_item(
            name=item["name"],
            category=item["category"],
            unit=item["unit"],
            package_size=item["package_size"],
        )
        with get_db() as db:
            db.execute(
                "UPDATE items SET id = ?, quantity = ?, min_quantity = ?, uncertain = ?,"
                " tracking_mode = CASE WHEN ? > 1 THEN 'qty' ELSE 'binary' END WHERE name = ?",
                (item["id"], item["quantity"], item["min_quantity"], item.get("uncertain", 0),
                 item["quantity"], item["name"]),
            )
            # barcodes attach after the id rewrite — earlier rows would be
            # orphaned by it (item_barcodes references the final id)
            if item.get("barcode"):
                db.execute(
                    "INSERT OR IGNORE INTO item_barcodes (item_id, barcode) VALUES (?, ?)",
                    (item["id"], item["barcode"]),
                )

    for receipt in SEED_RECEIPTS:
        repo.create_receipt(store=receipt["store"], date=receipt["date"], total=receipt["total"],
                            items=receipt["items"])
        with get_db() as db:
            for item in receipt["items"]:
                if item.get("status") == "matched":
                    db.execute(
                        "UPDATE receipt_items SET status = 'matched' WHERE raw_name = ?",
                        (item["raw_name"],),
                    )
            db.execute("UPDATE receipts SET status = ? WHERE store = ?", (receipt["status"], receipt["store"]))

    for recipe in SEED_RECIPES:
        ingredients = []
        for ing in recipe["ingredients"]:
            entry = {"raw": ing["raw"], "amount": ing.get("amount"), "tracked": ing.get("tracked", True),
                     "suggestion": ing.get("suggestion")}
            if ing.get("alt_group"):
                entry["alt_group"] = ing["alt_group"]
            if ing.get("item"):
                entry["item_id"] = ing["item"]
            ingredients.append(entry)
        repo.create_recipe(recipe["title"], recipe["source"], recipe["base_portions"], ingredients, recipe["steps"])
    return True
