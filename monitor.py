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
        print("✅ E-mail notificatie succesvol verzonden!")
    except Exception as e:
        print(f"❌ Fout bij versturen van e-mail: {e}")

# --- DATABANK INSTELLEN ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalog (
            url TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            price REAL,
            source TEXT
        )
    ''')
    try:
        cursor.execute("ALTER TABLE catalog ADD COLUMN source TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

# --- SCRAPERS ---
def scrape_sounds():
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
                        found_items.append({"url": href, "title": title, "category": cat_name, "price": price, "source": "Sounds.nl"})
    return found_items

def scrape_kroese():
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
        for item in soup.find_all(["div", "li"], class_=re.compile("product|item|album|grid", re.I)):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            links = item.find_all("a", href=True)
            product_link, title_text = None, ""

            for l in links:
                href_str = l['href']
                if "cart" not in href_str.lower() and "basket" not in href_str.lower() and "winkelwagen" not in href_str.lower():
                    product_link = href_str
                    t = l.get_text(strip=True) or l.get('title', '')
                    if len(t) > len(title_text) and "korting" not in t.lower():
                        title_text = t

            if not title_text:
                head = item.find(["h2", "h3", "h4", "strong", "span"], class_=re.compile("title|name|header", re.I))
                if head: title_text = head.get_text(strip=True)

            if price_match and product_link and title_text:
                price = float(price_match.group(1).replace(",", "."))
                if not product_link.startswith("http"): product_link = "https://www.kroese-online.nl" + product_link
                found_items.append({"url": product_link, "title": title_text, "category": cat_name, "price": price, "source": "Kroese Online"})
    return found_items

def scrape_velvet():
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
        for item in soup.find_all(["div", "article", "li"], class_=re.compile("product|card|grid-item", re.I)):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            title_tag = item.find(["a", "h2", "h3", "div", "span"], class_=re.compile("title|name|header", re.I))
            title_text = title_tag.get_text(strip=True) if title_tag else ""
            if not title_text or "korting" in title_text.lower() or "record store day" in title_text.lower():
                img = item.find("img", alt=True)
                if img and img.get("alt"): title_text = img["alt"].strip()

            link_tag = item.find("a", href=True)
            if price_match and link_tag and title_text and len(title_text) > 3:
                price = float(price_match.group(1).replace(",", "."))
                href = link_tag['href']
                if not href.startswith("http"): href = "https://www.velvetmusic.nl" + href
                found_items.append({"url": href, "title": title_text, "category": cat_name, "price": price, "source": "Velvet Music"})
    return found_items

def scrape_platomania():
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
        for item in soup.find_all(["div", "article", "li"], class_=re.compile("product|item|row", re.I)):
            text = item.get_text()
            price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
            title_tag = item.find(["a", "h2", "h3", "h4", "div", "span"], class_=re.compile("title|name|header|artist", re.I))
            title_text = title_tag.get_text(strip=True) if title_tag else ""
            if not title_text:
                img = item.find("img", alt=True)
                if img and img.get("alt"): title_text = img["alt"].strip()

            link_tag = item.find("a", href=True)
            if price_match and link_tag and title_text and len(title_text) > 3:
                price = float(price_match.group(1).replace(",", "."))
                href = link_tag['href']
                if not href.startswith("http"): href = "https://www.platomania.nl" + href
                found_items.append({"url": href, "title": title_text, "category": cat_name, "price": price, "source": "Platomania"})
    return found_items

# --- VERGELIJKING EN DATABASE UPDATE ---
def process_and_compare(scraped_items):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    new_items, price_changes = [], []

    for item in scraped_items:
        cursor.execute("SELECT price, title FROM catalog WHERE url = ?", (item["url"],))
        result = cursor.fetchone()

        if result is None:
            new_items.append(item)
            cursor.execute("INSERT INTO catalog (url, title, category, price, source) VALUES (?, ?, ?, ?, ?)",
                           (item["url"], item["title"], item["category"], item["price"], item["source"]))
        else:
            old_price, old_title = result[0], result[1]
            if old_title != item["title"] and len(item["title"]) > len(old_title):
                cursor.execute("UPDATE catalog SET title = ? WHERE url = ?", (item["title"], item["url"]))

            if old_price != item["price"]:
                price_changes.append({
                    "title": item["title"], "category": item["category"], "source": item["source"],
                    "old_price": old_price, "new_price": item["price"], "url": item["url"]
                })
                cursor.execute("UPDATE catalog SET price = ? WHERE url = ?", (item["price"], item["url"]))

    conn.commit()
    conn.close()
    return new_items, price_changes

# --- GENEREREN VAN GITHUB PAGES INDEX.HTML ---
def generate_html_dashboard():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT source, category, title, price, url FROM catalog ORDER BY source, price ASC")
    rows = cursor.fetchall()
    conn.close()

    html_content = f"""<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎵 Platen & CD Uitverkoop Overzicht</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; margin: 0; padding: 20px; color: #333; }}
        h1 {{ text-align: center; color: #2c3e50; margin-bottom: 5px; }}
        p.subtitle {{ text-align: center; color: #7f8c8d; margin-bottom: 25px; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .controls {{ display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }}
        input[type="text"], select {{ padding: 10px; border: 1px solid #ccc; border-radius: 5px; flex: 1; min-width: 180px; font-size: 14px; }}
        .stats {{ margin-bottom: 15px; font-weight: bold; color: #555; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #ddd; }}
        th {{ background: #2c3e50; color: white; }}
        tr:hover {{ background: #f8f9fa; }}
        tr.checked {{ opacity: 0.35; text-decoration: line-through; background: #e8f5e9; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; color: white; }}
        .badge-sounds {{ background: #e74c3c; }}
        .badge-velvet {{ background: #8e44ad; }}
        .badge-kroese {{ background: #27ae60; }}
        .badge-platomania {{ background: #d35400; }}
        .badge-onbekend {{ background: #95a5a6; }}
        a.buy-btn {{ text-decoration: none; background: #3498db; color: white; padding: 6px 12px; border-radius: 4px; font-size: 0.9em; font-weight: bold; }}
        a.buy-btn:hover {{ background: #2980b9; }}
    </style>
</head>
<body>

<div class="container">
    <h1>🎵 Platen & CD Uitverkoop Overzicht</h1>
    <p class="subtitle">Live overzicht — vinkjes worden automatisch opgeslagen in je browser</p>
    
    <div class="controls">
        <input type="text" id="searchInput" onkeyup="filterTable()" placeholder="🔍 Zoek op artiest of album...">
        <select id="sourceFilter" onchange="filterTable()">
            <option value="">Alle winkels</option>
            <option value="Sounds.nl">Sounds.nl</option>
            <option value="Velvet Music">Velvet Music</option>
            <option value="Kroese Online">Kroese Online</option>
            <option value="Platomania">Platomania</option>
        </select>
        <select id="catFilter" onchange="filterTable()">
            <option value="">Alle Dragend media (LP/CD)</option>
            <option value="LP">LP</option>
            <option value="CD">CD</option>
        </select>
    </div>

    <div class="stats" id="rowCount">Totaal items getoond: {len(rows)}</div>

    <table id="itemsTable">
        <thead>
            <tr>
                <th style="width: 40px;">Check</th>
                <th>Winkel</th>
                <th>Format</th>
                <th>Artiest & Album</th>
                <th>Prijs</th>
                <th>Link</th>
            </tr>
        </thead>
        <tbody>
    """

    for i, (source, category, title, price, url) in enumerate(rows):
        # Veilige afhandeling als source of gegevens leeg/None zijn
        source_name = source if source else "Onbekend"
        cat_name = category if category else "LP"
        title_name = title if title else "Onbekende titel"
        price_val = price if price is not None else 0.0

        badge_class = f"badge-{source_name.split()[0].lower()}"
        item_id = f"item_{abs(hash(url))}"
        
        html_content += f"""
            <tr>
                <td style="text-align: center;"><input type="checkbox" onchange="toggleRow(this)" id="{item_id}"></td>
                <td><span class="badge {badge_class}">{source_name}</span></td>
                <td><b>[{cat_name}]</b></td>
                <td>{title_name}</td>
                <td><b>€{price_val:.2f}</b></td>
                <td><a href="{url}" target="_blank" class="buy-btn">Bekijk</a></td>
            </tr>
        """

    html_content += """
        </tbody>
    </table>
</div>

<script>
document.addEventListener("DOMContentLoaded", function() {
    document.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
        const isChecked = localStorage.getItem(cb.id) === 'true';
        cb.checked = isChecked;
        if (isChecked) cb.closest('tr').classList.add('checked');
    });
});

function toggleRow(checkbox) {
    const row = checkbox.closest('tr');
    if (checkbox.checked) {
        row.classList.add('checked');
        localStorage.setItem(checkbox.id, 'true');
    } else {
        row.classList.remove('checked');
        localStorage.setItem(checkbox.id, 'false');
    }
}

function filterTable() {
    const search = document.getElementById("searchInput").value.toLowerCase();
    const source = document.getElementById("sourceFilter").value.toLowerCase();
    const cat = document.getElementById("catFilter").value.toLowerCase();
    
    const rows = document.querySelectorAll("#itemsTable tbody tr");
    let visibleCount = 0;

    rows.forEach(row => {
        const text = row.cells[3].innerText.toLowerCase();
        const rowSource = row.cells[1].innerText.toLowerCase();
        const rowCat = row.cells[2].innerText.toLowerCase();

        const matchesSearch = text.includes(search);
        const matchesSource = source === "" || rowSource.includes(source);
        const matchesCat = cat === "" || rowCat.includes(cat);

        if (matchesSearch && matchesSource && matchesCat) {
            row.style.display = "";
            visibleCount++;
        } else {
            row.style.display = "none";
        }
    });

    document.getElementById("rowCount").innerText = "Totaal items getoond: " + visibleCount;
}
</script>

</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("🌐 `index.html` succesvol gegenereerd!")

# --- MAIN ---
def main():
    print("=== START PLATEN & CD MONITOR ===")
    init_db()

    all_scraped_items = []
    all_scraped_items.extend(scrape_sounds())
    all_scraped_items.extend(scrape_kroese())
    all_scraped_items.extend(scrape_velvet())
    all_scraped_items.extend(scrape_platomania())

    print(f"\nTotaal {len(all_scraped_items)} items gevonden. Controleren met databank...")
    new_items, price_changes = process_and_compare(all_scraped_items)

    generate_html_dashboard()

    if new_items or price_changes:
        html_body = "<h2>🎵 Platen & CD Uitverkoop Update!</h2>"
        if new_items:
            html_body += f"<h3>✨ Nieuw in de uitverkoop ({len(new_items)}):</h3><ul>"
            for item in new_items:
                html_body += f"<li><b>[{item['source']}]</b> [{item['category']}] <b>{item['title']}</b> - €{item['price']:.2f} (<a href='{item['url']}'>Bekijk</a>)</li>"
            html_body += "</ul>"

        if price_changes:
            html_body += f"<h3>🏷️ Prijswijzigingen ({len(price_changes)}):</h3><ul>"
            for change in price_changes:
                diff = change['new_price'] - change['old_price']
                icon = "📉" if diff < 0 else "📈"
                html_body += f"<li>{icon} <b>[{change['source']}]</b> [{change['category']}] <b>{change['title']}</b>: van €{change['old_price']:.2f} naar <b>€{change['new_price']:.2f}</b> (<a href='{change['url']}'>Bekijk</a>)</li>"
            html_body += "</ul>"

        send_email_notification("Muziek Uitverkoop Update!", html_body)

if __name__ == "__main__":
    main()
