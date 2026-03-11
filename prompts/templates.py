# -*- coding: utf-8 -*-
### bot tiktok youtube/prompts/templates.py
"""
TEMPLATES DE PROMPTS — NEXUS V6 PREMIUM MOTION
Phases appliquées :
  · Phase 1 : Contraste de GRAISSES (Extra-Bold/Regular) comme signal principal
              Les MAJUSCULES ne sont utilisées que pour les chiffres et acronymes
  · Phase 2 : [PAUSE] marker — respiration visuelle avec espace négatif assumé
  · Phase 3 : Métaphores UI (cartes prix, icônes vectorielles, badges)
  · Phase 4 : Sound Design guidé + continuité des mots-pivots entre scènes
"""

# =============================================================================
# IDENTITÉS
# =============================================================================

IDENTITY_CLASH = """
ROLE: Expert Provocateur Haut de Gamme.
TONALITÉ: Brute, polarisante, intellectuellement supérieure.
CIBLE: Clients B2B, entrepreneurs à haut pouvoir d'achat.
"""

IDENTITY_INSIDER = """
ROLE: Consultant B2B / Analyste Senior.
TONALITÉ: Clinique, froid, factuel, autorité absolue.
CIBLE: Clients B2B, investisseurs institutionnels.
"""

IDENTITY_MENTOR = """
ROLE: Stratège Business / Grand Frère.
TONALITÉ: Direct, simple, démonstratif.
CIBLE: Débutants avancés, freelances, agences.
"""

IDENTITY_NEWS = """
ROLE: Rapporteur de Tendances Marché.
TONALITÉ: Rapide, factuelle, chiffrée.
CIBLE: Traders, analystes, professionnels de la finance.
"""

# =============================================================================
# DIRECTIVE ARTISTIQUE COMPLÈTE — PREMIUM MOTION V6
# =============================================================================

DA_FULL_TEKIYO = """
DIRECTION ARTISTIQUE (Premium Motion V6 — Apple / Arc / Linear Design Language) :

  · PALETTE
    Fond : blanc pur #FFFFFF (neutre absolu, pas de crème #F5F5F7 dans les scripts)
    Texte principal : Anthracite #1D1D1F
    Accent positif  : Violet premium #7B2CBF (gains, elite, record)
    Accent négatif  : Rouge vif #D90429 (perte, danger, alerte)
    Couleur JAMAIS utilisée en plages larges — seulement comme badge ou underline.

  · TYPOGRAPHIE — Inter / Neue Haas Grotesk / SF Pro Display (priorité dans cet ordre)
    RÈGLE D'OR : La hiérarchie passe par le POIDS, pas par les majuscules.
    – Mots d'IMPACT/ACTION → Extra-Bold (800) — écrit normalement, casse normale
    – Mots de liaison      → Light (300) — léger, en retrait
    – Chiffres / Acronymes → Extra-Bold + couleur accent OU badge carte UI
    Exemple correct   : "la simplicité bat la performance"
                         (simplicité et performance en Extra-Bold, reste en Light)
    Exemple incorrect : "la SIMPLICITÉ bat la PERFORMANCE" ← brutalisme à éviter

  · ESPACEMENT & RESPIRATION (L'espace vide EST du contenu)
    Safe zone 20 % de chaque côté → MAX_WIDTH = 60 % × 1080 = 648 px
    Letter-spacing : +0.04em sur les mots Extra-Bold (aération luxueuse)
    Line-height : 1.15 minimum — jamais de texte compressé
    Entre deux blocs de mots : au moins 1 scène vide [PAUSE] toutes les 8 scènes

  · ANIMATION — Courbes de Bézier "snap & glide"
    Entrée  : ease_in_expo sur 3 frames → arrêt net (départ vif, freinage précis)
    Sortie  : ease_out_back sur 4 frames → légère élasticité (naturel, pas robotique)
    Stacking: Le mot précédent monte 60 px et passe à 25 % d'opacité
    Continuité : si un mot-clé est commun à deux scènes consécutives,
                 il RESTE À L'ÉCRAN et les autres mots glissent autour de lui.

  · MICRO-SCÈNES UI (Métaphores visuelles)
    Prix / pourcentages → badge carte arrondie (neumorphique, ombre portée douce)
    Statistiques clés   → chip coloré avec fond semi-transparent
    Citations / axiomes → underline animé qui se "dessine" de gauche à droite

  · TRANSITIONS
    Changement de sujet → Slide latérale ease_out_back (0.25 s)
    Continuité du même sujet → Fade crossover 0.10 s (imperceptible)
    Jamais de cut sec sur un mot d'impact.
"""

# =============================================================================
# AGENT CRITIQUE V6
# =============================================================================

CRITIQUE_PROMPT = """
Tu es le Directeur Artistique de NEXUS Premium Motion V6.
Analyse le Script fourni selon les règles PREMIUM MOTION :

1. NOMBRE DE SCÈNES    : Entre 35 et 50 obligatoires.
2. MICRO-PACING        : Chaque TEXTE = 1 à 3 mots MAX, aucune exception.
3. HIÉRARCHIE GRAISSE  : Les mots-clés sont-ils identifiables (pas en majuscules, 
                          mais flaggés comme IMPACT dans le script) ?
4. CHIFFRES / BADGES   : Les prix, %, chiffres forts ont-ils un tag [BADGE] ?
5. PAUSES              : Au moins 3 scènes [PAUSE] présentes ?
6. CONTINUITÉ          : Y a-t-il des mots-pivots communs entre scènes consécutives
                          (permettant la continuité visuelle) ?
7. OVERLAY SFX         : CLICK sur mots d'impact, SWOOSH sur liaisons, SILENCE sur [PAUSE] ?
8. ESPACE NÉGATIF      : Le texte laisse-t-il "respirer" (pas de phrases complètes) ?

Corrige chaque violation.
Si tout est conforme : "✅ Script conforme Premium Motion V6."
"""

# =============================================================================
# NOUVEAU : SYSTEME DE BRAINSTORMING TEXTE STRUCTURE (ANTI-HALLUCINATION)
# =============================================================================

BRAINSTORM_PROMPT_TEMPLATE = """
Tu es un expert en marketing TikTok/YouTube Shorts B2B. Ton seul but est de générer un angle de vidéo hautement viral.

RÈGLES STRICTES :
1. NE RÉPONDS PAS EN JSON. Utilise uniquement le format texte structuré exact ci-dessous.
2. Le "TITRE" doit faire MAXIMUM 50 caractères. (Ex: "PropFirm : Mon 1er Payout")
3. Le "HOOK" est la phrase d'accroche (MAXIMUM 80 caractères).
4. N'inclus JAMAIS d'URL, de lien web, ni de texte d'introduction/conclusion.

EXEMPLE DE RÉPONSE ATTENDUE (Copie exactement cette structure) :
=== DEBUT IDEE ===
TITRE: Gagner avec les PropFirms
HOOK: 90% des traders échouent. Voici comment j'ai eu mon 1er payout.
=== FIN IDEE ===

CONTEXTE ET SUJET À TRAITER : 
{topic}
{error_feedback}
"""

def get_brainstorm_prompt(topic: str, previous_error: str = None) -> str:
    error_feedback = ""
    if previous_error:
        error_feedback = f"\nATTENTION : Lors de ta précédente tentative, tu as fait cette erreur sémantique : '{previous_error}'. CORRIGE CELA IMPÉRATIVEMENT DANS TA PROCHAINE RÉPONSE."
    return BRAINSTORM_PROMPT_TEMPLATE.format(topic=topic, error_feedback=error_feedback)

# =============================================================================
# MASTER PROMPT V6 — PREMIUM MOTION
# =============================================================================

def wrap_v3_prompt(user_topic: str, mode: str = "MENTOR") -> str:
    """
    Génère le Master Prompt V6 — Premium Motion Mode.
    Hiérarchie typographique par POIDS, espace négatif assumé, métaphores UI.
    Format : TEXTE STRUCTURÉ (robuste, sans JSON fragile).
    """
    identities = {
        "CLASH":   IDENTITY_CLASH,
        "INSIDER": IDENTITY_INSIDER,
        "MENTOR":  IDENTITY_MENTOR,
        "NEWS":    IDENTITY_NEWS,
    }
    identity = identities.get(mode, IDENTITY_MENTOR)

    return f"""
{identity}
{DA_FULL_TEKIYO}

TÂCHE : Tu es le Showrunner du compte TikTok 'NEXUS'.
Sujet : "{user_topic}"

═══════════════════════════════════════════════════════════════
RÈGLES DE PRODUCTION — PREMIUM MOTION V6 (RESPECTE CHAQUE POINT)
═══════════════════════════════════════════════════════════════

1. DURÉE : Script de 40 à 60 secondes → 100 à 130 mots au total.

2. DÉCOUPAGE : 35 à 50 SCÈNES obligatoires.

3. MICRO-PACING ABSOLU : 1 SCÈNE = 1 à 3 MOTS MAXIMUM.
   Zéro exception. Si une phrase a 6 mots, coupe-la en 3 scènes.

4. HIÉRARCHIE TYPOGRAPHIQUE PAR POIDS — RÈGLE D'OR :
   · La casse reste NORMALE dans le champ TEXTE.
   · Indique le poids avec un tag en ligne :
     [BOLD] pour les mots d'impact/action (seront rendus Extra-Bold 800)
     [LIGHT] pour les mots de liaison (seront rendus Light 300)
   · Exemple : "[LIGHT]les [BOLD]traders [LIGHT]qui [BOLD]perdent"
   · Exception : les chiffres, % et prix n'ont pas besoin de tag — ils 
     reçoivent automatiquement un badge carte (tag [BADGE] facultatif)

5. MARQUEUR [PAUSE] — OBLIGATOIRE :
   Insère au moins 3 scènes [PAUSE] dans le script, après chaque
   chiffre fort ou affirmation centrale. Une [PAUSE] = 1 à 1,5 s.
   Le fond blanc seul à l'écran. C'est du LUXE, pas du vide.

6. FOND : FOND BLANC #FFFFFF STRICT — propre, lumineux, premium.
   Jamais d'image de fond. L'espace vide EST le message.

7. CONTINUITÉ VISUELLE — MOT-PIVOT :
   Si un mot important (ex: "stratégie", "ratio") apparaît dans deux
   scènes consécutives, répète-le IDENTIQUEMENT dans les deux blocs TEXTE.
   Le moteur de rendu le détectera et le laissera à l'écran en continu.

8. OVERLAY SFX (Sound Design) :
   · Mots [BOLD] (impact)      → OVERLAY: CLICK
   · Mots [LIGHT] (liaison)    → OVERLAY: SWOOSH
   · [BADGE] (chiffre/prix)    → OVERLAY: CLICK_DEEP
   · Scène [PAUSE]             → OVERLAY: SILENCE

9. TRANSITION : Écris TRANSITION: SLIDE dans VISUEL quand tu
   changes d'argument principal (max 3 fois par vidéo).
   Pour les transitions douces dans le même argument : TRANSITION: FADE

═══════════════════════════════════════════════════════════════
FORMAT DE RÉPONSE (copie ce modèle exactement)
═══════════════════════════════════════════════════════════════

=== DEBUT SCRIPT ===
TITRE: [Titre de la vidéo]
TAGS: [tag1, tag2, tag3]

SCENE 1
TEXTE: [LIGHT]90% [BOLD]des traders
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: CLICK

SCENE 2
TEXTE: [BOLD]perdent tout
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: CLICK

SCENE 3
TEXTE: [LIGHT]leur argent.
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: SWOOSH

SCENE 4
TEXTE: [PAUSE]
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: SILENCE

SCENE 5
TEXTE: [LIGHT]La [BOLD]raison ?
VISUEL: TRANSITION: SLIDE
OVERLAY: CLICK

SCENE 6
TEXTE: [BADGE]179$
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: CLICK_DEEP

... (Continue jusqu'à SCENE 40-50, termine avec un CTA fort)
=== FIN SCRIPT ===
"""


def wrap_analysis(filename: str) -> str:
    return (f'Analyse le nom de fichier : "{filename}".\n'
            f"Déduis le sujet et le mode (CLASH, INSIDER, MENTOR, NEWS).\n"
            f"Réponds uniquement : Sujet: ... | Mode: ...")


def get_manual_ingestion_prompt(filename: str) -> str:
    return f"""
ANALYSE DE FICHIER VIDEO : "{filename}"

TÂCHE : Expert viralité TikTok/Shorts (Fintech/Trading/Business B2B).
1. Analyse le titre pour déduire le sujet.
2. Génère des métadonnées virales SEO — style Premium Motion V6.

RÉSULTAT ATTENDU :
TITRE: ...
DESCRIPTION: ...
TAGS: ...
"""