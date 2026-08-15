#!/usr/bin/env python3
"""
Convert batch recipes.json (streetkitchen.hu scraped) to active meal-rotation recipe files.
Handles schema conversion, deduplication, and field mapping.
"""

import json
import os
import re
from pathlib import Path

# Paths
BATCH_JSON = Path("/Users/hermes/.hermes/workspace/projects/meal-rotation-batch-2026-07-29/recipes.json")
ACTIVE_RECIPES_DIR = Path("/Users/hermes/.hermes/workspace/projects/meal-rotation/recipes")
DEDUP_REPORT = Path("/Users/hermes/.hermes/workspace/projects/meal-rotation-batch-2026-07-29/DEDUP_REPORT.md")

# Deduplication rules from DEDUP_REPORT.md
# HU recipes that were removed in favor of EG versions
HU_REMOVED_IN_FAVOR_OF_EG = {
    "HU-010",  # Frankfurti -> EG-006
    "HU-011",  # Bableves -> EG-007
    "HU-012",  # Paradicsomleves -> EG-008
    "HU-017",  # Hamburger halból -> EG-010
    "HU-018",  # Rántott zöldségek -> EG-011
    "HU-020",  # Rántott gombafej túróval -> EG-013
    "HU-022",  # Lencsefőzelék -> EG-001
    "HU-023",  # Grill csirke -> EG-012
    "HU-024",  # Lecsó -> EG-014
    "HU-026",  # Pásztortarhonya -> EG-015
}

# Kitchen code mapping
KITCHEN_TO_CUISINE = {
    "AS": "ázsiai",
    "HU": "magyar",
    "ME": "mediterrán",
    "TR": "török",
    "EG": "egészséges",
    "VE": "vegyes",
}

# Difficulty estimation based on total time
def estimate_difficulty(prep_min, cook_min):
    total = prep_min + cook_min
    if total <= 30:
        return "könnyű"
    elif total <= 60:
        return "közepes"
    else:
        return "nehéz"

# Kid-friendly estimation based on tags/ingredients
def estimate_kid_friendly(title, tags, ingredients, cuisine):
    text = (title + " " + " ".join(tags) + " " + " ".join(ingredients)).lower()
    
    # Negative indicators
    negative = ["chili", "csípős", "spicy", "gochugaru", "harissa", "paprika por", "voros paprika", 
                "alcohol", "bor", "sör", "kávé", "füstölt", "szárított bors", "kardamom", "kömény"]
    
    # Positive indicators
    positive = ["csirke", "hús", "tej", "tejföl", "sajt", "túró", "rizs", "tészta", "nokedli",
                "burgonya", "sült", "rántott", "pizza", "burger", "hamburger", "krumpli"]
    
    neg_score = sum(1 for n in negative if n in text)
    pos_score = sum(1 for p in positive if p in text)
    
    # Cuisine bias
    if cuisine in ["magyar", "török", "vegyes"]:
        pos_score += 1
    if cuisine == "ázsiai":
        neg_score += 1  # often spicy
    
    return pos_score > neg_score

# Extract main protein from ingredients
def extract_main_protein(ingredients):
    protein_keywords = {
        "csirke": ["csirke", "csirkemell", "csirkecomb", "csirkeláb", "baromfi"],
        "sertés": ["sertés", "sertésmell", "sertéskaraj", "kolbász", "szalonna", "sonka"],
        "marha": ["marha", "bogrács", "gulyás", "pörkölt", "darált"],
        "hal": ["hal", "ponty", "aranymogyoró", "harcsa", "losos", "tónus", "sügér"],
        "vegetáriánus": ["tofu", "tempeh", "bab", "lencse", "csicseriborsó", "nádi", "gomba"],
    }
    
    text = " ".join(ingredients).lower()
    for protein, keywords in protein_keywords.items():
        if any(k in text for k in keywords):
            return protein
    return "egyéb"

# Parse ingredient strings to structured objects
def parse_ingredients(ingredient_strings):
    parsed = []
    for ing in ingredient_strings:
        ing = ing.strip()
        if not ing:
            continue
        
        # Try to extract quantity and unit
        # Patterns: "1 db", "500 g", "2 ek", "3 tk", "1 fej", "1 l", "200 ml", "1 csokor", "ízlés szerint"
        qty = None
        unit = None
        name = ing
        
        # Match patterns like "1 db", "500 g", "2 ek", "3 tk", "1 l", "200 ml", "1 fej", "2 gerezd", "1 csokor"
        match = re.match(r'^([\d.,]+)\s*(db|g|kg|ek|tk|ml|l|fej|gerezd|csokor|tk|tk\.|ek\.|dl|dl\.|kg\.|g\.)\s*(.*)$', ing, re.IGNORECASE)
        if match:
            qty_str = match.group(1).replace(',', '.')
            try:
                qty = float(qty_str)
            except ValueError:
                qty = None
            unit = match.group(2).lower().rstrip('.')
            name = match.group(3).strip()
            if not name:
                name = ing  # fallback
        else:
            # Check for "ízlés szerint", "szerint", etc.
            if any(phrase in ing.lower() for phrase in ["ízlés szerint", "szerint", "korty", "csepp"]):
                qty = None
                unit = None
                name = ing
        
        parsed.append({
            "name": name,
            "quantity": qty,
            "unit": unit
        })
    return parsed

# Convert batch recipe to active schema
def convert_recipe(batch_recipe):
    kitchen = batch_recipe.get("kitchen", "")
    cuisine = KITCHEN_TO_CUISINE.get(kitchen, "vegyes")
    
    prep_min = batch_recipe.get("prep_time_min", 0) or 0
    cook_min = batch_recipe.get("cook_time_min", 0) or 0
    
    ingredients_raw = batch_recipe.get("ingredients", [])
    instructions_raw = batch_recipe.get("instructions", [])
    tags = batch_recipe.get("tags", [])
    
    # Title: prefer name_full, then name
    title = batch_recipe.get("name_full") or batch_recipe.get("name") or batch_recipe.get("id")
    
    # Parse ingredients
    ingredients = parse_ingredients(ingredients_raw)
    
    # Steps
    steps = [f"{i+1}. {step}" for i, step in enumerate(instructions_raw)] if instructions_raw else []
    
    # Notes
    notes = batch_recipe.get("notes", "")
    source = batch_recipe.get("source", "")
    source_url = batch_recipe.get("source_url", "")
    if source and source_url:
        if notes:
            notes += f"\n\nForrás: {source} ({source_url})"
        else:
            notes = f"Forrás: {source} ({source_url})"
    
    # Kid friendly
    kid_friendly = estimate_kid_friendly(title, tags, ingredients_raw, cuisine)
    
    # Difficulty
    difficulty = estimate_difficulty(prep_min, cook_min)
    
    # Main protein
    main_protein = extract_main_protein(ingredients_raw)
    
    # Servings
    servings = batch_recipe.get("servings", 4) or 4
    
    return {
        "id": batch_recipe["id"],
        "title": title,
        "cuisine": cuisine,
        "tags": tags[:10],  # limit tags
        "prep_minutes": prep_min,
        "cook_minutes": cook_min,
        "difficulty": difficulty,
        "kid_friendly": kid_friendly,
        "servings": servings,
        "main_protein": main_protein,
        "ingredients": ingredients,
        "steps": steps,
        "notes": notes
    }

def main():
    # Load batch data
    with open(BATCH_JSON, 'r', encoding='utf-8') as f:
        batch_data = json.load(f)
    
    print(f"Loaded batch data: {batch_data['total_recipes']} recipes")
    
    # Load existing active recipes to know existing IDs
    existing_ids = set()
    for f in ACTIVE_RECIPES_DIR.glob("*.json"):
        existing_ids.add(f.stem)
    print(f"Existing active recipes: {len(existing_ids)}")
    
    # Collect all batch recipes
    all_batch_recipes = []
    for kitchen, recipes in batch_data["by_kitchen"].items():
        for r in recipes:
            all_batch_recipes.append(r)
    
    print(f"Total batch recipes: {len(all_batch_recipes)}")
    
    # Filter: skip HU recipes that were deduped in favor of EG
    filtered = []
    for r in all_batch_recipes:
        if r["id"] in HU_REMOVED_IN_FAVOR_OF_EG:
            print(f"  SKIP (deduped): {r['id']} -> EG version preferred")
            continue
        filtered.append(r)
    
    print(f"After dedup filter: {len(filtered)} recipes")
    
    # Convert and write
    written = 0
    skipped = 0
    for batch_recipe in filtered:
        recipe_id = batch_recipe["id"]
        
        if recipe_id in existing_ids:
            print(f"  SKIP (exists): {recipe_id}")
            skipped += 1
            continue
        
        try:
            active_recipe = convert_recipe(batch_recipe)
            
            output_path = ACTIVE_RECIPES_DIR / f"{recipe_id}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(active_recipe, f, ensure_ascii=False, indent=2)
            
            print(f"  WRITTEN: {recipe_id} -> {active_recipe['title'][:50]}")
            written += 1
            
        except Exception as e:
            print(f"  ERROR {recipe_id}: {e}")
    
    print(f"\nDone. Written: {written}, Skipped (exists): {skipped}")
    
    # Update BRAIN.md
    update_brain_md(written)

def update_brain_md(new_count):
    brain_path = Path("/Users/hermes/.hermes/workspace/projects/meal-rotation/BRAIN.md")
    
    # Count current recipes by cuisine
    cuisine_counts = {}
    for f in ACTIVE_RECIPES_DIR.glob("*.json"):
        with open(f, 'r', encoding='utf-8') as rf:
            r = json.load(rf)
            cuisine = r.get("cuisine", "unknown")
            cuisine_counts[cuisine] = cuisine_counts.get(cuisine, 0) + 1
    
    total = sum(cuisine_counts.values())
    
    new_content = f"""# Projekt: meal-rotation
Státusz: FOLYAMATBAN
Kezdve: 2026-08-08
Utoljára frissítve: 2026-08-14

## Feladatok
- [x] Receptkönyvtár ellenőrzése — {total} recept ({cuisine_counts.get('ázsiai', 0)} AS, {cuisine_counts.get('magyar', 0)} HU, {cuisine_counts.get('mediterrán', 0)} ME, {cuisine_counts.get('török', 0)} TR, {cuisine_counts.get('egészséges', 0)} EG, {cuisine_counts.get('vegyes', 0)} VE)
- [x] Batch receptek importálása ({new_count} új recept hozzáadva)
- [ ] Első hét menüjavaslat kiküldése

## Felfedezések
- Batch projekt (meal-rotation-batch-2026-07-29) 68 receptet tartalmazott (dedup után 65)
- Deduplikáció: 10 HU recept eltávolítva EG verziók javára
- Aktív projekt most {total} receptet tartalmaz
- history.json még üres (még nem főztek)

## Kimenet
- {total} recept JSON fájl a recipes/ mappában
- BRAIN.md frissítve
"""
    
    with open(brain_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"BRAIN.md updated: {total} total recipes")

if __name__ == "__main__":
    main()