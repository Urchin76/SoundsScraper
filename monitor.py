import sqlite3
import re
import requests
from bs4 import BeautifulSoup

# --- CONFIGURATIE ---
CATEGORIES = {
    "LP": "https://www.sounds.nl/uitverkoop/{page}/lp/all/art",
    "CD": "https://www.sounds.nl/uitverkoop/{page}/cd/all/art",
    "12-inch": "https://www.sounds.nl/uitverkoop/{page}/sl/all/art",
}

# Hoeveel pagina's wil je per categorie scannen? (bijv. 1 tot 3 voor een snelle test)
MAX_PAGES_PER_CATEGORY = 3 

DB_NAME = "sounds_catalog.db"

# --- DATABANK INSTELLEN ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalog (
            url TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            price REAL
        )
    ''')
    conn.commit()
    conn.close()

# --- SCRAPER FUNCTIE ---
def scrape_category(category_name, url_template, max_pages=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    found_items = []

    for page in range(1, max_pages + 1):
        url = url_template.format(page=page)
        print(f"Scrapen van {category_name} - Pagina {page}...")
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Fout bij ophalen van {url} (Code {response.status_code})")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Op sounds.nl staan producten in specifieke blocks of links
        # We zoeken naar de links met productinformatie en de prijzen
        for item in soup.find_all("div", class_=re.compile("product|item|row|album", re.I)) or soup.find_all("tr"):
            text = item.get_text()
            
            # Zoek naar een prijsnotatie (bijv. € 15.00 of € 25,00)
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            link_tag = item.find("a", href=True)

            if price_match and link_tag:
                raw_price = price_match.group(1).replace(",", ".")
                price = float(raw_price)
                
                # Titel en URL ophalen
                href = link_tag['href']
                if not href.startswith("http"):
                    href = "https://www.sounds.nl" + href
                
                # Maak een nette titel van de gevonden tekst
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                title = lines[0] if lines else "Onbekende titel"
                
                # Mijd dubbele registraties van navigatielinks
                if "uitverkoop" not in href and "detail" in href:
                    found_items.append({
                        "url": href,
                        "title": title,
                        "category": category_name,
                        "price": price
                    })

    return found_items

# --- VERGELIJKING EN DATABASE UPDATE ---
def process_and_compare(scraped_items):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    new_items = []
    price_changes = []

    for item in scraped_items:
        cursor.execute("SELECT price, title FROM catalog WHERE url = ?", (item["url"],))
        result = cursor.fetchone()

        if result is None:
            # Nieuw item ontdekt!
            new_items.append(item)
            cursor.execute(
                "INSERT INTO catalog (url, title, category, price) VALUES (?, ?, ?, ?)",
                (item["url"], item["title"], item["category"], item["price"])
            )
        else:
            old_price = result[0]
            if old_price != item["price"]:
                # Prijs is veranderd!
                price_changes.append({
                    "title": item["title"],
                    "category": item["category"],
                    "old_price": old_price,
                    "new_price": item["price"],
                    "url": item["url"]
                })
                cursor.execute(
                    "UPDATE catalog SET price = ? WHERE url = ?",
                    (item["price"], item["url"])
                )

    conn.commit()
    conn.close()

    return new_items, price_changes

# --- HOOFDPROGRAMMA ---
def main():
    print("=== START MONITOR SOUNDS.NL ===\n")
    init_db()

    all_scraped_items = []
    for cat_name, url_template in CATEGORIES.items():
        items = scrape_category(cat_name, url_template, max_pages=MAX_PAGES_PER_CATEGORY)
        all_scraped_items.extend(items)

    print(f"\nTotaal opgehaald: {len(all_scraped_items)} artikelen.\n")

    new_items, price_changes = process_and_compare(all_scraped_items)

    # --- RAPPORTAGE ---
    print("=========================================")
    print(f" NIEUW TOEGEVOEGDE ITEMS ({len(new_items)})")
    print("=========================================")
    if new_items:
        for item in new_items:
            print(f"• [{item['category']}] {item['title']} - €{item['price']:.2f}")
            print(f"  Link: {item['url']}")
    else:
        print("Geen nieuwe items gevonden.")

    print("\n=========================================")
    print(f" PRIJSWIJZIGINGEN ({len(price_changes)})")
    print("=========================================")
    if price_changes:
        for change in price_changes:
            diff = change['new_price'] - change['old_price']
            direction = "VERHOOGD" if diff > 0 else "VERLAAGD"
            print(f"• [{change['category']}] {change['title']}")
            print(f"  Prijs {direction}: €{change['old_price']:.2f} -> €{change['new_price']:.2f} ({diff:+.2f})")
            print(f"  Link: {change['url']}")
    else:
        print("Geen prijswijzigingen opgemerkt.")

if __name__ == "__main__":
    main()