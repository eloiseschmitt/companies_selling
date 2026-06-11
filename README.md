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

Commandes locales via `Makefile` :

```bash
make format    # ruff format .
make lint      # ruff check .
make type      # mypy .
make test      # unittest
make coverage  # unittest avec rapport de couverture
make quality   # lint + mypy + tests
```

Commandes équivalentes sans `make` :

Formater le code avec Ruff :

```bash
ruff format .
```

Lint avec Ruff :

```bash
ruff check .
```

Vérifier le typage statique avec mypy :

```bash
mypy .
```

Lancer la suite de tests existante :

```bash
python3 -m unittest discover -s tests
```

Lancer les tests avec couverture :

```bash
coverage run -m unittest discover -s tests
coverage report -m
```

Notes :

- `ruff` remplace ici le besoin de `black` pour le formatage ; `black` n'est pas ajouté car le projet ne l'utilise pas explicitement.
- la configuration de `ruff`, `mypy` et `coverage` est centralisée dans `pyproject.toml`.
- `mypy` est configuré de façon pragmatique pour analyser le code existant sans imposer immédiatement un typage strict sur toutes les fonctions.

## Lancer l'application web

```bash
uvicorn main:app --reload
```

Puis ouvrir :

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/naf_sections`
- `http://127.0.0.1:8000/independants/table`

## Consultation des indépendants

La consultation des indépendants s'appuie sur le fichier CSV consolidé généré par l'export SIRENE :

```bash
python -m scripts.export_bordeaux_independants --output independants_bordeaux_metropole.csv
```

Lancer FastAPI :

```bash
uvicorn main:app --reload
```

Page tableau HTML :

```text
http://127.0.0.1:8000/independants/table
```

API JSON :

```text
http://127.0.0.1:8000/independants
```

Exemples d'URL filtrées :

```text
/independants/table?commune=BORDEAUX&score_min=6
/independants/table?code_postal=33700&code_naf=8121Z
/independants/table?q=nettoyage&employeur=oui
/independants?commune=MERIGNAC&sort_by=score_priorisation&sort_order=desc&limit=50&offset=0
```

Filtres disponibles :

- `q` : recherche texte libre sur les champs principaux.
- `commune` : filtre exact insensible à la casse, par exemple `BORDEAUX`.
- `code_postal` : filtre exact, par exemple `33000`.
- `code_naf` : filtre par code NAF, accepte les formes `8121Z` et `81.21Z`.
- `score_min` : score de priorisation minimum.
- `employeur` : `oui` ou `non`, basé sur `caractere_employeur_unite_legale`.
- `limit` : nombre de lignes chargées côté serveur.
- `offset` : décalage de pagination côté serveur.

Tri côté serveur :

- `sort_by` : colonne de tri.
- `sort_order` : `asc` ou `desc`.

Colonnes triables :

- `nom_ou_denomination`
- `commune`
- `code_postal`
- `code_naf_retenu`
- `date_creation_etablissement`
- `age_etablissement_annees`
- `score_priorisation`

La page tableau utilise aussi DataTables pour la recherche instantanée, le tri et la pagination côté navigateur sur les lignes déjà chargées. DataTables est chargé via CDN, car le projet ne sert pas encore de fichiers JS/CSS locaux.

Limites connues :

- la page HTML ne charge jamais plus de `500` lignes ; utiliser les filtres serveur pour les gros volumes ;
- l'API JSON borne `limit` à `200` lignes ;
- les filtres serveur relisent le CSV local `independants_bordeaux_metropole.csv` ;
- les données affichées ne sont à jour qu'après relance de l'export CSV ;
- le statut micro-entrepreneur reste probable, pas certain ;
- les coordonnées téléphone/email ne sont pas disponibles dans SIRENE ;
- le filtrage par code postal peut inclure des communes hors Bordeaux Métropole si le code postal est partagé.

## Routes principales

- `/` : liste des entreprises
- `/naf_sections` : liste des sections NAF
- `/api/companies` : API JSON des entreprises
- `/api/naf_sections` : API JSON des codes NAF
- `/independants/table` : page HTML des indépendants exportés depuis SIRENE
- `/independants` : API JSON des indépendants exportés depuis SIRENE

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
- `scripts/extract_bordeaux_iris_indicators.py` : extraction d'indicateurs INSEE IRIS pour des secteurs métier de Bordeaux Métropole
- `scripts/export_iris_candidates.py` : export des IRIS des communes concernées pour préparer le mapping manuel des secteurs

## Services

- `services/inpi_sftp.py` : connexion au SFTP INPI et listage des fichiers disponibles à partir de `SFTP_HOST`, `SFTP_USER` et `SFTP_PASSWORD`
- `services/inpi_annual_accounts.py` : client HTTP minimal pour l'API INPI/RNE des comptes annuels
- `services/insee_sirene.py` : client HTTP pour l'API SIRENE INSEE v3.11
- `services/insee_sirene_mapping.py` : mapping des réponses SIRENE vers les lignes CSV consolidées
- `services/data_sources.py` : téléchargement des sources externes, stockage dans `data/raw/` et maintenance du manifeste `data/source_manifest.json`
- `services/geography.py` : chargement de la table géographique IRIS et validation du mapping manuel secteur -> IRIS
- `services/income_loader.py` : chargement des fichiers Filosofi IRIS et extraction du revenu disponible médian par unité de consommation
- `services/population_loader.py` : chargement des fichiers de recensement IRIS et calcul de la population de 75 ans et plus
- `services/household_loader.py` : chargement des fichiers ménages/recensement IRIS et extraction des indicateurs 75 ans et plus vivant seuls
- `services/retired_csp_loader.py` : recherche conservatrice d'un indicateur retraités anciennement cadres/professions intellectuelles supérieures à l'échelle IRIS
- `services/sector_aggregator.py` : agrégation des indicateurs IRIS au niveau des secteurs définis manuellement
- `services/insee_iris_indicators.py` : chargement, calcul et persistance SQLite des indicateurs INSEE IRIS

## Indicateurs INSEE IRIS Bordeaux Métropole

Le script `scripts.extract_bordeaux_iris_indicators` produit un tableau d'indicateurs IRIS pour des secteurs métier de Bordeaux Métropole :

- revenu disponible médian par unité de consommation ;
- population de 75 ans et plus ;
- personnes ou ménages de 75 ans et plus vivant seuls, si la colonne est disponible ;
- retraités CSP+, uniquement en approximation si les colonnes nécessaires sont disponibles.

Le périmètre secteur -> IRIS doit être renseigné explicitement dans un fichier JSON. Le modèle fourni est `config/bordeaux_iris_sectors.example.json`. Les listes `iris_codes` sont volontairement vides : le script refuse de calculer un secteur sans IRIS validés afin de ne pas inventer de périmètre statistique.

Un mapping manuel YAML est aussi prévu dans `config/sector_iris_mapping.yml` pour documenter l'association secteur métier -> codes IRIS validés. Ce fichier doit être rempli après revue humaine ; le code ne déduit jamais automatiquement les IRIS d'un quartier.

Pour aider à remplir ce mapping, exporter tous les IRIS des communes concernées :

```bash
python -m scripts.export_iris_candidates \
  --iris-source path-to-iris-geography.csv \
  --output data/output/iris_candidates.csv
```

La table IRIS source doit contenir au minimum :

- code IRIS ;
- libellé IRIS ;
- code commune ;
- nom commune.

Le module `services.income_loader` charge les fichiers Filosofi IRIS en CSV, ZIP, XLS/XLSX ou Parquet via pandas et produit une table normalisée :

- `iris_code` ;
- `iris_label` si disponible ;
- `commune_code` si disponible ;
- `median_disposable_income` ;
- `source_name` ;
- `source_year`.

Le module `services.population_loader` charge les fichiers de recensement IRIS en CSV, ZIP, XLS/XLSX ou Parquet via pandas et produit une table normalisée :

- `iris_code` ;
- `population_total` si disponible ;
- `population_75_plus` ;
- `source_name` ;
- `source_year` ;
- `quality_flag`.

`quality_flag` vaut `exact` quand les colonnes disponibles permettent un calcul précis de 75 ans et plus, `approximate_age_bands` quand seules des tranches plus larges sont disponibles.

Le module `services.household_loader` extrait les indicateurs de personnes âgées vivant seules selon une priorité stricte :

- personnes de 75 ans et plus vivant seules, si disponible directement ;
- ménages d'une personne dont la personne de référence a 75 ans ou plus, si disponible ;
- estimation documentée à partir des variables disponibles.

La sortie inclut toujours `metric_definition` pour distinguer les personnes vivant seules des ménages d'une personne, et `quality_flag` pour signaler les valeurs exactes ou estimées.

Le module `services.retired_csp_loader` recherche uniquement des variables directes de retraités anciennement cadres ou professions intellectuelles supérieures. Si aucune variable fiable n'est présente dans le fichier IRIS, les valeurs restent vides et `quality_flag` vaut `not_available_directly_at_iris_level`. Le module ne fabrique pas d'estimation à partir de variables séparées comme retraités totaux et CSP+ actifs.

Le module `services.sector_aggregator` agrège les tables IRIS normalisées au niveau des secteurs de `config/sector_iris_mapping.yml` :

- `population_75_plus` est sommée ;
- `single_75_plus_count` est sommée uniquement si le `quality_flag` indique un indicateur sommable ;
- le revenu médian n'est jamais moyenné simplement : le module retourne la fourchette min/max des médianes IRIS et une moyenne pondérée seulement si une colonne de poids fiable est fournie ;
- `retired_csp_plus_count` est agrégé uniquement quand la source est directe et fiable.

Exemple d'exécution avec des fichiers INSEE CSV ou ZIP locaux ou distants :

```bash
python -m scripts.extract_bordeaux_iris_indicators \
  --config config/bordeaux_iris_sectors.json \
  --income-source path-or-url-to-filosofi-iris.zip \
  --income-vintage 2021 \
  --population-source path-or-url-to-rp-iris-population.zip \
  --population-vintage 2021 \
  --household-source path-or-url-to-rp-iris-households.zip \
  --household-vintage 2021 \
  --raw-dir data/raw \
  --manifest data/source_manifest.json \
  --output bordeaux_iris_indicators.csv \
  --db companies.db
```

Le script :

- accepte des sources CSV, XLSX, ZIP ou Parquet au niveau du registre des sources ;
- lit actuellement les sources tabulaires CSV ou ZIP contenant un CSV pour le calcul IRIS ;
- télécharge les URL dans `data/raw/` et réutilise le fichier local déjà présent ;
- retélécharge une source distante si l'option `--force-refresh` est utilisée ;
- maintient `data/source_manifest.json` avec le nom du jeu de données, l'URL, la date de téléchargement, le millésime détecté ou fourni, le fichier local et son hash SHA256 ;
- écrit les résultats dans `bordeaux_iris_indicators.csv` ;
- persiste les mêmes résultats dans la table SQLite `insee_iris_indicators` ;
- conserve pour chaque indicateur la source, le millésime, la qualité du calcul et la méthode.

Limites importantes :

- un revenu médian agrégé sur plusieurs IRIS n'est pas recalculable exactement depuis des médianes IRIS ; le script produit donc une approximation pondérée si une colonne de poids est disponible ;
- l'indicateur retraités CSP+ n'est pas une donnée standard directement croisée dans les fichiers IRIS ; quand les colonnes ne permettent pas une approximation explicite, la valeur reste vide avec une note ;
- les noms de secteurs comme `Mérignac centre` ou `Bègles secteur résidentiel` ne sont pas des zonages INSEE.

## Fichiers importants

- `companies.db` : base SQLite locale
- `templates/index.html` : page entreprises
- `templates/naf_sections.html` : page sections NAF
- `constants.py` : mapping des tranches d'effectifs

## Notes

- la page principale conserve l'organisation par sections NAF même quand le tri par score est activé
- le tri par score s'applique à l'intérieur de cette hiérarchie
- le générateur `generate_companies_html.py` existe encore, mais la documentation ci-dessus concerne principalement l'application FastAPI
