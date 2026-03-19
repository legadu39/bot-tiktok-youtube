# -*- coding: utf-8 -*-
# NEXUS_MASTER_V38: TEMPLATES DE PROMPTS — Visual Diversity Engine.
#
# DELTA V38 vs V6:
#
#   FIX #1 — VISUAL ELEMENT TAGS (NOUVEAU):
#     V6: Le prompt ne demandait que du texte [BOLD]/[LIGHT]/[BADGE]/[PAUSE].
#         → Le LLM ne générait JAMAIS de scènes visuelles (B-Roll, icônes, prix).
#         → Toutes les features visuelles du pipeline restaient mortes.
#     V38: Ajout de 4 tags visuels dans le prompt:
#         [BROLL:description] → Déclenche une carte B-Roll avec image procédurale
#         [ICON:nom]          → Déclenche une icône/emoji vectorielle centrée
#         [PRICE:79$,99$,179$]→ Déclenche le comparateur de prix coloré
#         [REPEATER:element]  → Déclenche le pattern grille répétitif
#
#   FIX #2 — SCENE COUNT TARGET ÉLARGI:
#     V6: target_scene_count = random(38, 48) → scripts souvent trop courts.
#     V38: target_scene_count = random(42, 55) → plus de mots, durée ~40-50s.
#
#   FIX #3 — EXEMPLES CONCRETS DANS LE PROMPT:
#     V6: Le schéma-exemple était abstrait et interdit de copie.
#     V38: Ajout de 5 scènes CONCRÈTES non-placeholder comme ancrage.
#         Le LLM voit le pattern réel et le reproduit avec du vrai contenu.
#
#   FIX #4 — INSTRUCTION VISUELLE EXPLICITE:
#     V6: "1 à 3 mots MAX par scène" uniquement.
#     V38: "1 à 3 mots MAX par scène TEXTE. Les scènes visuelles ([BROLL],
#          [ICON], [PRICE], [REPEATER]) n'ont PAS de texte à l'écran."
#
#   CONSERVÉ V6:
#     Identités (CLASH, INSIDER, MENTOR, NEWS), DA_FULL_TEKIYO palette,
#     brainstorm prompt, anti-ghost-text prohibitions.

import random

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

1. NOMBRE DE SCÈNES    : Entre 35 et 55 obligatoires.
2. MICRO-PACING        : Chaque TEXTE = 1 à 3 mots MAX, aucune exception.
3. HIÉRARCHIE GRAISSE  : Les mots-clés sont-ils identifiables ?
4. CHIFFRES / BADGES   : Les prix, %, chiffres forts ont-ils un tag [BADGE] ?
5. PAUSES              : Au moins 3 scènes [PAUSE] présentes ?
6. VISUELS             : Au moins 4 scènes visuelles ([BROLL], [ICON], [PRICE]) ?
7. OVERLAY SFX         : CLICK sur mots d'impact, SWOOSH sur liaisons ?
8. ESPACE NÉGATIF      : Le texte laisse-t-il "respirer" ?

Corrige chaque violation.
Si tout est conforme : "✅ Script conforme Premium Motion V38."
"""

# =============================================================================
# BRAINSTORMING TEXTE STRUCTURÉ (ANTI-HALLUCINATION)
# =============================================================================

BRAINSTORM_PROMPT_TEMPLATE = """
Tu es un expert en marketing TikTok/YouTube Shorts B2B. Ton seul but est de générer un angle de vidéo hautement viral.

RÈGLES STRICTES :
1. NE RÉPONDS PAS EN JSON. Utilise uniquement le format texte structuré exact ci-dessous.
2. Le "TITRE" doit faire MAXIMUM 50 caractères.
3. Le "HOOK" est la phrase d'accroche (MAXIMUM 80 caractères).
4. N'inclus JAMAIS d'URL, de lien web, ni de texte d'introduction/conclusion.

EXEMPLE DE RÉPONSE ATTENDUE (Utilise la STRUCTURE ci-dessous mais avec un contenu 100% NOUVEAU adapté au sujet) :
=== DEBUT IDEE ===
TITRE: [Ton Titre Accrocheur Ici]
HOOK: [Ta phrase d'accroche percutante basée sur le vrai sujet demandé]
=== FIN IDEE ===

CONTEXTE ET SUJET À TRAITER :
{topic}
{error_feedback}
"""

def get_brainstorm_prompt(topic: str, previous_error: str = None) -> str:
    error_feedback = ""
    if previous_error:
        error_feedback = (
            f"\nATTENTION : Lors de ta précédente tentative, tu as fait cette erreur "
            f"sémantique : '{previous_error}'. CORRIGE CELA IMPÉRATIVEMENT."
        )
    return BRAINSTORM_PROMPT_TEMPLATE.format(
        topic=topic,
        error_feedback=error_feedback,
    )


# =============================================================================
# NEXUS_MASTER_V38: VISUAL ELEMENT TAGS — DOCUMENTATION INTERNE
# =============================================================================
#
# Ces tags sont parsés par nexus_brain.py (_parse_script_from_text) et
# déclenchent les modules visuels correspondants dans le pipeline.
#
# Tag                        Module déclenché                 Rendu
# ─────────────────────────  ──────────────────────────────  ────────────────────
# [BROLL:description image]  generate_procedural_broll_card  Card avec shadow+radius
# [ICON:eye]                 Icône vectorielle PIL            Symbole centré ~120px
# [PRICE:79$,99$,179$]       create_price_comparison_clip    Blocs colorés + dashed
# [REPEATER:calculator]      create_repeater_matrix           Grille plein écran
# [PAUSE]                    Fond blanc vide                  Respiration 0.7s
# [BADGE]                    Chiffre en vert émeraude         Style prix/stat
#
# Les scènes avec tag visuel ont un TEXTE qui est lu par le TTS mais
# n'est PAS affiché à l'écran (remplacé par l'élément visuel).
# Le champ VISUEL contient la description sémantique pour le vault.
#

# =============================================================================
# NEXUS_MASTER_V38: BIBLIOTHÈQUE D'ICÔNES DISPONIBLES
# =============================================================================
#
# Le tag [ICON:nom] supporte ces noms (rendus en PIL vectoriel) :
#   eye, clock, lock, rocket, fire, diamond, chart, money, brain,
#   shield, target, lightning, crown, trophy, warning, phone
#
# Le nom est flexible — le pipeline fait un fuzzy match.
#

# =============================================================================
# NEXUS_MASTER_V38: MASTER PROMPT — VISUAL DIVERSITY ENGINE
# =============================================================================

def wrap_v3_prompt(user_topic: str, mode: str = "MENTOR") -> str:
    """
    NEXUS_MASTER_V38: Master Prompt avec Visual Diversity Engine.

    Changements majeurs vs V6 :
      1. 4 nouveaux tags visuels ([BROLL], [ICON], [PRICE], [REPEATER])
         injectés dans les règles du prompt pour que le LLM les utilise.
      2. Exemples concrets de scènes (pas de placeholders) pour ancrer
         le LLM sur le format réel attendu.
      3. Obligation de diversité visuelle : minimum 4 scènes non-texte.
      4. Scene count cible élargi à 42-55 pour atteindre 40-50s de vidéo.
    """
    identities = {
        "CLASH":   IDENTITY_CLASH,
        "INSIDER": IDENTITY_INSIDER,
        "MENTOR":  IDENTITY_MENTOR,
        "NEWS":    IDENTITY_NEWS,
    }
    identity = identities.get(mode, IDENTITY_MENTOR)

    # NEXUS_MASTER_V38: Nombre de scènes cible élargi (V6 était 38-48)
    target_scene_count = random.randint(42, 55)

    return f"""
{identity}
{DA_FULL_TEKIYO}

TÂCHE : Tu es le Showrunner du compte TikTok 'NEXUS'.
Sujet imposé : "{user_topic}"

═══════════════════════════════════════════════════════════════
RÈGLES DE PRODUCTION — NEXUS MASTER V38 (RESPECTE CHAQUE POINT)
═══════════════════════════════════════════════════════════════

1. DURÉE : Script de 40 à 55 secondes → 100 à 140 mots au total.

2. DÉCOUPAGE : {target_scene_count} SCÈNES OBLIGATOIRES (ni plus ni moins de ±3).

3. MICRO-PACING ABSOLU : 1 SCÈNE TEXTE = 1 à 3 MOTS MAXIMUM.
   Zéro exception. Si une phrase a 6 mots, coupe-la en 3 scènes.

4. HIÉRARCHIE TYPOGRAPHIQUE PAR POIDS — RÈGLE D'OR :
   · La casse reste NORMALE dans le champ TEXTE (pas de MAJUSCULES).
   · Indique le poids avec un tag en ligne :
     [BOLD] pour les mots d'impact/action (rendus Extra-Bold 800)
     [LIGHT] pour les mots de liaison (rendus Light 300)
   · Exception : les chiffres, % et prix reçoivent automatiquement [BADGE]

5. MARQUEUR [PAUSE] — OBLIGATOIRE :
   Insère au moins 3 scènes [PAUSE] dans le script.
   Une [PAUSE] = fond blanc seul à l'écran (respiration visuelle).

6. FOND : FOND BLANC #FFFFFF STRICT pour toutes les scènes texte.

7. ═══ DIVERSITÉ VISUELLE — RÈGLE V38 CRITIQUE ═══
   Ton script DOIT contenir AU MINIMUM 4 scènes visuelles parmi :

   a) [BROLL:description] — Carte image illustrative
      Usage : Quand tu parles d'un PRODUIT, d'un OUTIL, d'un RÉSULTAT.
      Le texte est lu par la voix mais l'écran montre une image.
      → VISUEL contiendra la description pour trouver/générer l'image.

   b) [ICON:nom] — Icône vectorielle centrée plein écran
      Usage : Quand tu évoques un CONCEPT ABSTRAIT (surveillance, temps,
      sécurité, croissance, danger).
      Noms disponibles : eye, clock, lock, rocket, fire, diamond,
      chart, money, brain, shield, target, lightning, crown, warning, phone
      → Le texte est lu mais l'écran montre l'icône seule.

   c) [PRICE:montant1,montant2,montant3] — Comparaison de prix
      Usage : Quand tu compares des TARIFS, des OFFRES, des NIVEAUX.
      → L'écran montre 3 blocs colorés avec les prix.

   d) [REPEATER:element] — Grille de motifs répétitifs
      Usage : Quand tu veux un effet de MASSE, d'ACCUMULATION, de VOLUME.
      Éléments : calculator, phone, money, chart, lock
      → L'écran montre une grille hypnotique plein écran.

   OBLIGATION : AU MOINS 1 [BROLL], AU MOINS 1 [ICON], ET AU MOINS
   1 [PRICE] OU 1 [REPEATER] DANS CHAQUE SCRIPT.

8. CONTINUITÉ VISUELLE — MOT-PIVOT :
   Si un mot important apparaît dans deux scènes consécutives, répète-le
   IDENTIQUEMENT dans les deux blocs TEXTE.

9. OVERLAY SFX :
   · Mots [BOLD]       → OVERLAY: CLICK
   · Mots [LIGHT]      → OVERLAY: SWOOSH
   · [BADGE]           → OVERLAY: CLICK_DEEP
   · Scène [PAUSE]     → OVERLAY: SILENCE
   · Scène [BROLL]     → OVERLAY: SWOOSH
   · Scène [ICON]      → OVERLAY: CLICK
   · Scène [PRICE]     → OVERLAY: CLICK_DEEP
   · Scène [REPEATER]  → OVERLAY: SWOOSH

10. TRANSITION :
    TRANSITION: SLIDE dans VISUEL sur changement d'argument (max 4 fois).
    TRANSITION: FADE pour les liaisons douces.

═══════════════════════════════════════════════════════════════
EXEMPLES CONCRETS DE SCÈNES (pour comprendre le format exact)
═══════════════════════════════════════════════════════════════

Voici 8 scènes d'exemple sur un sujet DIFFÉRENT du tien.
NE COPIE PAS le contenu. COPIE UNIQUEMENT la structure.

SCENE 1
TEXTE: [BOLD]on dérange
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: CLICK

SCENE 2
TEXTE: [LIGHT]le meilleur
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: SWOOSH

SCENE 3
TEXTE: [BROLL:smartphone premium dernière génération]
VISUEL: smartphone flagship high-end product shot dark background
OVERLAY: SWOOSH

SCENE 4
TEXTE: [LIGHT]de chaque client
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: SWOOSH

SCENE 5
TEXTE: [ICON:eye]
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: CLICK

SCENE 6
TEXTE: [PRICE:79$,99$,179$]
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: CLICK_DEEP

SCENE 7
TEXTE: [PAUSE]
VISUEL: FOND BLANC #FFFFFF STRICT
OVERLAY: SILENCE

SCENE 8
TEXTE: [REPEATER:calculator]
VISUEL: repeater grid pattern accounting theme
OVERLAY: SWOOSH

═══════════════════════════════════════════════════════════════
PROHIBITIONS ABSOLUES (violations détectées en production)
═══════════════════════════════════════════════════════════════

❌ INTERDIT : Écrire des mots en MAJUSCULES dans TEXTE (sauf tags [BOLD] etc.)
❌ INTERDIT : Écrire "[premier mot ou groupe de mots]" → c'est un placeholder
❌ INTERDIT : Écrire "[LIGHT]MOT_LIAISON [BOLD]MOT_IMPACT" verbatim
❌ INTERDIT : Écrire "[Titre accrocheur basé sur {user_topic}]"
❌ INTERDIT : Tout texte entre crochets qui n'est pas [BOLD], [LIGHT], [BADGE],
              [PAUSE], [BROLL:...], [ICON:...], [PRICE:...], [REPEATER:...]
❌ INTERDIT : Plus de 3 mots non-tag dans un TEXTE de scène
❌ INTERDIT : Scène sans VISUEL ou sans OVERLAY
❌ INTERDIT : Script avec 0 scènes visuelles — MINIMUM 4 ([BROLL]+[ICON]+[PRICE/REPEATER])

Si tu produis l'un de ces patterns → ta réponse sera REJETÉE.

═══════════════════════════════════════════════════════════════
GÉNÈRE MAINTENANT — TON SCRIPT RÉEL SUR "{user_topic}"
═══════════════════════════════════════════════════════════════

INSTRUCTION FINALE : Commence DIRECTEMENT par "=== DEBUT SCRIPT ===" puis
génère {target_scene_count} scènes avec du VRAI CONTENU sur "{user_topic}".
Chaque mot de TEXTE doit être un vrai mot français lié au sujet.
Rappel : AU MINIMUM 1 [BROLL], 1 [ICON], 1 [PRICE] ou [REPEATER], et 3 [PAUSE].

=== DEBUT SCRIPT ===
TITRE:"""


def wrap_analysis(filename: str) -> str:
    return (
        f'Analyse le nom de fichier : "{filename}".\n'
        f"Déduis le sujet et le mode (CLASH, INSIDER, MENTOR, NEWS).\n"
        f"Réponds uniquement : Sujet: ... | Mode: ..."
    )


def get_manual_ingestion_prompt(filename: str) -> str:
    return f"""
ANALYSE DE FICHIER VIDEO : "{filename}"

TÂCHE : Expert viralité TikTok/Shorts (Fintech/Trading/Business B2B).
1. Analyse le titre pour déduire le sujet.
2. Génère des métadonnées virales SEO — style Premium Motion V38.

RÉSULTAT ATTENDU :
TITRE: ...
DESCRIPTION: ...
TAGS: ...
"""