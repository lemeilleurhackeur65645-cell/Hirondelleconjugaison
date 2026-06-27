"""
Répétition espacée + gamification — Hirondelle Conjugaison.

Architecture mémoire-consciente :
- Le calcul des poids de répétition espacée se base sur AgregatVerbe (compact,
  une ligne par combinaison déjà vue) plutôt que sur l'historique brut.
- ReponseRecente n'est consultée que pour la fraîcheur fine et l'affichage
  "activité récente" — elle est bornée à MAX_HISTORIQUE_PAR_USER lignes.
"""

from datetime import datetime, timezone, date, timedelta

POIDS_MIN = 0.15
POIDS_MAX = 3.0
POIDS_NEUTRE = 1.0
DEMI_VIE_JOURS = 14


def _fraicheur(date_reponse):
    """Facteur de fraîcheur entre 0 (ancien) et 1 (à l'instant)."""
    now = datetime.now(timezone.utc)
    if date_reponse.tzinfo is None:
        date_reponse = date_reponse.replace(tzinfo=timezone.utc)
    age_jours = max((now - date_reponse).total_seconds() / 86400, 0)
    return 0.5 ** (age_jours / DEMI_VIE_JOURS)


def calculer_poids_depuis_agregats(agregats):
    """
    agregats : liste d'objets AgregatVerbe (déjà compacts : 1 ligne / combinaison)

    Retourne { (verbe, mode, temps): poids }. Le calcul utilise le taux de
    réussite cumulé pondéré par la fraîcheur de la dernière réponse — pas
    besoin de relire l'historique détaillé pour ça.
    """
    poids = {}
    for a in agregats:
        if a.nb_total == 0:
            continue
        score_maitrise = a.nb_correct / a.nb_total
        f = _fraicheur(a.derniere_date)
        # Une combinaison maîtrisée mais jamais revue récemment remonte
        # légèrement en priorité (rappel d'entretien), via le facteur (1 - f*0.3).
        poids_brut = (POIDS_MAX - (score_maitrise * (POIDS_MAX - POIDS_MIN))) * (1 - f * 0.15) + f * 0.15
        cle = (a.verbe, a.mode, a.temps)
        poids[cle] = max(POIDS_MIN, min(POIDS_MAX, poids_brut))
    return poids


def agreger_poids_par_verbe(poids_triplets):
    """{(verbe,mode,temps): poids} -> {verbe: poids_moyen}"""
    if not poids_triplets:
        return {}
    from collections import defaultdict
    sommes = defaultdict(lambda: [0.0, 0])
    for (verbe, _mode, _temps), p in poids_triplets.items():
        sommes[verbe][0] += p
        sommes[verbe][1] += 1
    return {v: total / n for v, (total, n) in sommes.items()}


def enregistrer_reponse(db, user, verbe, mode, temps, correct):
    """
    Point d'entrée unique appelé à chaque réponse au quiz pour un utilisateur
    connecté. Met à jour l'agrégat compact (upsert), ajoute une ligne bornée
    à l'historique récent, et purge le surplus si nécessaire.

    C'est volontairement une seule fonction : ça centralise toute la logique
    d'écriture mémoire-consciente en un point testable, plutôt que de la
    disperser dans la route Flask.
    """
    from models import AgregatVerbe, ReponseRecente, MAX_HISTORIQUE_PAR_USER

    # 1) Upsert de l'agrégat compact
    agg = AgregatVerbe.query.filter_by(user_id=user.id, verbe=verbe, mode=mode, temps=temps).first()
    if agg is None:
        agg = AgregatVerbe(user_id=user.id, verbe=verbe, mode=mode, temps=temps, nb_total=0, nb_correct=0)
        db.session.add(agg)
    agg.nb_total += 1
    if correct:
        agg.nb_correct += 1
    agg.derniere_date = datetime.now(timezone.utc)

    # 2) Historique récent borné
    entry = ReponseRecente(user_id=user.id, verbe=verbe, mode=mode, temps=temps, correct=correct)
    db.session.add(entry)

    db.session.flush()  # nécessaire pour que le COUNT ci-dessous voie la nouvelle ligne

    # 3) Purge : ne garder que les MAX_HISTORIQUE_PAR_USER plus récentes.
    # On ne fait cette vérification qu'une fois sur ~20 pour ne pas payer
    # le coût d'un COUNT à chaque question — la table reste bornée à
    # MAX_HISTORIQUE_PAR_USER + 19 lignes dans le pire cas, ce qui est négligeable.
    import random
    if random.random() < 0.05:
        total = ReponseRecente.query.filter_by(user_id=user.id).count()
        if total > MAX_HISTORIQUE_PAR_USER:
            a_supprimer = (
                ReponseRecente.query
                .filter_by(user_id=user.id)
                .order_by(ReponseRecente.date.asc())
                .limit(total - MAX_HISTORIQUE_PAR_USER)
                .all()
            )
            for r in a_supprimer:
                db.session.delete(r)


# ============================================================
# GAMIFICATION
# ============================================================

# XP par bonne réponse, et bonus si la réponse était sur un verbe à faible
# maîtrise (encourage à réviser ses points faibles plutôt qu'à répéter
# uniquement ce qu'on maîtrise déjà).
XP_BONNE_REPONSE = 10
XP_BONUS_DIFFICILE = 5

# Paliers de niveau : XP cumulé nécessaire pour chaque niveau (courbe simple,
# légèrement croissante — pas besoin d'un vrai modèle RPG pour cet usage).
def xp_requis_pour_niveau(niveau):
    return int(50 * (niveau ** 1.5))


BADGES = {
    "premiers_pas":   {"label": "Premiers pas",      "icone": "🌱", "desc": "Premier quiz terminé"},
    "serie_3":        {"label": "Sur la lancée",      "icone": "🔥", "desc": "3 jours de suite"},
    "serie_7":        {"label": "Semaine parfaite",   "icone": "⚡", "desc": "7 jours de suite"},
    "serie_30":       {"label": "Habitude ancrée",    "icone": "🏆", "desc": "30 jours de suite"},
    "cent_questions": {"label": "Centurion",          "icone": "💯", "desc": "100 questions répondues"},
    "mille_questions":{"label": "Marathonien",        "icone": "🎖️", "desc": "1000 questions répondues"},
    "sans_faute":     {"label": "Sans faute",         "icone": "✨", "desc": "10 bonnes réponses d'affilée"},
    "polyglotte":     {"label": "Polyglotte verbal",  "icone": "📚", "desc": "20 verbes différents travaillés"},
}


def appliquer_gain_xp(user, correct, etait_difficile=False):
    """Met à jour xp_total et niveau de l'utilisateur. Retourne True si level up."""
    if not correct:
        return False
    gain = XP_BONNE_REPONSE + (XP_BONUS_DIFFICILE if etait_difficile else 0)
    user.xp_total += gain

    level_up = False
    while user.xp_total >= xp_requis_pour_niveau(user.niveau + 1):
        user.niveau += 1
        level_up = True
    return level_up


def mettre_a_jour_streak(user):
    """
    À appeler une fois par session de quiz (pas à chaque question).
    Retourne True si le streak vient d'augmenter (nouvelle journée d'activité).
    """
    aujourd_hui = date.today()
    if user.derniere_session == aujourd_hui:
        return False  # déjà compté aujourd'hui

    if user.derniere_session == aujourd_hui - timedelta(days=1):
        user.streak_jours += 1
    else:
        user.streak_jours = 1  # streak cassé ou premier jour

    user.derniere_session = aujourd_hui
    user.streak_record = max(user.streak_record, user.streak_jours)
    return True


def verifier_nouveaux_badges(user, total_questions, bonnes_consecutives, nb_verbes_distincts):
    """Retourne la liste des codes de badges nouvellement débloqués."""
    nouveaux = []

    conditions = [
        ("premiers_pas", total_questions >= 1),
        ("serie_3", user.streak_jours >= 3),
        ("serie_7", user.streak_jours >= 7),
        ("serie_30", user.streak_jours >= 30),
        ("cent_questions", total_questions >= 100),
        ("mille_questions", total_questions >= 1000),
        ("sans_faute", bonnes_consecutives >= 10),
        ("polyglotte", nb_verbes_distincts >= 20),
    ]
    for code, condition in conditions:
        if condition and user.ajouter_badge(code):
            nouveaux.append(code)
    return nouveaux
