# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Configuration centrale.
# Toutes les valeurs sont calibrées depuis la vidéo référence (mesures pixel).
#
# MESURES VIDÉO RÉFÉRENCE (576×1024, 30fps) :
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  Canvas               : 1080×1920 (9:16 portrait)                      │
# │  Fond                 : #FFFFFF (blanc pur)                             │
# │  Centre texte Y       : H × 0.499 (légèrement au-dessus du 50%)        │
# │  Centre texte X       : W × 0.5  (centré horizontal exact)             │
# │  B-roll card width    : W × 0.53 (53% du canvas)                       │
# │  B-roll corner radius : W × 0.042 ≈ 45px à 1080px                      │
# │  Spring entry         : stiffness=900, damping=30 → settle ≈ 80ms      │
# │  Exit mode            : HARD CUT (0 frame de fondu)                     │
# │  Stop word color      : rgb(160,160,160) — gris moyen                   │
# │  Normal word color    : rgb(17,17,17) — quasi-noir                      │
# │  Accent gradient L    : rgb(190,115,218) — violet                       │
# │  Accent gradient R    : rgb(134,108,169) — mauve                        │
# └─────────────────────────────────────────────────────────────────────────┘

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ───────────────────────────────────────

TEXT_RGB      = (17,  17,  17)     # Quasi-noir — mots normaux
TEXT_DIM_RGB  = (160, 160, 160)    # Gris moyen — stop words (mesuré frame hd_0001)
ACCENT_RGB    = (0,   208, 132)    # Vert — héritage V9, remplacé par gradient pour accent
MUTED_RGB     = (230,  45,  35)    # Rouge — mots négatifs/danger

# ARCHITECTURE_MASTER_V22 : Gradient accent mesuré dans la référence
# Frame 3 "marché." : violet→mauve horizontal
ACCENT_GRADIENT_LEFT  = (190, 115, 218)   # rgb mesuré px x=239
ACCENT_GRADIENT_RIGHT = (134, 108, 169)   # rgb mesuré px x=329

# ── Couleurs thème INVERSÉ (fond noir) ───────────────────────────────────────

TEXT_RGB_INV   = (238, 238, 238)
TEXT_DIM_INV   = (150, 150, 150)
ACCENT_RGB_INV = (50,  235, 140)
MUTED_RGB_INV  = (255,  80,  70)

# ── Regex et listes sémantiques ───────────────────────────────────────────────

RE_NUMERIC = re.compile(r'[\d\$€%]')

STOP_WORDS = {
    # Français
    "le","la","les","un","une","des","ce","ces","de","du","à","au",
    "et","en","ne","se","sa","son","ses","on","y","il","elle","ils",
    "elles","je","tu","nous","vous","qui","que","quoi","dont","où",
    "si","or","ni","car","mais","ou","donc","par","sur","sous","avec",
    "pour","dans","vers","chez","c'est","salut","bonjour",
    # Anglais
    "the","a","an","in","on","at","to","for","of","and","is","it",
    "be","as","by","we","he","they","you","so","but","or","if",
}

KEYWORDS_ACCENT = {
    "argent","succès","secret","outil","profit","gain","winner",
    "croissance","million","stratégie","champion","payout","valide",
    "marché","produit","client","vendre","vente","commerce","créer",
}

KEYWORDS_MUTED = {
    "perdre","perte","crash","danger","scam","arnaque","échec",
    "chute","stop","alerte","attention","faillite","erreur","jamais",
}

IMPACT_WORDS = {
    "secret","argent","profit","gain","succès","winner","champion","million",
    "stratégie","risque","danger","crash","stop","alerte","révèle","jamais",
    "toujours","maintenant","gratuit","payant","incroyable","impossible",
    "réel","vrai","faux","piège","erreur","règle","marché","vendre",
}

# ── Dictionnaire d'assets emoji/icône ────────────────────────────────────────

ASSET_DICT = {
    "cerveau":   "brain.png",
    "argent":    "money.png",
    "risque":    "alert.png",
    "fusée":     "rocket.png",
    "graphique": "chart.png",
    "cadenas":   "lock.png",
    "feu":       "fire.png",
    "diamant":   "diamond.png",
}

ASSET_DIR = Path(__file__).parent / "assets" if "__file__" in dir() else Path("assets")


# ── Constantes de layout (calibrées référence) ───────────────────────────────

# ARCHITECTURE_MASTER_V22 : Position Y du texte = H * 0.499
# Mesuré référence : text_cy ≈ 507px sur 1024px canvas = 49.5% de H
# À 1080p : 1920 * 0.499 = 958px
TEXT_ANCHOR_Y_RATIO = 0.499

# Safe zone horizontale
SAFE_LEFT  = 80   # px à 1080p
SAFE_RIGHT = 80

# B-roll card
# ARCHITECTURE_MASTER_V22 : 53% du canvas mesuré pixel-exact (305/576 = 0.529)
BROLL_CARD_WIDTH_RATIO   = 0.53
BROLL_CARD_RADIUS_RATIO  = 0.042   # 45px @ 1080p
BROLL_SHADOW_BLUR        = 18
BROLL_SHADOW_OPACITY     = 0.25

# Spring physics (référence)
SPRING_STIFFNESS = 900
SPRING_DAMPING   = 30
SPRING_SLIDE_PX  = 8     # Y offset initial mesuré

# Timing
ENTRY_DUR      = 0.083   # 2.5 frames @ 30fps — ultra-rapide comme la référence
EXIT_DUR       = 0.0     # HARD CUT — 0 frames de fondu
PRE_ROLL       = 0.05    # 1.5 frames avant le début audio (anticipation)
OVERLAP_OFFSET = 0.0     # Pas d'overlap dans la référence

# Zoom global
GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03

# Slide exit (sur mots ACCENT/ACTION optionnellement)
SLIDE_OUT_PX = 500

# ── Alias pour rétrocompatibilité scene_animator ─────────────────────────────
WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)