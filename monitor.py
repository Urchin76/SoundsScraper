import sqlite3
import re
import os
import requests
import smtplib
import html
from urllib.parse import urljoin
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# --- CONFIGURATIE ---
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

DB_NAME = "sounds_catalog.db"

# Headers die exact een echte Chrome browser op Windows simuleren
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
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

# --- DATABANK INSTELLEN & HERSTELLEN ---
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

    cursor.execute("UPDATE catalog SET source = 'Sounds.nl' WHERE url LIKE '%sounds.nl%'")
    cursor.execute("UPDATE catalog SET source = 'Kroese Online' WHERE url LIKE '%kroese-online.nl%'")
    cursor.execute("UPDATE catalog SET source = 'Velvet Music' WHERE url LIKE '%velvetmusic.nl%'")
    cursor.execute("UPDATE catalog SET source = 'Platomania' WHERE url LIKE '%platomania.nl%'")

    conn.commit()
    conn.close()

def clean_title(title_text):
    """Schoont titels op en weigert teksten die eigenlijk prijzen zijn."""
    if not title_text:
        return ""
    title_text = title_text.strip()
    if re.match(r'^€?\s*\d+[\.,]\d{2}', title_text) or title_text.startswith("€"):
        return ""
    if len(title_text) < 3:
        return ""
    return title_text

# -------------------------------------------------------------------
# SCRAPERS WITH LOGGING AND FALLBACKS
# -------------------------------------------------------------------

def scrape_sounds():
    print("🔍 Scrapen van Sounds.nl...")
    categories = {
        "LP": "https://www.sounds.nl/uitverkoop/{page}/lp/all/art",
        "CD": "https://www.sounds.nl/uitverkoop/{page}/cd/all/art",
    }
    found_items = []
    for cat_name, url_template in categories.items():
        for page in range(1, 16):
            url = url_template.format(page=page)
            try:
                res = requests.get(url, headers=HEADERS, timeout=10)
                if res.status_code != 200: break
            except Exception: break

            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.find_all("div", class_=re.compile("product|item|row|album", re.I)) or soup.find_all("tr")
            if not items: break

            page_found = 0
            for item in items:
                text = item.get_text()
                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                link_tag = item.find("a", href=True)

                if price_match and link_tag:
                    price = float(price_match.group(1).replace(",", "."))
                    href = urljoin("https://www.sounds.nl", link_tag['href'])
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    title = clean_title(lines[0]) if lines else ""
                    if title and "uitverkoop" not in href and "detail" in href:
                        found_items.append({"url": href, "title": title, "category": cat_name, "price": price, "source": "Sounds.nl"})
                        page_found += 1
            if page_found == 0: break

    print(f"    ✅ Sounds.nl: {len(found_items)} items gevonden.")
    return found_items

def scrape_kroese():
    print("🔍 Scrapen van Kroese-Online.nl...")
    base_urls = [
        ("LP", "https://www.kroese-online.nl/actie/Vinyl-aanbiedingen_goedkope_lp_s"),
        ("CD", "https://www.kroese-online.nl/aanbiedingen/")
    ]
    found_items = []

    for cat_name, base_url in base_urls:
        for page in range(1, 15):
            url = f"{base_url}?page={page}" if page > 1 else base_url
            try:
                res = requests.get(url, headers=HEADERS, timeout=12)
                if res.status_code != 200:
                    break
            except Exception:
                break

            soup = BeautifulSoup(res.text, "html.parser")
            
            for tag in soup(["header", "nav", "footer"]):
                tag.decompose()

            page_found = 0
            containers = soup.find_all(["div", "li", "article"])

            for container in containers:
                text = container.get_text(separator=" ", strip=True)
                
                if len(text) > 400 or len(text) < 10:
                    continue

                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                if not price_match:
                    continue

                link = container.find("a", href=True)
                if not link:
                    continue

                href = link['href']
                if any(x in href.lower() for x in ["winkelwagen", "cart", "account", "login", "#"]):
                    continue

                title = clean_title(link.get_text(strip=True))
                if not title:
                    img = link.find("img", alt=True)
                    if img:
                        title = clean_title(img["alt"])

                if title and len(title) > 3 and title.lower() not in ["in winkelwagen", "bestel", "bekijk", "details"]:
                    price = float(price_match.group(1).replace(",", "."))
                    full_link = urljoin("https://www.kroese-online.nl", href)

                    found_items.append({
                        "url": full_link,
                        "title": title,
                        "category": cat_name,
                        "price": price,
                        "source": "Kroese Online"
                    })
                    page_found += 1

            if page_found == 0 and page > 1:
                break

    unique_items = list({v['url']: v for v in found_items}.values())
    print(f"    ✅ Kroese Online: {len(unique_items)} items gevonden.")
    return unique_items
    
def scrape_velvet():
    print("🔍 Scrapen van VelvetMusic.nl...")
    base_urls = [
        ("LP", "https://www.velvetmusic.nl/collections/aanbiedingen-lp"),
        ("CD", "https://www.velvetmusic.nl/collections/aanbiedingen-cd")
    ]
    found_items = []
    for cat_name, base_url in base_urls:
        for page in range(1, 16):
            url = f"{base_url}?page={page}"
            try:
                res = requests.get(url, headers=HEADERS, timeout=10)
                if res.status_code != 200: break
            except Exception: break

            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.find_all(["div", "article", "li"], class_=re.compile("product|card|grid-item", re.I))
            if not items: break

            page_found = 0
            for item in items:
                text = item.get_text()
                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                
                title_text = ""
                title_tags = item.find_all(["a", "h2", "h3", "h4"], class_=re.compile("title|heading|card-title|name", re.I)) or item.find_all("a", href=True)
                
                for tag in title_tags:
                    candidate = clean_title(tag.get_text(strip=True))
                    if candidate and "korting" not in candidate.lower() and "record store day" not in candidate.lower():
                        title_text = candidate
                        break

                if not title_text:
                    img = item.find("img", alt=True)
                    if img and img.get("alt"):
                        title_text = clean_title(img["alt"])

                link_tag = item.find("a", href=True)
                if price_match and link_tag and title_text:
                    price = float(price_match.group(1).replace(",", "."))
                    href = urljoin("https://www.velvetmusic.nl", link_tag['href'])
                    found_items.append({"url": href, "title": title_text, "category": cat_name, "price": price, "source": "Velvet Music"})
                    page_found += 1

            if page_found == 0: break

    print(f"    ✅ Velvet Music: {len(found_items)} items gevonden.")
    return found_items

def scrape_platomania():
    print("🚀 === DIT IS DE NIEUWE GEUPDATE SCRAPER VERSION 2.0 ===")
    base_urls = [
        ("LP", "https://www.platomania.nl/vinyl-aanbiedingen"),
        ("CD", "https://www.platomania.nl/search/results?search_in=sale&format=cd")
    ]
    found_items = []

    for cat_name, base_url in base_urls:
        for page in range(1, 20):
            url = f"{base_url}?page={page}" if page > 1 else base_url
            
            try:
                res = requests.get(url, headers=HEADERS, timeout=12)
                if res.status_code != 200:
                    break
            except Exception:
                break

            soup = BeautifulSoup(res.text, "html.parser")

            for tag in soup(["header", "nav", "footer", "script", "style"]):
                tag.decompose()

            page_found = 0
            cards = soup.find_all(class_=re.compile(r"article|product-card|item", re.I))
            if not cards:
                cards = [div for div in soup.find_all("div") if re.search(r'€\s*\d+', div.get_text())]

            for card in cards:
                card_text = card.get_text(separator=" ", strip=True)
                
                if len(card_text) > 800:
                    continue

                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', card_text)
                if not price_match:
                    continue

                price = float(price_match.group(1).replace(",", "."))

                for link in card.find_all("a", href=True):
                    href = link['href']
                    if any(bad in href.lower() for bad in ["login", "cart", "winkelwagen", "wishlist", "account", "service", "winkels"]):
                        continue

                    title = clean_title(link.get_text(strip=True))
                    if not title:
                        img = link.find("img", alt=True)
                        if img:
                            title = clean_title(img["alt"])

                    if title and len(title) > 3 and title.lower() not in ["bekijk", "bestel", "in winkelwagen", "details"]:
                        full_url = urljoin("https://www.platomania.nl", href)
                        found_items.append({
                            "url": full_url,
                            "title": title,
                            "category": cat_name,
                            "price": price,
                            "source": "Platomania"
                        })
                        page_found += 1
                        break

            if page_found == 0 and page > 1:
                break

    unique_items = list({v['url']: v for v in found_items}.values())
    print(f"    ✅ Platomania: {len(unique_items)} items gevonden.")
    return unique_items

# --- VERGELIJKING EN DATABASE UPDATE ---
def process_and_compare(scraped_items):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    new_items, price_changes = [], []

    for item in scraped_items:
        cursor.execute("SELECT price, title, source FROM catalog WHERE url = ?", (item["url"],))
        result = cursor.fetchone()

        if result is None:
            new_items.append(item)
            cursor.execute("INSERT INTO catalog (url, title, category, price, source) VALUES (?, ?, ?, ?, ?)",
                           (item["url"], item["title"], item["category"], item["price"], item["source"]))
        else:
            old_price, old_title, old_source = result[0], result[1], result[2]
            
            if not old_source or old_source == "Onbekend":
                cursor.execute("UPDATE catalog SET source = ? WHERE url = ?", (item["source"], item["url"]))

            if old_title != item["title"] and (old_title.startswith("€") or len(item["title"]) > len(old_title)):
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

    badge_mapping = {
        "Sounds.nl": "badge-sounds",
        "Velvet Music": "badge-velvet",
        "Kroese Online": "badge-kroese",
        "Platomania": "badge-platomania"
    }

    table_rows_html = []
    for source, category, title, price, url in rows:
        source_name = source if source else "Sounds.nl"
        cat_name = category if category else "LP"
        title_name = html.escape(title if title else "Onbekende titel")
        price_val = price if price is not None else 0.0
        safe_url = html.escape(url)

        badge_class = badge_mapping.get(source_name, "badge-onbekend")
        
        row_str = f"""
            <tr data-price="{price_val}" data-url="{safe_url}">
                <td style="text-align: center;">
                    <input type="checkbox" onchange="hideItem(this, '{safe_url}')" title="Verberg dit item definitief">
                </td>
                <td><span class="badge {badge_class}">{html.escape(source_name)}</span></td>
                <td><b>[{html.escape(cat_name)}]</b></td>
                <td>{title_name}</td>
                <td><b>€{price_val:.2f}</b></td>
                <td><a href="{safe_url}" target="_blank" class="buy-btn">Bekijk</a></td>
            </tr>"""
        table_rows_html.append(row_str)

    rows_joined = "\n".join(table_rows_html)

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
        .controls {{ display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }}
        input[type="text"], input[type="number"], select {{ padding: 10px; border: 1px solid #ccc; border-radius: 5px; flex: 1; min-width: 140px; font-size: 14px; }}
        .stats-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .stats {{ font-weight: bold; color: #555; }}
        .reset-btn {{ background: #e74c3c; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.85em; }}
        .reset-btn:hover {{ background: #c0392b; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #ddd; }}
        th {{ background: #2c3e50; color: white; }}
        tr:hover {{ background: #f8f9fa; }}
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
    <p class="subtitle">Live overzicht — vink een item aan om het permanent te verbergen</p>
    
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
        <input type="number" id="maxPriceInput" oninput="filterTable()" placeholder="💶 Max. prijs (€)" step="0.50">
        <select id="priceSort" onchange="filterTable()">
            <option value="asc">Prijs: Laag ➔ Hoog</option>
            <option value="desc">Prijs: Hoog ➔ Laag</option>
        </select>
    </div>

    <div class="stats-bar">
        <div class="stats" id="rowCount">Totaal items getoond: {len(rows)}</div>
        <button class="reset-btn" onclick="resetHiddenItems()">🔄 Verborgen items herstellen</button>
    </div>

    <table id="itemsTable">
        <thead>
            <tr>
                <th style="width: 50px; text-align: center;">Weg</th>
                <th>Winkel</th>
                <th>Format</th>
                <th>Artiest & Album</th>
                <th>Prijs</th>
                <th>Link</th>
            </tr>
        </thead>
        <tbody id="tableBody">
{rows_joined}
        </tbody>
    </table>
</div>

<script>
function getHiddenUrls() {{
    const hidden = localStorage.getItem("hidden_albums");
    return hidden ? JSON.parse(hidden) : [];
}}

function hideItem(checkbox, url) {{
    if (checkbox.checked) {{
        let hiddenUrls = getHiddenUrls();
        if (!hiddenUrls.includes(url)) {{
            hiddenUrls.push(url);
            localStorage.setItem("hidden_albums", JSON.stringify(hiddenUrls));
        }}
        const row = checkbox.closest('tr');
        row.style.display = "none";
        filterTable();
    }}
}}

function resetHiddenItems() {{
    if (confirm("Weet je zeker dat je alle verborgen items weer wilt tonen?")) {{
        localStorage.removeItem("hidden_albums");
        location.reload();
    }}
}}

function filterTable() {{
    const search = document.getElementById("searchInput").value.toLowerCase();
    const source = document.getElementById("sourceFilter").value.toLowerCase();
    const cat = document.getElementById("catFilter").value.toLowerCase();
    const maxPrice = parseFloat(document.getElementById("maxPriceInput").value);
    const sortOrder = document.getElementById("priceSort").value;
    const hiddenUrls = getHiddenUrls();
    
    const tbody = document.getElementById("tableBody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    let visibleCount = 0;

    rows.sort((a, b) => {{
        const priceA = parseFloat(a.getAttribute("data-price")) || 0;
        const priceB = parseFloat(b.getAttribute("data-price")) || 0;
        return sortOrder === "asc" ? priceA - priceB : priceB - priceA;
    }});

    rows.forEach(row => {{
        tbody.appendChild(row);

        const rowUrl = row.getAttribute("data-url");
        const text = row.cells[3].innerText.toLowerCase();
        const rowSource = row.cells[1].innerText.toLowerCase();
        const rowCat = row.cells[2].innerText.toLowerCase();
        const rowPrice = parseFloat(row.getAttribute("data-price")) || 0;

        const isHidden = hiddenUrls.includes(rowUrl);
        const matchesSearch = text.includes(search);
        const matchesSource = source === "" || rowSource.includes(source);
        const matchesCat = cat === "" || rowCat.includes(cat);
        const matchesPrice = isNaN(maxPrice) || rowPrice <= maxPrice;

        if (!isHidden && matchesSearch && matchesSource && matchesCat && matchesPrice) {{
            row.style.display = "";
            visibleCount++;
        }} else {{
            row.style.display = "none";
        }}
    }});

    document.getElementById("rowCount").innerText = "Totaal items getoond: " + visibleCount;
}}

document.addEventListener("DOMContentLoaded", filterTable);
</script>

</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("🌐 `index.html` succesvol gegenereerd met verberg-functionaliteit!")

# --- MAIN ---
def main():
    print("=== START PLATEN & CD MONITOR ===")
    init_db()

    all_scraped_items = []
    all_scraped_items.extend(scrape_sounds())
    all_scraped_items.extend(scrape_kroese())
    all_scraped_items.extend(scrape_velvet())
    all_scraped_items.extend(scrape_platomania())

    print(f"\nTotaal {len(all_scraped_items)} items gevonden op de websites. Database updaten...")
    new_items, price_changes = process_and_compare(all_scraped_items)

    # 1. Genereer het HTML dashboard met alle data uit de DB
    generate_html_dashboard()

    # 2. Optioneel e-mail notificatie versturen bij nieuwe items
    if new_items or price_changes:
        subject = f"🎵 Sale Monitor: {len(new_items)} nieuwe items / {len(price_changes)} prijswijzigingen"
        body = f"<h2>Er zijn updates in de platenkast!</h2>"
        body += f"<p>Aantal nieuwe items: <b>{len(new_items)}</b></p>"
        body += f"<p>Aantal prijswijzigingen: <b>{len(price_changes)}</b></p>"
        send_email_notification(subject, body)

    print("=== MONITOR VOLTOOID ===")

if __name__ == "__main__":
    main()
