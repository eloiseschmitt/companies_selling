"""Télécharge les derniers bilans PDF publics INPI pour une liste de SIREN."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from pathlib import Path
from typing import Any

from services.inpi_annual_accounts import (
    InpiAnnualAccountsClient,
    select_best_bilan_pdf,
)


DEFAULT_OUTPUT_DIR = Path("downloads/annual_accounts")
DEFAULT_RESULTS_FILE = Path("annual_accounts_results.csv")
RESULT_COLUMNS = [
    "siren",
    "status",
    "bilan_id",
    "date_cloture",
    "date_depot",
    "confidentiality",
    "type_bilan",
    "filename",
    "message",
]
REASON_STATUSES = {
    "no_bilan": "not_found",
    "only_confidential": "confidential",
    "only_deleted": "deleted_only",
}

logger = logging.getLogger(__name__)


def read_sirens(input_path: Path) -> list[str]:
    with input_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or "siren" not in reader.fieldnames:
            raise ValueError("Le CSV d'entrée doit contenir une colonne siren.")

        return [
            str(row.get("siren") or "").strip()
            for row in reader
            if str(row.get("siren") or "").strip()
        ]


def process_siren(
    client: InpiAnnualAccountsClient,
    siren: str,
    output_dir: Path,
) -> dict[str, str]:
    row = empty_result_row(siren)
    try:
        attachments = client.get_company_attachments(siren)
        if not isinstance(attachments, dict):
            raise ValueError("Réponse attachments INPI invalide.")

        bilan, reason = select_best_bilan_pdf(attachments)
        if bilan is None:
            row["status"] = REASON_STATUSES.get(reason or "", "not_found")
            row["message"] = reason or "no_bilan"
            return row

        bilan_id = get_bilan_id(bilan)
        if not bilan_id:
            raise ValueError("Identifiant de bilan absent.")

        output_path = build_output_path(output_dir, siren, bilan_id)
        downloaded_path = client.download_bilan_pdf(bilan_id, output_path)

        row.update(
            {
                "status": "downloaded",
                "bilan_id": bilan_id,
                "date_cloture": str(bilan.get("dateCloture") or ""),
                "date_depot": str(bilan.get("dateDepot") or ""),
                "confidentiality": str(bilan.get("confidentiality") or ""),
                "type_bilan": str(
                    bilan.get("typeBilan") or bilan.get("type_bilan") or ""
                ),
                "filename": downloaded_path.name,
                "message": "",
            }
        )
        return row
    except Exception as exc:
        logger.error("Erreur lors du traitement du SIREN %s: %s", siren, exc)
        row["status"] = "error"
        row["message"] = str(exc)
        return row


def download_annual_accounts(
    input_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    results_path: Path = DEFAULT_RESULTS_FILE,
    sleep_seconds: float = 0.5,
    client: InpiAnnualAccountsClient | None = None,
) -> None:
    sirens = read_sirens(input_path)
    inpi_client = client or InpiAnnualAccountsClient()
    results_path.parent.mkdir(parents=True, exist_ok=True)

    with results_path.open("w", newline="", encoding="utf-8") as results_file:
        writer = csv.DictWriter(results_file, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for index, siren in enumerate(sirens):
            writer.writerow(process_siren(inpi_client, siren, output_dir))
            results_file.flush()
            if index < len(sirens) - 1 and sleep_seconds > 0:
                time.sleep(sleep_seconds)


def empty_result_row(siren: str) -> dict[str, str]:
    return {column: "" for column in RESULT_COLUMNS} | {"siren": siren}


def get_bilan_id(bilan: dict[str, Any]) -> str:
    return str(
        bilan.get("id") or bilan.get("bilan_id") or bilan.get("bilanId") or ""
    )


def build_output_path(output_dir: Path, siren: str, bilan_id: str) -> Path:
    safe_bilan_id = re.sub(r"[^A-Za-z0-9_.-]", "_", bilan_id)
    return output_dir / siren / f"{safe_bilan_id}.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Télécharge les derniers bilans PDF publics INPI."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Chemin vers un CSV contenant une colonne siren.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Dossier de destination des PDF. Défaut: downloads/annual_accounts.",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS_FILE,
        help="Chemin du CSV de résultats. Défaut: annual_accounts_results.csv.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Délai en secondes entre deux SIREN. Défaut: 0.5.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    args = parse_args()
    download_annual_accounts(
        input_path=args.input,
        output_dir=args.output_dir,
        results_path=args.results,
        sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
    main()
