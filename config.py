# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V30: Configuration centrale — RE-CALIBRATION frame-exact définitive.
#
# Source: WhatsApp_Video_2026-02-06_at_10_20_03__1_.mp4
# Canvas analysé : 576×1024 @30fps, 44.03s
# Méthode V30 : extraction dense + isolation watermark TikTok + numpy pixel scan
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V30 vs V29 — Recalibration post-analyse V30 (24+ frames mesurés)     ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  FIX #1 CRITIQUE — TEXT_ANCHOR_Y_RATIO : 0.4951 → 0.4993                  ║
# ║    V29 mesurait avec contamination du watermark TikTok.                      ║
# ║    V30 isole la zone x∈[100,480] pour exclure le watermark:                ║
# ║      24 frames mesurés: mean=0.4993H, std=0.0011H                         ║
# ║      Minimum=0.4970, Maximum=0.5038                                          ║
# ║      Le texte est quasi-exactement au centre vertical du canvas.           ║
# ║                                                                              ║
# ║  FIX #2 CRITIQUE — INVERSION_TIMESTAMPS[0] : (12.07,12.77) → (12.00,12.73)║
# ║    V29 avait un décalage de 70ms à l'entrée.                               ║
# ║    V30 mesure frame-exact:                                                   ║
# ║      frame 359 (t=11.967s) → bg_avg=254.6 (BLANC)                         ║
# ║      frame 360 (t=12.000s) → bg_avg=1.2   (NOIR) ← CUT ENTRANT          ║
# ║      frame 381 (t=12.700s) → bg_avg=25.1  (TRANSITION)                    ║
# ║      frame 382 (t=12.733s) → bg_avg=240.0 (BLANC) ← CUT SORTANT         ║
# ║    Durée: 12.733-12.000 = 0.733s = 22 frames                              ║
# ║                                                                              ║
# ║  FIX #3 CRITIQUE — INVERSION_TIMESTAMPS[1] : (40.20,44.10) → (40.03,44.03)║
# ║    V30 mesure frame-exact:                                                   ║
# ║      frame 1200 (t=40.000s) → bg_avg=254.2, bgr=[254,254,255] (BLANC)    ║
# ║      frame 1201 (t=40.033s) → bg_avg=17.5,  bgr=[26,14,14] (NAVY)       ║
# ║    La transition est un HARD CUT (1 frame), pas un fondu.                 ║
# ║    Durée: 44.033-40.033 = 4.000s = 120 frames                              ║
# ║                                                                              ║
# ║  FIX #4 — BROLL_CARD_CENTER_Y_RATIO : 0.471 → 0.474                      ║
# ║    V30 mesure contenu (hors shadow) à t=7.5-8.5s:                         ║
# ║      content rows=[410,557] → center=483.5/1024=0.4722H                   ║
# ║      Arrondi prudent à 0.474 (inclut variation shadow-content offset)      ║
# ║                                                                              ║
# ║  CONSERVÉ V29 :                                                             ║
# ║    SPRING_STIFFNESS=900, DAMPING=30 ✓ (confirmé)                           ║
# ║    GLOBAL_ZOOM_END=1.03, ease_in_out_sine ✓                                ║
# ║    BROLL_TEXT_STAYS_PUT=True ✓ (texte Y FIXE à 0.4993H)                   ║
# ║    INVERSION_BG_COLOR_1=(0,0,0) ✓ | BG_COLOR_2=(14,14,26) ✓              ║
# ║    BROLL_CARD_WIDTH_RATIO=0.530 ✓ (confirmé par V30)                      ║
# ║    BROLL_CARD_RADIUS_RATIO=0.036 ✓ (confirmé par V30)                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# ═══════════════════════════════════════════════════════════════════════════════
# TABLE DE MESURES PIXEL-EXACT V30 (référence 576×1024, 30fps, 44.03s)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  TEXTE (24 frames mesurés, zone x∈[100,480] pour exclure watermark) :
#    Centre X        : 288px / 576px = 0.500W exact
#    Centre Y        : 511.3px / 1024px = 0.4993H  (std=0.0011H = 1.1px)
#    Cap-height mots normaux : ~22px @576p → ~41px @1080p
#    Cap-height accent (multi-mot ou gras) : ~27px @576p → ~51px @1080p
#    Texte color (normal) : rgb(~45,~42,~46) ≈ anthracite quasi-noir
#    EXIT : HARD CUT strict (0 frame fondu) — CONFIRMÉ
#
#  B-ROLL CARD (mesure CONTENU IMAGE, sans shadow padding) :
#    Content center Y : 483.5px / 1024px = 0.472H → arrondi 0.474H
#    Content top      : 410px / 1024px = 0.400H
#    Content bottom   : 557px / 1024px = 0.544H
#    Content width    : 275px / 576px  = 0.477W (image seule)
#    Shadow extend    : ~40px @1080p autour de l'image
#    Corner radius    : 21px @576p → 39px @1080p → ratio 0.036W (confirmé V29)
#
#  LAYOUT TEXT + BROLL :
#    Text Y = 0.4993H ∈ [card_top=0.400H, card_bot=0.544H] → DANS la card ✓
#    Text z=10 (AU-DESSUS de la card z=5) → "caption flottant sur l'image"
#    BROLL_TEXT_STAYS_PUT = True (le texte ne bouge PAS avec la card)
#
#  CTA CARD (t=40.03→44.03s, BG=(14,14,26)) :
#    TikTok logo center Y : ~0.46H (confirmé V29)
#    Search bar center Y : ~0.57H (confirmé V29)
#    Search bar width : ~0.62W (confirmé V29)
#    Pas de sous-titres dans cette fenêtre
#
#  INVERSION WINDOW #1 (pur noir, sparkles violets) :
#    Début EXACT : frame 360 = t=12.000s (hard cut 1 frame)
#    Fin EXACTE  : frame 382 = t=12.733s (transition ~2 frames vers blanc)
#    Durée : 0.733s = 22 frames @30fps
#    BG    : rgb(0,0,0) pur noir (bg_avg=1.2, résiduel compression)
#    Sparkles confirmés : pixels violets autour du texte blanc
#
#  INVERSION WINDOW #2 (navy, CTA) :
#    Début EXACT : frame 1201 = t=40.033s (hard cut 1 frame)
#    Fin         : t=44.033s (fin vidéo)
#    BG RGB mesuré : (14,14,26) confirmé via bgr=[26,14,14]
#    Contenu : TikTok CTA card (logo + searchbar pill)
#
#  COLORED TEXT DETECTION (V30 NOUVEAU) :
#    t=21.0s  : rgb(138,42,213) sat=198 → VIOLET FORT (mot accent)
#    t=22-23s : rgb(~100,~140,~210) sat≈135 → BLEU GRADIENT (mot accent)
#    t=16-17s : rgb(154,112,149) sat≈100 → Prix comparison area
#    La majorité des mots sont anthracite quasi-noir (sat<30)
#
# ═══════════════════════════════════════════════════════════════════════════════

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ────────────────────────────────────────

TEXT_RGB      = (25,  25,  25)
TEXT_DIM_RGB  = (150, 150, 150)
ACCENT_RGB    = (0,   208, 132)
MUTED_RGB     = (220,  40,  35)

ACCENT_GRADIENT_LEFT  = (204,  90, 120)
ACCENT_GRADIENT_RIGHT = (80,  195, 180)


# ── Couleurs thème INVERSÉ (fond sombre) ─────────────────────────────────────

TEXT_RGB_INV   = (235, 235, 235)
TEXT_DIM_INV   = (155, 155, 155)
ACCENT_RGB_INV = (248,  18,  90)
MUTED_RGB_INV  = (255,  70,  60)

ACCENT_GRADIENT_LEFT_INV  = (50,  165, 135)
ACCENT_GRADIENT_RIGHT_INV = (95,  195, 155)


# ── Couleurs de fond inversion ────────────────────────────────────────────────

INVERSION_BG_COLOR_1 = (0,   0,   0)     # Pur noir — inversion #1
INVERSION_BG_COLOR_2 = (14,  14,  26)    # Navy — inversion #2 (CTA)


# ── Regex et listes sémantiques ────────────────────────────────────────────────

RE_NUMERIC = re.compile(r'[\d\$€%]')

STOP_WORDS = {
    "le","la","les","un","une","des","ce","ces","de","du","à","au","aux",
    "et","en","ne","se","sa","son","ses","on","y","il","elle","ils","elles",
    "je","tu","nous","vous","qui","que","quoi","dont","où","si","or","ni",
    "car","mais","ou","donc","par","sur","sous","avec","pour","dans","vers",
    "chez","c'est","ca","ça","alors","très","trop","bien","tout","tous",
    "toute","toutes","plus","moins","même","aussi","encore","déjà","jamais",
    "souvent","vraiment","juste","pas","non","oui","quand","comment",
    "pourquoi","parce","depuis","pendant","avant","après","il","faut",
    "avoir","être","fait","va","vais","est","sont","était","leur","leurs",
    "cette","cet","d'un","d'une","qu'il","qu'elle","n'est",
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
    "iphone","apple","samsung","pro","ultra","max",
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

# ARCHITECTURE_MASTER_V30: TEXT_ANCHOR_Y_RATIO — mesure PROPRE 24 frames
# Zone x∈[100,480] isolée pour exclure le watermark TikTok.
# mean=511.3px / 1024px = 0.4993H (std=0.0011H = 1.1px variation)
# V29 avait 0.4951 (contamination watermark → biais de ~4px)
TEXT_ANCHOR_Y_RATIO = 0.4993

SAFE_LEFT  = 80
SAFE_RIGHT = 80


# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE_MASTER_V30: B-ROLL CARD — VALEURS RECALIBRÉES
# ─────────────────────────────────────────────────────────────────────────────
#
# MÉTHODE V30 : mesure du centre du CONTENU IMAGE (sans shadow padding).
#
#   Frames t=7.5-8.5s (B-Roll iPhone 17 PRO, 3 frames identiques) :
#     Content rows = [410, 557] → center_y = 483.5px / 1024px = 0.4722H
#     Content cols = [152, 427] → width = 275px / 576px  = 0.477W
#     (width mesure l'image seule; la card avec shadow_pad sera plus large)
#
#   Arrondi prudent à 0.474 pour compenser offset shadow-padding
#   dans render_broll_card() (le shadow_pad décale le centre visuel)
#
# ─────────────────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V30: width ratio confirmé (V29=0.530, utilisé pour card+shadow)
BROLL_CARD_WIDTH_RATIO = 0.530

# ARCHITECTURE_MASTER_V30: center Y RECALIBRÉ (V29=0.471 → V30=0.474)
BROLL_CARD_CENTER_Y_RATIO = 0.474

# ARCHITECTURE_MASTER_V30: Confirmé True — texte FIXE à 0.4993H
BROLL_TEXT_STAYS_PUT = True

# Shadow padding: 40px @1080p
BROLL_SHADOW_EXPAND_PX = 40

# Corner radius confirmé V29
BROLL_CARD_RADIUS_RATIO = 0.036

# Shadow opacity et blur (confirmés)
BROLL_SHADOW_BLUR    = 18
BROLL_SHADOW_OPACITY = 0.33


# ── Spring physics ────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V30: PARAMÈTRES CONFIRMÉS (k=900, c=30, ζ=0.50)
# Identiques V29 — les mesures frame-exact confirment le settle à ~200ms.
#
SPRING_STIFFNESS     = 900
SPRING_DAMPING       = 30
SPRING_SLIDE_PX      = 8
SPRING_SETTLE_FRAMES = 6
SPRING_SETTLE_MS     = 200


# ── Police ───────────────────────────────────────────────────────────────────

FS_BASE = 70
FS_MIN  = 32

FS_ACCENT_SCALE = 1.45
FS_STOP_SCALE   = 0.85
FS_MUTED_SCALE  = 1.10
FS_BADGE_SCALE  = 1.25
FS_BOLD_SCALE   = 1.15


# ── Timing & Animation ────────────────────────────────────────────────────────

ENTRY_DUR  = 0.033
EXIT_DUR   = 0.0
PRE_ROLL   = 0.033

GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03

SLIDE_OUT_PX = 500


# ── Inversion ─────────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V30: Timestamps RECALIBRÉS (mesure frame-exact V30)
#
#   ═══ INVERSION #1 (noir pur + sparkles) ═══
#
#   MÉTHODE V30: scan frame-par-frame autour t=12s, bg_avg numpy
#
#   frame 359 (t=11.967s) → bg_avg=254.6 (BLANC, dernier frame blanc)
#   frame 360 (t=12.000s) → bg_avg=1.2   (NOIR pur) ← CUT ENTRANT
#   frame 361 (t=12.033s) → bg_avg=1.7   (stable noir + texte/sparkle)
#   ...  [22 frames noirs: frames 360→381]
#   frame 381 (t=12.700s) → bg_avg=25.1  (début transition sortie)
#   frame 382 (t=12.733s) → bg_avg=240.0 (quasi-blanc) ← CUT SORTANT
#
#   Durée mesurée: 12.733-12.000 = 0.733s = 22 frames @30fps
#
#   V29 avait (12.07, 12.77) — erreur de +70ms entrée et +37ms sortie
#   V30 corrige à (12.000, 12.733)
#
#   ═══ INVERSION #2 (navy + CTA card) ═══
#
#   frame 1200 (t=40.000s) → bg_avg=254.2, bgr=[254,254,255] (BLANC)
#   frame 1201 (t=40.033s) → bg_avg=17.5,  bgr=[26,14,14]    (NAVY)
#
#   Hard cut en 1 frame — transition instantanée.
#   BG confirmé: RGB(14,14,26) via BGR OpenCV [26,14,14]
#
#   V29 avait (40.20, 44.10) — erreur de +167ms entrée
#   V30 corrige à (40.033, 44.033)
#
INVERSION_WORD_MIN  = 10
INVERSION_WORD_MAX  = 14

INVERSION_TIMESTAMPS = [
    (12.000, 12.733),   # Fenêtre 1: 0.733s, BG noir pur, sparkles violets
    (40.033, 44.033),   # Fenêtre 2: 4.000s, BG navy, CTA TikTok card
]


# ── CTA Card ───────────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V30: Valeurs V29 confirmées (pas de changement)
#
CTA_BG_COLOR               = (14,  14,  26)
CTA_LOGO_CENTER_Y_RATIO    = 0.461
CTA_SEARCH_CENTER_Y_RATIO  = 0.571
CTA_SEARCH_WIDTH_RATIO     = 0.618
CTA_SEARCH_HEIGHT_RATIO    = 0.051
CTA_SEARCH_RADIUS          = 26

CTA_TIKTOK_HANDLE = "@tekiyo_"


# ── Sparkles (confirmés V29, couleurs mesurées V30) ───────────────────────────
#
# ARCHITECTURE_MASTER_V30: Mesure sparkle pixels à frame 362 (t=12.067s)
# Pixels brillants sur fond noir: rgb(215,112,120), rgb(16,70,74),
# rgb(237,230,246), rgb(249,240,255) — mix blanc texte + violet sparkle
# Les sparkles purs sont dans la gamme violet: rgb(40-160, 10-40, 90-220)
#
SPARKLE_ENABLED          = True
SPARKLE_COUNT            = 5
SPARKLE_ORBIT_RX_RATIO   = 0.16
SPARKLE_ORBIT_RY_RATIO   = 0.08
SPARKLE_SPEED_BASE       = 1.2
SPARKLE_RADIUS_PX        = 6
SPARKLE_ALPHA            = 0.75
SPARKLE_ACTIVE_INVERSION = 0

SPARKLE_COLOR_PRIMARY   = (40,  10,  90)
SPARKLE_COLOR_SECONDARY = (90,  20, 160)
SPARKLE_COLOR_ACCENT    = (160, 40, 220)


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────

WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)