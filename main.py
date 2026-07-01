from flask import Flask, request, render_template, redirect, url_for, session, flash
import random
import time
import json
import os
import uuid
from pathlib import Path

# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Chargement actif.json
try:
    with open(DATA_DIR / "actif.json", encoding="utf-8") as f:
        ACTIF = json.load(f)
except FileNotFoundError:
    raise SystemExit("ERREUR : data/actif.json introuvable.")
except json.JSONDecodeError as e:
    raise SystemExit(f"ERREUR : data/actif.json mal formé : {e}")

# Chargement passif.json
try:
    with open(DATA_DIR / "passif.json", encoding="utf-8") as f:
        PASSIF = json.load(f)
except FileNotFoundError:
    raise SystemExit("ERREUR : data/passif.json introuvable.")
except json.JSONDecodeError as e:
    raise SystemExit(f"ERREUR : data/passif.json mal formé : {e}")

# Liste complète des verbes passivables (utilisée pour la révision ciblée)
VERBES_PASSIVABLES = [
    "tenir", "sentir", "voir", "recevoir", "cueillir", "acquérir",
    "faire", "appeler", "jeter", "peigner", "mouler", "tuer",
    "rendre", "peindre", "vaincre", "prendre"
]

# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "secret123")
if app.secret_key == "secret123":
    print("[ALERTE SÉCURITÉ] SECRET_KEY n'est pas définie en variable d'environnement — "
          "le fallback en dur dans le code est utilisé. N'importe qui lisant le code source "
          "peut forger une session valide. Configure SECRET_KEY sur Render immédiatement.", flush=True)

# Sécurité des cookies de session :
# - Secure   : le cookie n'est envoyé que sur HTTPS (Render fournit HTTPS par défaut)
# - HttpOnly : empêche tout JavaScript (même via une faille XSS) de lire le cookie
# - SameSite=Lax : empêche le cookie d'être envoyé sur des requêtes cross-site
#   déclenchées par un autre site (protection complémentaire au CSRF token)
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
print("[BOOT] cookies sécurisés (Secure, HttpOnly, SameSite) OK", flush=True)

# Limite globale par défaut, large pour ne pas gêner un usage normal du
# site — les routes sensibles (auth.py) ont leurs propres limites plus
# strictes qui priment sur celle-ci.
app.config["RATELIMIT_DEFAULT"] = "200 per hour"
app.config["RATELIMIT_STORAGE_URI"] = "memory://"  # un seul worker Gunicorn (WEB_CONCURRENCY=1 sur Render)

# ============================================================
# BASE DE DONNÉES (PostgreSQL via DATABASE_URL fourni par Render)
# ============================================================
from models import db, User

from flask_login import LoginManager, login_required, current_user

from auth import auth_bp, init_auth, limiter

db_url = os.environ.get("DATABASE_URL", "")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///local_dev.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

init_auth(app)

# ============================================================
# PROTECTION CSRF
# ============================================================
# Sans ça, un site malveillant peut construire un formulaire caché qui
# soumet une requête à ce site en se faisant passer pour l'utilisateur
# connecté (ex: déclencher une action en son nom sans qu'il s'en rende
# compte). CSRFProtect exige un jeton secret unique par session dans
# chaque formulaire POST, que seul ce site peut générer.
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
csrf.init_app(app)

app.register_blueprint(auth_bp)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.connexion"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _auto_migrer_colonnes_manquantes():
    """
    db.create_all() ne crée que les tables ABSENTES — il ne touche jamais
    une table déjà existante, même si le modèle Python a de nouvelles
    colonnes. Sans ça, ajouter un champ à User (xp_total, niveau...) plante
    en production avec "column does not exist", car la table "users" créée
    lors du premier déploiement n'a jamais ces colonnes.

    Cette fonction compare les colonnes attendues par les modèles à celles
    réellement présentes en base, et exécute des ALTER TABLE ADD COLUMN
    pour celles qui manquent. Idempotent : ne fait rien si tout est déjà
    à jour, donc sans risque à chaque redémarrage.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # la table n'existe pas encore, create_all() s'en occupe

        colonnes_existantes = {c["name"] for c in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in colonnes_existantes:
                continue

            # Construire le type SQL et la valeur par défaut compatible PostgreSQL
            col_type = column.type.compile(dialect=db.engine.dialect)
            default_sql = ""
            if column.default is not None and getattr(column.default, "arg", None) is not None:
                arg = column.default.arg
                if isinstance(arg, bool):
                    default_sql = f" DEFAULT {str(arg).upper()}"
                elif isinstance(arg, (int, float)):
                    default_sql = f" DEFAULT {arg}"
                elif isinstance(arg, str):
                    default_sql = f" DEFAULT '{arg}'"

            # Important : on ajoute TOUJOURS la colonne en NULLABLE d'abord,
            # même si le modèle Python la déclare nullable=False. Une table
            # qui contient déjà des lignes ne peut pas recevoir une nouvelle
            # colonne NOT NULL sans valeur par défaut pour les lignes
            # existantes — PostgreSQL rejette l'ALTER TABLE sinon.
            # Le DEFAULT (s'il existe) remplit automatiquement les lignes
            # existantes, donc passer en NOT NULL juste après est sûr.
            ddl_add = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}{default_sql}'
            try:
                with db.engine.begin() as conn:
                    conn.execute(text(ddl_add))
                print(f"[MIGRATION] Colonne ajoutée : {table.name}.{column.name}", flush=True)

                if not column.nullable and default_sql:
                    ddl_not_null = f'ALTER TABLE "{table.name}" ALTER COLUMN "{column.name}" SET NOT NULL'
                    with db.engine.begin() as conn:
                        conn.execute(text(ddl_not_null))
                    print(f"[MIGRATION] Contrainte NOT NULL appliquée : {table.name}.{column.name}", flush=True)
            except Exception as e:
                print(f"[ATTENTION] Échec migration {table.name}.{column.name} : {e}", flush=True)


try:
    with app.app_context():
        db.create_all()
        _auto_migrer_colonnes_manquantes()
    print("[BOOT] db.create_all() + migration OK", flush=True)
except Exception as e:
    # Si la base n'est pas encore joignable au démarrage (latence Render,
    # variable DATABASE_URL absente ou mal formée), on ne fait pas planter
    # tout le serveur — le site continue de fonctionner sans les comptes
    # jusqu'à ce que la connexion soit rétablie.
    print(f"[ATTENTION] Impossible d'initialiser la base de données au démarrage : {e}")

# ============================================================
# STOCKAGE EN MÉMOIRE DES LISTES DE QUESTIONS CIBLÉES
# Les cookies Flask sont limités à 4KB — impossible d'y stocker
# des centaines de questions. On les garde côté serveur,
# et on ne met qu'un UUID dans la session.
# ============================================================
_QUESTIONS_STORE: dict = {}  # {uuid_str: [liste de tuples]}


def calculer_stats_user(user):
    """
    Calcule les statistiques d'un utilisateur depuis AgregatVerbe (compact)
    plutôt que depuis l'historique brut — une seule requête légère, peu
    importe le nombre de questions jouées depuis la création du compte.
    """
    from models import AgregatVerbe
    from collections import Counter

    agregats = AgregatVerbe.query.filter_by(user_id=user.id).all()
    total = sum(a.nb_total for a in agregats)
    correctes = sum(a.nb_correct for a in agregats)
    taux = round(correctes / total * 100, 1) if total else 0

    erreurs_par_verbe = Counter()
    for a in agregats:
        erreurs = a.nb_total - a.nb_correct
        if erreurs > 0:
            erreurs_par_verbe[a.verbe] += erreurs
    verbe_a_revoir = erreurs_par_verbe.most_common(1)[0][0] if erreurs_par_verbe else None

    nb_verbes_distincts = len({a.verbe for a in agregats})

    return {
        "total": total, "correctes": correctes, "taux": taux,
        "verbe_a_revoir": verbe_a_revoir, "agregats": agregats,
        "nb_verbes_distincts": nb_verbes_distincts,
    }


# ============================================================
# ROUTES DE BASE
# ============================================================
@app.route("/badges")
@login_required
def badges():
    from repetition import BADGES
    obtenus = set(current_user.liste_badges())
    liste = [
        {"code": code, **info, "obtenu": code in obtenus}
        for code, info in BADGES.items()
    ]
    return render_template("badges.html", liste=liste, nb_obtenus=len(obtenus), nb_total=len(BADGES))


@app.route("/compte")
@login_required
def compte():
    stats = calculer_stats_user(current_user)
    return render_template("compte.html", stats=stats)


@app.route("/progression")
@login_required
def progression():
    from models import ReponseRecente
    from collections import Counter

    base = calculer_stats_user(current_user)
    agregats = base["agregats"]

    # Répartition par mode grammatical — calculée depuis les agrégats compacts,
    # pas depuis l'historique brut.
    par_mode = {}
    for a in agregats:
        m = par_mode.setdefault(a.mode, {"total": 0, "correctes": 0})
        m["total"] += a.nb_total
        m["correctes"] += a.nb_correct
    for m in par_mode.values():
        m["taux"] = round(m["correctes"] / m["total"] * 100, 1) if m["total"] else 0
    par_mode = dict(sorted(par_mode.items(), key=lambda kv: kv[1]["total"], reverse=True))

    # Verbes les plus ratés, en nombre absolu d'erreurs cumulées
    erreurs_par_verbe = Counter()
    for a in agregats:
        erreurs = a.nb_total - a.nb_correct
        if erreurs > 0:
            erreurs_par_verbe[a.verbe] += erreurs
    verbes_a_revoir = erreurs_par_verbe.most_common(5)

    # Activité récente : lue depuis l'historique borné (max ~150 lignes/utilisateur)
    historique_recent = (
        ReponseRecente.query
        .filter_by(user_id=current_user.id)
        .order_by(ReponseRecente.date.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "progression.html",
        total=base["total"], correctes=base["correctes"], taux=base["taux"],
        par_mode=par_mode, verbes_a_revoir=verbes_a_revoir,
        historique_recent=historique_recent,
        user=current_user,
    )


# ============================================================
# DASHBOARD ADMIN — vue interne sur les statistiques globales du site
# ============================================================
# Restreint à un email précis plutôt qu'à un rôle "admin" en base : plus
# simple pour un seul propriétaire de site, sans avoir à gérer un champ
# is_admin supplémentaire sur User pour l'instant.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "lemeilleurhackeur65645@gmail.com")


def _admin_requis():
    """Retourne une réponse de refus si l'utilisateur n'est pas l'admin, sinon None."""
    if not current_user.is_authenticated or current_user.email != ADMIN_EMAIL:
        return render_template("404.html"), 404  # 404 plutôt que 403 : ne révèle pas que la route existe
    return None


@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    refus = _admin_requis()
    if refus:
        return refus

    from models import User, AgregatVerbe, ReponseRecente
    from collections import Counter
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    # ── Vue d'ensemble ──
    tous_users = User.query.all()
    nb_users_total = len(tous_users)
    nb_verifies = sum(1 for u in tous_users if u.email_verifie)

    par_methode = Counter(u.methode_connexion for u in tous_users)

    # Inscriptions par jour sur les 30 derniers jours — pour une courbe de croissance
    inscriptions_30j = Counter()
    for u in tous_users:
        if u.date_creation:
            dc = u.date_creation.replace(tzinfo=timezone.utc) if u.date_creation.tzinfo is None else u.date_creation
            if (now - dc).days <= 30:
                inscriptions_30j[dc.strftime("%Y-%m-%d")] += 1
    inscriptions_30j = dict(sorted(inscriptions_30j.items()))

    # ── Rétention ──
    actifs_7j, actifs_30j, jamais_revenu = 0, 0, 0
    distribution_streak = {"0": 0, "1-3": 0, "4-7": 0, "8+": 0}

    for u in tous_users:
        if u.derniere_session:
            jours_depuis = (now.date() - u.derniere_session).days
            if jours_depuis <= 7:
                actifs_7j += 1
            if jours_depuis <= 30:
                actifs_30j += 1
        else:
            jamais_revenu += 1

        if u.streak_jours == 0:
            distribution_streak["0"] += 1
        elif u.streak_jours <= 3:
            distribution_streak["1-3"] += 1
        elif u.streak_jours <= 7:
            distribution_streak["4-7"] += 1
        else:
            distribution_streak["8+"] += 1

    taux_retention_7j = round(actifs_7j / nb_users_total * 100, 1) if nb_users_total else 0
    taux_retention_30j = round(actifs_30j / nb_users_total * 100, 1) if nb_users_total else 0

    # ── Engagement par contenu (agrégé tous utilisateurs confondus) ──
    tous_agregats = AgregatVerbe.query.all()

    par_mode_global = {}
    for a in tous_agregats:
        m = par_mode_global.setdefault(a.mode, {"total": 0, "correctes": 0})
        m["total"] += a.nb_total
        m["correctes"] += a.nb_correct
    for m in par_mode_global.values():
        m["taux"] = round(m["correctes"] / m["total"] * 100, 1) if m["total"] else 0
    par_mode_global = dict(sorted(par_mode_global.items(), key=lambda kv: kv[1]["total"], reverse=True))

    erreurs_verbe_global = Counter()
    jeu_verbe_global = Counter()
    for a in tous_agregats:
        jeu_verbe_global[a.verbe] += a.nb_total
        erreurs = a.nb_total - a.nb_correct
        if erreurs > 0:
            erreurs_verbe_global[a.verbe] += erreurs

    verbes_plus_joues = jeu_verbe_global.most_common(10)
    verbes_plus_rates = erreurs_verbe_global.most_common(10)

    # ── Table des utilisateurs (triée par activité la plus récente) ──
    def _tri_date(u):
        return u.derniere_session or datetime.min.date()

    users_tries = sorted(tous_users, key=_tri_date, reverse=True)

    xp_moyen = round(sum(u.xp_total for u in tous_users) / nb_users_total, 0) if nb_users_total else 0
    niveau_moyen = round(sum(u.niveau for u in tous_users) / nb_users_total, 1) if nb_users_total else 0

    return render_template(
        "admin_dashboard.html",
        nb_users_total=nb_users_total,
        nb_verifies=nb_verifies,
        par_methode=dict(par_methode),
        inscriptions_30j=inscriptions_30j,
        actifs_7j=actifs_7j,
        actifs_30j=actifs_30j,
        jamais_revenu=jamais_revenu,
        taux_retention_7j=taux_retention_7j,
        taux_retention_30j=taux_retention_30j,
        distribution_streak=distribution_streak,
        par_mode_global=par_mode_global,
        verbes_plus_joues=verbes_plus_joues,
        verbes_plus_rates=verbes_plus_rates,
        users_tries=users_tries,
        xp_moyen=xp_moyen,
        niveau_moyen=niveau_moyen,
        now=now,
    )


# Clé IndexNow — Bing (et les autres moteurs qui supportent le protocole :
# Yandex, Seznam, Naver) vérifient ce fichier pour confirmer qu'on contrôle
# bien le domaine avant d'accepter nos notifications d'URLs modifiées.
# Le nom de fichier ET le contenu doivent être identiques à la clé générée.
INDEXNOW_KEY = "930ac95847404f4b9073faa0c17ba87e"
INDEXNOW_ADMIN_TOKEN = os.environ.get("INDEXNOW_ADMIN_TOKEN", "")


@app.route(f"/{INDEXNOW_KEY}.txt")
@limiter.exempt
def indexnow_key():
    from flask import Response
    return Response(INDEXNOW_KEY, mimetype="text/plain")


def _toutes_les_urls_conjugaison():
    """Même logique que /sitemap.xml — réutilisée pour la soumission IndexNow."""
    base = "https://hirondelleconjugaison.onrender.com"
    urls = [base + "/", base + "/conjugaisons"]
    for verbe, modes_verbe in sorted(ACTIF.items()):
        urls.append(f"{base}/conjugaison/{verbe}")
        for mode, temps_dict in modes_verbe.items():
            for temps, formes in temps_dict.items():
                if formes:
                    urls.append(f"{base}/conjugaison/{verbe}/{mode}/{temps}")
    return urls


@app.route("/admin/envoyer-relances")
@limiter.limit("5 per hour")
def envoyer_relances():
    """
    Route destinée à être appelée automatiquement chaque jour par un service
    de cron externe (ex: cron-job.org, gratuit) — jamais manuellement en boucle.

    Envoie un email de relance aux utilisateurs inactifs depuis EXACTEMENT
    3 jours, pour les ramener avant que l'habitude ne soit perdue. Pas plus
    fréquent (sinon spam), pas moins (le 3e jour est le moment critique où
    un utilisateur décide de revenir ou d'abandonner définitivement).

    Protection : même token que IndexNow (INDEXNOW_ADMIN_TOKEN).
    URL à configurer sur cron-job.org :
      https://hirondelleconjugaison.onrender.com/admin/envoyer-relances?token=TON_TOKEN
    Fréquence recommandée : 1 fois par jour, à 9h00.
    """
    from flask import jsonify
    from models import User
    from datetime import date, timedelta
    from email_verification import envoyer_email_relance

    if not INDEXNOW_ADMIN_TOKEN:
        return jsonify({"erreur": "INDEXNOW_ADMIN_TOKEN non configuré."}), 503

    if request.args.get("token") != INDEXNOW_ADMIN_TOKEN:
        return jsonify({"erreur": "Token invalide."}), 403

    cible = date.today() - timedelta(days=3)
    users_a_relancer = [
        u for u in User.query.all()
        if u.email_verifie
        and u.derniere_session == cible
        and u.xp_total > 0  # n'a pas juste créé un compte sans jamais jouer
    ]

    envoyes, echecs = 0, 0
    for user in users_a_relancer:
        if envoyer_email_relance(user):
            envoyes += 1
        else:
            echecs += 1

    return jsonify({
        "date_cible": str(cible),
        "candidats": len(users_a_relancer),
        "envoyes": envoyes,
        "echecs": echecs,
    })


@app.route("/admin/indexnow-submit")
@limiter.limit("2 per hour")
def indexnow_submit():
    """
    Notifie IndexNow (Bing + moteurs partenaires) de toutes les URLs du site
    en une fois. Protégée par un token — sans ça, n'importe qui pourrait
    déclencher des soumissions en masse en notre nom, ce qui risquerait de
    nous faire bannir du protocole pour abus.

    Usage : /admin/indexnow-submit?token=<INDEXNOW_ADMIN_TOKEN>
    À utiliser une fois après le déploiement, puis occasionnellement après
    un ajout massif de pages — pas après chaque petite modification.
    """
    from flask import jsonify

    if not INDEXNOW_ADMIN_TOKEN:
        return jsonify({"erreur": "INDEXNOW_ADMIN_TOKEN non configuré sur le serveur."}), 503

    if request.args.get("token") != INDEXNOW_ADMIN_TOKEN:
        return jsonify({"erreur": "Token invalide."}), 403

    import requests as req_lib

    base = "https://hirondelleconjugaison.onrender.com"
    toutes_urls = _toutes_les_urls_conjugaison()

    # IndexNow accepte jusqu'à 10 000 URLs par requête — on découpe par
    # sécurité même si le site actuel reste largement sous cette limite.
    LOT = 10000
    resultats = []
    for i in range(0, len(toutes_urls), LOT):
        lot_urls = toutes_urls[i:i + LOT]
        try:
            resp = req_lib.post(
                "https://api.indexnow.org/indexnow",
                headers={"Content-Type": "application/json; charset=utf-8"},
                json={
                    "host": "hirondelleconjugaison.onrender.com",
                    "key": INDEXNOW_KEY,
                    "keyLocation": f"{base}/{INDEXNOW_KEY}.txt",
                    "urlList": lot_urls,
                },
                timeout=15,
            )
            resultats.append({"lot": i // LOT + 1, "nb_urls": len(lot_urls), "status": resp.status_code})
        except Exception as e:
            resultats.append({"lot": i // LOT + 1, "nb_urls": len(lot_urls), "erreur": str(e)})

    return jsonify({"total_urls": len(toutes_urls), "resultats": resultats})


@app.route("/robots.txt")
@limiter.exempt
def robots_txt():
    from flask import Response
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Sitemap: https://hirondelleconjugaison.onrender.com/sitemap.xml\n"
    )
    return Response(content, mimetype="text/plain")


@app.route("/")
@limiter.exempt
def index():
    # On vide la session de quiz (verbe en cours, score...) sans déconnecter
    # l'utilisateur : flask-login stocke l'identifiant de connexion sous la
    # clé "_user_id" dans cette même session, donc un clear() complet
    # déconnectait tout le monde à chaque retour à l'accueil.
    user_id = session.get("_user_id")
    session.clear()
    if user_id:
        session["_user_id"] = user_id

    stats = None
    xp_progress_pct = 0
    xp_prochain_niveau = 0
    streak_joue_aujourd_hui = False
    if current_user.is_authenticated:
        stats = calculer_stats_user(current_user)
        from repetition import xp_requis_pour_niveau
        from datetime import date
        xp_niveau_actuel = xp_requis_pour_niveau(current_user.niveau)
        xp_prochain_niveau = xp_requis_pour_niveau(current_user.niveau + 1)
        ecart = xp_prochain_niveau - xp_niveau_actuel
        progres = current_user.xp_total - xp_niveau_actuel
        xp_progress_pct = round(max(0, min(100, progres / ecart * 100)), 1) if ecart else 0
        streak_joue_aujourd_hui = (current_user.derniere_session == date.today())

    return render_template(
        "index.html", stats=stats,
        xp_progress_pct=xp_progress_pct, xp_prochain_niveau=xp_prochain_niveau,
        streak_joue_aujourd_hui=streak_joue_aujourd_hui,
    )

@app.route("/revision")
def revision():
    erreurs = session.get("erreurs", [])
    return render_template("revision.html", erreurs=erreurs)

@app.route("/parametres")
def parametres():
    return render_template("parametres.html")


@app.route("/changelog")
def changelog():
    return render_template("changelog.html")


@app.route("/cible")
def cible():
    # Déblocage progressif : le quiz ciblé est accessible dès le niveau 3
    # pour encourager les utilisateurs à progresser avant d'accéder aux modes
    # avancés. Les visiteurs non connectés peuvent y accéder librement.
    niveau_requis_cible = 3
    niveau_bloque = (
        current_user.is_authenticated
        and current_user.niveau < niveau_requis_cible
    )

    # Modes disponibles (à partir de ACTIF)
    modes = sorted({m for v in ACTIF.values() for m in v.keys()})

    # Mapping mode -> temps valides
    modes_temps = {}
    for v in ACTIF.values():
        for mode, temps_dict in v.items():
            modes_temps.setdefault(mode, set())
            for t in temps_dict.keys():
                modes_temps[mode].add(t)
    modes_temps = {m: sorted(list(ts)) for m, ts in modes_temps.items()}

    # Listes de verbes par groupe grammatical
    LISTES_VERBES = {
        # ── 1er GROUPE : verbes en -er ──────────────────────────────────────────
        "1er groupe — A à C": [
            "aimer", "aller", "amener", "amuser", "annoncer", "apporter", "appeler",
            "arriver", "avancer", "avouer", "baisser", "briser", "cacher", "calmer",
            "caresser", "casser", "causer", "céder", "cesser", "changer", "chanter",
            "charger", "chasser", "chercher", "commander", "commencer", "composer",
            "compter", "condamner", "confier", "considérer", "consulter", "contenter",
            "continuer", "copier", "coucher", "couler", "couper", "coûter", "créer",
            "creuser", "crier", "croiser",
        ],
        "1er groupe — D à G": [
            "danser", "décider", "déclarer", "dégager", "demander", "demeurer",
            "dépasser", "déposer", "désigner", "désirer", "dessiner", "détacher",
            "deviner", "diriger", "discuter", "disposer", "distinguer", "dominer",
            "donner", "douter", "dresser", "durer", "écarter", "échapper", "éclairer",
            "éclater", "écouter", "écraser", "effacer", "élever", "éloigner",
            "embrasser", "emmener", "empêcher", "employer", "emporter", "endormir",
            "enfermer", "enfoncer", "engager", "enlever", "entourer", "entraîner",
            "envelopper", "envoyer", "éprouver", "espérer", "essayer", "essuyer",
            "établir", "étaler", "étonner", "étouffer", "étudier", "éviter",
            "examiner", "exécuter", "exiger", "expliquer", "exposer", "exprimer",
            "fatiguer", "fermer", "figurer", "fixer", "fonder", "forcer", "former",
            "frapper", "fumer", "gagner", "garder", "glisser", "grandir",
        ],
        "1er groupe — H à P": [
            "habiller", "habiter", "hésiter", "ignorer", "imaginer", "importer",
            "imposer", "indiquer", "inquiéter", "inspirer", "installer", "intéresser",
            "interroger", "inventer", "inviter", "jeter", "jouer", "juger",
            "lever", "lier", "lisser", "livrer", "lutter", "maintenir", "manger",
            "manquer", "marcher", "marier", "marquer", "mêler", "menacer", "mener",
            "mériter", "monter", "montrer", "nommer", "nourrir", "obliger", "observer",
            "occuper", "oser", "oublier", "parcourir", "parler", "partager", "passer",
            "payer", "pencher", "penser", "peser", "placer", "pleurer", "plonger",
            "porter", "poser", "posséder", "pousser", "précipiter", "préparer",
            "présenter", "presser", "prêter", "prier", "profiter", "promener",
            "prononcer", "proposer", "protéger", "prouver",
        ],
        "1er groupe — R à Z": [
            "raconter", "ramasser", "ramener", "rappeler", "rapporter", "rassurer",
            "réclamer", "recommencer", "reculer", "réfléchir", "refuser", "regarder",
            "regretter", "relever", "remarquer", "remercier", "remplacer", "rencontrer",
            "renverser", "renvoyer", "répéter", "reposer", "repousser", "représenter",
            "réserver", "respecter", "respirer", "ressembler", "rester", "retirer",
            "retomber", "retourner", "retrouver", "réveiller", "révéler", "rêver",
            "risquer", "rouler", "saluer", "sauter", "sauver", "séparer", "serrer",
            "signer", "signifier", "songer", "sonner", "souhaiter", "soulever",
            "supposer", "surveiller", "terminer", "tenter", "tirer", "toucher",
            "tourner", "tracer", "traîner", "traiter", "transformer", "travailler",
            "traverser", "trembler", "tromper", "troubler", "trouver", "tuer",
            "user", "veiller", "verser", "voyager",
        ],
        "1er groupe — verbes en -eler / -eter": [
            "appeler", "jeter", "rappeler", "rejeter", "regeler", "surgeler",
            "voleter", "trompeter",
        ],
        "1er groupe — verbes en -cer / -ger": [
            "annoncer", "avancer", "commencer", "effacer", "lancer", "menacer",
            "placer", "remplacer", "renoncer", "tracer",
            "changer", "charger", "dégager", "déranger", "engager", "manger",
            "partager", "plonger", "protéger", "voyager",
        ],
        "1er groupe — verbes en -yer": [
            "appuyer", "employer", "envoyer", "essayer", "essuyer", "nettoyer",
            "payer", "renvoyer", "surpayer", "voussoyer", "vouvoyer",
        ],

        # ── 2e GROUPE : verbes en -ir / participe présent en -issant ───────────
        "2e groupe": [
            "accomplir", "agir", "choisir", "établir", "finir", "franchir",
            "grandir", "nourrir", "obéir", "réfléchir", "remplir", "réunir",
            "réussir", "saillir", "saisir", "subir",
        ],

        # ── 3e GROUPE : verbes irréguliers en -ir ───────────────────────────────
        "3e groupe — -ir irréguliers (courir, partir…)": [
            "acquérir", "accueillir", "assaillir", "bouillir", "consentir",
            "contenir", "convenir", "courir", "couvrir", "cueillir", "devenir",
            "dormir", "découvrir", "dévêtir", "endormir", "entretenir", "faillir",
            "fuir", "maintenir", "mentir", "mourir", "obtenir", "offrir", "ouvrir",
            "parcourir", "partir", "parvenir", "prévenir", "reconquérir", "recourir",
            "recueillir", "redormir", "refuir", "rendormir", "requérir", "resservir",
            "retenir", "revenir", "revêtir", "rouvrir", "secourir", "sentir",
            "servir", "sortir", "souffrir", "soutenir", "souvenir", "survenir",
            "tenir", "tressaillir", "venir", "vêtir",
        ],

        # ── 3e GROUPE : verbes en -oir ───────────────────────────────────────────
        "3e groupe — -oir (avoir, voir, pouvoir…)": [
            "avoir", "apercevoir", "asseoir", "boire", "choir", "croire",
            "déchoir", "dépourvoir", "devoir", "échoir", "émouvoir", "falloir",
            "mouvoir", "percevoir", "pleuvoir", "pourvoir", "pouvoir", "prévaloir",
            "prévoir", "promouvoir", "rasseoir", "recevoir", "revoir", "savoir",
            "seoir", "surseoir", "valoir", "voir", "vouloir",
        ],

        # ── 3e GROUPE : verbes en -ndre ──────────────────────────────────────────
        "3e groupe — -ndre (prendre, rendre, attendre…)": [
            "apprendre", "attendre", "comprendre", "confondre", "défendre",
            "descendre", "entendre", "pendre", "prendre", "prétendre", "rendre",
            "répandre", "répondre", "reprendre", "surprendre", "tendre", "vendre",
            "étendre",
        ],
        "3e groupe — -indre / -oindre / -aindre (peindre, joindre…)": [
            "atteindre", "craindre", "éteindre", "joindre", "peindre", "plaindre",
            "poindre", "rejoindre", "reteindre", "retreindre", "teindre",
        ],

        # ── 3e GROUPE : verbes en -ire ───────────────────────────────────────────
        "3e groupe — -ire (dire, faire, lire, écrire…)": [
            "conduire", "construire", "confire", "décrire", "déplaire", "détruire",
            "dire", "distraire", "écrire", "faire", "frire", "lire", "maudire",
            "plaire", "prédire", "produire", "redire", "réduire", "réélire",
            "relire", "rire", "satisfaire", "se taire", "sourire", "souscrire",
            "soustraire", "suffire", "suivre", "surfaire", "taire", "traduire",
            "traire", "transcrire",
        ],

        # ── 3e GROUPE : verbes en -re (autres) ──────────────────────────────────
        "3e groupe — -re (être, mettre, battre, vivre…)": [
            "être", "abattre", "accroître", "admettre", "apparaître", "battre",
            "clore", "conclure", "connaître", "convaincre", "décroître", "disparaître",
            "enclore", "foutre", "haïr", "interrompre", "mettre", "naître",
            "occlure", "paraître", "paître", "permettre", "poursuivre", "promettre",
            "reconnaître", "remettre", "renaître", "reparaître", "repaître", "revivre",
            "rompre", "soumettre", "survivre", "transmettre", "transparaître",
            "vaincre", "vivre",
        ],
    }
    # Filtrer : ne garder que les verbes présents dans ACTIF
    LISTES_VERBES = {
        nom: [v for v in verbes if v in ACTIF]
        for nom, verbes in LISTES_VERBES.items()
    }

    return render_template(
        "cible.html",
        modes=modes,
        modes_temps_json=json.dumps(modes_temps, ensure_ascii=False),
        listes=LISTES_VERBES,
        verbes_passivables=VERBES_PASSIVABLES,
        niveau_bloque=niveau_bloque,
        niveau_requis=niveau_requis_cible,
    )

# ============================================================
# GÉNÉRATION D'UNE QUESTION
# ============================================================

def _choix_pondere(candidats, poids_par_verbe):
    """
    Tire un élément au sort dans candidats. Si poids_par_verbe est fourni
    (répétition espacée pour un utilisateur connecté), favorise les verbes
    à poids élevé. Sinon, comportement strictement aléatoire (historique).
    """
    if not poids_par_verbe:
        return random.choice(candidats)
    poids_liste = [poids_par_verbe.get(c, 1.0) for c in candidats]
    return random.choices(candidats, weights=poids_liste, k=1)[0]


# Note : agréger_poids_par_verbe vit désormais dans repetition.py
# (importé localement où nécessaire), pour éviter la duplication.


def generer_question(modes=None, temps=None, personnes=None, verbes=None, base=None, voix_question="active", _depth=0, poids_verbes=None):
    """
    base = ACTIF ou PASSIF selon la voix choisie.
    _depth : compteur interne pour éviter la récursion infinie.
    poids_verbes : dict optionnel {(verbe, mode, temps): poids} pour la répétition
                   espacée — favorise les combinaisons récemment ratées.
                   None ou {} = tirage uniformément aléatoire (comportement historique).
    """
    # CORRECTION : limite de récursion explicite pour éviter RecursionError
    if _depth > 50:
        raise RuntimeError(
            "generer_question : impossible de trouver une combinaison valide "
            "avec les paramètres fournis (trop de tentatives)."
        )

    try:
        local_conj = base if base else ACTIF

        # 1) Sélection du verbe
        if verbes:
            candidats_verbes = [v for v in verbes if v in local_conj]
            if not candidats_verbes:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)
            verbe = _choix_pondere(candidats_verbes, poids_verbes)
        else:
            verbe = _choix_pondere(list(local_conj.keys()), poids_verbes)

        modes_dict = local_conj.get(verbe, {})
        if not modes_dict:
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

        # 2) Sélection du mode
        if modes:
            candidats_modes = [m for m in modes if m in modes_dict]
            if not candidats_modes:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)
            mode_v = random.choice(candidats_modes)
        else:
            mode_v = random.choice(list(modes_dict.keys()))

        temps_dict = modes_dict.get(mode_v, {})
        if not temps_dict:
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

        # 3) Sélection du temps
        if temps:
            candidats_temps = [t for (m, t) in temps if m == mode_v and t in temps_dict]
            if not candidats_temps:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)
            temps_sel = random.choice(candidats_temps)
        else:
            temps_sel = random.choice(list(temps_dict.keys()))

        formes = temps_dict.get(temps_sel, [])
        if not formes:
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

        # 4) Sélection de la personne
        mapping = ["je", "tu", "il", "nous", "vous", "ils"]

        if mode_v.lower() == "impératif":
            imperatif_personnes = ["tu", "nous", "vous"]

            if temps_sel not in ["présent", "passé"]:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

            if personnes:
                convert = {"2s": "tu", "1p": "nous", "2p": "vous"}
                sujets_possibles = [convert[p] for p in personnes if p in convert]
            else:
                sujets_possibles = imperatif_personnes

            if not sujets_possibles:
                sujets_possibles = imperatif_personnes

            sujet = random.choice(sujets_possibles)
            idx = imperatif_personnes.index(sujet)

        else:
            if len(formes) == 1:
                sujet = "(forme impersonnelle)"
                idx = 0
            else:
                if personnes:
                    convert = {
                        "1s": "je", "2s": "tu", "3s": "il",
                        "1p": "nous", "2p": "vous", "3p": "ils"
                    }
                    sujets_possibles = [
                        convert[p] for p in personnes
                        if convert[p] in mapping[:len(formes)]
                    ]
                else:
                    sujets_possibles = mapping[:len(formes)]

                if not sujets_possibles:
                    return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

                sujet = random.choice(sujets_possibles)
                idx = mapping.index(sujet)

        if idx >= len(formes):
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

        bonne = formes[idx]

        mapping_desc = {
            "je": "1re personne du singulier",
            "tu": "2e personne du singulier",
            "il": "3e personne du singulier",
            "nous": "1re personne du pluriel",
            "vous": "2e personne du pluriel",
            "ils": "3e personne du pluriel",
            "(forme impersonnelle)": "(forme impersonnelle)"
        }

        sujet_affiche = mapping_desc.get(sujet, sujet)
        question = f"Conjugue : {verbe} — {mode_v} — {temps_sel} — {sujet_affiche} — voix {voix_question}"

        return verbe, mode_v, temps_sel, sujet, bonne, question

    # CORRECTION : except ciblé — on ne rattrape plus Exception générique.
    # Les seules erreurs légitimes à relancer sont les erreurs de structure de données
    # (KeyError, IndexError, TypeError). ValueError et RuntimeError sont laissées remonter.
    except (KeyError, IndexError, TypeError):
        return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1, poids_verbes)

# ============================================================
# MODE RÉVISION CIBLÉE
# ============================================================

@app.route("/cible_start", methods=["POST"])
def cible_start():
    session["mode"] = "cible"
    session["score"] = 0
    session["total"] = 0
    session["start"] = time.time()
    session["cible_modes"] = request.form.getlist("modes")
    session["cible_personnes"] = request.form.getlist("personnes")
    session["cible_voix"] = request.form.getlist("voix")

    # Récupérer les verbes depuis le formulaire SANS les stocker directement en session
    # (un cookie Flask est limité à 4KB — 543 verbes le dépassent largement)
    raw_verbes = list(dict.fromkeys(request.form.getlist("verbes")))  # dédupliquer

    # Si uniquement passif, filtrer sur les passivables
    if session["cible_voix"] == ["passif"]:
        raw_verbes = [v for v in raw_verbes if v in VERBES_PASSIVABLES]

    if not raw_verbes:
        flash("Aucun verbe passivable sélectionné. Choisissez d'autres verbes ou activez la voix active.")
        return redirect("/cible")

    # Stocker en session seulement si la liste est courte (≤ 30 verbes)
    # Pour les sélections larges, on passe par le store mémoire _QUESTIONS_STORE
    if len(raw_verbes) <= 30:
        session["cible_verbes"] = raw_verbes
    else:
        session["cible_verbes"] = []  # sera lu depuis le store via questions_cibles_id

    raw_temps = request.form.getlist("temps")
    session["cible_temps"] = []
    for item in raw_temps:
        try:
            mode, temps = item.split("|")
            session["cible_temps"].append((mode, temps))
        except Exception:
            continue

    if not session["cible_modes"] or not session["cible_temps"] or not session["cible_personnes"] or not raw_verbes:
        flash("Veuillez sélectionner au moins un mode, un temps, une personne et un verbe.")
        return redirect("/cible")

    session["questions_cibles"] = []
    questions_cibles = []

    # Déterminer la base selon la voix
    voix = session["cible_voix"]
    if voix == ["passif"]:
        base = PASSIF
    elif voix == ["actif"]:
        base = ACTIF
    else:
        base = {**ACTIF, **PASSIF}  # union logique

    for verbe in raw_verbes:
        if verbe not in base:
            continue
        modes_dict = base[verbe]
        for mode, temps in session["cible_temps"]:
            if mode not in modes_dict:
                continue
            temps_dict = modes_dict[mode]
            if temps not in temps_dict:
                continue
            formes = temps_dict[temps]
            if not formes:
                continue
            for personne in session["cible_personnes"]:
                # Vérifier que la personne existe dans les formes
                mapping = ["je", "tu", "il", "nous", "vous", "ils"]
                idx = mapping.index({
                    "1s": "je", "2s": "tu", "3s": "il",
                    "1p": "nous", "2p": "vous", "3p": "ils"
                }[personne])
                if idx >= len(formes):
                    continue
                questions_cibles.append((verbe, mode, temps, personne))

    random.shuffle(questions_cibles)

    # Stocker côté serveur (pas dans le cookie — trop volumineux)
    qid = str(uuid.uuid4())
    _QUESTIONS_STORE[qid] = questions_cibles
    session["questions_cibles_id"] = qid
    session["questions_cibles"] = []  # vider pour éviter tout résidu

    return redirect("/quiz")

# ============================================================
# ROUTE DU QUIZ
# ============================================================

@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    # Initialisation depuis l'accueil
    if request.method == "GET" and "mode" in request.args:
        mode = request.args.get("mode")

        if mode == "revision":
            # Sauvegarder les erreurs AVANT le clear, puis les convertir en file de révision
            erreurs_a_retravailler = session.get("erreurs", [])
            user_id = session.get("_user_id")
            session.clear()
            if user_id:
                session["_user_id"] = user_id
            session["mode"] = mode
            session["score"] = 0
            session["total"] = 0
            session["start"] = time.time()
            session["erreurs"] = []  # bilan vierge pour cette session de révision
            # Convertir les dicts d'erreurs en tuples (verbe, mode, temps, sujet, donne, attendu)
            session["erreurs_revision"] = [
                (e["verbe"], e["mode"], e["temps"], e["personne"], e["donne"], e["attendu"])
                for e in erreurs_a_retravailler
            ]
        else:
            user_id = session.get("_user_id")
            session.clear()
            if user_id:
                session["_user_id"] = user_id
            session["mode"] = mode
            session["score"] = 0
            session["total"] = 0
            session["start"] = time.time()
            session["erreurs"] = []

            if mode == "evaluation":
                session["timer"] = 5 * 60
                session["questions_restantes"] = 10

    mode = session.get("mode", "entrainement")
    session.setdefault("score", 0)
    session.setdefault("total", 0)
    session.setdefault("erreurs", [])
    session.setdefault("start", time.time())

    if mode == "evaluation":
        session.setdefault("timer", 5 * 60)
        session.setdefault("questions_restantes", 10)

    if mode == "evaluation":
        if time.time() - session["start"] >= session["timer"]:
            return redirect("/fin")

    feedback = None

    # Réception réponse
    if request.method == "POST":
        rep = request.form["reponse"].strip().lower()

        if rep == "chateaubriand":
            return redirect("https://youtu.be/2Taq4fOVQ60")

        bonne = session["bonne"]
        session["total"] += 1
        est_correct = (rep == bonne.lower())

        if not est_correct:
            session["erreurs"].append({
                "verbe": session["verbe"],
                "mode": session["mode_verbe"],
                "temps": session["temps"],
                "personne": session["sujet"],
                "voix": session.get("voix_question", "active"),
                "attendu": bonne,
                "donne": rep
            })
        else:
            session["score"] += 1

        # Enregistrer la réponse en base pour les utilisateurs connectés —
        # via le système compact (agrégats + historique borné) plutôt que
        # l'ancien stockage à plat, et déclencher la gamification.
        session["nouveaux_badges"] = []
        session["level_up"] = False

        if current_user.is_authenticated:
            from repetition import (
                enregistrer_reponse, appliquer_gain_xp, mettre_a_jour_streak,
                verifier_nouveaux_badges,
            )
            try:
                enregistrer_reponse(
                    db, current_user,
                    verbe=session["verbe"], mode=session["mode_verbe"],
                    temps=session["temps"], correct=est_correct,
                )

                # XP : bonus si la combinaison était difficile pour cet utilisateur
                # (réutilise l'agrégat qu'on vient de mettre à jour)
                from models import AgregatVerbe
                agg = AgregatVerbe.query.filter_by(
                    user_id=current_user.id, verbe=session["verbe"],
                    mode=session["mode_verbe"], temps=session["temps"]
                ).first()
                etait_difficile = bool(agg and agg.nb_total > 1 and agg.taux < 60)
                level_up = appliquer_gain_xp(current_user, est_correct, etait_difficile)

                # Streak : une seule mise à jour par session (pas par question)
                if not session.get("streak_deja_compte"):
                    mettre_a_jour_streak(current_user)
                    session["streak_deja_compte"] = True

                # Bonnes réponses consécutives, suivies en session (compteur léger)
                if est_correct:
                    session["consecutives"] = session.get("consecutives", 0) + 1
                else:
                    session["consecutives"] = 0

                stats_rapides = calculer_stats_user(current_user)
                nouveaux = verifier_nouveaux_badges(
                    current_user,
                    total_questions=stats_rapides["total"],
                    bonnes_consecutives=session["consecutives"],
                    nb_verbes_distincts=stats_rapides["nb_verbes_distincts"],
                )

                db.session.commit()

                session["nouveaux_badges"] = nouveaux
                session["level_up"] = level_up

            except Exception as e:
                # On ne bloque jamais le quiz si l'enregistrement échoue
                # (ex: base temporairement indisponible).
                print(f"[ATTENTION] Échec enregistrement réponse en base : {e}", flush=True)
                db.session.rollback()

        if mode == "evaluation":
            session["questions_restantes"] -= 1
            if session["questions_restantes"] <= 0:
                return redirect("/fin")
        elif mode == "revision":
            if not session.get("erreurs_revision"):
                return redirect("/fin")
        else:
            feedback = "✔️ Correct" if rep == bonne.lower() else f"❌ Faux. Réponse attendue : {bonne}"

    # Nouvelle question
    if mode == "revision":
        if not session.get("erreurs_revision"):
            return redirect("/fin")

        verbe, mode_v, temps, sujet, rep_faute, bonne = session["erreurs_revision"].pop(0)
        question = f"Conjugue : {verbe} — {mode_v} — {temps} — {sujet}"
        voix_question = session.get("voix_question", "active")

    elif mode == "cible":
        # Sélection de la base actif/passif
        voix = session.get("cible_voix", ["actif"])

        if "actif" in voix and "passif" in voix:
            base = random.choice([ACTIF, PASSIF])
            voix_question = "passive" if base is PASSIF else "active"
        elif "passif" in voix:
            base = PASSIF
            voix_question = "passive"
        else:
            base = ACTIF
            voix_question = "active"

        # Lire les verbes depuis le store mémoire (pas depuis la session — trop volumineux)
        qid = session.get("questions_cibles_id")
        verbes_cibles = None
        if qid and qid in _QUESTIONS_STORE:
            # Extraire la liste unique des verbes depuis les questions stockées
            verbes_cibles = list(dict.fromkeys(q[0] for q in _QUESTIONS_STORE[qid]))

        verbe, mode_v, temps, sujet, bonne, question = generer_question(
            modes=session.get("cible_modes"),
            temps=session.get("cible_temps"),
            personnes=session.get("cible_personnes"),
            verbes=verbes_cibles or session.get("cible_verbes"),
            base=base,
            voix_question=voix_question
        )

    else:
        # Pour les modes entraînement et évaluation : choisir la voix au hasard
        base = random.choice([ACTIF, PASSIF])
        voix_question = "passive" if base is PASSIF else "active"

        # Répétition espacée : uniquement en mode entraînement, pour les
        # utilisateurs connectés disposant d'un historique. L'évaluation
        # reste un tirage équitable (c'est un contrôle, pas une révision).
        poids_verbes_agreges = None
        if mode == "entrainement" and current_user.is_authenticated:
            from models import AgregatVerbe
            from repetition import calculer_poids_depuis_agregats, agreger_poids_par_verbe
            try:
                agregats = AgregatVerbe.query.filter_by(user_id=current_user.id).all()
                poids_triplets = calculer_poids_depuis_agregats(agregats)
                poids_verbes_agreges = agreger_poids_par_verbe(poids_triplets)
            except Exception as e:
                print(f"[ATTENTION] Échec calcul répétition espacée : {e}", flush=True)

        verbe, mode_v, temps, sujet, bonne, question = generer_question(
            base=base,
            voix_question=voix_question,
            poids_verbes=poids_verbes_agreges
        )

    # Stockage
    session["verbe"] = verbe
    session["mode_verbe"] = mode_v
    session["temps"] = temps
    session["sujet"] = sujet
    session["bonne"] = bonne
    session["voix_question"] = voix_question

    temps_restant = None
    if mode == "evaluation":
        temps_restant = int(session["timer"] - (time.time() - session["start"]))

    # Récupérer puis vider les indicateurs de gamification pour qu'ils ne
    # s'affichent qu'une seule fois (sur la page qui suit la réponse).
    nouveaux_badges = session.pop("nouveaux_badges", [])
    level_up = session.pop("level_up", False)

    from repetition import BADGES
    badges_info = [BADGES[code] for code in nouveaux_badges if code in BADGES]

    return render_template(
        "quiz.html",
        question=question,
        feedback=feedback,
        mode=mode,
        temps_restant=temps_restant,
        nouveaux_badges=badges_info,
        level_up=level_up,
        user_niveau=current_user.niveau if current_user.is_authenticated else None,
    )

# ============================================================
# ROUTE DU BILAN
# ============================================================
@app.route("/fin")
def fin():
    end = time.time()
    # sécuriser l'existence des clés dans session
    start = session.get("start", end)
    duree = round(end - start, 1)

    total = int(session.get("total", 0))
    score = int(session.get("score", 0))
    taux = round(score / total * 100, 1) if total else 0
    temps_moyen = round(duree / total, 2) if total else 0
    erreurs = session.get("erreurs", [])

    # Par défaut, analyse vide (structure stable)
    analyse = {
        "verbes": [],
        "modes": [],
        "modes_complet": {},
        "temps": [],
        "temps_complet": {},
        "voix": {"active": 0, "passive": 0},
        "suggestion": None
    }

    if erreurs:
        # --- STATS ---
        stats_verbes = {}
        stats_modes = {}
        stats_temps = {}
        stats_voix = {"active": 0, "passive": 0}

        for e in erreurs:
            verbe = e.get("verbe")
            mode = e.get("mode")
            temps = e.get("temps")
            voix = e.get("voix")

            if verbe:
                stats_verbes[verbe] = stats_verbes.get(verbe, 0) + 1
            if mode:
                stats_modes[mode] = stats_modes.get(mode, 0) + 1
            if temps:
                stats_temps[temps] = stats_temps.get(temps, 0) + 1
            if voix in stats_voix:
                stats_voix[voix] += 1

        def top(d):
            return sorted(d.items(), key=lambda x: x[1], reverse=True)[:3]

        top_verbes = top(stats_verbes)
        top_modes = top(stats_modes)
        top_temps = top(stats_temps)

        suggestion = None
        if top_verbes and top_modes and top_temps:
            suggestion = f"{top_verbes[0][0]} — {top_modes[0][0]} — {top_temps[0][0]}"

        analyse = {
            "verbes": top_verbes,
            "modes": top_modes,
            "modes_complet": {k: int(v or 0) for k, v in stats_modes.items()},
            "temps": top_temps,
            "temps_complet": {k: int(v or 0) for k, v in stats_temps.items()},
            "voix": {"active": int(stats_voix.get("active", 0)), "passive": int(stats_voix.get("passive", 0))},
            "suggestion": suggestion
        }

        # garantir clés principales
        for m in ["indicatif", "conditionnel", "subjonctif", "impératif"]:
            analyse["modes_complet"].setdefault(m, 0)

        analyse["modes_sorted"] = sorted(
            analyse["modes_complet"].items(),
            key=lambda x: x[1],
            reverse=True
        )

    # Calculs sûrs pour la template
    voix = analyse.get("voix", {"active": 0, "passive": 0})
    active_voix = int(voix.get("active", 0))
    passive_voix = int(voix.get("passive", 0))
    total_voix = active_voix + passive_voix

    erreurs_voix = {
        "active": active_voix,
        "passive": passive_voix
    }

    return render_template(
        "fin.html",
        total=total,
        score=score,
        taux=taux,
        duree=duree,
        temps_moyen=temps_moyen,
        erreurs=erreurs,
        analyse=analyse,
        total_voix=total_voix,
        erreurs_voix=erreurs_voix,
        voix={"active": active_voix, "passive": passive_voix}
    )

# ============================================================
# PAGES SEO — /conjugaison/<verbe>/<mode>/<temps>
# ============================================================

# Mapping clés internes → labels affichés à l'utilisateur
LABELS_MODES = {
    "indicatif":    "Indicatif",
    "conditionnel": "Conditionnel",
    "subjonctif":   "Subjonctif",
    "impératif":    "Impératif",
}
LABELS_TEMPS = {
    "présent":           "Présent",
    "passé composé":     "Passé composé",
    "imparfait":         "Imparfait",
    "plus-que-parfait":  "Plus-que-parfait",
    "passé simple":      "Passé simple",
    "passé antérieur":   "Passé antérieur",
    "futur simple":      "Futur simple",
    "futur antérieur":   "Futur antérieur",
    "passé 1":           "Passé (1re forme)",
    "passé 2":           "Passé (2e forme)",
    "passé":             "Passé",
}

# Pronoms affichés dans le tableau (indicatif/conditionnel/subjonctif)
PRONOMS_TABLEAU = ["1re pers. sing.", "2e pers. sing.", "3e pers. sing.",
                   "1re pers. plur.", "2e pers. plur.", "3e pers. plur."]
PRONOMS_IMPERATIF = ["2e pers. sing.", "1re pers. plur.", "2e pers. plur."]

@app.route("/conjugaison/<verbe>/<mode>/<temps>")
@limiter.exempt
def page_conjugaison(verbe, mode, temps):
    # Vérifier que le verbe existe
    if verbe not in ACTIF:
        return render_template("404.html"), 404

    modes_verbe = ACTIF[verbe]
    if mode not in modes_verbe or temps not in modes_verbe[mode]:
        return render_template("404.html"), 404

    formes = modes_verbe[mode][temps]

    # Cas défectif : impératif vide pour falloir, pleuvoir, seoir... → pas de page utile
    if not formes:
        return render_template("404.html"), 404

    est_imperatif = (mode == "impératif")
    pronoms = PRONOMS_IMPERATIF if est_imperatif else PRONOMS_TABLEAU

    # Construire les autres temps du même mode (pour la navigation)
    autres_temps = [
        {"temps": t, "url": f"/conjugaison/{verbe}/{mode}/{t}"}
        for t in modes_verbe[mode].keys()
        if t != temps
    ]
    # Construire les autres modes (pour la navigation)
    autres_modes = [
        {"mode": m, "label": LABELS_MODES.get(m, m),
         "temps_defaut": list(modes_verbe[m].keys())[0],
         "url": f"/conjugaison/{verbe}/{m}/{list(modes_verbe[m].keys())[0]}"}
        for m in modes_verbe.keys()
        if m != mode
    ]

    label_mode  = LABELS_MODES.get(mode, mode.capitalize())
    label_temps = LABELS_TEMPS.get(temps, temps.capitalize())

    return render_template(
        "conjugaison.html",
        verbe=verbe,
        mode=mode,
        temps=temps,
        formes=formes,
        pronoms=pronoms,
        est_imperatif=est_imperatif,
        label_mode=label_mode,
        label_temps=label_temps,
        autres_temps=autres_temps,
        autres_modes=autres_modes,
        LABELS_TEMPS=LABELS_TEMPS,
        exemple=EXEMPLES_PHRASES.get((verbe, mode, temps)),
        famille=calculer_famille_verbe(verbe, ACTIF),
    )


@app.route("/conjugaisons")
@limiter.exempt
def page_conjugaisons():
    """Page de recherche et exploration de tous les verbes."""

    # Classifier les verbes par groupe
    g1, g2, g3 = [], [], []
    for v in sorted(ACTIF.keys()):
        imparfait = ACTIF[v].get("indicatif", {}).get("imparfait", [])
        est_g2 = any("issais" in f or "issait" in f or "issions" in f for f in imparfait)
        if v.endswith("er"):
            g1.append(v)
        elif v.endswith("ir") and est_g2:
            g2.append(v)
        else:
            g3.append(v)

    # Verbes essentiels bac
    top_verbes = ["être", "avoir", "faire", "aller", "vouloir", "pouvoir",
                  "savoir", "prendre", "venir", "voir", "partir", "mettre",
                  "dire", "croire", "écrire", "lire", "vivre", "connaître"]

    # Tous les verbes triés pour le datalist
    tous_verbes = sorted(ACTIF.keys())

    return render_template(
        "conjugaisons.html",
        g1=g1, g2=g2, g3=g3,
        top_verbes=[v for v in top_verbes if v in ACTIF],
        tous_verbes=tous_verbes,
        total=len(ACTIF),
    )


@app.route("/conjugaison/<verbe>")
@limiter.exempt
def page_verbe(verbe):
    """Page centrale d'un verbe — tableau récapitulatif de tous les modes."""
    if verbe not in ACTIF:
        return render_template("404.html"), 404

    modes_verbe = ACTIF[verbe]

    # Construire un résumé : pour chaque mode, afficher le présent (ou premier temps dispo)
    resume_modes = {}
    for mode, temps_dict in modes_verbe.items():
        temps_prefere = "présent" if "présent" in temps_dict else list(temps_dict.keys())[0]
        resume_modes[mode] = {
            "label": LABELS_MODES.get(mode, mode.capitalize()),
            "temps": temps_prefere,
            "label_temps": LABELS_TEMPS.get(temps_prefere, temps_prefere.capitalize()),
            "formes": temps_dict[temps_prefere],
            "tous_temps": [
                {"temps": t, "label": LABELS_TEMPS.get(t, t.capitalize()),
                 "url": f"/conjugaison/{verbe}/{mode}/{t}"}
                for t in temps_dict.keys()
            ],
        }

    # Verbes de la même famille (préfixés)
    racine = verbe
    for prefixe in ("re", "dé", "pré", "sur", "sous", "con", "pro", "dis"):
        if verbe.startswith(prefixe) and len(verbe) > len(prefixe) + 2:
            racine = verbe[len(prefixe):]
            break
    famille = sorted([v for v in ACTIF if v != verbe and
                      (v.endswith(racine) or racine.endswith(v.lstrip("se ").lstrip("s'"))
                       or (len(racine) > 4 and racine in v))])[:6]

    # Verbes fréquents du même mode principal
    mode_principal = list(modes_verbe.keys())[0]
    verbes_meme_mode = [v for v in ["être", "avoir", "faire", "aller", "vouloir",
                                     "pouvoir", "prendre", "venir", "voir", "savoir"]
                        if v != verbe and v in ACTIF][:6]

    return render_template(
        "verbe.html",
        verbe=verbe,
        resume_modes=resume_modes,
        famille=famille,
        verbes_meme_mode=verbes_meme_mode,
        LABELS_MODES=LABELS_MODES,
        LABELS_TEMPS=LABELS_TEMPS,
        total=len(ACTIF),
    )


@app.route("/sitemap.xml")
@limiter.exempt
def sitemap():
    """Sitemap XML généré dynamiquement — à soumettre à Google Search Console."""
    from flask import Response
    base = "https://hirondelleconjugaison.onrender.com"
    urls = []
    for verbe, modes_verbe in sorted(ACTIF.items()):
        for mode, temps_dict in modes_verbe.items():
            for temps, formes in temps_dict.items():
                # Exclure les cases vides (impératif des verbes défectifs : falloir, pleuvoir...)
                # qui généraient une page sans contenu et une erreur 500 au crawl.
                if formes:
                    urls.append(f"{base}/conjugaison/{verbe}/{mode}/{temps}")

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        xml_lines.append(f"  <url><loc>{url}</loc></url>")
    xml_lines.append("</urlset>")

    return Response("\n".join(xml_lines), mimetype="application/xml")


# ============================================================
# LANCEMENT LOCAL
# ============================================================

if __name__ == "__main__":
    # Ce bloc ne s'exécute pas sur Render (Gunicorn lance directement `app`).
    # Start Command Render recommandée : gunicorn main:app
    app.run(host="0.0.0.0", port=10000)

# ============================================================
# DICTIONNAIRE D'EXEMPLES DE PHRASES PAR VERBE + MODE + TEMPS
# ============================================================
# Couvre les verbes et combinaisons les plus consultés — enrichi
# progressivement. Les pages sans exemple affichent juste le tableau.
EXEMPLES_PHRASES = {
    ("faire", "indicatif", "présent"):      "Il <strong>fait</strong> ses devoirs chaque soir.",
    ("faire", "indicatif", "imparfait"):     "Elle <strong>faisait</strong> du sport tous les matins.",
    ("faire", "indicatif", "futur simple"):  "Nous <strong>ferons</strong> une pause dans dix minutes.",
    ("faire", "subjonctif", "présent"):      "Il faut que tu <strong>fasses</strong> attention.",
    ("faire", "conditionnel", "présent"):    "Je <strong>ferais</strong> ce voyage si j'avais le temps.",
    ("être", "indicatif", "présent"):        "Nous <strong>sommes</strong> prêts à commencer.",
    ("être", "indicatif", "imparfait"):      "Il <strong>était</strong> fatigué après la journée.",
    ("être", "indicatif", "futur simple"):   "Vous <strong>serez</strong> là à quelle heure ?",
    ("être", "subjonctif", "présent"):       "Je veux qu'il <strong>soit</strong> à l'heure.",
    ("être", "conditionnel", "présent"):     "Ce <strong>serait</strong> une bonne idée.",
    ("avoir", "indicatif", "présent"):       "J'<strong>ai</strong> rendez-vous à 14h.",
    ("avoir", "indicatif", "imparfait"):     "Elle <strong>avait</strong> les yeux bleus.",
    ("avoir", "indicatif", "futur simple"):  "Tu <strong>auras</strong> les résultats demain.",
    ("avoir", "subjonctif", "présent"):      "Il faut que vous <strong>ayez</strong> votre passeport.",
    ("avoir", "conditionnel", "présent"):    "Nous <strong>aurions</strong> besoin de plus de temps.",
    ("aller", "indicatif", "présent"):       "Tu <strong>vas</strong> à l'école à pied ?",
    ("aller", "indicatif", "futur simple"):  "Ils <strong>iront</strong> en vacances cet été.",
    ("aller", "subjonctif", "présent"):      "Il faut que tu <strong>ailles</strong> chez le médecin.",
    ("pouvoir", "indicatif", "présent"):     "Est-ce que je <strong>peux</strong> sortir ce soir ?",
    ("pouvoir", "subjonctif", "présent"):    "Je ne pense pas qu'il <strong>puisse</strong> venir.",
    ("pouvoir", "conditionnel", "présent"):  "Tu <strong>pourrais</strong> m'aider, s'il te plaît ?",
    ("vouloir", "indicatif", "présent"):     "Elle <strong>veut</strong> apprendre le piano.",
    ("vouloir", "subjonctif", "présent"):    "Je ne pense pas qu'il <strong>veuille</strong> refuser.",
    ("vouloir", "conditionnel", "présent"):  "Je <strong>voudrais</strong> un café, s'il vous plaît.",
    ("savoir", "indicatif", "présent"):      "Je ne <strong>sais</strong> pas encore décider.",
    ("savoir", "subjonctif", "présent"):     "Je doute qu'il <strong>sache</strong> la réponse.",
    ("prendre", "indicatif", "présent"):     "Il <strong>prend</strong> le bus tous les matins.",
    ("prendre", "indicatif", "imparfait"):   "Elle <strong>prenait</strong> toujours le temps d'écouter.",
    ("prendre", "subjonctif", "présent"):    "Il faut que tu <strong>prennes</strong> ton manteau.",
    ("venir", "indicatif", "présent"):       "Tu <strong>viens</strong> avec nous ce soir ?",
    ("venir", "indicatif", "futur simple"):  "Elle <strong>viendra</strong> dès qu'elle pourra.",
    ("venir", "subjonctif", "présent"):      "J'aimerais qu'il <strong>vienne</strong> nous voir.",
    ("voir", "indicatif", "présent"):        "Je <strong>vois</strong> ce que tu veux dire.",
    ("voir", "subjonctif", "présent"):       "Je ne pense pas qu'elle <strong>voie</strong> le problème.",
    ("dire", "indicatif", "présent"):        "Qu'est-ce que tu <strong>dis</strong> ?",
    ("dire", "subjonctif", "présent"):       "Il faut que vous leur <strong>disiez</strong> la vérité.",
    ("mettre", "indicatif", "présent"):      "Je <strong>mets</strong> mon manteau car il fait froid.",
    ("mettre", "subjonctif", "présent"):     "Il faut que tu <strong>mettes</strong> ta ceinture.",
    ("partir", "indicatif", "présent"):      "Le train <strong>part</strong> dans cinq minutes.",
    ("partir", "indicatif", "futur simple"): "Nous <strong>partirons</strong> très tôt demain matin.",
    ("sortir", "indicatif", "présent"):      "Elle <strong>sort</strong> avec ses amis ce week-end.",
    ("finir", "indicatif", "présent"):       "Je <strong>finis</strong> mon travail à 18h.",
    ("finir", "indicatif", "futur simple"):  "Il <strong>finira</strong> avant la fin de la semaine.",
    ("choisir", "indicatif", "présent"):     "Tu <strong>choisis</strong> entre les deux options.",
    ("devoir", "indicatif", "présent"):      "Tu <strong>dois</strong> rendre ce devoir demain.",
    ("devoir", "conditionnel", "présent"):   "Tu <strong>devrais</strong> réviser ce soir.",
    ("croire", "indicatif", "présent"):      "Je <strong>crois</strong> qu'il a raison.",
    ("croire", "subjonctif", "présent"):     "Je ne <strong>crois</strong> pas qu'il <strong>croie</strong> une seule parole.",
    ("recevoir", "indicatif", "présent"):    "Elle <strong>reçoit</strong> beaucoup de courrier.",
    ("ouvrir", "indicatif", "présent"):      "Il <strong>ouvre</strong> la fenêtre pour aérer.",
    ("écrire", "indicatif", "présent"):      "Elle <strong>écrit</strong> un roman depuis deux ans.",
    ("lire", "indicatif", "présent"):        "Je <strong>lis</strong> un livre par semaine.",
    ("connaître", "indicatif", "présent"):   "Je <strong>connais</strong> bien ce quartier.",
    ("vivre", "indicatif", "présent"):       "Ils <strong>vivent</strong> à la campagne depuis dix ans.",
}


# ============================================================
# FAMILLES DE VERBES (maillage interne pour le SEO)
# ============================================================
def calculer_famille_verbe(verbe, actif_dict):
    """
    Retourne la liste des verbes de la même famille morphologique
    (même radical, préfixé ou suffixé). Utilisé pour les liens internes
    sur les pages de conjugaison individuelles.
    """
    prefixes = ['re', 'dé', 'é', 'sur', 'sous', 'contre', 'entre', 'in', 'dis', 'par']
    famille = set()

    # Chercher des verbes dont ce verbe est le radical
    for p in prefixes:
        candidat = p + verbe
        if candidat in actif_dict and candidat != verbe:
            famille.add(candidat)

    # Chercher le radical de ce verbe (enlever un préfixe courant)
    for p in prefixes:
        if verbe.startswith(p) and len(verbe) > len(p) + 2:
            base = verbe[len(p):]
            if base in actif_dict:
                famille.add(base)
            # Chercher d'autres dérivés du même radical
            for p2 in prefixes:
                candidat = p2 + base
                if candidat in actif_dict and candidat != verbe:
                    famille.add(candidat)

    return sorted(list(famille))[:6]  # max 6 liens pour ne pas surcharger la page
