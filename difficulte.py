"""
Progression de difficulté — Hirondelle Conjugaison.

Le quiz suit une échelle de PALIERS, du plus simple au plus difficile.
Pour chaque mode, dans cet ordre : indicatif, conditionnel, impératif, subjonctif,
l'échelle compte trois paliers :
    1. « l'essentiel »      : verbes courants, temps de base
    2. « verbes difficiles » : verbes irréguliers ou piégeux, tous les temps
    3. « voix passive »      : les verbes passivables, tous les temps

- Joueur connecté : le palier découle de son niveau (donc il ne recule jamais,
  la progression est stable). Il peut choisir un palier plus bas avec le curseur.
- Visiteur sans compte : il règle lui-même le curseur (palier 1 par défaut).
- Pour consolider, une partie des questions (35 %) revient sur les paliers
  inférieurs en mode entraînement ; en mode évaluation, le tirage est
  équitable sur tous les paliers jusqu'au palier choisi.
"""
import random

ORDRE_MODES = ["indicatif", "conditionnel", "impératif", "subjonctif"]

TEMPS_BASE = {
    "indicatif": ["présent", "imparfait", "futur simple", "passé composé"],
    "conditionnel": ["présent"],
    "impératif": ["présent"],
    "subjonctif": ["présent"],
}

# Niveau du joueur nécessaire pour débloquer chaque palier (1 = dès le départ).
NIVEAUX_MIN = [1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]

PART_REVISION = 0.35

COURANTS = {
    "être", "avoir", "aller", "faire", "dire", "pouvoir", "vouloir", "savoir", "venir",
    "voir", "prendre", "mettre", "devoir", "partir", "finir", "choisir", "parler",
    "manger", "aimer", "donner", "trouver", "passer", "regarder", "demander", "penser",
    "arriver", "rester", "porter", "laisser", "commencer", "jouer", "travailler",
    "écouter", "appeler", "chercher", "entrer", "tomber", "montrer", "marcher",
    "retourner", "rentrer", "utiliser", "préparer", "changer", "aider", "oublier",
    "acheter", "payer", "danser", "chanter", "étudier", "habiter", "visiter",
    "voyager", "partager", "cuisiner", "nager", "sortir", "dormir", "ouvrir", "lire",
    "écrire", "vivre", "connaître", "croire", "recevoir", "attendre", "entendre",
    "perdre", "répondre", "rendre", "descendre", "réussir", "grandir", "obéir",
    "remplir", "réfléchir", "comprendre", "apprendre", "suivre", "boire", "courir",
    "devenir", "tenir", "offrir",
}

SUFFIXES_PIEGES = ("cer", "ger", "yer", "eler", "eter", "ayer", "oyer", "uyer")


def _est_facile(verbe):
    if verbe in COURANTS:
        return True
    return verbe.endswith("er") and not verbe.endswith(SUFFIXES_PIEGES) and verbe != "aller"


def _temps_disponibles(donnees, mode):
    """Temps du mode ayant au moins une forme non vide chez au moins un verbe."""
    vus = {}
    for modes in donnees.values():
        for t, formes in modes.get(mode, {}).items():
            if formes:
                vus[t] = True
    if mode == "impératif":  # le générateur ne gère que ces deux temps
        return [t for t in vus if t in ("présent", "passé")]
    return list(vus)


def construire_paliers(actif, passif):
    """Construit l'échelle de paliers à partir des données de conjugaison."""
    facile = [v for v in actif if _est_facile(v)]
    difficile = [v for v in actif if not _est_facile(v)]
    poids_facile = {v: (4.0 if v in COURANTS else 1.0) for v in facile}
    poids_difficile = {v: 1.0 for v in difficile}
    paliers = []
    for mode in ORDRE_MODES:
        t_actif = _temps_disponibles(actif, mode)
        if not t_actif:
            continue
        cap = mode.capitalize()
        t_base = [t for t in TEMPS_BASE[mode] if t in t_actif] or t_actif[:1]
        paliers.append(dict(
            nom=f"{cap} — l'essentiel", mode=mode, voix="active", modes=[mode],
            temps=[(mode, t) for t in t_base], verbes=facile, poids=poids_facile))
        if difficile:
            paliers.append(dict(
                nom=f"{cap} — verbes difficiles", mode=mode, voix="active", modes=[mode],
                temps=[(mode, t) for t in t_actif], verbes=difficile, poids=poids_difficile))
        t_pass = _temps_disponibles(passif, mode)
        v_pass = [v for v, ms in passif.items() if any(ms.get(mode, {}).values())]
        if t_pass and v_pass:
            paliers.append(dict(
                nom=f"{cap} — voix passive", mode=mode, voix="passive", modes=[mode],
                temps=[(mode, t) for t in t_pass], verbes=v_pass,
                poids={v: 1.0 for v in v_pass}))
    for i, p in enumerate(paliers):
        p["niveau_min"] = NIVEAUX_MIN[i] if i < len(NIVEAUX_MIN) else NIVEAUX_MIN[-1] + 2 * (i - len(NIVEAUX_MIN) + 1)
    return paliers


def palier_debloque(paliers, niveau):
    """Plus haut palier accessible pour un niveau de joueur (au moins 1)."""
    return max([i + 1 for i, p in enumerate(paliers) if niveau >= p["niveau_min"]] or [1])


def parametres_question(paliers, palier_courant, mode_quiz, poids_rep=None, rng=random):
    """
    Retourne les paramètres à passer à generer_question().
    poids_rep : poids de répétition espacée {verbe: poids}, multipliés aux poids du palier.
    """
    n = len(paliers)
    courant = max(1, min(palier_courant, n))
    if mode_quiz == "evaluation":
        choisi = rng.randint(1, courant)
    elif courant > 1 and rng.random() < PART_REVISION:
        choisi = rng.randint(1, courant - 1)
    else:
        choisi = courant
    p = paliers[choisi - 1]
    poids = dict(p["poids"])
    if poids_rep:
        for v in poids:
            poids[v] *= poids_rep.get(v, 1.0)
    return dict(palier=choisi, voix=p["voix"], modes=p["modes"], temps=p["temps"],
                verbes=p["verbes"], poids=poids)
