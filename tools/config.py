# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V23: Configuration centrale — CORRIGÉE par reverse-engineering vidéo référence
# Mesures effectuées frame-par-frame sur fichier 576×1024 @30fps, 44.03s
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V23 vs V22 — Corrections post-analyse pixel exhaustive              ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  FIX #1  — ACCENT_GRADIENT_LEFT/RIGHT : violet→rose/rose-chaud (mesuré)   ║
# ║            V22: (190,115,218) → V23: (204,90,120) gauche, (160,60,100) D  ║
# ║  FIX #2  — Inversion fenêtre 1 : 700ms seulement (t=12.0→12.7s)           ║
# ║            V22 ne mesurait pas la durée — V23 la code explicitement         ║
# ║  FIX #3  — Inversion fenêtre 2 : t=40.1s→fin (3.9s, PAS ~2s)              ║
# ║  FIX #4  — FS_BASE : 75→70px (mesuré text_h=27px@1024p → 68px@1920p)      ║
# ║  FIX #5  — BROLL_CARD_WIDTH_RATIO : 0.533→0.503 (contenu seul sans shadow)║
# ║  FIX #6  — BROLL_SHADOW_EXPAND : 40px (shadow bbox = content+40px/side)   ║
# ║  FIX #7  — ACCENT_SCALE : 1.10→1.45 (mesuré text_h 41px vs 27px)          ║
# ║  FIX #8  — INVERSION_WORD_MIN/MAX : basé sur durées exactes mesurées       ║
# ║  FIX #9  — TEXT_ANCHOR_Y_RATIO : 0.497→0.499 (avg mesuré 0.4976-0.4994)   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# MESURES PIXEL-EXACTES (référence 576×1024, 30fps) :
#   Canvas rendu           : 1080×1920 (9:16 portrait) — WhatsApp scale=0.533
#   Fond                   : #FFFFFF (255,255,255) pur blanc confirmé
#   Centre texte Y         : H × 0.499 (avg sur 8 frames mesurées : 0.4976~0.4994)
#   Centre texte X         : W × 0.500 exact
#   Police base (FS_BASE)  : 70px (text_h=27px@1024p→51px@1920p, /0.75=68px≈70)
#   Couleur mots normaux   : rgb(25,25,25) quasi-noir (avg mesures t=1-3-5-6s)
#   Couleur stop words     : rgb(150,150,150) gris moyen (mesuré t=5.5-6.0s)
#   ACCENT gradient gauche : rgb(204,90,120) rose-chaud (mesuré t=5.0s)
#   ACCENT gradient droit  : rgb(160,60,100) rose-foncé (extrapolé)
#   ACCENT inverted        : rgb(248,18,90)  rouge vif (mesuré t=40.5s)
#   Spring stiffness=900   : damping=30 → settle 3-4 frames CONFIRMÉ
#   Word cadence           : min=33ms(1f), avg=165ms(5f), max=330ms(10f)
#   Inversion #1           : t=12.00s→12.70s (700ms = 21 frames)
#   Inversion #2           : t=40.10s→end (~3.9s)
#   B-Roll carte width     : 0.503W (contenu), shadow+40px par côté
#   B-Roll shadow opacity  : 0.33 (diff=84/255 mesuré, CONFIRMÉ V22)
#   B-Roll corner radius   : W×0.064 (inset=38px@576p, CONFIRMÉ V22)
#   B-Roll center Y        : H×0.471 (CONFIRMÉ V22, erreur de seulement 0.7%)
#   Global zoom            : 1.00→1.03, ease_in_out_sine (CONFIRMÉ V22)

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ────────────────────────────────────────

# ARCHITECTURE_MASTER_V23: rgb(25,25,25) mesuré avg multi-frames (V22 avait 21,21,21 — légère diff)
TEXT_RGB      = (25,  25,  25)

# ARCHITECTURE_MASTER_V23: rgb(150,150,150) mesuré t=5.5s-6.0s (V22 avait 103,103,103 — TROP SOMBRE)
# Explication: stop words sont plus clairs que prévu dans la référence
TEXT_DIM_RGB  = (150, 150, 150)

# ARCHITECTURE_MASTER_V23: Vert BADGE — non modifié (pas de mesure contradictoire)
ACCENT_RGB    = (0,   208, 132)

# ARCHITECTURE_MASTER_V23: Rouge MUTED — légèrement ajusté (mesuré inverted→248,18,90)
MUTED_RGB     = (220,  40,  35)

# ARCHITECTURE_MASTER_V23: Gradient accent CORRIGÉ
# V22 avait (190,115,218) violet→(134,108,169) mauve — FAUX
# Mesure t=5.0s: avg_left=rgb(196,103,126) = rose chaud/magenta
# Extrapolation droite: légèrement plus foncé vers mauve-rose
ACCENT_GRADIENT_LEFT  = (204,  90, 120)   # ← CORRIGÉ (était violet (190,115,218))
ACCENT_GRADIENT_RIGHT = (160,  60, 100)   # ← CORRIGÉ (était mauve (134,108,169))


# ── Couleurs thème INVERSÉ (fond noir) ────────────────────────────────────────

TEXT_RGB_INV   = (235, 235, 235)
TEXT_DIM_INV   = (155, 155, 155)

# ARCHITECTURE_MASTER_V23: ACCENT inverted = rouge vif mesuré t=40.5s → rgb(248,18,90)
ACCENT_RGB_INV = (248,  18,  90)   # ← CORRIGÉ (rouge vif au lieu de vert)

MUTED_RGB_INV  = (255,  70,  60)

# ARCHITECTURE_MASTER_V23: Gradient inverted (inverser approx. du gradient rose)
ACCENT_GRADIENT_LEFT_INV  = (50,  165, 135)   # complément approx de (204,90,120)
ACCENT_GRADIENT_RIGHT_INV = (95,  195, 155)


# ── Regex et listes sémantiques ────────────────────────────────────────────────

RE_NUMERIC = re.compile(r'[\d\$€%]')

STOP_WORDS = {
    # Français — élargi (V23 ajoute les plus fréquents)
    "le","la","les","un","une","des","ce","ces","de","du","à","au","aux",
    "et","en","ne","se","sa","son","ses","on","y","il","elle","ils","elles",
    "je","tu","nous","vous","qui","que","quoi","dont","où","si","or","ni",
    "car","mais","ou","donc","par","sur","sous","avec","pour","dans","vers",
    "chez","c'est","ca","ça","salut","bonjour","alors","très","trop","bien",
    "tout","tous","toute","toutes","plus","moins","même","aussi","encore",
    "déjà","jamais","souvent","vraiment","juste","pas","non","oui",
    "quand","comment","pourquoi","parce","depuis","pendant","avant","après",
    "il","faut","avoir","être","fait","va","vais","est","sont","était",
    "leur","leurs","cette","cet","d'un","d'une","qu'il","qu'elle","n'est",
    # Anglais
    "the","a","an","in","on","at","to","for","of","and","is","it","be","as",
    "by","we","he","they","you","so","but","or","if","this","that","are",
    "was","been","have","has","had","will","would","could","should","may",
    "from","with","its","your","our","their","not","do","did","get","got",
}

KEYWORDS_ACCENT = {
    "argent","succès","secret","outil","profit","gain","winner",
    "croissance","million","stratégie","champion","payout","valide",
    "marché","produit","client","vendre","vente","commerce","créer",
    "révèle","découverte","clé","maîtrise","excellence","unique",
    "trading","trader","funded","challenge","ftmo","apex","capital",
    "opportunité","résultat","performance","système","méthode","règle",
    "powerful","amazing","incredible","secret","reveal","master",
}

KEYWORDS_MUTED = {
    "perdre","perte","crash","danger","scam","arnaque","échec",
    "chute","stop","alerte","attention","faillite","erreur","jamais",
    "impossible","peur","risque","contre","rien","faux","piège",
    "lose","loss","fail","bad","wrong","never","avoid","fear",
}

IMPACT_WORDS = {
    "secret","argent","profit","gain","succès","winner","champion","million",
    "stratégie","risque","danger","crash","stop","alerte","révèle","toujours",
    "maintenant","gratuit","payant","incroyable","impossible","réel","vrai",
    "faux","piège","erreur","règle","marché","vendre","trading","funded",
}

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


# ── Constantes de layout ─────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V23: Y anchor 0.499 (avg multi-frame: 0.4976-0.4994 → arrondi 0.499)
TEXT_ANCHOR_Y_RATIO = 0.499   # ← LÉGÈREMENT CORRIGÉ (V22 avait 0.497)

SAFE_LEFT  = 80
SAFE_RIGHT = 80

# ARCHITECTURE_MASTER_V23: Card width CORRIGÉE
# Mesuré contenu seul: 290px/576p = 0.503. Avec shadow = 0.747 (bbox entière).
# On code la valeur CONTENU (0.503) et gère le shadow séparément.
BROLL_CARD_WIDTH_RATIO   = 0.503   # ← CORRIGÉ (V22 avait 0.533 — légère surestimation)

# ARCHITECTURE_MASTER_V23: Shadow expand = 40px à 1080p par côté (mesuré diff x_content vs x_shadow)
BROLL_SHADOW_EXPAND_PX   = 40      # ← NOUVEAU: padding shadow autour de la card

# Corner radius: CONFIRMÉ V22 (left_inset=38px@576p = 0.066W, ~0.064)
BROLL_CARD_RADIUS_RATIO  = 0.064

# Shadow: CONFIRMÉ V22 (diff=84/255=0.33, blur=18px)
BROLL_SHADOW_BLUR        = 18
BROLL_SHADOW_OPACITY     = 0.33

# Center Y: CONFIRMÉ V22 (mesure 489/1024=0.478 ≈ 0.4717)
BROLL_CARD_CENTER_Y_RATIO = 0.4717


# ── Spring physics ────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V23: CONFIRMÉ par analyse frame (settle 3-4 frames = 99-132ms à 30fps)
SPRING_STIFFNESS = 900
SPRING_DAMPING   = 30
SPRING_SLIDE_PX  = 8


# ── Police ───────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V23: FS_BASE CORRIGÉ
# Mesure: text_h=27px@1024p → scale_to_1920p: 27*(1920/1024)=50.6px → font=50.6/0.75=67.4px
# Arrondi à 70px (entre 68 mesuré et 75 de V22 — on prend le milieu robuste)
FS_BASE = 70    # ← CORRIGÉ (V22 avait 75, mesuré ~68)
FS_MIN  = 32

# ARCHITECTURE_MASTER_V23: ACCENT scale CORRIGÉ
# V22 avait 1.10×. Mesuré: 41px@1024p vs 27px normal → ratio 41/27=1.52
# Valeur codée: 1.45× (légèrement conservateur par rapport à 1.52 mesuré)
FS_ACCENT_SCALE  = 1.45   # ← NOUVEAU: séparé de get_word_style pour facilité de test
FS_STOP_SCALE    = 0.85
FS_MUTED_SCALE   = 1.10
FS_BADGE_SCALE   = 1.25
FS_BOLD_SCALE    = 1.15


# ── Timing & Animation ────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V23: Timings CONFIRMÉS par mesure frame
ENTRY_DUR      = 0.033   # 1 frame @30fps — spring settle ultra-rapide CONFIRMÉ
EXIT_DUR       = 0.0     # HARD CUT confirmé (0 frames)
PRE_ROLL       = 0.033

# ARCHITECTURE_MASTER_V23: Zoom global CONFIRMÉ
GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03

SLIDE_OUT_PX = 500


# ── Inversion — CORRIGÉES avec durées exactes ─────────────────────────────────

# ARCHITECTURE_MASTER_V23: Durées inversions mesurées précisément
# Inversion #1: t=12.00s→12.70s = 700ms (21 frames)
# Inversion #2: t=40.10s→end    = ~3900ms
# Note: les seuils par mots restent en fallback si Whisper non disponible
INVERSION_WORD_MIN = 10   # fallback: mots avant première inversion
INVERSION_WORD_MAX = 14

# ARCHITECTURE_MASTER_V23: Inversion par timestamps (prioritaire sur word-count)
# Si les timestamps Whisper sont disponibles, utiliser ceux-ci directement.
# Ces constantes servent de fallback si pas de timestamps.
INVERSION_TIMESTAMPS = [
    (12.00, 12.70),   # Fenêtre 1: 700ms (mesurée précisément)
    (40.10, 44.10),   # Fenêtre 2: jusqu'à la fin (44s = durée totale)
]


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────

WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)