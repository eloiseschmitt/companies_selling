# companies_selling

Application FastAPI pour explorer une base SQLite d'entreprises et leur hiérarchie NAF.

Le dépôt contient aujourd'hui deux modes d'usage :

- une application web serveur dans `main.py`
- un générateur HTML statique dans `generate_companies_html.py`

## Fonctionnalités

### Page entreprises `/`

La page principale affiche les établissements de la table `companies` avec :

- regroupement par sections NAF
  - ligne de section niveau `2` caractères, ex. `01`
  - ligne de sous-section niveau `4` caractères, ex. `01.1`
- repli/extension des sections et sous-sections par clic
- filtre par section via le paramètre `section`
  - ex. `/?section=01`
  - ex. `/?section=15.1`
- pagination serveur
- tri sur la colonne `Score` en ascendant ou descendant via `sort_score`
- affichage du libellé NAF à partir de la table `naf_code`

### Calcul du score

Le score est calculé dynamiquement pour chaque entreprise :

- `0` par défaut
- `+3` si `dateCreationEtablissement` est supérieure à `30` ans
- `+2` si `trancheEffectifsEtablissement` correspond à un effectif strictement supérieur à `5` et strictement inférieur à `20`
  - codes utilisés : `03` et `11`

### Page sections NAF `/naf_sections`

Cette page affiche :

- les sections NAF de niveau `2` caractères
- leurs sous-sections de niveau `4` caractères
- un lien cliquable sur chaque section et sous-section vers la page entreprises filtrée

## Structure des données

### Table `companies`

Colonnes utilisées :

- `siret`
- `nic`
- `dateCreationEtablissement`
- `trancheEffectifsEtablissement`
- `activitePrincipaleEtablissement`

### Table `financial_documents`

Colonnes utilisées :

- `id`
- `siren`
- `siret`
- `closing_date`
- `filing_date`
- `document_path`
- `document_type`
- `source`
- `revenue`
- `created_at`
- `updated_at`

La table possède des index sur `siren`, `siret` et `closing_date`.
Une contrainte d'unicité sur `siren`, `closing_date` et `document_path` évite les doublons.

### Import des documents financiers

La table `financial_documents` stocke les métadonnées des documents financiers disponibles sur le SFTP INPI pour les entreprises déjà connues du projet. Elle ne stocke pas le contenu des PDF ou XML.

Variables d'environnement nécessaires :

- `SFTP_HOST`
- `SFTP_USER`
- `SFTP_PASSWORD`

Lancer l'import :

```bash
python import_financial_documents.py
```

Options utiles :

```bash
python import_financial_documents.py --year 2026 --dry-run
python import_financial_documents.py --year 2026 --limit 20
python import_financial_documents.py --year 2026 --recursive --max-depth 2
python import_financial_documents.py --siren 781241799
```

Données importées quand elles sont disponibles dans un index ou dans le chemin du fichier :

- `siren`
- `siret`
- `closing_date`
- `filing_date`
- `document_path`
- `document_type`
- `source`
- `revenue`

L'import ne conserve que les documents dont le SIREN correspond à une entreprise déjà présente dans `companies`. Cette règle évite de remplir la base avec des documents hors périmètre et garde `financial_documents` alignée avec la sélection d'entreprises existante.

Le script est relançable : la contrainte d'unicité sur `siren`, `closing_date` et `document_path` empêche les doublons. Si une ligne existe déjà, les champs `siret`, `filing_date`, `document_type`, `source` et `updated_at` peuvent être mis à jour.

Limites connues :

- les comptes confidentiels peuvent être absents ;
- certaines entreprises peuvent ne pas avoir de données disponibles ;
- le chiffre d'affaires n'est pas toujours directement présent dans les métadonnées importées.

### Table `naf_code`

Colonnes utilisées :

- `code`
- `name`

La hiérarchie NAF est déduite depuis le format des codes :

- `01` : niveau 2
- `01.1` : niveau 4
- `01.11`, `01.11Z` : codes enfants rattachés à `01.1`, lui-même rattaché à `01`

## Prérequis

- Python `3.10+` recommandé
- dépendances Python listées dans `requirements.txt`

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## Lancer l'application web

```bash
uvicorn main:app --reload
```

Puis ouvrir :

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/naf_sections`

## Routes principales

- `/` : liste des entreprises
- `/naf_sections` : liste des sections NAF
- `/api/companies` : API JSON des entreprises
- `/api/naf_sections` : API JSON des codes NAF

## Paramètres utiles

### Page entreprises `/`

- `page` : numéro de page
- `limit` : nombre de lignes par page
- `section` : filtre par préfixe NAF
- `sort_score` : `asc` ou `desc`

Exemples :

```text
/?section=01
/?section=15.1&sort_score=asc
/?page=3&section=56&sort_score=desc
```

## Scripts du dépôt

- `main.py` : application FastAPI principale
- `populate_naf_db.py` : alimentation de la table `naf_code`
- `retrieve_siren_companies.py` : import des entreprises dans `companies.db`
- `init_financial_documents.py` : création de la table `financial_documents`
- `import_financial_documents.py` : import des métadonnées de documents financiers depuis le SFTP INPI
- `generate_companies_html.py` : génération de `companies.html` en statique

## Services

- `services/inpi_sftp.py` : connexion au SFTP INPI et listage des fichiers disponibles à partir de `SFTP_HOST`, `SFTP_USER` et `SFTP_PASSWORD`

## Fichiers importants

- `companies.db` : base SQLite locale
- `templates/index.html` : page entreprises
- `templates/naf_sections.html` : page sections NAF
- `constants.py` : mapping des tranches d'effectifs

## Notes

- la page principale conserve l'organisation par sections NAF même quand le tri par score est activé
- le tri par score s'applique à l'intérieur de cette hiérarchie
- le générateur `generate_companies_html.py` existe encore, mais la documentation ci-dessus concerne principalement l'application FastAPI
