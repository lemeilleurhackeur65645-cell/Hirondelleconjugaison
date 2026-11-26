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
                data={
                    "email": "eleve@example.test",
                    "nom": "Élève",
                    "password": "un-mot-de-passe",
                    "age_ok": "1",
                    "conditions_ok": "1",
                },
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

    def test_registration_requires_age_and_terms_acknowledgements(self):
        for data in (
            {"age_ok": "1"},
            {"conditions_ok": "1"},
        ):
            response = self.client.post(
                "/inscription",
                data={
                    "email": "eleve@example.test",
                    "password": "un-mot-de-passe",
                    **data,
                },
            )
            self.assertEqual(response.status_code, 302)
            self.assertIn("/inscription", response.location)

        self.assertIsNone(CodeVerification.query.filter_by(email="eleve@example.test").first())

    def test_auth_pages_show_required_legal_checks_and_links(self):
        response = self.client.get("/inscription")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertNotIn("Un compte pour garder ton élan", page)
        self.assertIn('name="age_ok" value="1" required', page)
        self.assertIn('name="conditions_ok" value="1" required', page)
        self.assertIn('href="/conditions"', page)
        self.assertIn('href="/confidentialite"', page)
        self.assertIn('href="/mentions-legales"', page)
        self.assertIn('formaction="/inscription/oauth/google"', page)
        self.assertIn('formaction="/inscription/oauth/github"', page)

        response = self.client.get("/connexion")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Créer un compte", response.get_data(as_text=True))

    def test_oauth_registration_requires_legal_acknowledgements(self):
        response = self.client.post("/inscription/oauth/google")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/inscription", response.location)

        response = self.client.post(
            "/inscription/oauth/github",
            data={"age_ok": "1", "conditions_ok": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/inscription", response.location)
        self.assertEqual(User.query.count(), 0)

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

        response = self.client.post("/quiz", data={"reponse": "etaisent"})
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
        self.assertIn('role="timer"', page)
        self.assertIn('aria-valuenow="1"', page)
        self.assertIn('aria-valuemax="10"', page)
        self.assertIn("bilan s'affiche automatiquement", page)

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

    def test_targeted_quiz_page_explains_selection_steps(self):
        response = self.client.get("/cible")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Étape 1", page)
        self.assertIn("Ta sélection", page)
        self.assertIn("Pour commencer rapidement", page)
        self.assertIn("verb-filter", page)

    def test_targeted_quiz_rejects_empty_selection(self):
        response = self.client.post("/cible_start", data={})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/cible")

    def test_unknown_route_renders_custom_not_found_page(self):
        response = self.client.get("/page-inconnue-pour-test")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Oups, cette page a pris son envol", response.get_data(as_text=True))

    def test_targeted_quiz_with_both_voices_uses_only_available_voice(self):
        response = self.client.post(
            "/cible_start",
            data={
                "modes": ["indicatif"],
                "temps": ["indicatif|présent"],
                "personnes": ["1s"],
                "voix": ["actif", "passif"],
                "verbes": ["aller"],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/quiz")

        response = self.client.get("/quiz")
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["voix_question"], "active")
            self.assertEqual(session["verbe"], "aller")

    def test_legal_pages_are_routed_and_include_responsive_table_support(self):
        for path in ("/conditions", "/confidentialite", "/mentions-legales"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('class="legal"', response.get_data(as_text=True))
        privacy = self.client.get("/confidentialite").get_data(as_text=True)
        self.assertIn("<table>", privacy)
        self.assertIn("overflow-x:auto", privacy)

    def test_leaderboard_only_shows_opted_in_players_and_no_emails(self):
        opted_in = User(email="visible@example.test", nom="Élève", classement_public=True, xp_total=25)
        private = User(email="private@example.test", nom="Privé", classement_public=False, xp_total=1000)
        db.session.add_all([opted_in, private])
        db.session.commit()

        response = self.client.get("/classement")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Élève", page)
        self.assertNotIn("Privé", page)
        self.assertNotIn("visible@example.test", page)
        self.assertNotIn("private@example.test", page)

    def test_account_preferences_and_export_work(self):
        user = User(email="account@example.test", nom="Compte test")
        db.session.add(user)
        db.session.commit()
        with self.client.session_transaction() as login_session:
            login_session["_user_id"] = str(user.id)
            login_session["_fresh"] = True

        response = self.client.post("/compte/preferences", data={"classement": "on"})
        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertTrue(user.classement_public)
        self.assertFalse(user.rappels_email)

        response = self.client.get("/compte/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        export = response.get_json()
        self.assertEqual(export["compte"]["email"], user.email)
        self.assertNotIn("password_hash", export["compte"])

    def test_answer_normalization_accepts_missing_accents_and_case(self):
        self.assertEqual(main.normaliser_reponse(" ÉTAIS "), main.normaliser_reponse("etais"))

    def test_session_results_show_charts_and_use_informal_tone(self):
        with self.client.session_transaction() as quiz_session:
            quiz_session.update({
                "mode": "evaluation",
                "start": time.time(),
                "total": 2,
                "score": 1,
                "erreurs": [{
                    "verbe": "être", "mode": "indicatif", "temps": "imparfait",
                    "personne": "je", "voix": "active", "attendu": "étais", "donne": "étaient",
                }],
            })

        response = self.client.get("/fin")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Évaluation terminée", page)
        self.assertIn("analysis-charts", page)
        self.assertIn("tes résultats", page)
        self.assertIn("Créer un quiz ciblé", page)

    def test_unsubscribe_requires_confirmation_then_disables_reminders(self):
        user = User(email="unsubscribe@example.test")
        db.session.add(user)
        db.session.commit()
        from rappels import token_desabonnement

        url = f"/desabonnement/{token_desabonnement(user.id)}"
        self.assertIn("Me désabonner", self.client.get(url).get_data(as_text=True))
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        db.session.refresh(user)
        self.assertFalse(user.rappels_email)
        self.assertIn("Tu ne recevras plus de rappels", response.get_data(as_text=True))

    def test_password_reset_code_can_be_resent_from_verification_page(self):
        user = User(email="reset@example.test", methode_connexion="email")
        db.session.add(user)
        db.session.commit()
        with self.client.session_transaction() as reset_session:
            reset_session["email_reset"] = user.email

        with patch("email_verification.envoyer_email", return_value=(True, None)):
            response = self.client.post("/renvoyer-code-reset", data={})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/reinitialiser-password")
        self.assertIsNotNone(CodeVerification.query.filter_by(
            email=user.email, type="reset_password", utilise=False
        ).first())

    def test_perfect_evaluation_unlocks_its_badge(self):
        user = User(email="perfect@example.test", email_verifie=True)
        db.session.add(user)
        db.session.commit()
        with self.client.session_transaction() as login_session:
            login_session["_user_id"] = str(user.id)
            login_session["_fresh"] = True
            login_session.update({
                "mode": "evaluation", "score": 0, "total": 0, "erreurs": [],
                "start": time.time(), "timer": 300, "questions_restantes": 10,
                "bonne": "étais", "verbe": "être", "mode_verbe": "indicatif",
                "temps": "imparfait", "sujet": "je", "voix_question": "active",
            })

        for _ in range(10):
            with self.client.session_transaction() as quiz_session:
                quiz_session.update({
                    "bonne": "étais", "verbe": "être", "mode_verbe": "indicatif",
                    "temps": "imparfait", "sujet": "je", "voix_question": "active",
                })
            response = self.client.post("/quiz", data={"reponse": "étais"})

        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertIn("note_parfaite", user.liste_badges())


if __name__ == "__main__":
    unittest.main()
