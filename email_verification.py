"""
Vérification d'email, relance rétention, et réinitialisation de mot de passe.
Envoi via Gmail SMTP (smtplib) — fonctionne pour n'importe quel destinataire
sans besoin de domaine propre, car gmail.com est un domaine déjà authentifié
par Google. Nécessite un compte Gmail avec un "mot de passe d'application".

Variables d'environnement requises sur Render :
  GMAIL_ADDRESS      : ton adresse Gmail complète (ex: toi@gmail.com)
  GMAIL_APP_PASSWORD : le mot de passe d'application à 16 caractères généré
                       sur myaccount.google.com/apppasswords
                       (nécessite la validation en 2 étapes activée)

Limite du compte Gmail gratuit : 500 emails envoyés par jour.

Sécurité :
  - Code à 6 chiffres, expire après 15 minutes.
  - 5 tentatives max par code — au-delà le code est invalidé.
  - Anti-spam : pas plus d'un code toutes les 60 secondes par email.
  - Mot de passe haché AVANT stockage temporaire dans CodeVerification.
"""

import os
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

DUREE_VALIDITE_MINUTES = 15
MAX_TENTATIVES = 5
DELAI_RENVOI_SECONDES = 60

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
NOM_EXPEDITEUR = "Hirondelle Conjugaison"


# ──────────────────────────────────────────────────────────────
# ENVOI D'EMAIL VIA GMAIL SMTP
# ──────────────────────────────────────────────────────────────

def generer_code():
    return "".join(random.choices(string.digits, k=6))


def envoyer_email(destinataire, sujet, contenu_html):
    """
    Envoie un email via le serveur SMTP de Gmail, en tant que GMAIL_ADDRESS.
    Fonctionne vers n'importe quel destinataire (Gmail, Outlook, Yahoo...)
    car le domaine gmail.com est déjà authentifié par Google — pas besoin
    de configurer SPF/DKIM soi-même.

    Sans les variables d'environnement, affiche le contenu dans les logs
    (mode dev) au lieu d'échouer silencieusement.

    Retourne (succes: bool, erreur: str|None).
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print(f"[EMAIL SIMULÉ] À: {destinataire} | Sujet: {sujet}", flush=True)
        return True, None

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = sujet
        msg["From"] = f"{NOM_EXPEDITEUR} <{GMAIL_ADDRESS}>"
        msg["To"] = destinataire
        msg.attach(MIMEText(contenu_html, "html", "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as serveur:
            serveur.starttls()
            serveur.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            serveur.sendmail(GMAIL_ADDRESS, [destinataire], msg.as_string())

        return True, None
    except smtplib.SMTPAuthenticationError:
        return False, "Authentification Gmail échouée — vérifie GMAIL_ADDRESS et GMAIL_APP_PASSWORD."
    except Exception as e:
        return False, str(e)


def _template_email(titre, message_principal, code=None, cta_url=None, cta_label=None):
    """Template HTML minimal mais professionnel pour tous les emails du site."""
    code_html = f"""
    <div style="background:#eff6ff;border-radius:12px;padding:20px;text-align:center;margin:20px 0;">
        <span style="font-size:32px;font-weight:800;letter-spacing:6px;color:#007bff;font-family:monospace;">{code}</span>
        <p style="color:#94a3b8;font-size:12px;margin:8px 0 0;">Expire dans {DUREE_VALIDITE_MINUTES} minutes</p>
    </div>
    """ if code else ""

    cta_html = f"""
    <div style="text-align:center;margin:24px 0;">
        <a href="{cta_url}" style="background:linear-gradient(135deg,#007bff,#0056d6);color:#fff;
           padding:12px 28px;border-radius:10px;text-decoration:none;font-weight:700;font-size:14px;">
           {cta_label}
        </a>
    </div>
    """ if cta_url and cta_label else ""

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:0;">
        <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:20px 28px;border-radius:16px 16px 0 0;">
            <p style="color:#fff;font-size:18px;font-weight:800;margin:0;">🦅 Hirondelle Conjugaison</p>
        </div>
        <div style="background:#fff;padding:28px;border-radius:0 0 16px 16px;border:1px solid #e2e8f0;border-top:none;">
            <h2 style="color:#0f172a;font-size:20px;margin:0 0 10px;">{titre}</h2>
            <p style="color:#475569;font-size:14px;line-height:1.7;margin:0 0 6px;">{message_principal}</p>
            {code_html}
            {cta_html}
            <hr style="border:none;border-top:1px solid #f1f5f9;margin:20px 0;">
            <p style="color:#cbd5e1;font-size:11px;text-align:center;margin:0;">
                Tu reçois cet email car tu es inscrit(e) sur hirondelleconjugaison.onrender.com.<br>
                Si tu n'es pas à l'origine de cette demande, ignore simplement cet email.
            </p>
        </div>
    </div>
    """


# ──────────────────────────────────────────────────────────────
# VÉRIFICATION D'INSCRIPTION
# ──────────────────────────────────────────────────────────────

def creer_code_inscription(db, email, nom, password_hash):
    from models import CodeVerification

    recent = (
        CodeVerification.query
        .filter_by(email=email, type="inscription", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if recent:
        age = (datetime.now(timezone.utc) - recent.date_creation.replace(tzinfo=timezone.utc)).total_seconds()
        if age < DELAI_RENVOI_SECONDES:
            return False, "Un code a déjà été envoyé il y a moins d'une minute. Vérifie ta boîte mail (et les spams)."

    CodeVerification.query.filter_by(email=email, type="inscription", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="inscription",
        nom_en_attente=nom, password_hash_en_attente=password_hash,
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    html = _template_email(
        titre="Confirme ton inscription",
        message_principal=f"Bonjour {nom or ''} !<br>Voici ton code de vérification pour activer ton compte sur Hirondelle Conjugaison. Il est valable <strong>{DUREE_VALIDITE_MINUTES} minutes</strong>.",
        code=code,
    )
    succes, erreur = envoyer_email(email, "Confirme ton inscription — Hirondelle Conjugaison", html)
    if not succes:
        print(f"[ATTENTION] Échec envoi email inscription à {email} : {erreur}", flush=True)
        return False, "L'envoi de l'email a échoué. Réessaie dans quelques instants."

    return True, "Un code de vérification a été envoyé à ton adresse email."


def valider_code_inscription(db, email, code_saisi):
    from models import CodeVerification, User

    entry = (
        CodeVerification.query
        .filter_by(email=email, type="inscription", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )

    if not entry:
        return False, "Aucun code en attente pour cet email. Recommence l'inscription.", None

    if datetime.now(timezone.utc) > entry.expire_le.replace(tzinfo=timezone.utc):
        return False, "Ce code a expiré. Demande un nouveau code.", None

    if entry.tentatives >= MAX_TENTATIVES:
        return False, "Trop de tentatives incorrectes. Demande un nouveau code.", None

    if entry.code != code_saisi.strip():
        entry.tentatives += 1
        db.session.commit()
        restantes = MAX_TENTATIVES - entry.tentatives
        return False, f"Code incorrect. {restantes} tentative(s) restante(s).", None

    if User.query.filter_by(email=email).first():
        entry.utilise = True
        db.session.commit()
        return False, "Un compte existe déjà avec cet email.", None

    user = User(
        email=email,
        nom=entry.nom_en_attente,
        password_hash=entry.password_hash_en_attente,
        methode_connexion="email",
        email_verifie=True,
    )
    entry.utilise = True
    db.session.add(user)
    db.session.commit()

    return True, "Compte créé et vérifié avec succès !", user


# ──────────────────────────────────────────────────────────────
# RÉINITIALISATION DE MOT DE PASSE
# ──────────────────────────────────────────────────────────────

def creer_code_reset_password(db, email):
    from models import CodeVerification, User

    MSG_NEUTRE = "Si un compte existe avec cet email, un code de réinitialisation vient d'être envoyé."

    user = User.query.filter_by(email=email).first()
    if not user or user.methode_connexion != "email":
        return True, MSG_NEUTRE

    recent = (
        CodeVerification.query
        .filter_by(email=email, type="reset_password", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if recent:
        age = (datetime.now(timezone.utc) - recent.date_creation.replace(tzinfo=timezone.utc)).total_seconds()
        if age < DELAI_RENVOI_SECONDES:
            return True, MSG_NEUTRE

    CodeVerification.query.filter_by(email=email, type="reset_password", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="reset_password",
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    html = _template_email(
        titre="Réinitialise ton mot de passe",
        message_principal="Tu as demandé à réinitialiser ton mot de passe sur Hirondelle Conjugaison. Voici ton code :",
        code=code,
    )
    envoyer_email(email, "Réinitialisation de mot de passe — Hirondelle Conjugaison", html)
    return True, MSG_NEUTRE


def valider_code_et_changer_password(db, bcrypt, email, code_saisi, nouveau_password):
    from models import CodeVerification, User

    entry = (
        CodeVerification.query
        .filter_by(email=email, type="reset_password", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if not entry:
        return False, "Aucune demande de réinitialisation en attente pour cet email."

    if datetime.now(timezone.utc) > entry.expire_le.replace(tzinfo=timezone.utc):
        return False, "Ce code a expiré. Recommence la procédure."

    if entry.tentatives >= MAX_TENTATIVES:
        return False, "Trop de tentatives. Recommence la procédure."

    if entry.code != code_saisi.strip():
        entry.tentatives += 1
        db.session.commit()
        restantes = MAX_TENTATIVES - entry.tentatives
        return False, f"Code incorrect. {restantes} tentative(s) restante(s)."

    user = User.query.filter_by(email=email).first()
    if not user:
        return False, "Compte introuvable."

    user.password_hash = bcrypt.generate_password_hash(nouveau_password).decode("utf-8")
    entry.utilise = True
    db.session.commit()
    return True, "Mot de passe mis à jour. Tu peux te connecter."


# ──────────────────────────────────────────────────────────────
# EMAIL DE RELANCE RÉTENTION (streak en danger)
# ──────────────────────────────────────────────────────────────

def envoyer_email_relance(user, base_url="https://hirondelleconjugaison.onrender.com"):
    if not user.email_verifie:
        return False

    if user.streak_jours > 0:
        message = f"Ton streak de <strong>{user.streak_jours} jour{'s' if user.streak_jours > 1 else ''}</strong> est en danger ! Si tu ne joues pas aujourd'hui, ton streak repart à zéro."
        titre = f"🔥 Ton streak de {user.streak_jours} jour(s) risque de tomber !"
    else:
        message = "Tu n'as pas conjugué depuis 3 jours. Reprends là où tu t'es arrêté(e) — seulement 2 minutes suffisent pour rester en forme."
        titre = "🦅 Reviens t'entraîner — 2 minutes, c'est tout !"

    html = _template_email(
        titre=titre,
        message_principal=message,
        cta_url=f"{base_url}/quiz?mode=entrainement",
        cta_label="Reprendre l'entraînement →",
    )
    succes, _ = envoyer_email(user.email, titre, html)
    return succes
