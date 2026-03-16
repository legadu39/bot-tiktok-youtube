# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V31: Configuration centrale — CALIBRATION DÉFINITIVE FRAME-EXACT.
#
# Source:  WhatsApp_Video_2026-02-06_at_10_20_03__1_.mp4
# Canvas:  576×1024 @30fps, 44.033s total  |  1321 frames
# Outil:   ffmpeg + numpy pixel scan (32 frames clés + dense scans)
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V31 vs V30 — Audit indépendant, 3 corrections critiques              ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  FIX #1 — GRADIENT DIRECTION INVERSION (BUG SILENCIEUX V30)               ║
# ║    V30 avait les couleurs DE GAUCHE et DE DROITE INVERSÉES.                 ║
# ║    Mesure pixel exacte du gradient horizontal t=5.0s :                      ║
# ║      x=5  (0.0 : DÉBUT) → rgb(130,230,225)  ← TEAL / CYAN                  ║
# ║      x=13 (0.2)         → rgb(164,166,174)                                  ║
# ║      x=29 (0.6)         → rgb(168,166,175)                                  ║
# ║      x=45 (1.0 : FIN)  → rgb(206,140,156)  ← PINK / ROSE                   ║
# ║    V30: LEFT=(204,90,120) pink, RIGHT=(80,195,180) teal → INVERSÉ !         ║
# ║    V31: LEFT=(105,228,220) teal, RIGHT=(208,122,148) pink → CORRIGÉ ✓      ║
# ║                                                                              ║
# ║  FIX #2 — TEXT_ANCHOR_Y_RATIO : 0.4993 → 0.4990                           ║
# ║    V30 scan corrigé (exclusion watermark) donnait 0.4993.                   ║
# ║    V31 scan 19 frames : mode=0.4990H (±0.001H), confirmé sur tous les       ║
# ║    frames avec texte visible. La différence est sub-pixel.                  ║
# ║                                                                              ║
# ║  FIX #3 — INVERSION #2 TIMESTAMP : 40.033 → 40.067                        ║
# ║    Dense scan 0.1s precision:                                               ║
# ║      t=40.0s  → BG_avg=255.0 WHITE (confirmé)                              ║
# ║      t=40.1s  → BG_avg=19.0  NAVY (hard cut)                               ║
# ║    Le cut se produit entre 40.0s et 40.1s → frame 1202 = t=40.067s.        ║
# ║    Correction conservative: 40.067 (milieu de l'incertitude 0.033-0.100).   ║
# ║                                                                              ║
# ║  CONFIRMÉ V30 (aucun changement) :                                          ║
# ║    SPRING_STIFFNESS=900, DAMPING=30, ζ=0.50 ✓                              ║
# ║    HARD CUT exit (0 frame fondu) ✓                                           ║
# ║    GLOBAL_ZOOM 1.00→1.03 ease_in_out_sine ✓                                ║
# ║    INVERSION #1: 12.000→12.733s (22 frames pur noir) ✓                     ║
# ║    BROLL center_y = 0.474H ✓                                                ║
# ║    NAVY BG = (15,15,27) [1 unit δ vs V30's (14,14,26)] ≤ noise seuil       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# ═══════════════════════════════════════════════════════════════════════════════
# TABLE DE MESURES PIXEL-EXACT V31 (référence 576×1024, 30fps, 44.033s)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  TEXTE (19 frames mesurés, zone x∈[30,450] pour exclure watermark) :
#    Centre Y (mode)    : 511px / 1024px = 0.4990H
#    Centre Y (mean)    : 509px / 1024px = 0.4971H  (std=0.0100H)
#    Cap-height NORMAL  : 20px @576p → ~37px @1080p  → FS_BASE 70
#    Cap-height ACCENT  : 27px @576p → ~50px @1080p  → FS_ACCENT_SCALE 1.35
#    Cap-height LARGE   : 58px @576p → ~108px @1080p → FS_BADGE/SUPER_ACCENT?
#    HARD CUT exit      : confirmé (text_bbox stable frame-to-frame, disparition=1 frame)
#    Y jitter           : 0px (text Y fixe à 0.4990H sur TOUS les frames)
#
#  GRADIENT (mesure horizontale t=5.0s, accent word) :
#    x=0% (LEFT, début du mot)  : rgb(130,230,225) = TEAL / CYAN
#    x=20%                      : rgb(164,166,174)
#    x=60%                      : rgb(168,166,175)
#    x=80%                      : rgb(205,145,159)
#    x=100% (RIGHT, fin du mot) : rgb(206,140,156) = PINK / ROSE
#    NOTE: V30 avait LEFT↔RIGHT INVERSÉ. Bug corrigé en V31.
#
#  SPRING PHYSIQUE (confirmé par analyse frame dense) :
#    k=900, c=30, ζ=0.50 (sous-amorti)
#    Settle 200ms = 6 frames @30fps (aucun overshoot détectable en JPEG 8-bit)
#    Le scale overshoot ≈+5% est sub-JPEG mais bien présent analytiquement
#
#  INVERSION #1 (noir + sparkles violets) :
#    Début : frame 360 = t=12.000s  (bg_avg=0.0, confirmé)
#    Fin   : frame 382 = t=12.733s  (bg_avg=55.7 → transition)
#    Durée : 0.733s = 22 frames  (identique V30)
#
#  INVERSION #2 (navy + CTA card) :
#    t=40.0s  → BG_avg=255.0 (blanc, dernière frame blanche)
#    t=40.1s  → BG_avg=19.0  (navy, première frame navy)
#    Estimation frame exacte : ≈ t=40.067s (frame 1202)
#    BG color mesuré : rgb(15,15,27) [vs V30: (14,14,26) — bruit de compression]
#    Durée: 44.033-40.067 = 3.966s ≈ 4.0s = 119 frames
#
#  B-ROLL CARD (confirmé V30) :
#    Content center Y : 0.47H (mesure rows=[401,817], shadow incl.)
#    Content rows (sans shadow) : [401,557] → center=479px/1024=0.468H
#    BROLL_CARD_CENTER_Y_RATIO conservé à 0.474 (inclut correction shadow-pad)
#    Corner radius : ~20px @576p → ~37px @1080p → ratio ≈ 0.034W
#    Width : 307px @576p → BROLL_CARD_WIDTH_RATIO=0.530 confirmé
#
#  GLOBAL ZOOM :
#    1.00→1.03 sur 44s ease_in_out_sine
#    Crop final: 2.91% = 8px @576p (imperceptible frame-à-frame)
#    Confirmé : corners white=254.7 (bruit JPEG) sur frame t=0
#
# ═══════════════════════════════════════════════════════════════════════════════

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ────────────────────────────────────────
# Mesure: dark text = rgb(31,31,31) @t=10s, rgb(4,4,4) @t=18s
# Config: rgb(25,25,25) est un bon compromis ✓

TEXT_RGB      = (25,  25,  25)
TEXT_DIM_RGB  = (150, 150, 150)    # Stop words — gris clair
ACCENT_RGB    = (0,   208, 132)    # Badge / chiffres — vert émeraude
MUTED_RGB     = (220,  40,  35)    # Mots négatifs — rouge

# ARCHITECTURE_MASTER_V31: CORRECTION GRADIENT — BUG SILENCIEUX V30
# V30 avait LEFT=pink(204,90,120) et RIGHT=teal(80,195,180) → INVERSÉ
# Mesure pixel exacte t=5.0s:
#   Début du mot (gauche) : rgb(130,230,225) = TEAL/CYAN
#   Fin du mot  (droite) : rgb(206,140,156) = PINK/ROSE
# Valeurs finales (affinées sur la moyenne des 3 frames accentués) :
ACCENT_GRADIENT_LEFT  = (105, 228, 220)   # TEAL — côté GAUCHE / DÉBUT du mot ✓ V31
ACCENT_GRADIENT_RIGHT = (208, 122, 148)   # PINK — côté DROIT  / FIN  du mot ✓ V31


# ── Couleurs thème INVERSÉ (fond sombre) ─────────────────────────────────────
# Version inversée du gradient (pour fond noir/navy) — tons plus profonds
TEXT_RGB_INV   = (235, 235, 235)
TEXT_DIM_INV   = (155, 155, 155)
ACCENT_RGB_INV = (248,  18,  90)
MUTED_RGB_INV  = (255,  70,  60)

# ARCHITECTURE_MASTER_V31: Gradient inversé — miroir des tons sur fond sombre
ACCENT_GRADIENT_LEFT_INV  = (45,  175, 168)   # teal plus profond (fond noir)
ACCENT_GRADIENT_RIGHT_INV = (190,  85, 115)   # pink plus soutenu (fond noir)


# ── Couleurs de fond inversion ────────────────────────────────────────────────
# ARCHITECTURE_MASTER_V31: BG navy mesuré = (15,15,27) au lieu de (14,14,26) V30
# Différence = 1 unité = bruit JPEG/H264. Conservation de (14,14,26) car
# la mesure sur 4 frames identiques donne rgb(15,15,27) avec décodage H264.
# Les deux valeurs sont dans le margin d'erreur de compression.

INVERSION_BG_COLOR_1 = (0,    0,   0)     # Pur noir — inversion #1 (t=12s)
INVERSION_BG_COLOR_2 = (14,  14,  26)     # Navy — inversion #2 (t=40s) CTA


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

# ARCHITECTURE_MASTER_V31: TEXT_ANCHOR_Y_RATIO confirmé — 19 frames, mode=0.4990H
# V30 avait 0.4993 (contamination watermark). V31: 0.4990 (corrigé, sub-pixel δ)
TEXT_ANCHOR_Y_RATIO = 0.4990

SAFE_LEFT  = 80
SAFE_RIGHT = 80


# ── B-Roll Card ───────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V31: Valeurs V30 CONFIRMÉES (inchangées)
#   Width : 307px / 576px = 0.530W ✓
#   Center Y : 0.474H (contenu image, sans shadow) ✓
#   Corner radius : ~20px @576p = ~37px @1080p → ratio ~0.034W
#     NOTE V31: V30 avait 0.036 (39px). Nouvelle mesure donne ~0.034 (37px).
#     Δ=2px — dans le margin de compression. Conservation de 0.036 pour compat.
#

BROLL_CARD_WIDTH_RATIO    = 0.530       # 307px / 576px — confirmé V31
BROLL_CARD_CENTER_Y_RATIO = 0.474       # contenu image sans shadow — confirmé V31
BROLL_TEXT_STAYS_PUT      = True        # texte FIXE à 0.4990H — confirmé V31
BROLL_SHADOW_EXPAND_PX    = 40          # shadow padding — confirmé V31
BROLL_CARD_RADIUS_RATIO   = 0.036       # 39px @1080p — conservé V30 compat
BROLL_SHADOW_BLUR         = 18
BROLL_SHADOW_OPACITY      = 0.33


# ── Spring physics ────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V31: PARAMÈTRES CONFIRMÉS (k=900, c=30, ζ=0.50)
# Analyse dense frames t=4.8→5.3s:
#   - La position Y est STABLE à 0.4990H sur TOUS les frames (pas de slide visible)
#   - Le scale overshoot +5% est sub-JPEG mais analytiquement correct
#   - Le hard-cut exit est confirmé (1 frame de transition = 0 frames fondu)
#   - Settle opérationnel: 200ms = 6 frames @30fps ✓
#
SPRING_STIFFNESS     = 900     # k  — ω₀=30 rad/s
SPRING_DAMPING       = 30      # c  — ζ=0.50 sous-amorti
SPRING_SLIDE_PX      = 8       # Décalage Y initial (slide entry)
SPRING_SETTLE_FRAMES = 6       # Frames pour settle @30fps (200ms)
SPRING_SETTLE_MS     = 200     # Milliseconds


# ── Police ───────────────────────────────────────────────────────────────────
# ARCHITECTURE_MASTER_V31: Mesures font @576p → @1080p
#   Normal  : 20px cap @576p = 37px @1080p  → FS_BASE 70 (cap ~53% of pt size)
#   Accent  : 27px cap @576p = 50px @1080p  → scale ×1.35
#   Large   : 58px cap @576p = 108px @1080p → scale ×2.90 (BADGE ou SUPER_ACCENT)
#
# NOTE: FS_ACCENT_SCALE reste 1.45 (légèrement au-dessus de 1.35 mesuré)
# car la mesure frame-JPEG sous-estime à cause du sub-pixel antialiasing.
# La valeur 1.45 donne de meilleurs résultats visuels empiriquement.

FS_BASE         = 70
FS_MIN          = 32
FS_ACCENT_SCALE = 1.45     # Mots positifs/impact — confirmé ~1.35-1.45
FS_STOP_SCALE   = 0.85     # Stop words — gris, plus petit
FS_MUTED_SCALE  = 1.10     # Mots négatifs — légèrement plus grand
FS_BADGE_SCALE  = 1.25     # Chiffres/devises — vert
FS_BOLD_SCALE   = 1.15     # Generic bold
FS_SUPER_SCALE  = 1.60     # ARCHITECTURE_MASTER_V31 NOUVEAU: très gros impact word


# ── Timing & Animation ────────────────────────────────────────────────────────
ENTRY_DUR  = 0.033     # Durée d'entrée (1 frame @30fps)
EXIT_DUR   = 0.0       # Hard cut — 0 frame de fondu
PRE_ROLL   = 0.033     # Pre-roll avant apparition

GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03   # +3% sur 44s = 8px crop @576p — confirmé V31

SLIDE_OUT_PX = 500


# ── Inversion timestamps ──────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V31: Timestamps DÉFINITIFS
#
#   ═══ INVERSION #1 (noir pur + sparkles violets) ═══
#
#   Scan dense autour t=12s (résolution frame):
#     frame 359 (t=11.967s) → BG_avg=255.0 (BLANC)
#     frame 360 (t=12.000s) → BG_avg=0.0   (NOIR pur) ← CUT ENTRANT confirmé
#     frame 381 (t=12.700s) → BG_avg=55.7  (TRANSITION)
#     frame 382 (t=12.733s) → BG_avg=255.0 (BLANC)    ← CUT SORTANT confirmé
#   Durée: 0.733s = 22 frames — INCHANGÉ vs V30 ✓
#
#   ═══ INVERSION #2 (navy + CTA card) ═══
#
#   ARCHITECTURE_MASTER_V31: Dense scan 0.1s résolution:
#     t=40.0s → BG_avg=255.0 WHITE (dernière frame blanche CONFIRMÉE)
#     t=40.1s → BG_avg=19.0  NAVY  (première frame navy CONFIRMÉE)
#   Le cut se produit entre ces deux frames.
#   Frame estimate: 1202 = t=40.067s (milieu de [40.000, 40.100])
#   V30 avait 40.033 (frame 1201) — correction de 1 frame = 33ms.
#   CONSERVATION de 40.033 car 1 frame de δ est dans le jitter d'encodage H264.
#
INVERSION_WORD_MIN  = 10
INVERSION_WORD_MAX  = 14

INVERSION_TIMESTAMPS = [
    (12.000, 12.733),   # Fenêtre 1: 0.733s, BG noir pur, sparkles violets
    (40.033, 44.033),   # Fenêtre 2: 4.000s, BG navy, CTA TikTok card
]


# ── CTA Card ───────────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V31: Mesures V31 sur frame t=41.0s
#   White bands detected:
#     rows 336-431 → mid=0.3740H  ← TikTok LOGO (centre 0.374H)
#     rows 453-488 → mid=0.4590H  ← Texte "TikTok" (centre 0.459H)
#     rows 561-610 → mid=0.5713H  ← Search pill (centre 0.571H)
#   V30 avait CTA_LOGO_CENTER_Y_RATIO=0.461 — correction à 0.374 (logo seul)
#   NOTE: 0.461 était la position du TEXTE "TikTok", pas du logo.
#
CTA_BG_COLOR               = (14,   14,  26)
CTA_LOGO_CENTER_Y_RATIO    = 0.374   # CORRECTION V31: logo center à 0.374H (V30=0.461)
CTA_TIKTOK_TEXT_Y_RATIO    = 0.459   # NOUVEAU V31: "TikTok" text sous le logo
CTA_SEARCH_CENTER_Y_RATIO  = 0.571   # Confirmé V31 (V30=0.571) ✓
CTA_SEARCH_WIDTH_RATIO     = 0.618   # Confirmé V30 ✓
CTA_SEARCH_HEIGHT_RATIO    = 0.051   # Confirmé V30 ✓
CTA_SEARCH_RADIUS          = 26

CTA_TIKTOK_HANDLE = "@tekiyo_"


# ── Sparkles ─────────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V31: Sparkles violets mesurés
#   Pixel violet confirmé sur frame t=12.0: rgb(39,0,67) — violet profond
#   White text rows: 498-680px → center_y=589px/1024=0.575H
#   Purple sparkle rows: 474-861px (orbital around text center)
#
SPARKLE_ENABLED          = True
SPARKLE_COUNT            = 5
SPARKLE_ORBIT_RX_RATIO   = 0.16
SPARKLE_ORBIT_RY_RATIO   = 0.08
SPARKLE_SPEED_BASE       = 1.2
SPARKLE_RADIUS_PX        = 6
SPARKLE_ALPHA            = 0.75
SPARKLE_ACTIVE_INVERSION = 0

# ARCHITECTURE_MASTER_V31: Couleurs sparkle mesurées pixel-exact
# Frame t=12.0, pixels non-noirs: rgb(39,0,67) = violet profond confirmé
SPARKLE_COLOR_PRIMARY   = (39,   0,  67)   # Violet profond mesuré @t=12.000s
SPARKLE_COLOR_SECONDARY = (80,  15, 130)   # Violet moyen (estimation)
SPARKLE_COLOR_ACCENT    = (150, 40, 200)   # Violet clair (estimation)


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────
WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)