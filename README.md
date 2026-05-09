# companies_selling

Ce dépôt contient un petit script Python pour interroger l'API Sirene (INSEE) afin de :

- lister les SIREN correspondant à un filtre (ex. PME créées avant 2000),
- récupérer les informations du siège actif pour ces entreprises.

Résumé du fonctionnement

- Le script récupère les SIREN page par page via l'endpoint `/siren`.
- Pour chaque SIREN, il interroge l'endpoint `/siret` afin d'obtenir le siège actif.
- Les requêtes HTTP utilisent une `requests.Session()` configurée avec un mécanisme de retry et un `RateLimiter` simple.
- Pour la scalabilité, le script propose :
	- `fetch_siren_batches()` : générateur qui stream les pages de SIREN,
	- `fetch_head_offices_parallel()` : récupère les sièges en parallèle via `ThreadPoolExecutor` (contrôle du débit).

Prérequis

- Python 3.8+
- Une clé API INSEE valide (API Sirene).

Installation

1. Créez et activez un environnement virtuel (recommandé) :

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Installez les dépendances :

```bash
python3 -m pip install -r requirements.txt
```

Configuration

- Définissez la variable d'environnement `API_KEY` contenant votre clé :

```bash
# companies_selling

Ce dépôt contient un script Python qui interroge l'API Sirene (INSEE) pour :

- lister les SIREN correspondant à un filtre (ex. PME créées avant 2000),
- récupérer les informations du siège actif pour ces entreprises,
- exporter les résultats dans un fichier CSV (`companies.csv`).

Résumé du comportement actuel

- Récupération des SIREN page par page via l'endpoint `/siren`.
- Pour chaque SIREN, le script interroge `/siret` pour obtenir le siège actif.
- La requête dans `fetch_head_offices` contient actuellement un filtre additionnel `codeRegionEtablissement:75` (modifiable dans le code).
- Les requêtes utilisent une `requests.Session()` configurée avec des retries et un `RateLimiter` simple pour éviter de dépasser le débit.
- Le script propose un pipeline streaming :
	- `fetch_siren_batches()` : générateur qui retourne une liste de SIREN par page,
	- `fetch_head_offices_parallel()` : récupère les sièges en parallèle avec contrôle du débit et option de barre de progression (`tqdm`).

Prérequis

- Python 3.8+
- Une clé API INSEE valide (API Sirene).

Installation

1. Créez et activez un environnement virtuel (recommandé) :

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Installez les dépendances :

```bash
python3 -m pip install -r requirements.txt
```

Remarque : `tqdm` est listé dans `requirements.txt`. Si vous ne souhaitez pas la barre de progression, vous pouvez ignorer son installation (le script utilise `tqdm.tqdm` directement et lèvera une erreur si `tqdm` n'est pas installé).

Configuration

- Définir la variable d'environnement `API_KEY` contenant votre clé :

```bash
export API_KEY="votre_cle_api"
```

- Paramètres modifiables dans le code :
	- `PAGE_SIZE` : taille de page pour l'API (défaut 100)
	- `RATE_LIMIT_PER_SEC` : requêtes/seconde globales pour `fetch_head_offices_parallel`
	- `MAX_WORKERS` : nombre max de threads pour la parallélisation
	- Filtre de région dans `fetch_head_offices` (actuellement `codeRegionEtablissement:75`).

Utilisation

Lancer le script principal (après avoir exporté `API_KEY`) :

```bash
python3 retrieve_siren_companies.py
```

Résultat

- Le script écrit un fichier `companies.csv` à la racine du projet contenant les colonnes : `siren`, `siret`, `nom`, `date_creation`, `region`, `naf`.

Dépannage

- `API_KEY not set in environment` : assurez-vous d'avoir exporté `API_KEY` dans la même session terminal.
- Si `ModuleNotFoundError: No module named 'tqdm'` : installez `tqdm` via `pip install tqdm` ou installez les dépendances via `requirements.txt`.
- Si l'API renvoie beaucoup de 429, réduisez `RATE_LIMIT_PER_SEC` ou augmentez le `backoff_factor` dans la configuration `Retry`.

Améliorations possibles

- Ajouter un CLI (`argparse`) pour configurer `--workers`, `--rate`, `--page-size`, et `--out` pour nommer le CSV de sortie.
- Rendre `tqdm` optionnel (fallback) pour éviter l'échec si non installé.
- Persister directement dans un CSV/BD par lot pour réduire l'empreinte mémoire.
- Ajouter des tests unitaires (avec `requests-mock`) pour valider le parsing des réponses.

Contact

Pour toute question, ouvrez une issue ou contactez l'auteur du dépôt.

