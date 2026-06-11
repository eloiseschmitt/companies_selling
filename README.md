# companies_selling

Pipeline Python/FastAPI pour produire un rapport INSEE à l'échelle IRIS sur des secteurs métier de Bordeaux Métropole.

Le périmètre statistique est volontairement explicite : les quartiers métier ne sont jamais déduits automatiquement. Chaque secteur doit être relié manuellement à une liste de codes IRIS validés dans `config/sector_iris_mapping.yml`.

## Sources INSEE Utilisées

Le rapport s'appuie sur des fichiers INSEE IRIS téléchargés ou fournis localement.

Sources prioritaires :

- `INSEE Filosofi IRIS` : revenu disponible médian par unité de consommation.
- `INSEE Recensement de la population, base infracommunale IRIS` : population par âge, notamment 75 ans et plus.
- `Couples - Familles - Ménages en 2022 - Recensement de la population - Base infracommunale IRIS` : personnes âgées vivant seules ou ménages d'une personne selon les variables disponibles.
- Fichiers détaillés ou bases agrégées INSEE IRIS : recherche conservative de deux indicateurs séparés, `retired_count` et `csp_plus_15_plus_count`.
- Table géographique IRIS : code IRIS, libellé IRIS, code commune, nom commune.

Le code accepte des sources `CSV`, `ZIP` contenant un CSV, `XLS/XLSX` ou `Parquet` selon les loaders. Les URL officielles ne sont pas codées en dur : elles doivent être passées explicitement, afin d'éviter de figer une source incertaine ou obsolète.

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Pour les outils de développement :

```bash
python -m pip install -r requirements-dev.txt
```

## Télécharger Les Données

La CLI principale est exposée via `python -m app`.

Exemple :

```bash
python -m app download-sources \
  --income-source "https://example/insee-filosofi-iris.zip" \
  --population-source "https://example/insee-rp-population-iris.zip" \
  --household-source "https://example/insee-rp-menages-iris.zip" \
  --retired-csp-source "https://example/insee-rp-detail-iris.zip" \
  --iris-source "https://example/insee-iris-geography.csv"
```

Les fichiers distants sont stockés dans `data/raw/`. Le manifeste est écrit dans `data/source_manifest.json` avec :

- nom du jeu de données ;
- URL source ;
- date de téléchargement ;
- millésime détecté si possible ;
- nom du fichier local ;
- hash SHA256.

Par défaut, un fichier déjà présent n'est pas retéléchargé. Pour forcer un rafraîchissement :

```bash
python -m app download-sources \
  --force-refresh \
  --income-source "https://example/insee-filosofi-iris.zip"
```

Après un premier téléchargement, les autres commandes retrouvent automatiquement les fichiers depuis `data/source_manifest.json`. En usage courant, le flux devient :

```bash
python -m app download-sources
python -m app export-iris-candidates
python -m app validate-mapping
python -m app build-report
```

## Remplir Le Mapping IRIS Par Quartier

Les secteurs métier attendus sont définis dans `config/sector_iris_mapping.yml` :

- Bordeaux Caudéran
- Bordeaux Fondaudège
- Bordeaux Chartrons
- Le Bouscat
- Bruges
- Mérignac centre
- Saint-Médard-en-Jalles
- Talence
- Pessac centre
- Bègles secteur résidentiel

Pour préparer le mapping, exporter tous les IRIS des communes concernées :

```bash
python -m app export-iris-candidates
```

La commande utilise `--iris-source` si fourni. Sinon elle cherche automatiquement la source géographique IRIS dans `data/source_manifest.json`.

Le fichier source IRIS doit contenir au minimum :

- code IRIS ;
- libellé IRIS ;
- code commune ;
- nom commune.

Ensuite, ouvrir `data/output/iris_candidates.csv`, examiner les libellés IRIS, puis reporter manuellement les codes retenus dans `config/sector_iris_mapping.yml`.

Exemple :

```yaml
sectors:
  Bordeaux Caudéran:
    - 330630101
    - 330630102
  Bordeaux Fondaudège: []
```

Règle importante : ne pas affecter un IRIS à un quartier sans validation humaine. Les libellés métier comme `Mérignac centre` ou `Bègles secteur résidentiel` ne sont pas des zonages INSEE normalisés.

Valider le mapping :

```bash
python -m app validate-mapping
```

Comme pour l'export des candidats, `validate-mapping` utilise `--iris-source` si fourni, sinon la source IRIS du manifeste.

La validation vérifie notamment que les IRIS mappés existent et appartiennent à la commune attendue.

## Construire Et Relancer Le Rapport

Pour diagnostiquer une source avant de l'utiliser dans le pipeline :

```bash
python -m app inspect-source --source data/raw/ma-source-insee.zip
```

La commande lit `CSV`, `XLS/XLSX` ou `ZIP` contenant ces formats. Elle affiche les fichiers internes du ZIP, les colonnes, les 5 premières lignes, les colonnes contenant des motifs utiles (`AGE`, `75`, `SEUL`, `MENAGE`, `CS`, `RETR`, `P22`, etc.), le nombre de lignes et le nombre de codes IRIS distincts.

Commande type :

```bash
python -m app build-report
```

`build-report` utilise les chemins explicites si `--income-file`, `--population-file`, `--household-file` ou `--retired-csp-file` sont fournis. Sinon il recherche automatiquement les fichiers correspondants dans `data/source_manifest.json`.

La commande génère :

- `data/output/sector_report.csv`
- `data/output/sector_report.xlsx`
- `data/output/source_manifest.json`
- `data/output/quality_report.md`

Options utiles :

```bash
python -m app build-report --verbose
python -m app build-report --output-format xlsx
python -m app build-report --sector-mapping config/sector_iris_mapping.yml
```

Pour relancer proprement :

1. Mettre à jour les fichiers sources dans `data/raw/` ou relancer `download-sources --force-refresh`.
2. Vérifier ou compléter `config/sector_iris_mapping.yml`.
3. Relancer `validate-mapping`.
4. Relancer `build-report`.
5. Lire `data/output/quality_report.md` avant d'utiliser les chiffres.

## Indicateurs Produits

Le rapport secteur contient notamment :

- `sector_name`
- `iris_codes`
- `median_income_min`
- `median_income_max`
- `median_income_weighted`
- `median_income_iris_values`
- `population_75_plus`
- `single_75_plus_count`
- `retired_count`
- `csp_plus_15_plus_count`
- `quality_notes`
- `source_years`

Les loaders normalisent les données IRIS avant agrégation :

- `services.income_loader` : revenu disponible médian Filosofi.
- `services.population_loader` : population de 75 ans et plus.
- `services.household_loader` : personnes âgées vivant seules ou ménages d'une personne si une variable directe 75+ existe.
- `services.retired_csp_loader` : retraités totaux et CSP+ 15 ans et plus comme deux marges séparées.
- `services.sector_aggregator` : agrégation au niveau secteur.

## Limites Statistiques

### Revenu Médian IRIS

Le revenu disponible médian par unité de consommation est une médiane locale. Une médiane n'est pas additive.

Il ne faut pas calculer une moyenne simple des médianes IRIS pour obtenir un revenu médian de secteur, car cela donnerait le même poids à un IRIS très peu peuplé et à un IRIS très peuplé.

Le pipeline applique donc cette règle :

- il fournit toujours `median_income_min` et `median_income_max` pour afficher la fourchette des IRIS du secteur ;
- il peut exporter `median_income_iris_values` pour auditer les valeurs IRIS individuelles ;
- il calcule `median_income_weighted` uniquement si une colonne de pondération fiable est fournie ;
- même pondérée, cette valeur reste une approximation à partir de médianes IRIS, pas une vraie médiane recalculée sur les ménages/personnes du secteur.

### Population 75 Ans Et Plus

`population_75_plus` est sommée lorsque les colonnes d'âge le permettent.

Le loader cherche en priorité :

- une colonne directe 75+ ;
- sinon des tranches exactes comme `75-79`, `80-84`, `85-89`, `90+` ;
- sinon des tranches plus larges, avec `quality_flag = approximate_age_bands`.

Si les tranches disponibles ne permettent pas un calcul exploitable, le code lève une erreur explicite plutôt que d'inventer un chiffre.

### Personnes De 75+ Vivant Seules Vs Ménages D'une Personne 75+

Ces deux indicateurs sont proches mais ne doivent pas être confondus.

`Personnes de 75 ans et plus vivant seules` :

- l'unité statistique est la personne ;
- la variable compte des individus âgés de 75 ans ou plus dont la situation de vie est seul ;
- c'est l'indicateur prioritaire si une colonne directe existe.

`Ménages d'une personne dont la personne de référence a 75 ans ou plus` :

- l'unité statistique est le ménage ;
- la variable compte des ménages composés d'une seule personne, dont la personne de référence a 75 ans ou plus ;
- pour un ménage d'une personne, le volume peut être proche d'un nombre de personnes, mais la définition reste différente.

Le rapport garde donc une colonne `metric_definition` au niveau IRIS et des notes de qualité au niveau secteur. Quand le calcul agrège des ménages d'une personne plutôt que des personnes vivant seules, `quality_notes` le signale.

### Retraités Et CSP+

L'indicateur `retraités anciennement cadres / professions intellectuelles supérieures` n'est pas systématiquement disponible directement à l'échelle IRIS dans les fichiers standards.

Le pipeline est volontairement conservateur :

- `retired_count` est produit si une colonne de retraités est disponible ;
- `csp_plus_15_plus_count` est produit si une colonne CSP+ 15 ans et plus est disponible ;
- ces deux colonnes sont agrégées séparément ;
- elles ne sont jamais fusionnées pour fabriquer un indicateur `retraités CSP+`, car cela mélangerait deux marges statistiques différentes.

## Qualité Et Tests

Lancer les tests unitaires :

```bash
python -m unittest discover -s tests
```

Lancer les tests ciblés du pipeline IRIS :

```bash
python -m unittest \
  tests.test_iris_pipeline_units \
  tests.test_income_loader \
  tests.test_population_loader \
  tests.test_household_loader \
  tests.test_retired_csp_loader \
  tests.test_sector_aggregator \
  tests.test_geography \
  tests.test_data_sources
```

Lint :

```bash
ruff check .
```

## Application Web Historique

Le dépôt contient aussi une application FastAPI historique pour explorer une base SQLite d'entreprises et des exports SIRENE. Elle reste lançable avec :

```bash
uvicorn main:app --reload
```

La CLI INSEE IRIS est exposée par `app.py` via `python -m app` ; l'application web principale reste dans `main.py`.
