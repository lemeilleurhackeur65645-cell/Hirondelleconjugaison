import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from flask import g

os.environ["SECRET_KEY"] = "unit-test-session-secret"
os.environ["DATABASE_URL"] = "sqlite:////tmp/hirondelle-tests.db"
os.environ["ADMIN_EMAIL"] = "admin@example.test"

import main
from models import CodeVerification, Ticket, User, db


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        main.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SESSION_COOKIE_SECURE=False,
        )
        self.app_context = main.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        main.limiter.reset()
        self.client = main.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_missing_secret_key_fails_startup(self):
        env = os.environ.copy()
        env.pop("SECRET_KEY", None)
        env["DATABASE_URL"] = "sqlite:////tmp/hirondelle-missing-secret.db"
        result = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=Path(main.__file__).parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY doit être définie", result.stderr)

    def test_registration_verification_and_login(self):
        with patch("email_verification.envoyer_email", return_value=(True, None)):
            response = self.client.post(
                "/inscription",
                data={"email": "eleve@example.test", "nom": "Élève", "password": "un-mot-de-passe"},
            )
            self.assertEqual(response.status_code, 302)
            code = CodeVerification.query.filter_by(email="eleve@example.test").one()
            response = self.client.post(
                "/verifier-inscription",
                data={"code": code.code},
            )

        self.assertEqual(response.status_code, 302)
        user = User.query.filter_by(email="eleve@example.test").one()
        self.assertTrue(user.email_verifie)
        self.assertNotEqual(user.password_hash, "un-mot-de-passe")

        login_client = main.app.test_client()
        response = login_client.post(
            "/connexion",
            data={"email": user.email, "password": "un-mot-de-passe"},
        )
        self.assertEqual(response.status_code, 302)

    def test_quiz_feedback_includes_learning_hint(self):
        with self.client.session_transaction() as quiz_session:
            quiz_session.update({
                "mode": "entrainement",
                "score": 0,
                "total": 0,
                "erreurs": [],
                "start": time.time(),
                "bonne": "étais",
                "verbe": "être",
                "mode_verbe": "indicatif",
                "temps": "imparfait",
                "sujet": "je",
                "voix_question": "active",
            })

        response = self.client.post("/quiz", data={"reponse": "etais"})
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Réponse attendue", page)
        self.assertIn("À retenir", page)
        self.assertIn("à l’imparfait", page.casefold())
        with self.client.session_transaction() as quiz_session:
            self.assertEqual(len(quiz_session["erreurs"]), 1)

    def test_evaluation_hides_answer_and_learning_hint_until_results(self):
        with self.client.session_transaction() as quiz_session:
            quiz_session.update({
                "mode": "evaluation",
                "score": 0,
                "total": 0,
                "erreurs": [],
                "start": time.time(),
                "timer": 300,
                "questions_restantes": 10,
                "bonne": "étais",
                "verbe": "être",
                "mode_verbe": "indicatif",
                "temps": "imparfait",
                "sujet": "je",
                "voix_question": "active",
            })

        response = self.client.post("/quiz", data={"reponse": "etais"})
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertNotIn("Réponse attendue", page)
        self.assertNotIn("À retenir", page)

    def test_cleanup_requires_admin_and_post(self):
        self.assertEqual(self.client.get("/admin/nettoyer-bdd").status_code, 405)
        self.assertEqual(self.client.post("/admin/nettoyer-bdd").status_code, 302)

        admin = User(email="admin@example.test", nom="Admin", email_verifie=True)
        db.session.add(admin)
        db.session.flush()
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        ticket = Ticket(
            user_id=admin.id,
            type="bug",
            sujet="ancien ticket",
            statut="fermé",
            date_creation=old_date,
        )
        expired_code = CodeVerification(
            email=admin.email,
            code="123456",
            type="inscription",
            expire_le=old_date,
            date_creation=old_date,
        )
        db.session.add_all([ticket, expired_code])
        db.session.commit()

        with self.client.session_transaction() as login_session:
            login_session["_user_id"] = str(admin.id)
            login_session["_fresh"] = True
        g.pop("_login_user", None)
        response = self.client.post("/admin/nettoyer-bdd")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"codes_supprimés": 1, "tickets_supprimés": 1})

    def test_homepage_uses_real_counts_and_valid_image_markup(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("543 verbes", page)
        self.assertNotIn("stats_comm", page)
        self.assertIn('alt="Hirondelle Conjugaison" id="hirondelle-img"', page)

    def test_learning_hint_handles_common_rules(self):
        self.assertIn("radical du futur", main.conseil_conjugaison("conditionnel", "présent"))
        self.assertIn("s’accorde", main.conseil_conjugaison("indicatif", "présent", "passive"))


if __name__ == "__main__":
    unittest.main()
