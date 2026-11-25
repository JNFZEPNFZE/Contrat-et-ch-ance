"""Suivi des contrats et de leurs échéances, classés par immeuble.

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
from urllib.parse import parse_qs, urlparse

from echeances import calculer

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_PATH = Path(os.environ.get("CONTRATS_DB", BASE / "contrats.db"))

CHAMPS = {
    # nom: (type SQL, valeur par défaut)
    "nom": ("TEXT NOT NULL", ""),
    "immeuble_id": ("INTEGER REFERENCES immeubles(id)", None),
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

CHAMPS_IMMEUBLE = ("nom", "adresse", "notes")

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
            "CREATE TABLE IF NOT EXISTS immeubles (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " nom TEXT NOT NULL UNIQUE COLLATE NOCASE, adresse TEXT, notes TEXT, cree_le TEXT)"
        )
        con.execute(
            f"CREATE TABLE IF NOT EXISTS contrats (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols},"
            " cree_le TEXT, modifie_le TEXT)"
        )
        # Migration douce : ajoute les colonnes manquantes (bases créées par une version antérieure).
        existantes = {r["name"] for r in con.execute("PRAGMA table_info(contrats)")}
        for n, (t, _) in CHAMPS.items():
            if n not in existantes:
                con.execute(f"ALTER TABLE contrats ADD COLUMN {n} {t.replace(' NOT NULL', '')}")


def maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


# -------------------------------------------------------------------- Immeubles
def lister_immeubles() -> list[dict]:
    """Immeubles avec le nombre de contrats et d'alertes de chacun."""
    with connexion() as con:
        immeubles = [dict(r) for r in con.execute("SELECT * FROM immeubles ORDER BY nom COLLATE NOCASE")]
    stats: dict = {}
    for c in lister():
        s = stats.setdefault(c["immeuble_id"], {"nb_contrats": 0, "nb_urgents": 0, "nb_a_surveiller": 0})
        s["nb_contrats"] += 1
        s["nb_urgents"] += c["statut"] == "urgent"
        s["nb_a_surveiller"] += c["statut"] == "a_surveiller"
    vide = {"nb_contrats": 0, "nb_urgents": 0, "nb_a_surveiller": 0}
    for i in immeubles:
        i.update(stats.get(i["id"], vide))
    return immeubles


def obtenir_immeuble(iid: int) -> dict | None:
    with connexion() as con:
        r = con.execute("SELECT * FROM immeubles WHERE id = ?", (iid,)).fetchone()
    return dict(r) if r else None


def nettoyer_immeuble(donnees: dict) -> dict:
    d = {n: str(donnees.get(n) or "").strip() for n in CHAMPS_IMMEUBLE}
    if not d["nom"]:
        raise ValueError("Le nom de l'immeuble est obligatoire.")
    return d


def _ecrire_immeuble(requete: str, params: tuple):
    try:
        with connexion() as con:
            return con.execute(requete, params)
    except sqlite3.IntegrityError:
        raise ValueError("Un immeuble porte déjà ce nom.") from None


def creer_immeuble(donnees: dict) -> dict:
    d = nettoyer_immeuble(donnees)
    cur = _ecrire_immeuble(
        "INSERT INTO immeubles (nom, adresse, notes, cree_le) VALUES (?, ?, ?, ?)", (*d.values(), maintenant())
    )
    return obtenir_immeuble(cur.lastrowid)


def modifier_immeuble(iid: int, donnees: dict) -> dict | None:
    d = nettoyer_immeuble(donnees)
    cur = _ecrire_immeuble("UPDATE immeubles SET nom = ?, adresse = ?, notes = ? WHERE id = ?", (*d.values(), iid))
    return obtenir_immeuble(iid) if cur.rowcount else None


def supprimer_immeuble(iid: int) -> bool:
    with connexion() as con:
        n = con.execute("SELECT COUNT(*) FROM contrats WHERE immeuble_id = ?", (iid,)).fetchone()[0]
        if n:
            raise ValueError(
                f"Cet immeuble contient encore {n} contrat(s). Déplacez-les ou supprimez-les d'abord."
            )
        return con.execute("DELETE FROM immeubles WHERE id = ?", (iid,)).rowcount > 0


# --------------------------------------------------------------------- Contrats
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
                if v is not None and v < 0:
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
    if propre["immeuble_id"] is not None and not obtenir_immeuble(propre["immeuble_id"]):
        raise ValueError("Immeuble inconnu.")
    return propre


def enrichir(row: sqlite3.Row) -> dict:
    c = dict(row)
    c["reconduction_tacite"] = bool(c["reconduction_tacite"])
    c["resilie"] = bool(c["resilie"])
    c.update(calculer(c))
    c["statut_libelle"] = LIBELLES_STATUT[c["statut"]]
    return c


REQUETE_CONTRATS = (
    "SELECT c.*, COALESCE(i.nom, '') AS immeuble_nom FROM contrats c"
    " LEFT JOIN immeubles i ON i.id = c.immeuble_id"
)


def lister(immeuble: str | None = None) -> list[dict]:
    """Liste des contrats. `immeuble` : id d'immeuble, "aucun" (sans immeuble) ou None (tous)."""
    requete, params = REQUETE_CONTRATS, ()
    if immeuble == "aucun":
        requete += " WHERE c.immeuble_id IS NULL"
    elif immeuble:
        requete += " WHERE c.immeuble_id = ?"
        params = (int(immeuble),)
    with connexion() as con:
        rows = con.execute(requete, params).fetchall()
    contrats = [enrichir(r) for r in rows]
    contrats.sort(key=lambda c: (c["date_action"] is None, c["date_action"] or "", c["nom"].lower()))
    return contrats


def obtenir(cid: int) -> dict | None:
    with connexion() as con:
        r = con.execute(REQUETE_CONTRATS + " WHERE c.id = ?", (cid,)).fetchone()
    return enrichir(r) if r else None


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
    colonnes = ["id", "immeuble_nom", *CHAMPS, "echeance", "limite_resiliation", "date_action",
                "jours_restants", "statut_libelle"]
    colonnes.remove("immeuble_id")
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
        prefixe = f"[{c['immeuble_nom']}] " if c["immeuble_nom"] else ""
        desc = (f"Immeuble : {c['immeuble_nom'] or '—'}\nPartenaire : {c['partenaire']}\n"
                f"Référence : {c['reference']}\nResponsable : {c['responsable']}")
        if c["limite_resiliation"]:
            evenement(f"limite-{c['id']}-{c['limite_resiliation']}", c["limite_resiliation"],
                      f"{prefixe}Limite de résiliation : {c['nom']}", desc)
        if c["echeance"]:
            evenement(f"echeance-{c['id']}-{c['echeance']}", c["echeance"],
                      f"{prefixe}Échéance : {c['nom']}", desc)
    lignes.append("END:VCALENDAR")
    return "\r\n".join(lignes) + "\r\n"


# ---------------------------------------------------------------------- Serveur
# Ressources REST : nom dans l'URL -> (lire, créer, modifier, supprimer)
RESSOURCES = {
    "contrats": (obtenir, creer, modifier, supprimer),
    "immeubles": (obtenir_immeuble, creer_immeuble, modifier_immeuble, supprimer_immeuble),
}


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

    def _route(self):
        """Retourne (ressource, id) pour /api/<ressource>[/<id>], sinon (None, None)."""
        parties = urlparse(self.path).path.strip("/").split("/")
        if len(parties) in (2, 3) and parties[0] == "api" and parties[1] in RESSOURCES:
            if len(parties) == 2:
                return parties[1], None
            if parties[2].isdigit():
                return parties[1], int(parties[2])
        return None, None

    def _ecrire(self, action):
        try:
            return action()
        except (ValueError, json.JSONDecodeError) as e:
            return self._envoyer(400, {"erreur": str(e)})

    def do_GET(self):
        url = urlparse(self.path)
        immeuble = (parse_qs(url.query).get("immeuble") or [None])[0]
        if immeuble not in (None, "", "aucun") and not immeuble.isdigit():
            return self._envoyer(400, {"erreur": "Paramètre immeuble invalide"})
        if url.path == "/api/contrats":
            return self._envoyer(200, lister(immeuble))
        if url.path == "/api/immeubles":
            return self._envoyer(200, lister_immeubles())
        if url.path == "/api/export.csv":
            return self._envoyer(200, export_csv(lister(immeuble)), "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="contrats.csv"'})
        if url.path == "/api/export.ics":
            return self._envoyer(200, export_ics(lister(immeuble)), "text/calendar; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="echeances.ics"'})
        res, rid = self._route()
        if res and rid is not None:
            obj = RESSOURCES[res][0](rid)
            return self._envoyer(200, obj) if obj else self._envoyer(404, {"erreur": "Introuvable"})
        return super().do_GET()

    def do_POST(self):
        res, rid = self._route()
        if not res or rid is not None:
            return self._envoyer(404, {"erreur": "Introuvable"})
        self._ecrire(lambda: self._envoyer(201, RESSOURCES[res][1](self._json_recu())))

    def do_PUT(self):
        res, rid = self._route()
        if not res or rid is None:
            return self._envoyer(404, {"erreur": "Introuvable"})

        def action():
            obj = RESSOURCES[res][2](rid, self._json_recu())
            return self._envoyer(200, obj) if obj else self._envoyer(404, {"erreur": "Introuvable"})
        self._ecrire(action)

    def do_DELETE(self):
        res, rid = self._route()
        if not res or rid is None:
            return self._envoyer(404, {"erreur": "Introuvable"})

        def action():
            ok = RESSOURCES[res][3](rid)
            return self._envoyer(204, b"") if ok else self._envoyer(404, {"erreur": "Introuvable"})
        self._ecrire(action)


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
