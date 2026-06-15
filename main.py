from flask import Flask, request, render_template, redirect, url_for, session, flash

import random
import time
import json
import os
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
# CORRECTION : clé secrète via variable d'environnement.
# Sur Render : définir SECRET_KEY dans Environment Variables.
# Le fallback "secret123" ne s'applique qu'en développement local.
app.secret_key = os.environ.get("SECRET_KEY", "secret123")

# ============================================================
# ROUTES DE BASE
# ============================================================

@app.route("/")
def index():
    session.clear()
    return render_template("index.html")

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
        verbes_passivables=VERBES_PASSIVABLES
    )

# ============================================================
# GÉNÉRATION D'UNE QUESTION
# ============================================================

def generer_question(modes=None, temps=None, personnes=None, verbes=None, base=None, voix_question="active", _depth=0):
    """
    base = ACTIF ou PASSIF selon la voix choisie.
    _depth : compteur interne pour éviter la récursion infinie.
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
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)
            verbe = random.choice(candidats_verbes)
        else:
            verbe = random.choice(list(local_conj.keys()))

        modes_dict = local_conj.get(verbe, {})
        if not modes_dict:
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

        # 2) Sélection du mode
        if modes:
            candidats_modes = [m for m in modes if m in modes_dict]
            if not candidats_modes:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)
            mode_v = random.choice(candidats_modes)
        else:
            mode_v = random.choice(list(modes_dict.keys()))

        temps_dict = modes_dict.get(mode_v, {})
        if not temps_dict:
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

        # 3) Sélection du temps
        if temps:
            candidats_temps = [t for (m, t) in temps if m == mode_v and t in temps_dict]
            if not candidats_temps:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)
            temps_sel = random.choice(candidats_temps)
        else:
            temps_sel = random.choice(list(temps_dict.keys()))

        formes = temps_dict.get(temps_sel, [])
        if not formes:
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

        # 4) Sélection de la personne
        mapping = ["je", "tu", "il", "nous", "vous", "ils"]

        if mode_v.lower() == "impératif":
            imperatif_personnes = ["tu", "nous", "vous"]

            if temps_sel not in ["présent", "passé"]:
                return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

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
                    return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

                sujet = random.choice(sujets_possibles)
                idx = mapping.index(sujet)

        if idx >= len(formes):
            return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

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
        return generer_question(modes, temps, personnes, verbes, base, voix_question, _depth + 1)

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
    session["cible_verbes"] = request.form.getlist("verbes")

    # VOIX (actif/passif)
    session["cible_voix"] = request.form.getlist("voix")

    # Dédupliquer en conservant l'ordre
    session["cible_verbes"] = list(dict.fromkeys(session["cible_verbes"]))

    # Si l'utilisateur a choisi uniquement le passif, ne garder que les verbes passivables
    if session["cible_voix"] == ["passif"]:
        session["cible_verbes"] = [v for v in session["cible_verbes"] if v in VERBES_PASSIVABLES]

    # Si après filtrage il n'y a plus de verbes, prévenir et renvoyer à la page
    if not session["cible_verbes"]:
        flash("Aucun verbe passivables sélectionné. Choisissez d'autres verbes ou activez la voix active.")
        return redirect("/cible")

    raw_temps = request.form.getlist("temps")
    session["cible_temps"] = []
    for item in raw_temps:
        try:
            mode, temps = item.split("|")
            session["cible_temps"].append((mode, temps))
        except Exception:
            continue

    if not session["cible_modes"] or not session["cible_temps"] or not session["cible_personnes"] or not session["cible_verbes"]:
        flash("Veuillez sélectionner au moins un mode, un temps, une personne et un verbe.")
        return redirect("/cible")

    session["questions_cibles"] = []

    # Déterminer la base selon la voix
    voix = session["cible_voix"]
    if voix == ["passif"]:
        base = PASSIF
    elif voix == ["actif"]:
        base = ACTIF
    else:
        base = {**ACTIF, **PASSIF}  # union logique

    for verbe in session["cible_verbes"]:
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
                session["questions_cibles"].append((verbe, mode, temps, personne))

    random.shuffle(session["questions_cibles"])
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
            session.clear()
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
            session.clear()
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

        if rep != bonne.lower():
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

        # CORRECTION : suppression de la vérification de cohérence par parsing de string.
        # La voix est maintenant portée directement par le flag booléen `base`,
        # déterminé avant l'appel. generer_question() reçoit la bonne base dès le départ.
        verbe, mode_v, temps, sujet, bonne, question = generer_question(
            modes=session.get("cible_modes"),
            temps=session.get("cible_temps"),
            personnes=session.get("cible_personnes"),
            verbes=session.get("cible_verbes"),
            base=base,
            voix_question=voix_question
        )

    else:
        # Pour les modes entraînement et évaluation : choisir la voix au hasard
        base = random.choice([ACTIF, PASSIF])
        voix_question = "passive" if base is PASSIF else "active"

        verbe, mode_v, temps, sujet, bonne, question = generer_question(
            base=base,
            voix_question=voix_question
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

    return render_template(
        "quiz.html",
        question=question,
        feedback=feedback,
        mode=mode,
        temps_restant=temps_restant
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
def page_conjugaison(verbe, mode, temps):
    # Vérifier que le verbe existe
    if verbe not in ACTIF:
        return render_template("404.html"), 404

    modes_verbe = ACTIF[verbe]
    if mode not in modes_verbe or temps not in modes_verbe[mode]:
        return render_template("404.html"), 404

    formes = modes_verbe[mode][temps]
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
    )


@app.route("/conjugaisons")
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
def sitemap():
    """Sitemap XML généré dynamiquement — à soumettre à Google Search Console."""
    from flask import Response
    base = "https://hirondelleconjugaison.onrender.com"
    urls = []
    for verbe, modes_verbe in sorted(ACTIF.items()):
        for mode, temps_dict in modes_verbe.items():
            for temps in temps_dict.keys():
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
