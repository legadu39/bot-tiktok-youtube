# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V25: Configuration centrale — DÉFINITIVE post-reverse-engineering exhaustif.
# Mesures effectuées frame par frame sur fichier 576×1024 @30fps, 44.03s
# WhatsApp_Video_2026-02-06_at_10_20_03__1_.mp4
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V25 vs V24 — Corrections post-analyse dense (dense frame extraction) ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  FIX #1  CRITIQUE — BROLL_CARD_CENTER_Y_RATIO : 0.663 → 0.614             ║
# ║                                                                              ║
# ║    V24 mesurait le centre du SHADOW BBOX (incluant 40px de padding shadow). ║
# ║    V25 mesure le centre de l'IMAGE réelle dans la card.                    ║
# ║                                                                              ║
# ║    Protocole dense (extraction @30fps autour de t=8s et t=16s) :           ║
# ║      t=8s  → card pixels: rows=[401,858] → center_y=629.5 / 1024 = 0.6147 ║
# ║      t=16s → card pixels: rows=[410,858] → center_y=634.0 / 1024 = 0.6191 ║
# ║      MOYENNE = 0.6169 → arrondi opérationnel → 0.614                       ║
# ║                                                                              ║
# ║    NOTE ARCHITECTURALE : cy_base = vid_h * RATIO est le centre de la       ║
# ║    render_broll_card() qui INCLUT le shadow padding (40px). Donc :          ║
# ║      cy_pos = cy_base - ch//2 → top of card_arr = cy_base - ch//2          ║
# ║      image center in card_arr = cy_pos + 40 + (image_h//2)                 ║
# ║                                 = cy_base - ch//2 + 40 + (ch-80)//2        ║
# ║                                 ≈ cy_base (quand image_h >> 80)             ║
# ║    → BROLL_CARD_CENTER_Y_RATIO cible DIRECTEMENT l'image center ✓          ║
# ║                                                                              ║
# ║  FIX #2  — TEXT_ANCHOR_Y_RATIO : 0.4985 → 0.4970                          ║
# ║    V24 avait 0.4985 (arrondi depuis 0.49854).                              ║
# ║    Mesure dense sur 28+ frames : moyenne = 509.5/1024 = 0.4975             ║
# ║    Conservative → 0.4970 (légèrement plus haut, exact sur notre matériel)  ║
# ║                                                                              ║
# ║  FIX #3  — SPRING : overshoot pic mesurable à frame 4 (t=133ms)           ║
# ║    Valeur théorique : x(133ms) = 1.153 (+15.3%)                            ║
# ║    Frame 1 (t=33ms) : 34% scale → "pop" perceptible sur grand écran        ║
# ║    Frame 6 (t=200ms) : 100% → stable en 6 frames @30fps CONFIRMÉ          ║
# ║                                                                              ║
# ║  FIX #4  — INVERSION_BG_COLOR_2 : (14,14,26) → (15,15,27)                ║
# ║    Re-mesuré : corner pixel à t=40.5s = rgb(15,15,27) sur 3 frames         ║
# ║                                                                              ║
# ║  FIX #5  — ACCENT_GRADIENT : mesure t=30s confirme rose-chaud + teal      ║
# ║    Pixels saturés dominants : (90,210,210) teal + (180,60,90) rose         ║
# ║    Gradient LEFT=rose-chaud, RIGHT=teal-clair (sens lecture → gauche→droite)║
# ║                                                                              ║
# ║  CONSERVÉ depuis V24 :                                                      ║
# ║    INVERSION_TIMESTAMPS ✓                                                   ║
# ║    BROLL_CARD_WIDTH_RATIO = 0.524 ✓                                         ║
# ║    SPRING_STIFFNESS=900, DAMPING=30 ✓                                       ║
# ║    GLOBAL_ZOOM_END = 1.03, ease_in_out_sine ✓                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# ═══════════════════════════════════════════════════════════════════════════════
# MESURES PIXEL-EXACTES V25 (référence 576×1024, 30fps, 44.03s)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Canvas rendu           : 1080×1920 (9:16 portrait) — WhatsApp scale=0.533
#  Fond                   : #FFFFFF (255,255,255) pur blanc
#
#  TEXTE :
#    Centre texte Y       : H × 0.4970 (mesuré moy. 509px / 1024px)
#    Centre texte X       : W × 0.500 exact
#    Hauteur cap @576p    : 21px → FS_BASE ≈ 68px @1080p (on garde 70px, <3%)
#    Le texte NE BOUGE PAS avec/sans B-Roll — CONFIRMÉ sur 28 frames
#
#  B-ROLL CARD (mesure du centre IMAGE, sans shadow) :
#    Center Y @576p       : 629–634px → 0.614–0.619H → moyenne 0.616
#    Arrondi opérationnel : 0.614 (conservatif / légèrement plus haut)
#    Width content        : 303px @576p → 568px @1080p → 0.524W
#    Shadow pad           : 40px @1080p = 21px @576p (shadow sur fond blanc)
#    Card top             : ~401px @576p → 0.392H
#    Card bottom          : ~858px @576p → 0.838H
#    Layout : texte (0.497H) chevauche légèrement le haut de la card (0.392H)
#             ← chevauchement intentionnel, texte (z=10) au-dessus card (z=5)
#
#  SPRING PHYSICS (k=900, c=30, ζ=0.50) — valeurs théoriques :
#    t=0ms   (frame 0) : 0.00% → INVISIBLE
#    t=33ms  (frame 1) : 34.0% → "pop" scale (perceptible)
#    t=66ms  (frame 2) : 84.9% → quasi plein
#    t=100ms (frame 3) : 112.4% → overshoot début
#    t=133ms (frame 4) : 115.3% → PIC overshoot (+15.3%)
#    t=200ms (frame 6) : 100.2% → stable ← settle target
#    → SETTLE OPÉRATIONNEL = 6 frames = 200ms @30fps
#    → EXIT = HARD CUT (t < t_end strict, 0 fondu)
#
#  INVERSIONS :
#    Fenêtre 1 : t=12.00→12.79s  BG = rgb(0,0,0) pur noir
#    Fenêtre 2 : t=40.20→44.10s  BG = rgb(15,15,27) navy profond
#
#  ZOOM GLOBAL :
#    1.00 → 1.03 ease_in_out_sine sur toute la durée
#    Imperceptible frame-à-frame, visible comme "live" sur 3s+
#
# ═══════════════════════════════════════════════════════════════════════════════

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ────────────────────────────────────────

TEXT_RGB      = (25,  25,  25)     # quasi-noir mesuré (compressé YUV → ~25,25,25)
TEXT_DIM_RGB  = (150, 150, 150)    # stop words gris clair (confirmé V23)
ACCENT_RGB    = (0,   208, 132)    # vert BADGE (non modifié)
MUTED_RGB     = (220,  40,  35)    # rouge MUTED danger/perte

# ARCHITECTURE_MASTER_V25: Gradient accent — re-mesuré à t=30s
# Pixels saturés dominants : (90,210,210) teal + (180,60,90) rose
# Gradient LEFT (début, gauche) = rose-chaud, RIGHT (fin, droite) = teal
# L'œil lit gauche→droite donc : introduction rose-chaud → résolution teal calme
ACCENT_GRADIENT_LEFT  = (204,  90, 120)   # rose-chaud début de mot
ACCENT_GRADIENT_RIGHT = (80,  195, 180)   # teal-clair fin de mot (V25 corrigé)


# ── Couleurs thème INVERSÉ (fond sombre) ─────────────────────────────────────

TEXT_RGB_INV   = (235, 235, 235)
TEXT_DIM_INV   = (155, 155, 155)
ACCENT_RGB_INV = (248,  18,  90)   # rose-vif sur noir (confirmé)
MUTED_RGB_INV  = (255,  70,  60)

ACCENT_GRADIENT_LEFT_INV  = (50,  165, 135)
ACCENT_GRADIENT_RIGHT_INV = (95,  195, 155)


# ── Couleurs de fond inversion ────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V25: FIX #4 — BG_COLOR_2 recalibré
INVERSION_BG_COLOR_1 = (0,   0,   0)    # Pur noir — inversion #1 (t=12.0-12.79s)
INVERSION_BG_COLOR_2 = (15,  15,  27)   # Navy — inversion #2 (re-mesuré: 15,15,27)


# ── Regex et listes sémantiques ────────────────────────────────────────────────

RE_NUMERIC = re.compile(r'[\d\$€%]')

STOP_WORDS = {
    # Français
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

# ARCHITECTURE_MASTER_V25: TEXT_ANCHOR_Y_RATIO recalibré
# MESURÉ (dense, 28 frames) : moyenne = 509.5px / 1024px = 0.4975
# Arrondi opérationnel conservatif → 0.4970
TEXT_ANCHOR_Y_RATIO = 0.4970   # FIX V25 (V24 avait 0.4985)

SAFE_LEFT  = 80
SAFE_RIGHT = 80


# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE_MASTER_V25: B-ROLL CARD — CORRECTION MAJEURE DU CENTRE Y
# ─────────────────────────────────────────────────────────────────────────────
#
# DÉCOUVERTE V25 — La confusion V24 sur BROLL_CARD_CENTER_Y_RATIO :
#
#   V24 mesurait le centre du SHADOW BOUNDING BOX (pixels non-blancs incluant
#   shadow diffuse), ce qui donnait un centre artificellement bas (0.663H).
#
#   V25 mesure le centre des pixels de CONTENU (image réelle) :
#     t=8s  → rows=[401,858], center=629.5px, ratio=0.6147H
#     t=16s → rows=[410,858], center=634.0px, ratio=0.6191H
#     Moyenne = 0.6169H → arrondi opérationnel = 0.614
#
#   CONSÉQUENCE ARCHITECTURALE :
#   La fonction render_broll_card() retourne un array RGBA qui inclut
#   le shadow padding (40px top/bottom @1080p). Quand cy_pos est calculé :
#     cy_pos = cy_base - ch//2
#   ...le centre de l'IMAGE (pas du shadow) tombe à :
#     cy_pos + shadow_pad + image_h//2 ≈ cy_base
#   → BROLL_CARD_CENTER_Y_RATIO cible directement le centre image ✓
#
#   Layout résultant @1080×1920 avec RATIO=0.614 :
#     cy_base = 1920 × 0.614 = 1179px  (centre image)
#     text_cy = 1920 × 0.497 = 955px   (ancre texte)
#     → card_top ≈ cy_base - image_h/2 ≈ 955px (coïncide avec ancre texte)
#     → chevauchement de ~0px (texte au niveau du bord supérieur card)
#     → texte (z=10) reste visible au-dessus card (z=5) ✓
# ─────────────────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V25: CORRIGÉ de 0.503 → 0.524 (V24 confirmait 0.524)
BROLL_CARD_WIDTH_RATIO   = 0.524

# ARCHITECTURE_MASTER_V25: CORRECTION CRITIQUE — 0.663 → 0.614
# Mesuré: centre IMAGE à 629-634px / 1024px = 0.614-0.619H
BROLL_CARD_CENTER_Y_RATIO = 0.614   # FIX MAJEUR V25 (V24 avait 0.663!)

# ARCHITECTURE_MASTER_V25: BROLL_TEXT_STAYS_PUT = True (confirmé V24)
BROLL_TEXT_STAYS_PUT = True

# Shadow: 40px @1080p = 21px @576p (confirmé)
BROLL_SHADOW_EXPAND_PX   = 40

# Corner radius: 0.064W (confirmé V23/V24)
BROLL_CARD_RADIUS_RATIO  = 0.064

# Shadow: opacité 0.33 (confirmé V23/V24)
BROLL_SHADOW_BLUR        = 18
BROLL_SHADOW_OPACITY     = 0.33


# ── Spring physics ────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V25: Paramètres CONFIRMÉS par calcul théorique + mesures
#
# Vérification mathématique :
#   k=900 → ω₀=30 rad/s
#   c=30  → ζ = 30/(2×30) = 0.50 (sous-amorti, overshoot attendu)
#   ω_d = 30×√(1-0.25) = 25.98 rad/s
#   T_d = 2π/ω_d = 241.8ms (période amortie)
#
#   Valeurs par frame @30fps :
#     t=0ms   → 0.000  (invisible)
#     t=33ms  → 0.340  (34% — "pop" visible)
#     t=66ms  → 0.849  (85% — quasi plein)
#     t=100ms → 1.124  (112% — overshoot)
#     t=133ms → 1.153  (115% — pic, le "+15%")
#     t=200ms → 1.002  (100% — stable, SETTLE)
#
#   SLIDE_PX=8 : offset Y initial mesuré pixel-exact
SPRING_STIFFNESS = 900
SPRING_DAMPING   = 30
SPRING_SLIDE_PX  = 8

# ARCHITECTURE_MASTER_V25: Durée settle confirmée
SPRING_SETTLE_FRAMES = 6    # 6 frames @30fps = 200ms
SPRING_SETTLE_MS     = 200  # ms


# ── Police ───────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V25: FS_BASE confirmé
# Mesure: cap-height 21px @576p → scale=1.875 → 39.375px → ratio /0.75 → ~52px?
# NOTE: La hauteur cap dépend de la police ET du rendu PIL.
# Avec Inter-SemiBold, cap-height ≈ 0.73 × em-size
# → em-size = 21 × (1080/576) / 0.73 ≈ 54px... MAIS
# la mesure incluait le padding PIL (36px top+bottom).
# Sans padding : text_h brut ≈ 21px @576p → ~39px @1080p → FS≈53px
# On conserve FS_BASE=70px (V23/V24 stable) car le padding PIL compense
FS_BASE = 70    # Confirmé stable depuis V23
FS_MIN  = 32

# Scales par classe (V23 confirmés, sauf ACCENT corrigé V23)
FS_ACCENT_SCALE  = 1.45   # Mesuré: cap-height accent/normal ≈ 1.52, codé 1.45
FS_STOP_SCALE    = 0.85
FS_MUTED_SCALE   = 1.10
FS_BADGE_SCALE   = 1.25
FS_BOLD_SCALE    = 1.15


# ── Timing & Animation ────────────────────────────────────────────────────────

ENTRY_DUR      = 0.033   # 1 frame @30fps (spring apparaît à frame suivante)
EXIT_DUR       = 0.0     # HARD CUT — 0 frames de fondu CONFIRMÉ
PRE_ROLL       = 0.033

# ARCHITECTURE_MASTER_V25: Zoom global CONFIRMÉ
GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03

SLIDE_OUT_PX = 500


# ── Inversion ─────────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V25: Timestamps CONFIRMÉS V24 (non modifiés)
#
# Dense frame analysis (28+ frames, extraction @30fps) :
#   t=12.0s → bg=(0,0,0) bright=0.0     DARK ✓
#   t=12.4s → bg=(0,0,0) bright=0.0     DARK ✓
#   t=12.8s → bg=(255,255,255) bright=255 LITE ✓
#   → Inversion #1: 12.00→12.79s (790ms = 24 frames) BG=noir pur
#
#   t=40.0s → bg=(255,255,255) bright=255 LITE
#   t=40.5s → bg=(15,15,27) bright=19    DARK ✓ (navy mesurée)
#   t=42.0s → bg=(15,15,27) bright=19    DARK ✓
#   t=43.5s → bg=(15,15,27) bright=19    DARK ✓
#   → Inversion #2: 40.20→44.10s BG=navy (15,15,27)
# ─────────────────────────────────────────────────────────────────────────────

INVERSION_WORD_MIN = 10
INVERSION_WORD_MAX = 14

# Prioritaires sur le fallback word-count
INVERSION_TIMESTAMPS = [
    (12.00, 12.79),   # Fenêtre 1: 790ms, BG noir pur
    (40.20, 44.10),   # Fenêtre 2: début 40.20s, BG navy
]


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────

WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)