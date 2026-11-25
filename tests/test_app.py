import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CONTRATS_DB"] = str(Path(self.tmp.name) / "test.db")
        import app
        self.app = importlib.reload(app)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("CONTRATS_DB", None)


class TestImmeubles(BaseTest):
    def setUp(self):
        super().setUp()
        self.app.init_db()

    def test_contrats_classes_par_immeuble(self):
        a = self.app.creer_immeuble({"nom": "Les Tilleuls", "adresse": "1 rue A"})
        b = self.app.creer_immeuble({"nom": "Le Belvédère"})
        self.app.creer({"nom": "Ascenseur", "immeuble_id": a["id"], "date_fin": "2099-01-01"})
        self.app.creer({"nom": "Nettoyage", "immeuble_id": str(a["id"])})  # id reçu en texte du formulaire
        self.app.creer({"nom": "Assurance", "immeuble_id": b["id"]})
        self.app.creer({"nom": "Siège", "immeuble_id": ""})

        self.assertEqual({c["nom"] for c in self.app.lister(str(a["id"]))}, {"Ascenseur", "Nettoyage"})
        self.assertEqual([c["nom"] for c in self.app.lister("aucun")], ["Siège"])
        self.assertEqual(len(self.app.lister()), 4)
        self.assertEqual(self.app.lister(str(b["id"]))[0]["immeuble_nom"], "Le Belvédère")

        stats = {i["nom"]: i["nb_contrats"] for i in self.app.lister_immeubles()}
        self.assertEqual(stats, {"Les Tilleuls": 2, "Le Belvédère": 1})

    def test_nom_obligatoire_et_unique(self):
        self.app.creer_immeuble({"nom": "Les Tilleuls"})
        with self.assertRaises(ValueError):
            self.app.creer_immeuble({"nom": "  "})
        with self.assertRaises(ValueError):
            self.app.creer_immeuble({"nom": "les tilleuls"})

    def test_immeuble_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            self.app.creer({"nom": "X", "immeuble_id": 999})

    def test_suppression_refusee_si_contrats(self):
        a = self.app.creer_immeuble({"nom": "A"})
        c = self.app.creer({"nom": "X", "immeuble_id": a["id"]})
        with self.assertRaises(ValueError):
            self.app.supprimer_immeuble(a["id"])
        self.app.supprimer(c["id"])
        self.assertTrue(self.app.supprimer_immeuble(a["id"]))

    def test_exports_contiennent_immeuble(self):
        a = self.app.creer_immeuble({"nom": "Les Tilleuls"})
        self.app.creer({"nom": "Ascenseur", "immeuble_id": a["id"], "date_fin": "2099-01-01"})
        self.assertIn("Les Tilleuls", self.app.export_csv(self.app.lister()))
        self.assertIn("[Les Tilleuls] Échéance : Ascenseur", self.app.export_ics(self.app.lister()))


class TestMigration(BaseTest):
    def test_ancienne_base_sans_immeubles(self):
        con = sqlite3.connect(os.environ["CONTRATS_DB"])
        con.execute("CREATE TABLE contrats (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL,"
                    " date_fin TEXT, cree_le TEXT, modifie_le TEXT)")
        con.execute("INSERT INTO contrats (nom, date_fin) VALUES ('Ancien', '2099-01-01')")
        con.commit()
        con.close()

        self.app.init_db()
        contrats = self.app.lister()
        self.assertEqual(contrats[0]["nom"], "Ancien")
        self.assertIsNone(contrats[0]["immeuble_id"])
        self.assertEqual(len(self.app.lister("aucun")), 1)


if __name__ == "__main__":
    unittest.main()
