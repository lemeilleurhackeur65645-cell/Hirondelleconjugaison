"""
Authentification — Hirondelle Conjugaison.
Gère : inscription/connexion par email, et connexion OAuth Google + Github.

Variables d'environnement nécessaires sur Render :
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
Tant qu'elles ne sont pas définies, les boutons Google/Github affichent
un message clair plutôt que de planter.
"""

import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from authlib.integrations.flask_client import OAuth

from models import db, User

bcrypt = Bcrypt()
oauth = OAuth()
auth_bp = Blueprint("auth", __name__)


def init_auth(app):
    """Appelé depuis main.py pour brancher bcrypt + oauth sur l'app Flask."""
    bcrypt.init_app(app)
    print("[BOOT] bcrypt.init_app OK", flush=True)

    oauth.init_app(app)
    print("[BOOT] oauth.init_app OK", flush=True)

    google_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if google_id and google_secret:
        try:
            oauth.register(
                name="google",
                client_id=google_id,
                client_secret=google_secret,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )
            print("[BOOT] OAuth Google enregistré", flush=True)
        except Exception as e:
            print(f"[ATTENTION] Échec enregistrement OAuth Google : {e}", flush=True)
    else:
        print("[BOOT] OAuth Google ignoré (clés absentes)", flush=True)

    github_id = os.environ.get("GITHUB_CLIENT_ID")
    github_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    if github_id and github_secret:
        try:
            oauth.register(
                name="github",
                client_id=github_id,
                client_secret=github_secret,
                access_token_url="https://github.com/login/oauth/access_token",
                authorize_url="https://github.com/login/oauth/authorize",
                api_base_url="https://api.github.com/",
                client_kwargs={"scope": "user:email"},
            )
            print("[BOOT] OAuth Github enregistré", flush=True)
        except Exception as e:
            print(f"[ATTENTION] Échec enregistrement OAuth Github : {e}", flush=True)
    else:
        print("[BOOT] OAuth Github ignoré (clés absentes)", flush=True)


def _oauth_configured(provider):
    """Vérifie si un provider OAuth a été enregistré (clés API présentes)."""
    try:
        return oauth.create_client(provider) is not None
    except Exception:
        return False


# ============================================================
# INSCRIPTION / CONNEXION PAR EMAIL
# ============================================================

@auth_bp.route("/inscription", methods=["GET", "POST"])
def inscription():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nom = request.form.get("nom", "").strip()
        password = request.form.get("password", "")

        if not email or "@" not in email:
            flash("Adresse email invalide.")
            return redirect(url_for("auth.inscription"))

        if len(password) < 8:
            flash("Le mot de passe doit faire au moins 8 caractères.")
            return redirect(url_for("auth.inscription"))

        if User.query.filter_by(email=email).first():
            flash("Un compte existe déjà avec cet email. Connecte-toi plutôt.")
            return redirect(url_for("auth.connexion"))

        hash_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(email=email, nom=nom or None, password_hash=hash_pw, methode_connexion="email")
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        flash("Compte créé — bienvenue !")
        return redirect(url_for("index"))

    return render_template("inscription.html")


@auth_bp.route("/connexion", methods=["GET", "POST"])
def connexion():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if not user or not user.password_hash:
            flash("Email ou mot de passe incorrect.")
            return redirect(url_for("auth.connexion"))

        if not bcrypt.check_password_hash(user.password_hash, password):
            flash("Email ou mot de passe incorrect.")
            return redirect(url_for("auth.connexion"))

        login_user(user, remember=True)
        return redirect(url_for("index"))

    return render_template("connexion.html")


@auth_bp.route("/deconnexion")
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for("index"))


# ============================================================
# OAUTH GOOGLE
# ============================================================

@auth_bp.route("/connexion/google")
def connexion_google():
    if not _oauth_configured("google"):
        flash("La connexion Google n'est pas encore configurée sur ce site.")
        return redirect(url_for("auth.connexion"))
    redirect_uri = url_for("auth.callback_google", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/callback/google")
def callback_google():
    token = oauth.google.authorize_access_token()
    info = token.get("userinfo")
    if not info or not info.get("email"):
        flash("Connexion Google impossible — réessaie.")
        return redirect(url_for("auth.connexion"))

    email = info["email"].lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, nom=info.get("name"), methode_connexion="google")
        db.session.add(user)
        db.session.commit()

    login_user(user, remember=True)
    return redirect(url_for("index"))


# ============================================================
# OAUTH GITHUB
# ============================================================

@auth_bp.route("/connexion/github")
def connexion_github():
    if not _oauth_configured("github"):
        flash("La connexion Github n'est pas encore configurée sur ce site.")
        return redirect(url_for("auth.connexion"))
    redirect_uri = url_for("auth.callback_github", _external=True)
    return oauth.github.authorize_redirect(redirect_uri)


@auth_bp.route("/callback/github")
def callback_github():
    token = oauth.github.authorize_access_token()
    resp = oauth.github.get("user", token=token)
    profile = resp.json()

    email = profile.get("email")
    if not email:
        # Github ne renvoie pas toujours l'email dans /user — fallback sur /user/emails
        resp_emails = oauth.github.get("user/emails", token=token)
        emails = resp_emails.json()
        primary = next((e["email"] for e in emails if e.get("primary")), None)
        email = primary or (emails[0]["email"] if emails else None)

    if not email:
        flash("Impossible de récupérer ton email Github — réessaie ou utilise un autre mode de connexion.")
        return redirect(url_for("auth.connexion"))

    email = email.lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, nom=profile.get("login"), methode_connexion="github")
        db.session.add(user)
        db.session.commit()

    login_user(user, remember=True)
    return redirect(url_for("index"))
