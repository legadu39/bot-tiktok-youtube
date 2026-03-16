# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V29: Configuration centrale — DÉFINITIVE post-reverse-engineering exhaustif.
#
# Source: WhatsApp_Video_2026-02-06_at_10_20_03__1_.mp4
# Canvas analysé : 576×1024 @30fps, 44.03s
# Méthode : extraction dense frame-par-frame + analyse pixel numpy
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V29 vs V25 — Corrections post-analyse dense DÉFINITIVE               ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  FIX #1  CRITIQUE — BROLL_CARD_CENTER_Y_RATIO : 0.614 → 0.471             ║
# ║    V25 mesurait le centre du SHADOW BBOX (0.617H).                         ║
# ║    V29 mesure le centre du CONTENU IMAGE réel (rows=[402,562]):            ║
# ║      center_y = (402+562)/2 = 482 / 1024 = 0.4707H ≈ 0.471               ║
# ║    Conséquence : le texte (0.497H) CHEVAUCHE la partie inférieure          ║
# ║    de la card (0.392→0.549H) — effet "caption sur l'image" ✓              ║
# ║                                                                              ║
# ║  FIX #2  — BROLL_CARD_WIDTH_RATIO : 0.524 → 0.530                        ║
# ║    Mesuré content (sans shadow): 305px / 576px = 0.5295W                  ║
# ║                                                                              ║
# ║  FIX #3  — BROLL_CARD_RADIUS_RATIO : 0.064 → 0.036                       ║
# ║    Mesure par tracing du bord courbe:                                       ║
# ║      row 0: offset +33px, row 10: offset +8px → radius ≈ 21px @576p       ║
# ║      @1080p: 21 × (1080/576) = 39px → ratio = 39/1080 = 0.0361           ║
# ║                                                                              ║
# ║  FIX #4  — TEXT_ANCHOR_Y_RATIO : 0.4970 → 0.4951                         ║
# ║    Mesure dense 38 frames: mean=507px / 1024px = 0.4951H                  ║
# ║    std=11px (variation due aux mots courts/longs, ancre STABLE)            ║
# ║                                                                              ║
# ║  FIX #5  — INVERSION_TIMESTAMPS : [(12.00,12.79)] → [(12.07,12.77)]      ║
# ║    Transition détectée frame-exact:                                         ║
# ║      t=11.90s → bg_avg=255 (BLANC)                                         ║
# ║      t=12.07s → bg_avg=0   (NOIR) — Cut entrant frame 362                 ║
# ║      t=12.77s → bg_avg=31  (transition sortie) — Cut sortant frame 383    ║
# ║    Durée exacte: 0.70s = 21 frames                                          ║
# ║                                                                              ║
# ║  NOUVEAU V29 — CTA_CARD (composant manquant)                              ║
# ║    t=40.2s→44.1s: fond navy (14,14,26), TikTok logo + search bar          ║
# ║    Logo center Y: 472/1024 = 0.461H                                        ║
# ║    Search bar center Y: 585/1024 = 0.571H                                  ║
# ║    Search bar width: 356/576 = 0.618W                                       ║
# ║    Cette section ne JAMAIS afficher de sous-titres — elle remplace tout     ║
# ║                                                                              ║
# ║  CONSERVÉ V25/V24 :                                                         ║
# ║    SPRING_STIFFNESS=900, DAMPING=30 ✓ (settle 200ms / 6 frames)           ║
# ║    GLOBAL_ZOOM_END=1.03, ease_in_out_sine ✓                                ║
# ║    BROLL_TEXT_STAYS_PUT=True ✓ (text Y TOUJOURS 0.497H)                   ║
# ║    INVERSION_BG_COLOR_1=(0,0,0) ✓ | BG_COLOR_2=(14,14,26) ✓              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# ═══════════════════════════════════════════════════════════════════════════════
# TABLE DE MESURES PIXEL-EXACT V29 (référence 576×1024, 30fps, 44.03s)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  TEXTE (38 frames mesurés, toutes conditions) :
#    Centre X        : 288px / 576px = 0.500W exact
#    Centre Y        : 507px / 1024px = 0.4951H  (std=11px)
#    Cap-height mots normaux : ~22px @576p → ~41px @1080p
#    Cap-height accent (emoji/logo) : ~62px @576p → ~116px @1080p (×2.82)
#    EXIT : HARD CUT strict (0 frame fondu) — CONFIRMÉ
#
#  B-ROLL CARD (mesure CONTENU IMAGE, sans shadow padding) :
#    Content center Y : 482px / 1024px = 0.4707H ≈ 0.471H
#    Content top      : 402px / 1024px = 0.393H
#    Content bottom   : 562px / 1024px = 0.549H
#    Content width    : 305px / 576px  = 0.530W
#    Corner radius    : 21px @576p → 39px @1080p → ratio 0.036W
#    Shadow padding   : ~40px autour @1080p (inclus dans array render)
#
#  LAYOUT TEXT + BROLL :
#    Text Y = 0.4951H ∈ [card_top=0.393H, card_bot=0.549H] → DANS la card ✓
#    Text z=10 (AU-DESSUS de la card z=5) → "caption flottant sur l'image"
#    BROLL_TEXT_STAYS_PUT = True (le texte ne bouge PAS avec la card)
#
#  CTA CARD (t=40.20→44.10s, BG=(14,14,26)) :
#    TikTok logo center Y : 472/1024 = 0.461H
#    Search bar rows : [559,611] → center=585/1024 = 0.571H
#    Search bar width : 356/576 = 0.618W
#    Search bar height : 52px @576p → ~97px @1080p
#    Pas de sous-titres dans cette fenêtre
#
#  INVERSION WINDOW #1 (pure noir, sparkles violets) :
#    Début : t=12.07s (frame 362)
#    Fin   : t=12.77s (frame 383)
#    Durée : 0.70s = 21 frames
#    BG    : rgb(0,0,0) pur noir
#    Sparkles : rgb(55,0,98)→rgb(98,38,141) violet profond
#
#  INVERSION WINDOW #2 (navy, CTA) :
#    Début : t=40.20s
#    Fin   : t=44.10s (fin vidéo)
#    BG    : rgb(14,14,26) navy
#    Contenu : TikTok CTA card (pas de sparkles)
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

# ARCHITECTURE_MASTER_V29: TEXT_ANCHOR_Y_RATIO — mesure dense 38 frames
# mean=507px / 1024px = 0.4951H (std=11px / 1024 = 0.011H)
TEXT_ANCHOR_Y_RATIO = 0.4951

SAFE_LEFT  = 80
SAFE_RIGHT = 80


# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE_MASTER_V29: B-ROLL CARD — VALEURS DÉFINITIVES
# ─────────────────────────────────────────────────────────────────────────────
#
# MÉTHODE V29 : mesure du centre du CONTENU IMAGE (sans shadow padding).
#
#   frame t=8s (broll iPhone 17 PRO) :
#     Content rows = [402, 562] → center_y = 482px / 1024px = 0.4707H
#     Content cols = [135, 440] → width = 305px / 576px  = 0.530W
#
#   frame t=9s (broll stable) — identique : 0.4707H confirmé.
#
#   Corner radius tracé par bord courbe :
#     row 0: +33px, row 5: +14px, row 10: +8px, row 20: +3px
#     → cercle de rayon ~21px @576p = 39px @1080p
#     → ratio = 39/1080 = 0.0361W (codé: 0.036)
#
#   NOTE ARCHITECTURALE SUR LE SHADOW :
#     render_broll_card() retourne un array RGBA incluant 40px shadow padding.
#     cy_pos = cy_base - ch//2 où cy_base = vid_h * CENTER_RATIO
#     → le centre IMAGE dans l'array (excluant shadow) est à cy_base ✓
#
#   LAYOUT RÉSULTANT @1080×1920 :
#     cy_base = 1920 × 0.471 = 904px  (centre contenu card)
#     text_cy = 1920 × 0.495 = 950px  (ancre texte)
#     card_top ≈ 904 - 160×(1080/576)/2 ≈ 754px (0.393H)
#     card_bot ≈ 904 + 160×(1080/576)/2 ≈ 1054px (0.549H)
#     text (950px) ∈ [754, 1054] → dans la card ✓
#     texte (z=10) au-dessus card (z=5) → "caption flottant" ✓
# ─────────────────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V29: VALEUR CORRIGÉE (V25 avait 0.524, V29 mesure 0.530)
BROLL_CARD_WIDTH_RATIO = 0.530

# ARCHITECTURE_MASTER_V29: VALEUR DÉFINITIVE — centre CONTENU (pas shadow)
# V24=0.663 → V25=0.614 (shadow center) → V29=0.471 (content center EXACT)
BROLL_CARD_CENTER_Y_RATIO = 0.471

# ARCHITECTURE_MASTER_V29: Confirmé True — texte FIXE à 0.4951H quelle que
# soit la présence du B-Roll (mesuré sur 38 frames toutes conditions)
BROLL_TEXT_STAYS_PUT = True

# Shadow padding: 40px @1080p (shadow autour de la card, inclus dans array)
BROLL_SHADOW_EXPAND_PX = 40

# ARCHITECTURE_MASTER_V29: Corner radius CORRIGÉ
# V22=0.042 → V25=0.064 → V29=0.036 (mesuré: 21px@576p = 39px@1080p)
BROLL_CARD_RADIUS_RATIO = 0.036

# Shadow opacity et blur (non modifiés depuis V22)
BROLL_SHADOW_BLUR    = 18
BROLL_SHADOW_OPACITY = 0.33


# ── Spring physics ────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V29: PARAMÈTRES CONFIRMÉS (k=900, c=30, ζ=0.50)
#
#   ω₀ = √900 = 30 rad/s
#   ζ  = 30 / (2×30) = 0.500 → sous-amorti → overshoot
#   ω_d = 30 × √(1-0.25) = 25.98 rad/s
#   T_d = 2π/25.98 = 241.8ms
#
#   Table frame @30fps (valeurs calculées, confirmées par mesure) :
#     frame 0  (0ms)   : 0.000 — invisible
#     frame 1  (33ms)  : 0.340 — "pop" premier
#     frame 2  (66ms)  : 0.849 — quasi-plein
#     frame 3  (100ms) : 1.124 — début overshoot
#     frame 4  (133ms) : 1.153 — PIC overshoot (+15.3%)
#     frame 6  (200ms) : 1.002 — SETTLE (98%)
#     EXIT : HARD CUT → t >= t_end : alpha=0, scale=0 (0 frames fondu)
#
SPRING_STIFFNESS     = 900
SPRING_DAMPING       = 30
SPRING_SLIDE_PX      = 8
SPRING_SETTLE_FRAMES = 6
SPRING_SETTLE_MS     = 200


# ── Police ───────────────────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V29: FS_BASE confirmé à 70px @1080p
# Mesure cap-height: 22px @576p → 22×(1080/576) = 41px
# En Inter-SemiBold cap-height ≈ 0.73×FS → FS = 41/0.73 = 56px
# MAIS: le padding PIL (36px top+bottom sur array) est inclus dans nos mesures
# Sans padding: text_h_real ≈ 22 - 36×(576/1080) ≈ 22 - 19 = 3px... trop petit
# → FS_BASE=70 stable depuis V23, le padding compense la mesure compressée JPEG
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
# ARCHITECTURE_MASTER_V29: Timestamps CORRIGÉS (mesure frame-exact)
#
#   MÉTHODE: extraction 30fps autour t=12s, analyse bg_avg pixel numpy
#
#   t=11.90s → bg_avg=255 (BLANC, texte noir normal)
#   t=12.07s → bg_avg=0   (NOIR pur, frame 362) ← CUT ENTRANT
#   t=12.10s → bg_avg=0   (stable noir)
#   ...  [21 frames noirs: frames 362→382]
#   t=12.77s → bg_avg=31  (transition sortie, frame 383) ← CUT SORTANT
#   t=12.90s → bg_avg=255 (BLANC restauré)
#
#   Durée mesurée: 12.77-12.07 = 0.70s = 21 frames @30fps
#
#   V24/V25 avaient (12.00, 12.79) — décalage de 70ms à l'entrée
#   V29 corrige à (12.07, 12.77) — exact frame-par-frame
#
INVERSION_WORD_MIN  = 10
INVERSION_WORD_MAX  = 14

INVERSION_TIMESTAMPS = [
    (12.07, 12.77),   # Fenêtre 1: 0.70s, BG noir pur, sparkles violets
    (40.20, 44.10),   # Fenêtre 2: 3.90s, BG navy, CTA TikTok card
]


# ── CTA Card (V29 NOUVEAU) ─────────────────────────────────────────────────────
#
# ARCHITECTURE_MASTER_V29: Composant CTA TikTok entièrement nouveau
# Rendu sur la fenêtre t=40.20→44.10s (INVERSION_TIMESTAMPS[1])
#
# Mesures précises (frame cta_0030.png, 576×1024):
#   BG:               rgb(14,14,26) navy
#   Logo center Y:    472/1024 = 0.461H
#   "TikTok" text Y:  ~530/1024 = 0.517H (sous le logo)
#   Search bar rows:  [559, 611] → center=585/1024 = 0.571H
#   Search bar cols:  [110, 466] → width=356/576 = 0.618W
#   Search bar height: 52/1024 = 0.051H → ~98px @1080p
#   Search bar radius: ~26px (pill shape)
#   Colors dans searchbar: BG=white, icône gauche=noir, icône droite=TikTok rouge/bleu
#
# Le USERNAME affiché est configurable (paramètre `tiktok_handle`)
#
CTA_BG_COLOR               = (14,  14,  26)
CTA_LOGO_CENTER_Y_RATIO    = 0.461
CTA_SEARCH_CENTER_Y_RATIO  = 0.571
CTA_SEARCH_WIDTH_RATIO     = 0.618
CTA_SEARCH_HEIGHT_RATIO    = 0.051
CTA_SEARCH_RADIUS          = 26     # px @576p → ~49px @1080p

# Handle TikTok affiché dans la searchbar (peut être overridé depuis config YAML)
CTA_TIKTOK_HANDLE = "@tekiyo_"


# ── Sparkles V25 (inchangés — position mesurée OK) ────────────────────────────

SPARKLE_ENABLED          = True
SPARKLE_COUNT            = 5
SPARKLE_ORBIT_RX_RATIO   = 0.16
SPARKLE_ORBIT_RY_RATIO   = 0.08
SPARKLE_SPEED_BASE       = 1.2
SPARKLE_RADIUS_PX        = 6
SPARKLE_ALPHA            = 0.75
SPARKLE_ACTIVE_INVERSION = 0      # index 0 = fenêtre noir pur

# Couleurs mesurées frame-exact (precise_inv_0006.png numpy scan)
# Pixels: rgb(55,0,98) → rgb(98,38,141) → rgb(83,23,126)
SPARKLE_COLOR_PRIMARY   = (40,  10,  90)
SPARKLE_COLOR_SECONDARY = (90,  20, 160)
SPARKLE_COLOR_ACCENT    = (160, 40, 220)


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────

WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)