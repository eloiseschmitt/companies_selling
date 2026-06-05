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

### Téléchargement des comptes annuels INPI/RNE

Le script `download_annual_accounts.py` télécharge le dernier bilan PDF public disponible via l'API INPI/RNE pour une liste de SIREN.

Prérequis :

- disposer d'un compte INPI/RNE autorisé à utiliser l'API ;
- avoir installé les dépendances Python du projet.

Variables d'environnement nécessaires :

```bash
export SFTP_USER="..."
export SFTP_PASSWORD="..."
```

Format attendu du CSV d'entrée :

```csv
siren
123456789
987654321
```

La colonne `siren` est obligatoire. Chaque valeur doit correspondre à un SIREN à 9 chiffres.

Exemple de commande :

```bash
python download_annual_accounts.py --input sirens.csv --output-dir downloads --results results.csv
```

Options utiles :

```bash
python download_annual_accounts.py --input sirens.csv --sleep 1
python download_annual_accounts.py --input sirens.csv --force
```

Le script est relançable. Si le fichier de résultats existe déjà, les SIREN avec un statut final ne sont pas retraités. Les lignes en `error` sont rejouées. L'option `--force` force le retraitement complet. Si le PDF cible existe déjà et n'est pas vide, il n'est pas retéléchargé.

Colonnes du fichier `results.csv` :

```csv
siren,status,bilan_id,date_cloture,date_depot,confidentiality,type_bilan,filename,message
```

Statuts possibles :

- `downloaded` : un bilan public a été sélectionné et le PDF est disponible localement ;
- `not_found` : aucun bilan n'est présent dans la réponse INPI/RNE ;
- `confidential` : seuls des bilans non publics sont disponibles ;
- `deleted_only` : seuls des bilans marqués comme supprimés sont disponibles ;
- `error` : une erreur est survenue pour ce SIREN, le script continue avec les suivants.

Limites connues :

- les comptes confidentiels ne sont pas téléchargeables ;
- certaines entreprises n'ont pas de dépôt disponible ;
- les quotas et limites de débit de l'API INPI peuvent ralentir ou interrompre un lot ;
- les données téléchargées doivent être réutilisées dans le respect de la licence de réutilisation applicable.

### Export SIRENE Bordeaux Métropole

La commande `scripts.export_bordeaux_independants` interroge l'API SIRENE INSEE pour exporter les entrepreneurs individuels actifs dont l'établissement siège est situé dans les codes postaux ciblés de Bordeaux Métropole.

Variable d'environnement nécessaire :

```bash
export INSEE_API_KEY="..."
```

Exemple d'exécution :

```bash
python -m scripts.export_bordeaux_independants --output independants_bordeaux_metropole.csv
```

Si l'environnement local utilise le virtualenv du projet :

```bash
venv/bin/python -m scripts.export_bordeaux_independants --output independants_bordeaux_metropole.csv
```

La commande :

- recherche les établissements actifs et sièges via `/siret` ;
- filtre sur les codes postaux utiles de Bordeaux Métropole ;
- filtre sur les codes NAF ciblés ;
- enrichit chaque établissement avec `/siren/{siren}` ;
- conserve les unités légales dont `categorieJuridiqueUniteLegale == "1000"` ;
- écrit un CSV UTF-8 avec BOM compatible Excel ;
- utilise un cache JSON local, par défaut `.cache/insee_sirene_unites_legales.json`, pour éviter de rappeler plusieurs fois `/siren/{siren}` ;
- respecte les limites de débit avec retry sur `429`, prise en compte de `Retry-After` et backoff progressif.

Options utiles :

```bash
python -m scripts.export_bordeaux_independants --output independants_bordeaux_metropole.csv --enrich-delay 2
python -m scripts.export_bordeaux_independants --output test.csv --limit 50
python -m scripts.export_bordeaux_independants --cache .cache/sirene.json --output independants.csv
```

Options disponibles :

- `--output` : chemin du CSV de sortie ;
- `--cache` : chemin du cache JSON local des réponses `/siren/{siren}` ;
- `--limit` : nombre maximal d'établissements récupérés avant enrichissement ;
- `--enrich-delay` : délai en secondes après chaque nouvel appel `/siren/{siren}`. Augmenter cette valeur si l'API renvoie encore des `429`.

Codes NAF utilisés :

- `8121Z` : nettoyage courant des bâtiments
- `8129B` : autres activités de nettoyage
- `8130Z` : services d'aménagement paysager
- `8810A` : aide à domicile
- `8810B` : accueil ou accompagnement sans hébergement

Colonnes principales du CSV :

```csv
siren,siret,nic,nom_ou_denomination,denomination_unite_legale,nom_unite_legale,prenom_usuel_unite_legale,categorie_juridique_unite_legale,est_entrepreneur_individuel,est_micro_entrepreneur_probable,activite_principale_unite_legale,activite_principale_etablissement,code_naf_retenu,date_creation_unite_legale,date_creation_etablissement,etat_administratif_unite_legale,etat_administratif_etablissement,tranche_effectifs_unite_legale,tranche_effectifs_etablissement,caractere_employeur_unite_legale,caractere_employeur_etablissement,enseigne_1,enseigne_2,enseigne_3,denomination_usuelle_etablissement,numero_voie,type_voie,libelle_voie,complement_adresse,code_postal,commune,code_commune,adresse_complete,age_etablissement_annees,score_priorisation,raison_score
123456789,12345678900012,00012,ALICE DUPONT,,DUPONT,ALICE,1000,True,True,8121Z,8121Z,8121Z,2018-04-10,2018-04-10,A,A,NN,NN,N,N,CLEAN SERVICES,,,,12,RUE,DES LILAS,,33000,BORDEAUX,33063,"12 RUE DES LILAS, 33000 BORDEAUX",8,5,"activite_8121Z:+2; age_plus_5_ans:+2; enseigne_renseignee:+1"
```

Limites connues :

- l'API SIRENE ne donne pas toujours le statut micro-entrepreneur avec certitude ; la colonne `est_micro_entrepreneur_probable` est donc une approximation ;
- les coordonnées téléphone/email ne sont pas disponibles dans SIRENE ;
- le filtrage par code postal peut inclure des communes hors Bordeaux Métropole si le code postal est partagé.
- l'API SIRENE retourne souvent les activités au format pointé, par exemple `81.21Z`, même si les constantes métier du projet utilisent `8121Z`.

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

## Qualité de code et tests

Le projet utilise `requirements.txt` pour les dépendances runtime. Les outils de développement sont séparés dans `requirements-dev.txt`.

Installer les dépendances de développement :

```bash
python3 -m pip install -r requirements-dev.txt
```

Lint avec Ruff :

```bash
python -m ruff check .
```

Formater le code avec Ruff :

```bash
python -m ruff format .
```

Vérifier le typage statique avec mypy :

```bash
python -m mypy
```

Lancer la suite de tests existante :

```bash
python -m unittest discover -s tests
```

Notes :

- `ruff` remplace ici le besoin de `black` pour le formatage ; `black` n'est pas ajouté car le projet ne l'utilise pas explicitement.
- la configuration de `ruff` et `mypy` est centralisée dans `pyproject.toml`.
- `mypy` est configuré de façon pragmatique pour analyser le code existant sans imposer immédiatement un typage strict sur toutes les fonctions.

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
- `naf_code` : filtre par un ou plusieurs codes NAF séparés par des virgules
- `sort_score` : `asc` ou `desc`

Exemples :

```text
/?section=01
/?section=15.1&sort_score=asc
/?naf_code=68.20B,81.10Z
/?page=3&section=56&sort_score=desc
```

## Scripts du dépôt

- `main.py` : application FastAPI principale
- `populate_naf_db.py` : alimentation de la table `naf_code`
- `import_siren_csv_companies.py` : import et enrichissement des entreprises dans `companies.db` depuis les fichiers stock SIRENE
- `init_financial_documents.py` : création de la table `financial_documents`
- `import_financial_documents.py` : import des métadonnées de documents financiers depuis le SFTP INPI
- `download_annual_accounts.py` : téléchargement des derniers bilans PDF publics via l'API INPI/RNE
- `generate_companies_html.py` : génération de `companies.html` en statique
- `scripts/export_bordeaux_independants.py` : export CSV des entrepreneurs individuels ciblés depuis l'API SIRENE

## Services

- `services/inpi_sftp.py` : connexion au SFTP INPI et listage des fichiers disponibles à partir de `SFTP_HOST`, `SFTP_USER` et `SFTP_PASSWORD`
- `services/inpi_annual_accounts.py` : client HTTP minimal pour l'API INPI/RNE des comptes annuels
- `services/insee_sirene.py` : client HTTP pour l'API SIRENE INSEE v3.11
- `services/insee_sirene_mapping.py` : mapping des réponses SIRENE vers les lignes CSV consolidées

## Fichiers importants

- `companies.db` : base SQLite locale
- `templates/index.html` : page entreprises
- `templates/naf_sections.html` : page sections NAF
- `constants.py` : mapping des tranches d'effectifs

## Notes

- la page principale conserve l'organisation par sections NAF même quand le tri par score est activé
- le tri par score s'applique à l'intérieur de cette hiérarchie
- le générateur `generate_companies_html.py` existe encore, mais la documentation ci-dessus concerne principalement l'application FastAPI
