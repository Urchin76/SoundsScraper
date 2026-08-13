import sqlite3
import re
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# --- CONFIGURATIE ---
# Haalt de geheimen op uit GitHub (of gebruikt lege waarden bij lokaal testen)
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

CATEGORIES = {
    "LP": "https://www.sounds.nl/uitverkoop/{page}/lp/all/art",
    "CD": "https://www.sounds.nl/uitverkoop/{page}/cd/all/art",
    "12-inch": "https://www.sounds.nl/uitverkoop/{page}/sl/all/art",
}

MAX_PAGES_PER_CATEGORY = 3 
DB_NAME = "sounds_catalog.db"

# --- E-MAIL FUNCTIE ---
def send_email_notification(subject, html_content):
    """Verstuur een geformatteerde e-mail via Gmail."""
    if not GMAIL_USER or not GMAIL_PASS:
        print("⚠️ Geen Gmail gegevens gevonden. E-mail wordt niet verzonden.")
        return

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER  # Stuurt het naar jezelf
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
        print(" E-mail succesvol verzonden!")
    except Exception as e:
        print(f"Fout bij versturen van e-mail: {e}")

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
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue
        except Exception as e:
            print(f"Fout bij verbinden met {url}: {e}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        
        for item in soup.find_all("div", class_=re.compile("product|item|row|album", re.I)) or soup.find_all("tr"):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            link_tag = item.find("a", href=True)

            if price_match and link_tag:
                raw_price = price_match.group(1).replace(",", ".")
                price = float(raw_price)
                
                href = link_tag['href']
                if not href.startswith("http"):
                    href = "https://www.sounds.nl" + href
                
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                title = lines[0] if lines else "Onbekende titel"
                
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
        cursor.execute("SELECT price FROM catalog WHERE url = ?", (item["url"],))
        result = cursor.fetchone()

        if result is None:
            new_items.append(item)
            cursor.execute(
                "INSERT INTO catalog (url, title, category, price) VALUES (?, ?, ?, ?)",
                (item["url"], item["title"], item["category"], item["price"])
            )
        else:
            old_price = result[0]
            if old_price != item["price"]:
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
    print("=== START MONITOR SOUNDS.NL ===")
    init_db()

    all_scraped_items = []
    for cat_name, url_template in CATEGORIES.items():
        items = scrape_category(cat_name, url_template, max_pages=MAX_PAGES_PER_CATEGORY)
        all_scraped_items.extend(items)

    new_items, price_changes = process_and_compare(all_scraped_items)

    # --- E-MAIL OPBOUWEN ---
    if new_items or price_changes:
        html_body = "<h2>🎵 Sounds.nl Uitverkoop Update!</h2>"

        if new_items:
            html_body += f"<h3>✨ Nieuw in de uitverkoop ({len(new_items)}):</h3><ul>"
            for item in new_items[:15]:  # Toon maximaal 15 items
                html_body += f"<li>[{item['category']}] <b>{item['title']}</b> - €{item['price']:.2f} (<a href='{item['url']}'>Bekijk op site</a>)</li>"
            if len(new_items) > 15:
                html_body += f"<li><i>...en nog {len(new_items) - 15} andere items.</i></li>"
            html_body += "</ul>"

        if price_changes:
            html_body += f"<h3>🏷️ Prijswijzigingen ({len(price_changes)}):</h3><ul>"
            for change in price_changes[:15]:
                diff = change['new_price'] - change['old_price']
                icon = "📉" if diff < 0 else "📈"
                html_body += f"<li>{icon} [{change['category']}] <b>{change['title']}</b>: van €{change['old_price']:.2f} naar <b>€{change['new_price']:.2f}</b> (<a href='{change['url']}'>Bekijk op site</a>)</li>"
            html_body += "</ul>"

        send_email_notification("Sounds.nl Uitverkoop Update!", html_body)
    else:
        print("Geen nieuwe items of prijswijzigingen gevonden.")

if __name__ == "__main__":
    main()
