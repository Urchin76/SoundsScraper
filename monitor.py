import sqlite3
import re
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

DB_NAME = "sounds_catalog.db"
# (De overige instellingen en scrapers blijven hetzelfde als voorheen)

# --- WEBPAAINA GEBRUIKEN VOOR GEVERIFICEERDE OVERZICHTEN ---
def generate_html_dashboard():
    """Genereert een index.html bestand met zoekbalk, filters en vinkjes."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Haal het complete assortiment op uit de database
    cursor.execute("SELECT source, category, title, price, url FROM catalog ORDER BY source, price ASC")
    rows = cursor.fetchall()
    conn.close()

    # HTML & JavaScript Template
    html_content = f"""<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎵 Platen & CD Uitverkoop Overzicht</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; margin: 0; padding: 20px; color: #333; }}
        h1 {{ text-align: center; color: #2c3e50; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        
        /* Controls & Filters */
        .controls {{ display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }}
        input[type="text"], select {{ padding: 10px; border: 1px solid #ccc; border-radius: 5px; flex: 1; min-width: 200px; }}
        .stats {{ margin-bottom: 15px; font-weight: bold; color: #666; }}

        /* Tabel Styling */
        table {{ width: 100%; border-collapse: collapse; text-align: left; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #ddd; }}
        th {{ background: #2c3e50; color: white; }}
        tr:hover {{ background: #f1f1f1; }}
        tr.checked {{ opacity: 0.4; text-decoration: line-through; background: #e8f5e9; }}
        
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; color: white; }}
        .badge-sounds {{ background: #e74c3c; }}
        .badge-velvet {{ background: #8e44ad; }}
        .badge-kroese {{ background: #27ae60; }}
        .badge-platomania {{ background: #d35400; }}
        
        a.buy-btn {{ text-decoration: none; background: #3498db; color: white; padding: 6px 12px; border-radius: 4px; font-size: 0.9em; }}
        a.buy-btn:hover {{ background: #2980b9; }}
    </style>
</head>
<body>

<div class="container">
    <h1>🎵 Platen & CD Uitverkoop Overzicht</h1>
    
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
        badge_class = f"badge-{source.split()[0].lower()}"
        html_content += f"""
            <tr>
                <td><input type="checkbox" onchange="toggleRow(this)" id="check_{i}"></td>
                <td><span class="badge {badge_class}">{source}</span></td>
                <td><b>[{category}]</b></td>
                <td>{title}</td>
                <td><b>€{price:.2f}</b></td>
                <td><a href="{url}" target="_blank" class="buy-btn">Bekijk</a></td>
            </tr>
        """

    html_content += """
        </tbody>
    </table>
</div>

<script>
// Vinkjes onthouden in de browser
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

// Zoeken en Filteren
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
    print("🌐 `index.html` succesvol aangemaakt!")
