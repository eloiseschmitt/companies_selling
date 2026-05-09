import math
import sqlite3
import pandas as pd
from tqdm import tqdm

file = "StockEtablissement_utf8.csv"
chunksize = 100_000

try:
    with open(file, "r", encoding="utf-8") as f:
        total_lines = sum(1 for _ in f) - 1
    total_chunks = math.ceil(total_lines / chunksize) if total_lines > 0 else None
except Exception:
    total_chunks = None

chunks = pd.read_csv(file, sep=",", dtype=str, chunksize=chunksize)
conn = sqlite3.connect("companies.db")

results = []

for chunk in tqdm(chunks, total=total_chunks, desc="Lecture", unit="chunk"):
    filtered = chunk[
        (chunk["etablissementSiege"] == "true")
        & (chunk["etatAdministratifEtablissement"] == "A")
        & (chunk["dateCreationEtablissement"] <= "2000-01-01")
        & (chunk["trancheEffectifsEtablissement"].isin(["01", "02", "03", "11", "12"]))
    ]
    filtered[
        [
            "siret",
            "nic",
            "dateCreationEtablissement",
            "trancheEffectifsEtablissement",
            "activitePrincipaleEtablissement",
        ]
    ].to_sql("companies", conn, if_exists="append", index=False)

#     results.append(filtered)
#
# df = pd.concat(results)
#
# df.to_csv("result.csv", index=False)
