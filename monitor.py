import sqlite3
import re
import os
import asyncio
import httpx
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

# --- E-MAIL FUNCTIE (RIJK GEVULD) ---
def send_email_notification(subject, new_items, price_changes):
    if not GMAIL_USER or not GMAIL_PASS:
        print("⚠️ Geen Gmail gegevens gevonden. E-mail wordt niet verzonden.")
        return

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = subject

    # Bouw een nette HTML-body met tabellen voor nieuwe items en prijswijzigingen
    html_body = f"""
    <h2>🎵 Er zijn updates in de platenkast!</h2>
    <p>Aantal nieuwe items: <b>{len(new_items)}</b> | Aantal prijswijzigingen: <b>{len(price_changes)}</b></p>
    """

    if new_items:
        html_body += "<h3>✨ Nieuwe Items (Top 10)</h3><table border='1' cellspacing='0' cellpadding='5' style='border-collapse: collapse; font-size: 12px;'>"
        html_body += "<tr style='background: #2c3e50; color: white;'><th>Winkel</th><th>Cat</th><th>Titel</th><th>Prijs</th><th>Link</th></tr>"
        for item in new_items[:10]:
            html_body += f"<tr><td>{item['source']}</td><td>{item['category']}</td><td>{item['title']}</td><td>€{item['price']:.2f}</td><td><a href='{item['url']}'>Bekijk</a></td></tr>"
        html_body += "</table>"

    if price_changes:
        html_body += "<h3>📉 Prijswijzigingen (Top 10)</h3><table border='1' cellspacing='0' cellpadding='5' style='border-collapse: collapse; font-size: 12px;'>"
        html_body += "<tr style='background: #e74c3c; color: white;'><th>Winkel</th><th>Titel</th><th>Oud</th><th>Nieuw</th><th>Link</th></tr>"
        for pc in price_changes[:10]:
            html_body += f"<tr><td>{pc['source']}</td><td>{pc['title']}</td><td>€{pc['old_price']:.2f}</td><td>€{pc['new_price']:.2f}</td><td><a href='{pc['url']}'>Bekijk</a></td></tr>"
        html_body += "</table>"

    msg.attach(MIMEText(html_body, 'html'))

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
    cursor.execute("UPDATE catalog SET source = 'Concerto' WHERE url LIKE '%concerto.nl%'")

    conn.commit()
    conn.close()

def clean_title(title_text):
    if not title_text:
        return ""
    title_text = title_text.strip()
    if re.match(r'^€?\s*\d+[\.,]\d{2}', title_text) or title_text.startswith("€"):
        return ""
    if len(title_text) < 3:
        return ""
    return title_text

# -------------------------------------------------------------------
# ASYNCHRONE SCRAPERS
# -------------------------------------------------------------------

async def fetch(client, url):
    try:
        res = await client.get(url, headers=HEADERS, timeout=12, follow_redirects=True)
        return res if res.status_code == 200 else None
    except Exception:
        return None

async def scrape_sounds(client):
    print("🔍 Scrapen van Sounds.nl...")
    categories = {
        "LP": "https://www.sounds.nl/uitverkoop/{page}/lp/all/art",
        "CD": "https://www.sounds.nl/uitverkoop/{page}/cd/all/art",
    }
    found_items = []
    for cat_name, url_template in categories.items():
        for page in range(1, 16):
            url = url_template.format(page=page)
            res = await fetch(client, url)
            if not res: break

            soup = BeautifulSoup(res.text, "html.parser")
            # Sounds.nl gebruikt vaak product rijen of grid items
            items = soup.find_all(["div", "tr"], class_=re.compile("product|item|row|album|col", re.I))
            if not items: break

            page_found = 0
            for item in items:
                text = item.get_text()
                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                link_tag = item.find("a", href=True)

                if price_match and link_tag:
                    price = float(price_match.group(1).replace(",", "."))
                    href = urljoin("https://www.sounds.nl", link_tag['href'])
                    
                    # Zoek specifiek naar de titel in heading tags of de link zelf
                    title_elem = item.find(["h2", "h3", "h4", "a"], class_=re.compile("title|name|album", re.I))
                    title = clean_title(title_elem.get_text()) if title_elem else clean_title(link_tag.get_text())
                    
                    if title and len(title) > 3 and "uitverkoop" not in href:
                        found_items.append({"url": href, "title": title, "category": cat_name, "price": price, "source": "Sounds.nl"})
                        page_found += 1
            if page_found == 0: break

    unique = list({v['url']: v for v in found_items}.values())
    print(f"    ✅ Sounds.nl: {len(unique)} items gevonden.")
    return unique

async def scrape_kroese(client):
    print("🔍 Scrapen van Kroese-Online.nl...")
    base_urls = [
        ("LP", "https://www.kroese-online.nl/actie/Vinyl-aanbiedingen_goedkope_lp_s"),
        ("CD", "https://www.kroese-online.nl/aanbiedingen/")
    ]
    found_items = []
    for cat_name, base_url in base_urls:
        for page in range(1, 15):
            url = f"{base_url}?page={page}" if page > 1 else base_url
            res = await fetch(client, url)
            if not res: break

            soup = BeautifulSoup(res.text, "html.parser")
            page_found = 0
            containers = soup.find_all(["div", "article", "li"], class_=re.compile("product|item|card", re.I))
            if not containers:
                containers = soup.find_all("div", class_=re.compile("row|grid", re.I))

            for container in containers:
                text = container.get_text(separator=" ", strip=True)
                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                if not price_match: continue

                link = container.find("a", href=True)
                if not link: continue

                href = link['href']
                if any(x in href.lower() for x in ["winkelwagen", "cart", "account", "login", "#"]): continue

                # Probeer een duidelijke titel te vinden
                title_elem = container.find(["h2", "h3", "h4", "a"], class_=re.compile("title|name|product", re.I))
                title = clean_title(title_elem.get_text()) if title_elem else clean_title(link.get_text())

                if title and len(title) > 3 and title.lower() not in ["in winkelwagen", "bestel", "bekijk", "details", "details weergeven"]:
                    price = float(price_match.group(1).replace(",", "."))
                    found_items.append({
                        "url": urljoin("https://www.kroese-online.nl", href),
                        "title": title, "category": cat_name, "price": price, "source": "Kroese Online"
                    })
                    page_found += 1

            if page_found == 0 and page > 1: break

    unique = list({v['url']: v for v in found_items}.values())
    print(f"    ✅ Kroese Online: {len(unique)} items gevonden.")
    return unique
    
async def scrape_velvet(client):
    print("🔍 Scrapen van VelvetMusic.nl...")
    return await scrape_shopify_store(client, "https://www.velvetmusic.nl", "Velvet Music")

aasync def scrape_concerto(client):
    print("🔍 Scrapen van Concerto.nl...")
    return await scrape_shopify_store(client, "https://www.concerto.nl", "Concerto")

# Hulpfunctie voor winkels die Shopify-achtige structuren gebruiken (zoals Velvet en Concerto)
async def scrape_shopify_store(client, base_domain, source_name):
    base_urls = [
        ("LP", f"{base_domain}/collections/aanbiedingen-lp"),
        ("CD", f"{base_domain}/collections/aanbiedingen-cd")
    ]
    found_items = []
    for cat_name, base_url in base_urls:
        for page in range(1, 16):
            url = f"{base_url}?page={page}"
            res = await fetch(client, url)
            if not res: break

            soup = BeautifulSoup(res.text, "html.parser")
            # Zoek naar standaard productkaarten
            items = soup.find_all(["div", "article", "li"], class_=re.compile("product|card|grid-item", re.I))
            if not items: break

            page_found = 0
            for item in items:
                text = item.get_text()
                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', text)
                if not price_match: continue

                title_text = ""
                # Zoek naar typische titel-elementen binnen de kaart
                title_tags = item.find_all(["a", "h2", "h3", "h4"], class_=re.compile("title|heading|card-title|name|product-item", re.I))
                
                for tag in title_tags:
                    candidate = clean_title(tag.get_text(strip=True))
                    # Filter rommelteksten eruit
                    if candidate and not any(bad in candidate.lower() for bad in ["korting", "details weergeven", "in winkelwagen", "bestel"]):
                        title_text = candidate
                        break

                # Fallback op afbeelding alt-tekst als de titel niet via tekst te vinden is
                if not title_text:
                    img = item.find("img", alt=True)
                    if img and img.get("alt"): 
                        title_text = clean_title(img["alt"])

                link_tag = item.find("a", href=True)
                if price_match and link_tag and title_text:
                    price = float(price_match.group(1).replace(",", "."))
                    href = urljoin(base_domain, link_tag['href'])
                    found_items.append({"url": href, "title": title_text, "category": cat_name, "price": price, "source": source_name})
                    page_found += 1

            if page_found == 0: break

    unique = list({v['url']: v for v in found_items}.values())
    print(f"    ✅ {source_name}: {len(unique)} items gevonden.")
    return unique

async def scrape_platomania(client):
    print("🔍 Scrapen van Platomania.nl...")
    base_urls = [
        ("LP", "https://www.platomania.nl/vinyl-aanbiedingen"),
        ("CD", "https://www.platomania.nl/search/results?search_in=sale&format=cd")
    ]
    found_items = []
    for cat_name, base_url in base_urls:
        for page in range(1, 20):
            url = f"{base_url}?page={page}" if page > 1 else base_url
            res = await fetch(client, url)
            if not res: break

            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["header", "nav", "footer", "script", "style"]): tag.decompose()

            page_found = 0
            cards = soup.find_all(class_=re.compile(r"article|product-card|item", re.I))
            if not cards: cards = [div for div in soup.find_all("div") if re.search(r'€\s*\d+', div.get_text())]

            for card in cards:
                card_text = card.get_text(separator=" ", strip=True)
                if len(card_text) > 800: continue

                price_match = re.search(r'€\s*(\d+[\.,]\d{2})', card_text)
                if not price_match: continue

                price = float(price_match.group(1).replace(",", "."))
                for link in card.find_all("a", href=True):
                    href = link['href']
                    if any(bad in href.lower() for bad in ["login", "cart", "winkelwagen", "wishlist", "account"]): continue

                    title = clean_title(link.get_text(strip=True))
                    if not title:
                        img = link.find("img", alt=True)
                        if img: title = clean_title(img["alt"])

                    if title and len(title) > 3 and title.lower() not in ["bekijk", "bestel", "in winkelwagen"]:
                        full_url = urljoin("https://www.platomania.nl", href)
                        found_items.append({"url": full_url, "title": title, "category": cat_name, "price": price, "source": "Platomania"})
                        page_found += 1
                        break

            if page_found == 0 and page > 1: break

    unique = list({v['url']: v for v in found_items}.values())
    print(f"    ✅ Platomania: {len(unique)} items gevonden.")
    return unique

# --- DATABASE VERWERKING ---
# --- DATABASE VERWERKING & AUTOMATISCH OPSCHONEN ---
def process_and_compare(scraped_items):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    new_items, price_changes = [], []
    
    # Verzamel alle URL's die zojuist zijn gemaand/gescraped
    scraped_urls = {item["url"] for item in scraped_items}

    # Haal alle bestaande items op uit de database
    cursor.execute("SELECT url, price, title, source FROM catalog")
    existing_items = {row[0]: {"price": row[1], "title": row[2], "source": row[3]} for row in cursor.fetchall()}

    for item in scraped_items:
        url = item["url"]
        if url not in existing_items:
            new_items.append(item)
            cursor.execute("INSERT OR REPLACE INTO catalog (url, title, category, price, source) VALUES (?, ?, ?, ?, ?)",
                           (url, item["title"], item["category"], item["price"], item["source"]))
        else:
            old_data = existing_items[url]
            old_price = old_data["price"]
            
            if old_price != item["price"]:
                price_changes.append({
                    "title": item["title"], "category": item["category"], "source": item["source"],
                    "old_price": old_price, "new_price": item["price"], "url": url
                })
            # Update altijd voor de zekerheid de prijs en titel
            cursor.execute("UPDATE catalog SET price = ?, title = ? WHERE url = ?", (item["price"], item["title"], url))

    # 🧹 STAP 3: Verwijder items die niet meer op de webshops staan (uitverkocht / verdwenen)
    existing_urls = set(existing_items.keys())
    stale_urls = existing_urls - scraped_urls
    if stale_urls:
        cursor.executemany("DELETE FROM catalog WHERE url = ?", [(u,) for u in stale_urls])
        print(f"🗑️ {len(stale_urls)} verlopen/uitverkochte items automatisch opgeschoond uit de database.")

    conn.commit()
    conn.close()
    return new_items, price_changes

# --- GENEREREN HTML DASHBOARD MET STATISTIEKEN ---
def generate_html_dashboard():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT source, category, title, price, url FROM catalog ORDER BY source, price ASC")
    rows = cursor.fetchall()
    
    # Bereken statistieken voor de topkaarten
    total_items = len(rows)
    avg_price = sum(r[3] for r in rows if r[3]) / total_items if total_items > 0 else 0
    cheapest = min(rows, key=lambda x: x[3] if x[3] else float('inf')) if rows else None
    
    conn.close()

    badge_mapping = {
        "Sounds.nl": "badge-sounds",
        "Velvet Music": "badge-velvet",
        "Kroese Online": "badge-kroese",
        "Platomania": "badge-platomania",
        "Concerto": "badge-concerto"
    }

    table_rows_html = []
    for source, category, title, price, url in rows:
        source_name = source or "Sounds.nl"
        cat_name = category or "LP"
        title_name = html.escape(title or "Onbekende titel")
        price_val = price if price is not None else 0.0
        safe_url = html.escape(url)
        badge_class = badge_mapping.get(source_name, "badge-onbekend")

        row_str = f"""
            <tr data-price="{price_val}" data-url="{safe_url}">
                <td style="text-align: center;"><input type="checkbox" onchange="hideItem(this, '{safe_url}')" title="Verberg dit item"></td>
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
        .container {{ max-width: 1100px; margin: 0 auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        
        /* Stats Cards */
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px; }}
        .stat-card {{ background: #f8f9fa; border-left: 4px solid #3498db; padding: 15px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        .stat-card h3 {{ margin: 0 0 5px 0; font-size: 0.85em; color: #7f8c8d; text-transform: uppercase; }}
        .stat-card p {{ margin: 0; font-size: 1.4em; font-weight: bold; color: #2c3e50; }}

        .controls {{ display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }}
        input[type="text"], input[type="number"], select {{ padding: 10px; border: 1px solid #ccc; border-radius: 5px; flex: 1; min-width: 140px; font-size: 14px; }}
        .stats-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
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
        .badge-concerto {{ background: #2980b9; }}
        .badge-onbekend {{ background: #95a5a6; }}
        a.buy-btn {{ text-decoration: none; background: #3498db; color: white; padding: 6px 12px; border-radius: 4px; font-size: 0.9em; font-weight: bold; }}
        a.buy-btn:hover {{ background: #2980b9; }}
    </style>
</head>
<body>

<div class="container">
    <h1>🎵 Platen & CD Uitverkoop Overzicht</h1>
    <p class="subtitle">Live overzicht van alle uitverkoopitems over meerdere muziekwinkels</p>
    
    <!-- Statistieken Kaarten -->
    <div class="stats-grid">
        <div class="stat-card">
            <h3>Totaal Gevonden</h3>
            <p>{total_items} items</p>
        </div>
        <div class="stat-card" style="border-left-color: #27ae60;">
            <h3>Gemiddelde Prijs</h3>
            <p>€{avg_price:.2f}</p>
        </div>
        <div class="stat-card" style="border-left-color: #8e44ad;">
            <h3>Goedkoopste Item</h3>
            <p>{f"€{cheapest[3]:.2f}" if cheapest else "N.v.t."}</p>
        </div>
    </div>

    <div class="controls">
        <input type="text" id="searchInput" onkeyup="filterTable()" placeholder="🔍 Zoek op artiest of album...">
        <select id="sourceFilter" onchange="filterTable()">
            <option value="">Alle winkels</option>
            <option value="Sounds.nl">Sounds.nl</option>
            <option value="Velvet Music">Velvet Music</option>
            <option value="Kroese Online">Kroese Online</option>
            <option value="Platomania">Platomania</option>
            <option value="Concerto">Concerto</option>
        </select>
        <select id="catFilter" onchange="filterTable()">
            <option value="">Alle formaten (LP/CD)</option>
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
        <div id="rowCount" style="font-weight: bold; color: #555;">Totaal getoond: {total_items}</div>
        <button class="reset-btn" onclick="resetHiddenItems()">🔄 Verborgen items herstellen</button>
    </div>

    <table>
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

    document.getElementById("rowCount").innerText = "Totaal getoond: " + visibleCount;
}}

document.addEventListener("DOMContentLoaded", filterTable);
</script>

</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("🌐 `index.html` succesvol gegenereerd met statistiek-kaarten!")

# --- MAIN ASYNC RUNNER ---
async def main_async():
    print("=== START PLATEN & CD MONITOR (ASYNC V3.0) ===")
    init_db()

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            scrape_sounds(client),
            scrape_kroese(client),
            scrape_velvet(client),
            scrape_concerto(client),
            scrape_platomania(client)
        )

    all_scraped_items = []
    for res_list in results:
        all_scraped_items.extend(res_list)

    print(f"\nTotaal {len(all_scraped_items)} items gevonden. Database updaten...")
    new_items, price_changes = process_and_compare(all_scraped_items)

    generate_html_dashboard()

    if new_items or price_changes:
        subject = f"🎵 Sale Monitor: {len(new_items)} nieuwe items / {len(price_changes)} prijswijzigingen"
        send_email_notification(subject, new_items, price_changes)

    print("=== MONITOR VOLTOOID ===")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
