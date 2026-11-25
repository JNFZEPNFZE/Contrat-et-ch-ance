import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from echeances import ajouter_mois, calculer  # noqa: E402

AUJ = date(2026, 11, 25)


class TestAjouterMois(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(ajouter_mois(date(2026, 1, 15), 1), date(2026, 2, 15))

    def test_fin_de_mois(self):
        self.assertEqual(ajouter_mois(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(ajouter_mois(date(2028, 1, 31), 1), date(2028, 2, 29))

    def test_negatif_et_annee(self):
        self.assertEqual(ajouter_mois(date(2026, 2, 15), -3), date(2025, 11, 15))
        self.assertEqual(ajouter_mois(date(2026, 11, 30), 14), date(2028, 1, 30))


class TestCalculer(unittest.TestCase):
    def test_duree_indeterminee(self):
        self.assertEqual(calculer({}, AUJ)["statut"], "indetermine")

    def test_resilie(self):
        r = calculer({"date_fin": "2027-01-01", "resilie": True}, AUJ)
        self.assertEqual(r["statut"], "resilie")

    def test_expire_sans_reconduction(self):
        r = calculer({"date_fin": "2026-10-01"}, AUJ)
        self.assertEqual(r["statut"], "expire")

    def test_ok_sans_preavis(self):
        r = calculer({"date_fin": "2027-12-31"}, AUJ)
        self.assertEqual(r["statut"], "ok")
        self.assertEqual(r["date_action"], "2027-12-31")
        self.assertIsNone(r["limite_resiliation"])

    def test_preavis_en_mois_urgent(self):
        r = calculer({"date_fin": "2027-02-28", "preavis_valeur": 3, "preavis_unite": "mois"}, AUJ)
        self.assertEqual(r["limite_resiliation"], "2026-11-28")
        self.assertEqual(r["jours_restants"], 3)
        self.assertEqual(r["statut"], "urgent")

    def test_a_surveiller(self):
        r = calculer({"date_fin": "2027-02-15", "alerte_jours": 30}, AUJ)
        self.assertEqual(r["statut"], "a_surveiller")

    def test_reconduction_tacite_avance_echeance(self):
        r = calculer({"date_fin": "2024-03-01", "reconduction_tacite": True,
                      "duree_reconduction_mois": 12}, AUJ)
        self.assertEqual(r["echeance"], "2027-03-01")

    def test_reconduction_preavis_depasse_passe_a_la_periode_suivante(self):
        # Échéance 2026-12-31, préavis 2 mois => limite 2026-10-31, déjà passée.
        r = calculer({"date_fin": "2025-12-31", "reconduction_tacite": True,
                      "duree_reconduction_mois": 12, "preavis_valeur": 2,
                      "preavis_unite": "mois"}, AUJ)
        self.assertTrue(r["preavis_depasse"])
        self.assertEqual(r["echeance"], "2027-12-31")
        self.assertEqual(r["limite_resiliation"], "2027-10-31")
        self.assertEqual(r["statut"], "ok")

    def test_preavis_depasse_sans_reconduction(self):
        r = calculer({"date_fin": "2026-12-10", "preavis_valeur": 30}, AUJ)
        self.assertTrue(r["preavis_depasse"])
        self.assertEqual(r["date_action"], "2026-12-10")
        self.assertEqual(r["statut"], "urgent")


if __name__ == "__main__":
    unittest.main()
