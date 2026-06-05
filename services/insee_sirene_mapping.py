"""Mapping des réponses SIRENE INSEE vers des lignes CSV consolidées."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Protocol

CSV_COLUMNS = (
    "siren",
    "siret",
    "nic",
    "nom_ou_denomination",
    "denomination_unite_legale",
    "nom_unite_legale",
    "prenom_usuel_unite_legale",
    "categorie_juridique_unite_legale",
    "est_entrepreneur_individuel",
    "est_micro_entrepreneur_probable",
    "activite_principale_unite_legale",
    "activite_principale_etablissement",
    "code_naf_retenu",
    "date_creation_unite_legale",
    "date_creation_etablissement",
    "etat_administratif_unite_legale",
    "etat_administratif_etablissement",
    "tranche_effectifs_unite_legale",
    "tranche_effectifs_etablissement",
    "caractere_employeur_unite_legale",
    "caractere_employeur_etablissement",
    "enseigne_1",
    "enseigne_2",
    "enseigne_3",
    "denomination_usuelle_etablissement",
    "numero_voie",
    "type_voie",
    "libelle_voie",
    "complement_adresse",
    "code_postal",
    "commune",
    "code_commune",
    "adresse_complete",
    "age_etablissement_annees",
    "score_priorisation",
    "raison_score",
)

NO_OR_SMALL_HEADCOUNT_CODES = {"", "NN", "00", "01", "02"}


class SireneClient(Protocol):
    def get_siren(self, siren: str) -> dict[str, Any]:
        """Retourne le payload brut `/siren/{siren}`."""


def build_consolidated_etablissement_rows(
    client: SireneClient,
    etablissements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrichit chaque établissement et retourne les lignes CSV."""
    return [
        build_consolidated_etablissement_row(client, etablissement)
        for etablissement in etablissements
    ]


def build_consolidated_etablissement_row(
    client: SireneClient,
    etablissement: dict[str, Any],
) -> dict[str, Any]:
    """Construit une ligne CSV consolidée pour un établissement SIRENE."""
    siren = _siren_from_etablissement(etablissement)
    unite_legale_payload = client.get_siren(siren)
    unite_legale = extract_unite_legale(unite_legale_payload)
    return map_etablissement_to_csv_row(etablissement, unite_legale)


def extract_unite_legale(payload: dict[str, Any]) -> dict[str, Any]:
    """Extrait l'objet UniteLegale depuis la réponse `/siren/{siren}`."""
    unite_legale = payload.get("uniteLegale")
    if isinstance(unite_legale, dict):
        return unite_legale
    return payload


def map_etablissement_to_csv_row(
    etablissement: dict[str, Any],
    unite_legale: dict[str, Any],
) -> dict[str, Any]:
    """Mappe les données Etablissement et UniteLegale vers une ligne CSV."""
    denomination_usuelle = _clean(etablissement.get("denominationUsuelleEtablissement"))
    enseigne_1 = _clean(etablissement.get("enseigne1Etablissement"))
    denomination = _clean(unite_legale.get("denominationUniteLegale"))
    nom_unite_legale = _clean(unite_legale.get("nomUniteLegale"))
    prenom_usuel = _clean(unite_legale.get("prenomUsuelUniteLegale"))
    categorie_juridique = _clean(unite_legale.get("categorieJuridiqueUniteLegale"))
    activite_unite_legale = _clean(unite_legale.get("activitePrincipaleUniteLegale"))
    activite_etablissement = _clean(
        etablissement.get("activitePrincipaleEtablissement")
    )
    tranche_unite_legale = _clean(unite_legale.get("trancheEffectifsUniteLegale"))
    tranche_etablissement = _clean(etablissement.get("trancheEffectifsEtablissement"))
    est_entrepreneur_individuel = categorie_juridique == "1000"

    numero_voie = _address_value(etablissement, "numeroVoieEtablissement")
    type_voie = _address_value(etablissement, "typeVoieEtablissement")
    libelle_voie = _address_value(etablissement, "libelleVoieEtablissement")
    complement_adresse = _address_value(
        etablissement,
        "complementAdresseEtablissement",
    )
    code_postal = _address_value(etablissement, "codePostalEtablissement")
    commune = _address_value(etablissement, "libelleCommuneEtablissement")
    code_commune = _address_value(etablissement, "codeCommuneEtablissement")

    row: dict[str, Any] = {
        "siren": _siren_value(etablissement, unite_legale),
        "siret": _clean(etablissement.get("siret")),
        "nic": _clean(etablissement.get("nic")),
        "nom_ou_denomination": _first_present(
            denomination_usuelle,
            enseigne_1,
            denomination,
            _join_parts(prenom_usuel, nom_unite_legale),
        ),
        "denomination_unite_legale": denomination,
        "nom_unite_legale": nom_unite_legale,
        "prenom_usuel_unite_legale": prenom_usuel,
        "categorie_juridique_unite_legale": categorie_juridique,
        "est_entrepreneur_individuel": est_entrepreneur_individuel,
        "est_micro_entrepreneur_probable": _is_probable_micro_entrepreneur(
            est_entrepreneur_individuel,
            tranche_unite_legale,
            tranche_etablissement,
        ),
        "activite_principale_unite_legale": activite_unite_legale,
        "activite_principale_etablissement": activite_etablissement,
        "code_naf_retenu": activite_etablissement or activite_unite_legale,
        "date_creation_unite_legale": _clean(
            unite_legale.get("dateCreationUniteLegale")
        ),
        "date_creation_etablissement": _clean(
            etablissement.get("dateCreationEtablissement")
        ),
        "etat_administratif_unite_legale": _clean(
            unite_legale.get("etatAdministratifUniteLegale")
        ),
        "etat_administratif_etablissement": _clean(
            etablissement.get("etatAdministratifEtablissement")
        ),
        "tranche_effectifs_unite_legale": tranche_unite_legale,
        "tranche_effectifs_etablissement": tranche_etablissement,
        "caractere_employeur_unite_legale": _clean(
            unite_legale.get("caractereEmployeurUniteLegale")
        ),
        "caractere_employeur_etablissement": _clean(
            etablissement.get("caractereEmployeurEtablissement")
        ),
        "enseigne_1": enseigne_1,
        "enseigne_2": _clean(etablissement.get("enseigne2Etablissement")),
        "enseigne_3": _clean(etablissement.get("enseigne3Etablissement")),
        "denomination_usuelle_etablissement": denomination_usuelle,
        "numero_voie": numero_voie,
        "type_voie": type_voie,
        "libelle_voie": libelle_voie,
        "complement_adresse": complement_adresse,
        "code_postal": code_postal,
        "commune": commune,
        "code_commune": code_commune,
        "adresse_complete": build_adresse_complete(
            numero_voie=numero_voie,
            type_voie=type_voie,
            libelle_voie=libelle_voie,
            complement_adresse=complement_adresse,
            code_postal=code_postal,
            commune=commune,
        ),
    }
    row.update(
        compute_prioritization_score(
            activite_principale=row["code_naf_retenu"],
            date_creation_etablissement=row["date_creation_etablissement"],
            caractere_employeur_unite_legale=row["caractere_employeur_unite_legale"],
            enseigne_1=row["enseigne_1"],
            enseigne_2=row["enseigne_2"],
            enseigne_3=row["enseigne_3"],
        )
    )
    return {column: row.get(column, "") for column in CSV_COLUMNS}


def compute_prioritization_score(
    activite_principale: str,
    date_creation_etablissement: str,
    caractere_employeur_unite_legale: str,
    enseigne_1: str = "",
    enseigne_2: str = "",
    enseigne_3: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """Calcule le score de priorisation d'une ligne exportée."""
    score = 0
    reasons: list[str] = []

    normalized_activity = _clean(activite_principale).replace(".", "")
    if normalized_activity == "8810A":
        score += 3
        reasons.append("activite_8810A:+3")
    if normalized_activity == "8121Z":
        score += 2
        reasons.append("activite_8121Z:+2")

    age = compute_age_years(date_creation_etablissement, today=today)
    if age is not None:
        if age > 5:
            score += 2
            reasons.append("age_plus_5_ans:+2")
        if age > 10:
            score += 3
            reasons.append("age_plus_10_ans:+3")
        if age < 1:
            score -= 2
            reasons.append("creation_moins_1_an:-2")

    if _clean(caractere_employeur_unite_legale) == "O":
        score += 2
        reasons.append("employeur_unite_legale:+2")

    if any(_clean(enseigne) for enseigne in (enseigne_1, enseigne_2, enseigne_3)):
        score += 1
        reasons.append("enseigne_renseignee:+1")

    return {
        "age_etablissement_annees": "" if age is None else age,
        "score_priorisation": score,
        "raison_score": "; ".join(reasons),
    }


def compute_age_years(
    date_creation: str,
    today: date | None = None,
) -> int | None:
    """Retourne l'âge en années révolues ou None si la date est absente/invalide."""
    cleaned_date = _clean(date_creation)
    if not cleaned_date:
        return None

    try:
        creation_date = datetime.strptime(cleaned_date, "%Y-%m-%d").date()
    except ValueError:
        return None

    reference_date = today or date.today()
    age = (
        reference_date.year
        - creation_date.year
        - (
            (reference_date.month, reference_date.day)
            < (creation_date.month, creation_date.day)
        )
    )
    return max(0, age)


def build_adresse_complete(
    numero_voie: str = "",
    type_voie: str = "",
    libelle_voie: str = "",
    complement_adresse: str = "",
    code_postal: str = "",
    commune: str = "",
) -> str:
    """Construit une adresse lisible depuis les champs d'adresse établissement."""
    voie = _join_parts(numero_voie, type_voie, libelle_voie)
    ville = _join_parts(code_postal, commune)
    return ", ".join(part for part in (voie, complement_adresse, ville) if part)


def _siren_from_etablissement(etablissement: dict[str, Any]) -> str:
    siren = _siren_value(etablissement, {})
    if siren:
        return siren

    raise ValueError("Impossible de récupérer le SIREN de l'établissement.")


def _siren_value(
    etablissement: dict[str, Any],
    unite_legale: dict[str, Any],
) -> str:
    siren = _clean(etablissement.get("siren")) or _clean(unite_legale.get("siren"))
    if siren:
        return siren

    siret = _clean(etablissement.get("siret"))
    if len(siret) >= 9:
        return siret[:9]
    return ""


def _is_probable_micro_entrepreneur(
    est_entrepreneur_individuel: bool,
    tranche_unite_legale: str,
    tranche_etablissement: str,
) -> bool:
    if not est_entrepreneur_individuel:
        return False
    tranche_reference = tranche_unite_legale or tranche_etablissement
    return tranche_reference in NO_OR_SMALL_HEADCOUNT_CODES


def _address_value(etablissement: dict[str, Any], field_name: str) -> str:
    value = _clean(etablissement.get(field_name))
    if value:
        return value

    address = etablissement.get("adresseEtablissement")
    if not isinstance(address, dict):
        return ""
    return _clean(address.get(field_name))


def _first_present(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _join_parts(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
