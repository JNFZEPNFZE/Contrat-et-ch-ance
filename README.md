# Contrats & échéances

Application web légère pour suivre ses contrats (assurances, baux, maintenance,
abonnements, licences…) et surtout **ne plus rater une date de résiliation**.

Aucune dépendance : Python 3.10+ (bibliothèque standard) et une base SQLite locale.

## Démarrage

```bash
python3 app.py          # ou : python3 app.py 8080 pour un autre port
```

Puis ouvrir <http://localhost:8000>. Les données sont stockées dans `contrats.db`
(à sauvegarder ; chemin modifiable via la variable `CONTRATS_DB`).

## Fonctionnalités

- Fiche contrat : nom, référence, partenaire, catégorie, responsable, dates,
  montant et périodicité, notes.
- **Reconduction tacite** : l'échéance est automatiquement reportée de la durée
  de reconduction (12 mois par défaut).
- **Préavis** (en jours ou en mois) : calcul de la **date limite de résiliation**.
  Si elle est dépassée pour une reconduction tacite, l'application indique que le
  contrat sera reconduit et affiche la prochaine date limite utile.
- Statuts automatiques : *Urgent* (dans le délai d'alerte du contrat, 30 j par
  défaut), *À surveiller* (90 j de plus), *OK*, *Expiré*, *Résilié*, *Durée indéterminée*.
- Tableau de bord : contrats actifs, actions urgentes, coût annuel estimé.
- Recherche et filtres par statut / catégorie.
- Exports : **CSV** (compatible Excel) et **agenda .ics** (Outlook, Google
  Agenda, Apple Calendrier) avec un rappel 7 jours avant chaque date.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Structure

| Fichier | Rôle |
|---|---|
| `echeances.py` | Calcul des échéances, préavis et statuts (logique pure, testée) |
| `app.py` | Serveur HTTP, API REST (`/api/contrats`), exports, base SQLite |
| `static/` | Interface web (HTML/CSS/JS sans framework) |
| `tests/` | Tests unitaires |

## API

| Méthode | URL | Description |
|---|---|---|
| GET | `/api/contrats` | Liste des contrats avec échéances calculées |
| POST | `/api/contrats` | Créer un contrat |
| GET / PUT / DELETE | `/api/contrats/<id>` | Lire / modifier / supprimer |
| GET | `/api/export.csv` | Export tableur |
| GET | `/api/export.ics` | Export agenda |
