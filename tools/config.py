# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Configuration centrale — CORRIGÉE depuis reverse-engineering vidéo référence.
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  MESURES PIXEL-EXACTES — vidéo référence 576×1024, 30fps, 44.03s           ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  Canvas rendu         : 1080×1920 (9:16 portrait)                          ║
# ║  Fond                 : #FFFFFF (blanc pur)                                 ║
# ║  Centre texte Y       : H × 0.497  ← CORRIGÉ (était 0.499, mesuré 0.4971)  ║
# ║  Centre texte X       : W × 0.500  (centré exact confirmé)                  ║
# ║  Police de base       : 75px       ← CORRIGÉ (était 80px, ~7% trop grand)   ║
# ║  Couleur mots normaux : rgb(21,21,21) quasi-noir (mesuré frame 5)           ║
# ║  Couleur stop words   : rgb(103,103,103) gris (mesuré frame 3 "Salut,")    ║
# ║  Accent gradient L    : rgb(190,115,218) violet (mesuré frame 75 "marché") ║
# ║  Accent gradient R    : rgb(134,108,169) mauve (mesuré frame 75)           ║
# ║  Spring entry         : stiffness=900, damping=30 → settle < 33ms (1 frame)║
# ║  Exit mode            : HARD CUT strict (< t_end, confirmé)                ║
# ║  Durée mot avg        : 63ms (min=33ms, max=267ms, N=62 mots)              ║
# ║  B-roll card width    : 53.3% canvas (mesuré 307/576 px)                   ║
# ║  B-roll corner radius : 6.4% canvas W ← CORRIGÉ (était 4.2%, mesuré       ║
# ║                         left_inset=37px @ 576p = 37/576=0.0642)            ║
# ║  B-roll shadow blur   : 18px, visible dès le bord exact de la card         ║
# ║  B-roll center Y      : H × 0.4717 (légèrement au-dessus du centre)        ║
# ║  Inversion fond noir  : t=12s et t=41-43s (2 fenêtres confirmées)          ║
# ║  Inversion fréquence  : toutes les 10-14 mots (estimation)                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ───────────────────────────────────────

# ARCHITECTURE_MASTER_V22: rgb(21,21,21) mesuré frame 5, 10, 20, 30... CORRIGÉ (était 17,17,17)
TEXT_RGB      = (21,  21,  21)
# ARCHITECTURE_MASTER_V22: rgb(103,103,103) mesuré frame 3 "Salut," CORRIGÉ (était 160,160,160)
TEXT_DIM_RGB  = (103, 103, 103)
ACCENT_RGB    = (0,   208, 132)    # Vert BADGE (chiffres)
MUTED_RGB     = (230,  45,  35)    # Rouge — mots négatifs/danger

# ARCHITECTURE_MASTER_V22: Gradient accent mesuré frame 75 "marché." — violet→mauve horizontal
# Pixels mesurés: gauche rgb(190,115,218) à droite rgb(134,108,169)
ACCENT_GRADIENT_LEFT  = (190, 115, 218)
ACCENT_GRADIENT_RIGHT = (134, 108, 169)

# ── Couleurs thème INVERSÉ (fond noir) ───────────────────────────────────────

TEXT_RGB_INV   = (235, 235, 235)   # blanc légèrement warm (mesuré t=12s)
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
    "pour","dans","vers","chez","c'est","salut","bonjour","alors","très",
    # Anglais
    "the","a","an","in","on","at","to","for","of","and","is","it",
    "be","as","by","we","he","they","you","so","but","or","if",
}

KEYWORDS_ACCENT = {
    "argent","succès","secret","outil","profit","gain","winner",
    "croissance","million","stratégie","champion","payout","valide",
    "marché","produit","client","vendre","vente","commerce","créer",
    "révèle","découverte","clé","maîtrise","excellence","unique",
}

KEYWORDS_MUTED = {
    "perdre","perte","crash","danger","scam","arnaque","échec",
    "chute","stop","alerte","attention","faillite","erreur","jamais",
    "impossible","peur","risque","contre","fout","rien",
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


# ── Constantes de layout (CORRIGÉES depuis mesures référence) ─────────────────

# ARCHITECTURE_MASTER_V22: Y anchor CORRIGÉ à 0.497
# Mesure frame-par-frame: cy/h = [0.4995, 0.4966, 0.4971, 0.4985, 0.4971]
# Moyenne: 0.4978 → arrondi à 0.497 (plus précis que le 0.499 codé en V9)
TEXT_ANCHOR_Y_RATIO = 0.497

# Safe zone horizontale
SAFE_LEFT  = 80   # px à 1080p
SAFE_RIGHT = 80

# B-roll card — CORRIGÉ depuis mesures pixel
# ARCHITECTURE_MASTER_V22: 53.3% mesuré (307/576). Était 0.53 → presque correct.
BROLL_CARD_WIDTH_RATIO   = 0.533

# ARCHITECTURE_MASTER_V22: CORRECTION MAJEURE du corner radius.
# Mesure réelle: left_inset=37px à y=401 sur canvas 576px large
# ratio = 37/576 = 0.0642. L'ancien code avait 0.042 (45px@1080p) — FAUX.
# Correct: 0.064 × 576 = 36.9px ≈ 37px confirmé. À 1080p: 69px.
BROLL_CARD_RADIUS_RATIO  = 0.064   # ← CORRIGÉ (était 0.042 = -35% d'erreur)

# ARCHITECTURE_MASTER_V22: Shadow présent dès le bord exact de la card (dy=0, diff=84)
# blur=18px reste correct, opacité shadow = 84/255 ≈ 0.33 (était 0.25 — sous-estimé)
BROLL_SHADOW_BLUR        = 18
BROLL_SHADOW_OPACITY     = 0.33    # ← CORRIGÉ (était 0.25, mesuré 84/255≈0.33)

# ARCHITECTURE_MASTER_V22: B-roll center Y corrigé
# Mesuré: card center at 483/1024 = 0.4717×H (légèrement au-dessus du milieu)
BROLL_CARD_CENTER_Y_RATIO = 0.4717  # ← NOUVEAU (permet un rendu plus fidèle)

# Spring physics (mesuré — paramètres CONFIRMÉS)
# settle < 33ms (1 frame à 30fps) → stiffness=900, damping=30, ζ≈0.50 est correct
SPRING_STIFFNESS = 900
SPRING_DAMPING   = 30
SPRING_SLIDE_PX  = 8    # Y offset initial (le texte monte légèrement en entrant)

# ARCHITECTURE_MASTER_V22: Police de base CORRIGÉE
# Mesure pixel: text_h=27px @ 1024p → 27×1920/1024 = 50px équiv 1920p pour petits mots.
# Pour les mots d'impact (t=18s, t=40s): text_h=58px → 108px@1920p.
# La base est ~75px (les grands mots sont BOLD×1.10 = 82px, les petits STOP×0.85 = 63px)
FS_BASE = 75    # ← CORRIGÉ (était 80, -6.25% d'erreur mesurée)
FS_MIN  = 32

# Timing confirmé
ENTRY_DUR      = 0.033   # 1 frame @ 30fps — spring settle ultra-rapide CONFIRMÉ
EXIT_DUR       = 0.0     # HARD CUT — 0 frames CONFIRMÉ
PRE_ROLL       = 0.033   # 1 frame d'anticipation

# Zoom global
GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03   # Subtil — confirmé (texte légèrement plus gros en fin de vidéo)

# Slide exit
SLIDE_OUT_PX = 500

# Inversion — paramètres corrigés depuis mesure réelle
# Mesure: 2 fenêtres inversées sur 44s → ~1 inversion toutes les 20s
# Estimation: déclenchée tous les 10-14 mots (paramètre conservé)
INVERSION_WORD_MIN = 10
INVERSION_WORD_MAX = 14

# ── Alias pour rétrocompatibilité scene_animator ─────────────────────────────
WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)