# companies_selling

Ce dépôt contient deux petits scripts pour extraire et visualiser des informations d'établissements à partir du fichier
`StockEtablissement_utf8.csv` fourni et d'une table SQLite intermédiaire :

- `retrieve_siren_companies.py` : lit `StockEtablissement_utf8.csv` par chunks, applique des filtres, et écrit les enregistrements retenus dans la base SQLite `companies.db` (table `companies`).
- `generate_companies_html.py` : lit `companies.db` et génère `companies.html` — une page HTML paginée (client-side) avec tri et filtre. Une colonne `Libellé` est ajoutée en mappant les codes NAF via `int_courts_naf_rev_2.xls` si présent.

Etat actuel

- `retrieve_siren_companies.py` : filtre les établissements (siège = true, état administratif = A, date de création ≤ 2000-01-01, tranches d'effectifs dans [01,02,03,11,12]) et insère les colonnes suivantes dans `companies` :
  - `siret`, `nic`, `dateCreationEtablissement`, `trancheEffectifsEtablissement`, `activitePrincipaleEtablissement`.
- `generate_companies_html.py` :
  - embarque toutes les lignes en JSON dans la page et affiche 50 lignes par page par défaut;
  - permet de trier par `dateCreationEtablissement` et `trancheEffectifsEtablissement` (clic sur l'en-tête) ;
  - propose un filtre sur `activitePrincipaleEtablissement` (sélecteur) ;
  - tente de lire `int_courts_naf_rev_2.xls` (colonne `Code` et colonne d'intitulés contenant `Intitul`) pour remplir la nouvelle colonne `Libellé` ; si un code NAF est présent mais non mappé, la valeur sera `INCONNU` ; si `pandas` n'est pas installé ou le fichier absent, `Libellé` restera vide.

Prérequis

- Python 3.8+
- Dépendances (recommandé via `requirements.txt`) :
  - `tqdm` (déjà listé)
  - `pandas` et `xlrd` si vous souhaitez activer le mapping NAF depuis `int_courts_naf_rev_2.xls`

Installation rapide

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
# installer pandas/xlrd si nécessaire
pip install pandas xlrd
```

Usage

1) Générez la base SQLite à partir du CSV (lecture par chunks) :

```bash
python3 retrieve_siren_companies.py
```

2) Générez la page HTML paginée :

```bash
python3 generate_companies_html.py
```

3) Servez la page localement et ouvrez-la dans votre navigateur :

```bash
python3 -m http.server 8000
# ouvrir http://localhost:8000/companies.html
```

Fichiers importants

- `StockEtablissement_utf8.csv` : source CSV d'origine (non commité normalement).
- `companies.db` : base SQLite générée contenant la table `companies`.
- `generate_companies_html.py` : génère `companies.html` (filtre / tri / pagination côté client).
- `int_courts_naf_rev_2.xls` : (optionnel) fichier Excel utilisé pour mapper `Code NAF` → `Libellé`.

Remarques

- Le script `generate_companies_html.py` embarque toutes les données dans le HTML (JSON). Pour de très gros jeux de données, envisager une pagination serveur ou une génération côté serveur par lots afin d'éviter de charger tout en mémoire côté client.

