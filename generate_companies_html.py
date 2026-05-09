import os
import sqlite3
import html
import json
from typing import List

try:
    import pandas as pd
except Exception:
    pd = None

DB = "companies.db"
OUT = "companies.html"
# DB column names (must match the `companies` table)
DB_COLS = [
    "siret",
    "nic",
    "dateCreationEtablissement",
    "trancheEffectifsEtablissement",
    "activitePrincipaleEtablissement",
]

# Headers to display in the HTML table (one-to-one with DB_COLS, plus Libellé)
HEADERS = [
    "siret",
    "nic",
    "Date de création",
    "trancheEffectifsEtablissement",
    "Code NAF",
    "Libellé",
]


def fetch_rows(db_path: str, cols: List[str]):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(cols)} FROM companies")
    rows = cur.fetchall()
    conn.close()
    return rows


def build_naf_map(xls_path: str):
    """Read the int_courts_naf_rev_2.xls file and return a dict code->libelle."""
    naf_map = {}
    if not os.path.exists(xls_path):
        return naf_map
    if pd is None:
        # pandas not available in this environment
        return naf_map
    try:
        df = pd.read_excel(xls_path)
    except Exception:
        # try with engine xlrd if needed
        df = pd.read_excel(xls_path, engine="xlrd")

    # try to find the proper column names
    cols = df.columns.tolist()
    # find 'Code' column
    code_col = None
    label_col = None
    for c in cols:
        if str(c).strip().lower() == "code":
            code_col = c
        if "intitul" in str(c).lower():
            label_col = c
    if code_col is None or label_col is None:
        return naf_map

    for _, row in df.iterrows():
        code = str(row[code_col]).strip()
        label = str(row[label_col]).strip()
        if code:
            naf_map[code] = label
    return naf_map


def render_table(cols: List[str], rows: List[tuple]) -> str:
    # cols here are the display headers
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)

    # build naf mapping from file in workspace
    naf_map = build_naf_map("int_courts_naf_rev_2.xls")

    # append Libellé to each row (map Code NAF -> libellé). Code NAF is at index 4 in DB_COLS
    data_rows = []
    for r in rows:
        code = r[4] if len(r) > 4 else ""
        label = naf_map.get(str(code).strip(), "")
        # if a code exists but no mapping found, mark as INCONNU
        if (not label) and str(code).strip():
            label = "INCONNU"
        data_rows.append(list(r) + [label])

    # prepare data as JSON for client-side pagination
    data = data_rows
    data_json = json.dumps(data, ensure_ascii=False)
    db_cols_json = json.dumps(DB_COLS)

    # prepare list of unique activities for filter dropdown (still at index 4)
    activities = sorted({r[4] for r in rows if r and r[4]})
    activities_json = json.dumps(activities, ensure_ascii=False)

    html_page = f"""
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Companies</title>
  <style>
    body {{ font-family: system-ui, sans-serif; padding: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f4f4f8; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fbfbfb; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .info {{ margin-bottom: 1rem; color: #333; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Companies</h1>
    <div class="info">Nombre d'enregistrements: {len(rows)}</div>
    <div id="controls" style="margin-bottom:0.5rem; display:flex; gap:0.5rem; align-items:center;">
      <button id="prev">Précédent</button>
      <button id="next">Suivant</button>
      <span id="page-info"></span>
      <label style="margin-left:1rem">Activité:
        <select id="activity-filter"></select>
      </label>
      <label style="margin-left:auto">Afficher par page:
        <select id="page-size">
          <option value="50" selected>50</option>
          <option value="100">100</option>
          <option value="200">200</option>
        </select>
      </label>
    </div>
    <table>
      <thead>
        <tr>{head}</tr>
      </thead>
      <tbody id="table-body">
      </tbody>
    </table>
    <script>
      const DATA = {data_json};
      const COLS = {db_cols_json};
      const ACTIVITIES = {activities_json};
      let pageSize = 50;
      let currentPage = 1;
      let currentFilter = 'ALL';
      let sortKey = null; // column index
      let sortDir = 1; // 1 asc, -1 desc

      function escapeHtml(str) {{
        return String(str)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#039;');
      }}

      function getFilteredSorted() {{
        let arr = DATA.filter(r => currentFilter === 'ALL' || r[4] === currentFilter);
        if (sortKey !== null) {{
          arr = arr.slice().sort((a, b) => {{
            let va = a[sortKey] ?? '';
            let vb = b[sortKey] ?? '';
            // date (index 2) compare as string (YYYY-MM-DD works lexicographically)
            if (sortKey === 3) {{
              // trancheEffectifsEtablissement, compare numerically
              va = parseInt(va) || 0;
              vb = parseInt(vb) || 0;
            }}
            if (va < vb) return -1 * sortDir;
            if (va > vb) return 1 * sortDir;
            return 0;
          }});
        }}
        return arr;
      }}

      function renderPage(page) {{
        const filtered = getFilteredSorted();
        const total = filtered.length;
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        if (page < 1) page = 1;
        if (page > totalPages) page = totalPages;
        currentPage = page;
        const start = (page - 1) * pageSize;
        const end = Math.min(start + pageSize, total);
        const rows = filtered.slice(start, end);
        const tbody = document.getElementById('table-body');
        tbody.innerHTML = rows.map(r => '<tr>' + r.map(c => '<td>' + escapeHtml(c == null ? '' : String(c)) + '</td>').join('') + '</tr>').join('\n');
        document.getElementById('page-info').textContent = `Page ${{currentPage}} / ${{totalPages}} — affichant ${{start + 1}}-${{end}} sur ${{total}}`;
      }}

      function populateActivityFilter() {{
        const sel = document.getElementById('activity-filter');
        sel.innerHTML = '<option value="ALL">Tous</option>' + ACTIVITIES.map(a => `<option value="${{escapeHtml(a)}}">${{escapeHtml(a)}}</option>`).join('');
        sel.addEventListener('change', (e) => {{ currentFilter = e.target.value; renderPage(1); }});
      }}

      document.getElementById('prev').addEventListener('click', () => renderPage(currentPage - 1));
      document.getElementById('next').addEventListener('click', () => renderPage(currentPage + 1));
      document.getElementById('page-size').addEventListener('change', (e) => {{
        pageSize = Number(e.target.value) || 50;
        renderPage(1);
      }});

      // make headers sortable for date and tranche columns
      document.addEventListener('DOMContentLoaded', () => {{
        populateActivityFilter();
        const ths = document.querySelectorAll('thead th');
        // find indices for the two columns
        COLS.forEach((c, i) => {{
          if (c === 'dateCreationEtablissement' || c === 'trancheEffectifsEtablissement') {{
            ths[i].classList.add('sortable');
            ths[i].addEventListener('click', () => {{
              if (sortKey === i) sortDir = -sortDir; else {{ sortKey = i; sortDir = 1; }}
              renderPage(1);
            }});
          }}
        }});
        renderPage(1);
      }});
    </script>
  </div>
</body>
</html>
"""
    return html_page


def main():
    rows = fetch_rows(DB, DB_COLS)
    page = render_table(HEADERS, rows)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Généré {OUT} avec {len(rows)} lignes.")


if __name__ == "__main__":
    main()
