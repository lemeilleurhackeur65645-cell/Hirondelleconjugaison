"""
Répétition espacée — Hirondelle Conjugaison.

Principe simplifié (pas un vrai SM-2/Anki, mais suffisant pour un usage réel) :
- Chaque combinaison (verbe, mode, temps) a un "score de maîtrise" entre 0 et 1,
  calculé depuis l'historique récent de l'utilisateur.
- Score bas (raté récemment) → poids élevé → revient plus souvent dans le quiz.
- Score haut (maîtrisé) → poids faible mais jamais nul → rappel d'entretien occasionnel.
- Les combinaisons jamais vues ont un poids neutre (ni privilégiées ni pénalisées).

Ne s'applique qu'aux utilisateurs connectés : les visiteurs anonymes n'ont pas
d'historique en base, donc le tirage reste uniformément aléatoire pour eux.
"""

from datetime import datetime, timezone
from collections import defaultdict

# Poids minimum et maximum — bornes pour éviter qu'une combinaison
# disparaisse complètement (poids 0) ou écrase tout le reste (poids infini).
POIDS_MIN = 0.15
POIDS_MAX = 3.0
POIDS_NEUTRE = 1.0

# Demi-vie en jours : une erreur d'il y a 14 jours compte moitié moins
# qu'une erreur d'aujourd'hui dans le calcul du score de maîtrise.
DEMI_VIE_JOURS = 14


def _fraicheur(date_reponse):
    """Retourne un facteur de fraîcheur entre 0 (très ancien) et 1 (à l'instant)."""
    now = datetime.now(timezone.utc)
    if date_reponse.tzinfo is None:
        date_reponse = date_reponse.replace(tzinfo=timezone.utc)
    age_jours = max((now - date_reponse).total_seconds() / 86400, 0)
    return 0.5 ** (age_jours / DEMI_VIE_JOURS)


def calculer_poids(reponses):
    """
    reponses : liste d'objets ReponseQuiz (verbe, mode, temps, correct, date)

    Retourne un dict { (verbe, mode, temps): poids } utilisable pour
    pondérer le tirage aléatoire des questions.
    """
    if not reponses:
        return {}

    # Pour chaque combinaison : somme pondérée des réussites et des échecs,
    # pondération par fraîcheur (un échec récent compte plus qu'un ancien).
    stats = defaultdict(lambda: {"reussite": 0.0, "echec": 0.0})

    for r in reponses:
        cle = (r.verbe, r.mode, r.temps)
        f = _fraicheur(r.date)
        if r.correct:
            stats[cle]["reussite"] += f
        else:
            stats[cle]["echec"] += f * 1.5  # un échec pèse un peu plus qu'une réussite équivalente

    poids = {}
    for cle, s in stats.items():
        total = s["reussite"] + s["echec"]
        if total == 0:
            continue
        # score_maitrise proche de 1 = bien maîtrisé, proche de 0 = à revoir
        score_maitrise = s["reussite"] / total
        # poids inversement proportionnel à la maîtrise, borné
        poids_brut = POIDS_MAX - (score_maitrise * (POIDS_MAX - POIDS_MIN))
        poids[cle] = max(POIDS_MIN, min(POIDS_MAX, poids_brut))

    return poids


def tirage_pondere(candidats, poids_par_cle, cle_fn):
    """
    candidats : liste d'éléments à tirer au sort (verbes, modes ou temps)
    poids_par_cle : dict {clé: poids} issu de calculer_poids()
    cle_fn : fonction qui construit la clé de lookup à partir d'un candidat

    Retourne un seul élément tiré, en favorisant ceux qui ont un poids élevé.
    Les candidats absents de poids_par_cle reçoivent le poids neutre.
    """
    import random

    if not candidats:
        return None

    poids_liste = [poids_par_cle.get(cle_fn(c), POIDS_NEUTRE) for c in candidats]
    return random.choices(candidats, weights=poids_liste, k=1)[0]
