import sqlite3
import re
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# --- CONFIGURATIE ---
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

DB_NAME = "sounds_catalog.db"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

# --- E-MAIL FUNCTIE ---
def send_email_notification(subject, html_content):
    """Verstuur een geformatteerde e-mail via Gmail."""
    if not GMAIL_USER or not GMAIL_PASS:
        print("⚠️ Geen Gmail gegevens gevonden. E-mail wordt niet verzonden.")
        return

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
        print("✅ E-mail succesvol verzonden!")
    except Exception as e:
        print(f"❌ Fout bij versturen van e-mail: {e}")

# --- DATABANK INSTELLEN ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Maak de tabel aan als deze nog niet bestaat
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalog (
            url TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            price REAL,
            source TEXT
        )
    ''')
    
    # Werkt een eventuele oude database automatisch bij met de 'source' kolom
    try:
        cursor.execute("ALTER TABLE catalog ADD COLUMN source TEXT")
    except sqlite3.OperationalError:
        pass  # Kolom bestaat al, niks aan de hand!

    conn.commit()
    conn.close()

# -------------------------------------------------------------------
# SCRAPERS PER WINKEL
# -------------------------------------------------------------------

def scrape_sounds():
    """Scraper voor Sounds.nl"""
    print("🔍 Scrapen van Sounds.nl...")
    categories = {
        "LP": "https://www.sounds.nl/uitverkoop/{page}/lp/all/art",
        "CD": "https://www.sounds.nl/uitverkoop/{page}/cd/all/art",
    }
    found_items = []

    for cat_name, url_template in categories.items():
        for page in range(1, 3):
            url = url_template.format(page=page)
            try:
                res = requests.get(url, headers=HEADERS, timeout=10)
                if res.status_code != 200: continue
            except Exception: continue

            soup = BeautifulSoup(res.text, "html.parser")
            for item in soup.find_all("div", class_=re.compile("product|item|row|album", re.I)) or soup.find_all("tr"):
                text = item.get_text()
                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                link_tag = item.find("a", href=True)

                if price_match and link_tag:
                    price = float(price_match.group(1).replace(",", "."))
                    href = link_tag['href']
                    if not href.startswith("http"): href = "https://www.sounds.nl" + href
                    
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    title = lines[0] if lines else "Onbekende titel"
                    
                    if "uitverkoop" not in href and "detail" in href:
                        found_items.append({
                            "url": href, "title": title, "category": cat_name, "price": price, "source": "Sounds.nl"
                        })
    return found_items

def scrape_kroese():
    """Scraper voor Kroese-Online.nl"""
    print("🔍 Scrapen van Kroese-Online.nl...")
    urls = [
        ("LP", "https://www.kroese-online.nl/actie/Vinyl-aanbiedingen_goedkope_lp_s"),
        ("CD", "https://www.kroese-online.nl/aanbiedingen/")
    ]
    found_items = []

    for cat_name, url in urls:
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code != 200: continue
        except Exception: continue

        soup = BeautifulSoup(res.text, "html.parser")
        for item in soup.find_all("div", class_=re.compile("product|item|album|grid", re.I)) or soup.find_all("li"):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            link_tag = item.find("a", href=True)

            if price_match and link_tag:
                price = float(price_match.group(1).replace(",", "."))
                href = link_tag['href']
                if not href.startswith("http"): href = "https://www.kroese-online.nl" + href

                title = link_tag.get_text().strip() or "Onbekende titel"
                if len(title) < 3: continue

                found_items.append({
                    "url": href, "title": title, "category": cat_name, "price": price, "source": "Kroese Online"
                })
    return found_items

def scrape_velvet():
    """Scraper voor VelvetMusic.nl"""
    print("🔍 Scrapen van VelvetMusic.nl...")
    urls = [
        ("LP", "https://www.velvetmusic.nl/collections/aanbiedingen-lp"),
        ("CD", "https://www.velvetmusic.nl/collections/aanbiedingen-cd")
    ]
    found_items = []

    for cat_name, url in urls:
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code != 200: continue
        except Exception: continue

        soup = BeautifulSoup(res.text, "html.parser")
        for item in soup.find_all(["div", "article"], class_=re.compile("product|card|grid", re.I)):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            link_tag = item.find("a", href=True)

            if price_match and link_tag:
                price = float(price_match.group(1).replace(",", "."))
                href = link_tag['href']
                if not href.startswith("http"): href = "https://www.velvetmusic.nl" + href

                lines = [line.strip() for line in text.split("\n") if line.strip()]
                title = lines[0] if lines else "Onbekende titel"

                found_items.append({
                    "url": href, "title": title, "category": cat_name, "price": price, "source": "Velvet Music"
                })
    return found_items

def scrape_platomania():
    """Scraper voor Platomania.nl"""
    print("🔍 Scrapen van Platomania.nl...")
    urls = [
        ("LP", "https://www.platomania.nl/plato-50-aanbiedingen"),
        ("LP", "https://www.platomania.nl/music-on-vinyl-sale")
    ]
    found_items = []

    for cat_name, url in urls:
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code != 200: continue
        except Exception: continue

        soup = BeautifulSoup(res.text, "html.parser")
        for item in soup.find_all("div", class_=re.compile("product|item|row", re.I)):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            link_tag = item.find("a", href=True)

            if price_match and link_tag:
                price = float(price_match.group(1).replace(",", "."))
                href = link_tag['href']
                if not href.startswith("http"): href = "https://www.platomania.nl" + href

                lines = [line.strip() for line in text.split("\n") if line.strip()]
                title = lines[0] if lines else "Onbekende titel"

                found_items.append({
                    "url": href, "title": title, "category": cat_name, "price": price, "source": "Platomania"
                })
    return found_items

# -------------------------------------------------------------------
# VERGELIJKING EN DATABASE UPDATE
# -------------------------------------------------------------------
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
                "INSERT INTO catalog (url, title, category, price, source) VALUES (?, ?, ?, ?, ?)",
                (item["url"], item["title"], item["category"], item["price"], item["source"])
            )
        else:
            old_price = result[0]
            if old_price != item["price"]:
                price_changes.append({
                    "title": item["title"],
                    "category": item["category"],
                    "source": item["source"],
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
    print("=== START PLATEN & CD MONITOR ===")
    init_db()

    all_scraped_items = []

    # Voer alle scrapers uit
    all_scraped_items.extend(scrape_sounds())
    all_scraped_items.extend(scrape_kroese())
    all_scraped_items.extend(scrape_velvet())
    all_scraped_items.extend(scrape_platomania())

    print(f"\nTotaal {len(all_scraped_items)} items gevonden. Controleren met databank...")

    new_items, price_changes = process_and_compare(all_scraped_items)

    # --- E-MAIL OPBOUWEN ---
    if new_items or price_changes:
        html_body = "<h2>🎵 Platen & CD Uitverkoop Update!</h2>"

        if new_items:
            html_body += f"<h3>✨ Nieuw in de uitverkoop ({len(new_items)}):</h3><ul>"
            for item in new_items[:25]:  # Toon maximaal 25 items
                html_body += f"<li><b>[{item['source']}]</b> [{item['category']}] <b>{item['title']}</b> - €{item['price']:.2f} (<a href='{item['url']}'>Bekijk</a>)</li>"
            if len(new_items) > 25:
                html_body += f"<li><i>...en nog {len(new_items) - 25} andere nieuwe items.</i></li>"
            html_body += "</ul>"

        if price_changes:
            html_body += f"<h3>🏷️ Prijswijzigingen ({len(price_changes)}):</h3><ul>"
            for change in price_changes[:20]:
                diff = change['new_price'] - change['old_price']
                icon = "📉" if diff < 0 else "📈"
                html_body += f"<li>{icon} <b>[{change['source']}]</b> [{change['category']}] <b>{change['title']}</b>: van €{change['old_price']:.2f} naar <b>€{change['new_price']:.2f}</b> (<a href='{change['url']}'>Bekijk</a>)</li>"
            html_body += "</ul>"

        send_email_notification("Muziek Uitverkoop Update!", html_body)
    else:
        print("Geen nieuwe items of prijswijzigingen gevonden.")

if __name__ == "__main__":
    main()
