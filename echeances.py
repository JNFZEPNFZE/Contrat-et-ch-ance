"""Calcul des échéances de contrats.

Logique pure (sans base de données) pour pouvoir être testée facilement.

Notions :
- échéance : date de fin de la période contractuelle en cours ;
- reconduction tacite : à l'échéance, le contrat repart pour `duree_reconduction_mois` ;
- préavis : délai avant l'échéance pour résilier (en jours ou en mois) ;
- date limite de résiliation : échéance - préavis. C'est la date d'action réelle.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

# Seuil (en jours) au-delà du seuil d'alerte du contrat pour signaler "à surveiller".
SEUIL_SURVEILLANCE_JOURS = 90


def ajouter_mois(d: date, mois: int) -> date:
    """Ajoute (ou retire) un nombre de mois en restant sur un jour valide."""
    total = d.month - 1 + mois
    annee = d.year + total // 12
    m = total % 12 + 1
    jour = min(d.day, calendar.monthrange(annee, m)[1])
    return date(annee, m, jour)


def parse_date(valeur) -> date | None:
    if not valeur:
        return None
    if isinstance(valeur, date):
        return valeur
    return date.fromisoformat(str(valeur)[:10])


def retirer_preavis(echeance: date, valeur: int, unite: str) -> date:
    if not valeur:
        return echeance
    if unite == "mois":
        return ajouter_mois(echeance, -valeur)
    return echeance - timedelta(days=valeur)


def calculer(contrat: dict, aujourd_hui: date | None = None) -> dict:
    """Retourne les informations d'échéance d'un contrat.

    Clés retournées : echeance, limite_resiliation, date_action, jours_restants,
    preavis_depasse, statut ("resilie", "expire", "urgent", "a_surveiller",
    "ok", "indetermine").
    """
    aujourd_hui = aujourd_hui or date.today()
    date_fin = parse_date(contrat.get("date_fin"))
    tacite = bool(contrat.get("reconduction_tacite"))
    duree = int(contrat.get("duree_reconduction_mois") or 0)
    preavis = int(contrat.get("preavis_valeur") or 0)
    unite = contrat.get("preavis_unite") or "jours"
    alerte = int(contrat.get("alerte_jours") or 30)

    res = {
        "echeance": None,
        "limite_resiliation": None,
        "date_action": None,
        "jours_restants": None,
        "preavis_depasse": False,
        "statut": "indetermine",
    }

    if contrat.get("resilie"):
        res["statut"] = "resilie"
        if date_fin:
            res["echeance"] = date_fin.isoformat()
        return res

    if not date_fin:
        return res  # durée indéterminée, rien à calculer

    echeance = date_fin
    if tacite and duree > 0:
        # Avancer jusqu'à la première échéance non encore passée.
        while echeance < aujourd_hui:
            echeance = ajouter_mois(echeance, duree)
    elif echeance < aujourd_hui:
        res["echeance"] = echeance.isoformat()
        res["statut"] = "expire"
        return res

    limite = retirer_preavis(echeance, preavis, unite) if preavis else None
    date_action = limite or echeance

    if tacite and duree > 0 and limite and limite < aujourd_hui:
        # Trop tard pour résilier cette échéance : le contrat sera reconduit.
        # La prochaine date utile est la limite de la période suivante.
        res["preavis_depasse"] = True
        echeance = ajouter_mois(echeance, duree)
        limite = retirer_preavis(echeance, preavis, unite)
        date_action = limite
    elif limite and limite < aujourd_hui:
        # Pas de reconduction : le préavis est dépassé, seule l'échéance compte.
        res["preavis_depasse"] = True
        date_action = echeance

    jours = (date_action - aujourd_hui).days
    if jours <= alerte:
        statut = "urgent"
    elif jours <= alerte + SEUIL_SURVEILLANCE_JOURS:
        statut = "a_surveiller"
    else:
        statut = "ok"

    res.update(
        echeance=echeance.isoformat(),
        limite_resiliation=limite.isoformat() if limite else None,
        date_action=date_action.isoformat(),
        jours_restants=jours,
        statut=statut,
    )
    return res
