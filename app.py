"""Suivi des contrats et de leurs échéances.

Serveur web minimal (bibliothèque standard uniquement) + base SQLite.
Lancement : python3 app.py  puis ouvrir http://localhost:8000
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from echeances import calculer

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_PATH = Path(os.environ.get("CONTRATS_DB", BASE / "contrats.db"))

CHAMPS = {
    # nom: (type SQL, valeur par défaut)
    "nom": ("TEXT NOT NULL", ""),
    "reference": ("TEXT", ""),
    "partenaire": ("TEXT", ""),
    "categorie": ("TEXT", ""),
    "responsable": ("TEXT", ""),
    "date_debut": ("TEXT", None),
    "date_fin": ("TEXT", None),
    "reconduction_tacite": ("INTEGER", 0),
    "duree_reconduction_mois": ("INTEGER", 12),
    "preavis_valeur": ("INTEGER", 0),
    "preavis_unite": ("TEXT", "jours"),
    "alerte_jours": ("INTEGER", 30),
    "montant": ("REAL", None),
    "periodicite": ("TEXT", ""),
    "resilie": ("INTEGER", 0),
    "notes": ("TEXT", ""),
}

LIBELLES_STATUT = {
    "urgent": "Urgent",
    "a_surveiller": "À surveiller",
    "ok": "OK",
    "expire": "Expiré",
    "resilie": "Résilié",
    "indetermine": "Durée indéterminée",
}


# --------------------------------------------------------------------------- DB
def connexion() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    cols = ", ".join(f"{n} {t}" for n, (t, _) in CHAMPS.items())
    with connexion() as con:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS contrats (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols},"
            " cree_le TEXT, modifie_le TEXT)"
        )
        # Migration douce : ajoute les colonnes manquantes.
        existantes = {r["name"] for r in con.execute("PRAGMA table_info(contrats)")}
        for n, (t, _) in CHAMPS.items():
            if n not in existantes:
                con.execute(f"ALTER TABLE contrats ADD COLUMN {n} {t.replace(' NOT NULL', '')}")


def nettoyer(donnees: dict) -> dict:
    """Valide et normalise les champs reçus du client."""
    propre = {}
    for n, (t, defaut) in CHAMPS.items():
        v = donnees.get(n, defaut)
        if n in ("date_debut", "date_fin"):
            v = v or None
            if v:
                date.fromisoformat(v)  # lève ValueError si invalide
        elif t.startswith("INTEGER"):
            if n in ("reconduction_tacite", "resilie"):
                v = int(bool(v))
            else:
                v = int(v) if v not in (None, "") else defaut
                if v < 0:
                    raise ValueError(f"Valeur négative interdite : {n}")
        elif t == "REAL":
            v = float(v) if v not in (None, "") else None
        else:
            v = (str(v) if v is not None else "").strip()
        propre[n] = v
    if not propre["nom"]:
        raise ValueError("Le nom du contrat est obligatoire.")
    if propre["preavis_unite"] not in ("jours", "mois"):
        raise ValueError("Unité de préavis invalide (jours ou mois).")
    if propre["date_debut"] and propre["date_fin"] and propre["date_fin"] < propre["date_debut"]:
        raise ValueError("La date de fin est antérieure à la date de début.")
    return propre


def enrichir(row: sqlite3.Row) -> dict:
    c = dict(row)
    c["reconduction_tacite"] = bool(c["reconduction_tacite"])
    c["resilie"] = bool(c["resilie"])
    c.update(calculer(c))
    c["statut_libelle"] = LIBELLES_STATUT[c["statut"]]
    return c


def lister() -> list[dict]:
    with connexion() as con:
        rows = con.execute("SELECT * FROM contrats").fetchall()
    contrats = [enrichir(r) for r in rows]
    contrats.sort(key=lambda c: (c["date_action"] is None, c["date_action"] or "", c["nom"].lower()))
    return contrats


def obtenir(cid: int) -> dict | None:
    with connexion() as con:
        r = con.execute("SELECT * FROM contrats WHERE id = ?", (cid,)).fetchone()
    return enrichir(r) if r else None


def maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def creer(donnees: dict) -> dict:
    d = nettoyer(donnees)
    noms = ", ".join(d) + ", cree_le, modifie_le"
    marques = ", ".join("?" for _ in d) + ", ?, ?"
    with connexion() as con:
        cur = con.execute(
            f"INSERT INTO contrats ({noms}) VALUES ({marques})",
            (*d.values(), maintenant(), maintenant()),
        )
        cid = cur.lastrowid
    return obtenir(cid)


def modifier(cid: int, donnees: dict) -> dict | None:
    d = nettoyer(donnees)
    affect = ", ".join(f"{n} = ?" for n in d) + ", modifie_le = ?"
    with connexion() as con:
        cur = con.execute(f"UPDATE contrats SET {affect} WHERE id = ?", (*d.values(), maintenant(), cid))
        if cur.rowcount == 0:
            return None
    return obtenir(cid)


def supprimer(cid: int) -> bool:
    with connexion() as con:
        return con.execute("DELETE FROM contrats WHERE id = ?", (cid,)).rowcount > 0


# ---------------------------------------------------------------------- Exports
def export_csv(contrats: list[dict]) -> str:
    colonnes = ["id", *CHAMPS, "echeance", "limite_resiliation", "date_action", "jours_restants", "statut_libelle"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colonnes, delimiter=";", extrasaction="ignore")
    w.writeheader()
    for c in contrats:
        w.writerow(c)
    return "\ufeff" + buf.getvalue()  # BOM pour qu'Excel lise bien les accents


def _ics_texte(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def export_ics(contrats: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Contrats et echeances//FR", "CALSCALE:GREGORIAN"]

    def evenement(uid, jour, titre, description):
        j = jour.replace("-", "")
        lignes.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}@contrats-echeances",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{j}",
            f"SUMMARY:{_ics_texte(titre)}",
            f"DESCRIPTION:{_ics_texte(description)}",
            "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-P7D", f"DESCRIPTION:{_ics_texte(titre)}", "END:VALARM",
            "END:VEVENT",
        ])

    for c in contrats:
        if c["statut"] in ("resilie", "expire", "indetermine"):
            continue
        desc = f"Partenaire : {c['partenaire']}\nRéférence : {c['reference']}\nResponsable : {c['responsable']}"
        if c["limite_resiliation"]:
            evenement(f"limite-{c['id']}-{c['limite_resiliation']}", c["limite_resiliation"],
                      f"Limite de résiliation : {c['nom']}", desc)
        if c["echeance"]:
            evenement(f"echeance-{c['id']}-{c['echeance']}", c["echeance"], f"Échéance : {c['nom']}", desc)
    lignes.append("END:VCALENDAR")
    return "\r\n".join(lignes) + "\r\n"


# ---------------------------------------------------------------------- Serveur
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):  # journal plus discret
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _envoyer(self, code: int, corps, type_mime="application/json; charset=utf-8", extra=None):
        if not isinstance(corps, (bytes, str)):
            corps = json.dumps(corps, ensure_ascii=False)
        if isinstance(corps, str):
            corps = corps.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corps)

    def _json_recu(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _id(self, chemin: str) -> int | None:
        parties = chemin.strip("/").split("/")
        if len(parties) == 3 and parties[:2] == ["api", "contrats"] and parties[2].isdigit():
            return int(parties[2])
        return None

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin == "/api/contrats":
            return self._envoyer(200, lister())
        if (cid := self._id(chemin)) is not None:
            c = obtenir(cid)
            return self._envoyer(200, c) if c else self._envoyer(404, {"erreur": "Contrat introuvable"})
        if chemin == "/api/export.csv":
            return self._envoyer(200, export_csv(lister()), "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="contrats.csv"'})
        if chemin == "/api/export.ics":
            return self._envoyer(200, export_ics(lister()), "text/calendar; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="echeances.ics"'})
        return super().do_GET()

    def _ecrire(self, action):
        try:
            return action()
        except (ValueError, json.JSONDecodeError) as e:
            return self._envoyer(400, {"erreur": str(e)})

    def do_POST(self):
        if urlparse(self.path).path != "/api/contrats":
            return self._envoyer(404, {"erreur": "Introuvable"})
        self._ecrire(lambda: self._envoyer(201, creer(self._json_recu())))

    def do_PUT(self):
        cid = self._id(urlparse(self.path).path)
        if cid is None:
            return self._envoyer(404, {"erreur": "Introuvable"})

        def action():
            c = modifier(cid, self._json_recu())
            return self._envoyer(200, c) if c else self._envoyer(404, {"erreur": "Contrat introuvable"})
        self._ecrire(action)

    def do_DELETE(self):
        cid = self._id(urlparse(self.path).path)
        if cid is not None and supprimer(cid):
            return self._envoyer(204, b"")
        return self._envoyer(404, {"erreur": "Contrat introuvable"})


def main():
    init_db()
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8000))
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Suivi des contrats : http://localhost:{port}  (base : {DB_PATH})")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
