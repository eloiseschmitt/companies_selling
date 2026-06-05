"""Exporte les entrepreneurs individuels ciblés de Bordeaux Métropole via SIRENE."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from services.insee_sirene import InseeSireneClient
from services.insee_sirene_mapping import (
    CSV_COLUMNS,
    extract_unite_legale,
    map_etablissement_to_csv_row,
)

DEFAULT_OUTPUT = Path("independants_bordeaux_metropole.csv")
DEFAULT_CACHE = Path(".cache") / "insee_sirene_unites_legales.json"
DEFAULT_ENRICH_DELAY_SECONDS = 1.0


class JsonSirenCache:
    """Cache JSON minimal pour éviter les appels répétés à `/siren/{siren}`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._payloads: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    def get(self, siren: str) -> dict[str, Any] | None:
        return self._payloads.get(siren)

    def set(self, siren: str, payload: dict[str, Any]) -> None:
        self._payloads[siren] = payload
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._payloads, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._dirty = False

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cache JSON INSEE invalide: {self.path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Cache JSON INSEE invalide: {self.path}")
        self._payloads = {
            str(siren): value
            for siren, value in payload.items()
            if isinstance(value, dict)
        }


class CachedSireneClient:
    """Décore le client SIRENE avec un cache local pour les unités légales."""

    def __init__(
        self,
        client: InseeSireneClient,
        cache: JsonSirenCache,
        enrich_delay_seconds: float = DEFAULT_ENRICH_DELAY_SECONDS,
    ) -> None:
        self.client = client
        self.cache = cache
        self.enrich_delay_seconds = enrich_delay_seconds

    def get_siren(self, siren: str) -> dict[str, Any]:
        cached_payload = self.cache.get(siren)
        if cached_payload is not None:
            return cached_payload

        payload = self.client.get_siren(siren)
        self.cache.set(siren, payload)
        self.cache.save()
        if self.enrich_delay_seconds > 0:
            time.sleep(self.enrich_delay_seconds)
        return payload


class ProgressBar:
    """Barre de progression texte simple, sans dépendance externe."""

    def __init__(self, total: int, stream: TextIO = sys.stderr) -> None:
        self.total = max(0, total)
        self.stream = stream
        self.current = 0

    def advance(self) -> None:
        self.current += 1
        self.render()

    def render(self) -> None:
        if self.total <= 0:
            return
        width = 24
        ratio = min(1.0, self.current / self.total)
        filled = int(width * ratio)
        bar = "#" * filled + "-" * (width - filled)
        percent = int(ratio * 100)
        self.stream.write(f"\r[{bar}] {self.current}/{self.total} {percent}%")
        self.stream.flush()

    def finish(self) -> None:
        if self.total > 0:
            self.stream.write("\n")
            self.stream.flush()


def export_bordeaux_independants(
    output_path: Path = DEFAULT_OUTPUT,
    cache_path: Path = DEFAULT_CACHE,
    limit: int | None = None,
    client: InseeSireneClient | None = None,
    progress_stream: TextIO = sys.stderr,
    enrich_delay_seconds: float = DEFAULT_ENRICH_DELAY_SECONDS,
) -> int:
    """Recherche, enrichit et exporte les entrepreneurs individuels ciblés."""
    sirene_client = client or InseeSireneClient()
    etablissements = sirene_client.search_etablissements(limit=limit)
    cache = JsonSirenCache(cache_path)
    cached_client = CachedSireneClient(
        sirene_client,
        cache,
        enrich_delay_seconds=enrich_delay_seconds,
    )
    uncached_count = count_uncached_etablissements(etablissements, cache)
    progress = ProgressBar(uncached_count, progress_stream)
    rows: list[dict[str, Any]] = []
    seen_sirens: set[str] = set()
    seen_sirets: set[str] = set()
    skipped_cached = 0

    try:
        for etablissement in etablissements:
            siren = extract_siren_from_etablissement(etablissement)
            if not siren:
                continue

            cached_payload = cache.get(siren)
            if cached_payload is not None:
                skipped_cached += 1
                row = map_etablissement_to_csv_row(
                    etablissement,
                    extract_unite_legale(cached_payload),
                )
            else:
                try:
                    unite_legale_payload = cached_client.get_siren(siren)
                    row = map_etablissement_to_csv_row(
                        etablissement,
                        extract_unite_legale(unite_legale_payload),
                    )
                finally:
                    progress.advance()

            siren = str(row.get("siren") or "")
            siret = str(row.get("siret") or "")
            if not siren or not siret:
                continue
            if siren in seen_sirens or siret in seen_sirets:
                continue
            if row.get("categorie_juridique_unite_legale") != "1000":
                continue

            seen_sirens.add(siren)
            seen_sirets.add(siret)
            rows.append(row)
    finally:
        cache.save()
        progress.finish()

    write_csv(output_path, rows)
    progress_stream.write(
        f"Export terminé: {len(rows)} lignes écrites dans {output_path}. "
        f"{skipped_cached} établissement(s) repris depuis le cache.\n"
    )
    progress_stream.flush()
    return len(rows)


def count_uncached_etablissements(
    etablissements: list[dict[str, Any]],
    cache: JsonSirenCache,
) -> int:
    uncached_sirens: set[str] = set()
    for etablissement in etablissements:
        siren = extract_siren_from_etablissement(etablissement)
        if siren and cache.get(siren) is None:
            uncached_sirens.add(siren)
    return len(uncached_sirens)


def extract_siren_from_etablissement(etablissement: dict[str, Any]) -> str:
    siren = str(etablissement.get("siren") or "").strip()
    if siren:
        return siren

    siret = str(etablissement.get("siret") or "").strip()
    if len(siret) >= 9:
        return siret[:9]
    return ""


def write_csv(output_path: Path, rows: list[dict[str, Any]]) -> None:
    """Écrit un CSV UTF-8 avec BOM compatible Excel."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exporte les entrepreneurs individuels SIRENE actifs et sièges "
            "de Bordeaux Métropole pour les codes NAF ciblés."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Chemin du CSV de sortie.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="Chemin du cache JSON local des unités légales.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre maximal d'établissements à récupérer avant enrichissement.",
    )
    parser.add_argument(
        "--enrich-delay",
        type=float,
        default=DEFAULT_ENRICH_DELAY_SECONDS,
        help="Temps d'attente en secondes après chaque nouvel appel /siren.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    export_bordeaux_independants(
        output_path=args.output,
        cache_path=args.cache,
        limit=args.limit,
        enrich_delay_seconds=args.enrich_delay,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
