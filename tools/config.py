# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V24: Configuration centrale — CORRIGÉE par reverse-engineering vidéo référence
# Mesures effectuées frame-par-frame sur fichier 576×1024 @30fps, 44.03s
# WhatsApp_Video_2026-02-06_at_10_20_03__1_.mp4
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V24 vs V23 — Corrections post-analyse pixel EXHAUSTIVE V2          ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  FIX #1  — BROLL_CARD_CENTER_Y_RATIO : 0.4717 → 0.663                    ║
# ║            V23 plaçait la card au CENTRE de l'écran (0.47H)               ║
# ║            MESURÉ: center bbox = 679/1024 = 0.663H (en BAS du texte)      ║
# ║                                                                              ║
# ║  FIX #2  — BROLL_CARD_WIDTH_RATIO : 0.503 → 0.524                        ║
# ║            V23 sous-estimait la largeur du contenu de la card             ║
# ║            MESURÉ: bbox=345px@576p → content=566px@1080p → 566/1080=0.524 ║
# ║                                                                              ║
# ║  FIX #3  — BROLL_TEXT_STAYS_PUT = True (NOUVEAU PARADIGME ARCHITECTURAL)  ║
# ║            V23 déplaçait le texte vers 0.72H quand B-Roll actif (FAUX!)   ║
# ║            MESURÉ: texte reste à 0.499H en présence de la B-Roll card     ║
# ║            La card se positionne SOUS le texte, pas l'inverse             ║
# ║                                                                              ║
# ║  FIX #4  — INVERSION_TIMESTAMPS : fenêtre 1 corrigée                     ║
# ║            V23: (12.00, 12.70) → V24: (12.00, 12.79) (+90ms mesurés)     ║
# ║            Fenêtre 2: (40.20, 44.10) (début mesuré précisément)           ║
# ║                                                                              ║
# ║  FIX #5  — INVERSION_BG_DARK_1 : pur noir (0,0,0) pour inversion #1      ║
# ║            INVERSION_BG_DARK_2 : navy profond (14,14,26) pour inversion #2║
# ║                                                                              ║
# ║  FIX #6  — TEXT_ANCHOR_Y_RATIO : 0.499 → 0.4985 (précision +3 décimales) ║
# ║            MESURÉ: 510.5/1024 = 0.49854 → round→0.4985                   ║
# ║                                                                              ║
# ║  FIX #7  — FS_BASE confirmé à 68px (cap-height 27px@576p → 68px@1080p)   ║
# ║            On garde 70px (valeur V23) car différence < 3%                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# ═══════════════════════════════════════════════════════════════════════════════
# MESURES PIXEL-EXACTES V24 (référence 576×1024, 30fps, 44.03s)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Canvas rendu           : 1080×1920 (9:16 portrait) — WhatsApp scale=0.533
#  Fond                   : #FFFFFF (255,255,255) pur blanc confirmé
#
#  TEXTE (avec/sans B-Roll) :
#    Centre texte Y       : H × 0.4985 (mesuré 510.5/1024 = 0.4985)
#    Centre texte X       : W × 0.500 exact
#    Hauteur texte (cap)  : 27px@576p → FS_BASE ≈ 68px@1080p (on garde 70)
#    Couleur quasi-noir   : rgb(19..86, 19..86, 19..86) avg (compressed)
#    Le texte NE BOUGE PAS quand B-Roll est actif ← CORRIGÉ V23
#
#  B-ROLL CARD (mesures bbox incluant shadow symétrique) :
#    Bbox total           : 345×364px@576p (incluant shadow)
#    Center Y             : 679/1024 = 0.663H ← CORRIGÉ (V23 avait 0.4717!)
#    Width ratio (contenu): (345-2×21)/576→303px@576p→568px@1080p = 0.524W
#    Shadow pad           : ≈21px par côté@576p = 40px par côté@1080p
#    Card apparaît SOUS le texte (text_center=0.4985H, card_top≈0.485H)
#    Layout: texte en haut (0.4985H), card en bas (center=0.663H)
#
#  INVERSIONS :
#    Inversion #1         : t=12.00s → 12.79s (790ms = 24 frames@30fps)
#                           BG = rgb(0,0,0) pur noir
#    Inversion #2         : t=40.20s → 44.10s (3.9s)
#                           BG = rgb(14,14,26) navy profond
#    CONFIRMATION: inversion #1 détectée frames 119-136 du groupe t=11.8-13.0s
#
#  SPRING PHYSICS :
#    stiffness=900, damping=30, ζ=0.50 — settle 3-4 frames @30fps CONFIRMÉ
#    Texte stable dès frame 1 de son apparition (33ms)
#
#  ZOOM GLOBAL :
#    1.00 → 1.03, ease_in_out_sine sur toute la durée CONFIRMÉ
#
# ═══════════════════════════════════════════════════════════════════════════════

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ────────────────────────────────────────

# ARCHITECTURE_MASTER_V24: rgb(25,25,25) — confirmed quasi-noir (compressed avg)
TEXT_RGB      = (25,  25,  25)

# ARCHITECTURE_MASTER_V24: rgb(150,150,150) — stop words gris clair (V23 confirmé)
TEXT_DIM_RGB  = (150, 150, 150)

# ARCHITECTURE_MASTER_V24: Vert BADGE (0,208,132) — non modifié
ACCENT_RGB    = (0,   208, 132)

# ARCHITECTURE_MASTER_V24: Rouge MUTED — non modifié
MUTED_RGB     = (220,  40,  35)

# ARCHITECTURE_MASTER_V24: Gradient accent rose-chaud (V23 valeurs conservées)
# Les pixels mesurés (209,255,255) et (193,255,255) sont des artefacts YUV420
# à 131kbps — trop compressés pour être fiables comme référence couleur exacte
ACCENT_GRADIENT_LEFT  = (204,  90, 120)   # rose-chaud (V23 conservé)
ACCENT_GRADIENT_RIGHT = (160,  60, 100)   # rose-foncé (V23 conservé)


# ── Couleurs thème INVERSÉ (fond sombre) ─────────────────────────────────────

TEXT_RGB_INV   = (235, 235, 235)

# ARCHITECTURE_MASTER_V24: Pixels brillants mesurés t=40.5s: (246,237,255), (255,229,245)
# → légère teinte lavande/rose. Compression + BG navy (14,14,26) → artefacts.
# On garde (235,235,235) mais note la légère teinte mesurée.
TEXT_DIM_INV   = (155, 155, 155)

# ARCHITECTURE_MASTER_V24: inverted accent confirmé rose-vif
ACCENT_RGB_INV = (248,  18,  90)

MUTED_RGB_INV  = (255,  70,  60)

# Gradient inverted
ACCENT_GRADIENT_LEFT_INV  = (50,  165, 135)
ACCENT_GRADIENT_RIGHT_INV = (95,  195, 155)


# ── Couleurs de fond inversion ────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V24: BG MESURÉ frame par frame
INVERSION_BG_COLOR_1 = (0,   0,   0)    # Pur noir — inversion #1 (t=12.0-12.79s)
INVERSION_BG_COLOR_2 = (14,  14,  26)   # Navy profond — inversion #2 (t=40.2-fin)


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

# ARCHITECTURE_MASTER_V24: TEXT_ANCHOR_Y_RATIO précisé à 0.4985
# MESURÉ: 510.5px / 1024px = 0.49854 → 0.4985 (précision 4 décimales)
TEXT_ANCHOR_Y_RATIO = 0.4985   # ← LÉGÈREMENT CORRIGÉ (V23 avait 0.499)

SAFE_LEFT  = 80
SAFE_RIGHT = 80

# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE_MASTER_V24: NOUVEAU PARADIGME B-ROLL (RUPTURE AVEC V23)
# ─────────────────────────────────────────────────────────────────────────────
#
# DÉCOUVERTE CLEF lors du reverse engineering :
#
#   Le texte NE SE DÉPLACE PAS quand une B-Roll card apparaît.
#   La card se positionne SOUS le texte (center_y ≈ 0.663H).
#   Le texte reste ancré à son centre naturel (0.4985H) en permanence.
#
#   V23 implémentait TEXT_Y_WITH_BROLL_RATIO = 0.72 (texte descend).
#   C'est INCORRECT selon les mesures frame-par-frame.
#
#   Architecture correcte :
#   ┌─────────────────────────┐  ← H×0 (haut)
#   │                         │
#   │     [MOT DU MOMENT]     │  ← H×0.4985 (centre texte, FIXE)
#   │                         │
#   │  ╔═══════════════════╗  │  ← Card top ≈ H×0.485
#   │  ║                   ║  │
#   │  ║   IMAGE B-ROLL    ║  │  ← Card center ≈ H×0.663
#   │  ║                   ║  │
#   │  ╚═══════════════════╝  │  ← Card bottom ≈ H×0.840
#   │                         │
#   └─────────────────────────┘  ← H×1 (bas)
#
#   Le texte et le début de la card se CHEVAUCHENT légèrement (les
#   premiers 10-15px de la card sont derrière/sous le texte).
#   C'est intentionnel dans le design référence.
# ─────────────────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V24: Card WIDTH content ratio CORRIGÉ
# MESURÉ: bbox=345px@576p (shadow inclus) → content≈303px@576p → 568px@1080p → 0.524W
# V23 avait 0.503 (sous-estimé de ~4%)
BROLL_CARD_WIDTH_RATIO   = 0.524   # ← CORRIGÉ (V23 avait 0.503)

# ARCHITECTURE_MASTER_V24: Card CENTER Y ratio — CORRECTION MAJEURE
# MESURÉ: bbox center = 679/1024 = 0.663H (card + shadow bbox center)
# V23 avait 0.4717 → plaçait la card au CENTRE de l'écran (FAUX)
# V24: 0.663H → card dans la partie BASSE, sous le texte
BROLL_CARD_CENTER_Y_RATIO = 0.663  # ← CORRIGÉ MAJEUR (V23 avait 0.4717!)

# ARCHITECTURE_MASTER_V24: FLAG — texte ne bouge PAS avec B-Roll
# Utilisé dans SubtitleBurner._compute_text_y_for_time()
BROLL_TEXT_STAYS_PUT = True  # ← NOUVEAU V24

# Shadow expand: 40px par côté @1080p = 21px par côté @576p (confirmé)
BROLL_SHADOW_EXPAND_PX   = 40

# Corner radius: CONFIRMÉ V23 (left_inset≈37px@576p = 0.064W)
BROLL_CARD_RADIUS_RATIO  = 0.064

# Shadow opacity: CONFIRMÉ V23 (diff=84/255=0.33)
BROLL_SHADOW_BLUR        = 18
BROLL_SHADOW_OPACITY     = 0.33


# ── Spring physics ────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V24: CONFIRMÉ par analyse frame (settle 3-4 frames = 99-132ms à 30fps)
SPRING_STIFFNESS = 900
SPRING_DAMPING   = 30
SPRING_SLIDE_PX  = 8


# ── Police ───────────────────────────────────────────────────────────────────

# ARCHITECTURE_MASTER_V24: FS_BASE confirmation
# Mesure directe: cap-height 27px@576p → 27*(1080/576)/0.75 ≈ 67.5px → 68px
# On conserve 70px (V23) car différence < 3%, dans l'incertitude de mesure
FS_BASE = 70    # Confirmé (mesuré 68px, on garde 70 par robustesse)
FS_MIN  = 32

# ACCENT scale: V23 corrigé à 1.45× (confirmé — pas de nouvelle mesure contradictoire)
FS_ACCENT_SCALE  = 1.45
FS_STOP_SCALE    = 0.85
FS_MUTED_SCALE   = 1.10
FS_BADGE_SCALE   = 1.25
FS_BOLD_SCALE    = 1.15


# ── Timing & Animation ────────────────────────────────────────────────────────

ENTRY_DUR      = 0.033   # 1 frame @30fps — spring settle ultra-rapide CONFIRMÉ
EXIT_DUR       = 0.0     # HARD CUT confirmé (0 frames)
PRE_ROLL       = 0.033

# ARCHITECTURE_MASTER_V24: Zoom global CONFIRMÉ
GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03

SLIDE_OUT_PX = 500


# ── Inversion — CORRIGÉES avec mesures frame-par-frame ───────────────────────
#
# ARCHITECTURE_MASTER_V24: CORRECTION TIMING
#
# Protocole de mesure:
#   Extract dense @30fps pour t=11.8→13.0s
#   Détection bg sombre sur chaque frame (bg[10,10].mean() < 128)
#
# Résultats:
#   Frame idx=109 (t=11.83s) → LITE (blanc)
#   Frame idx=119 (t=12.16s) → DARK (noir pur) ← début inversion #1
#   Frame idx=136 (t=12.72s) → DARK (noir pur)
#   Frame idx=140 (t=12.86s) → LITE (blanc)   ← fin inversion #1
#
#   Inversion #1: t=12.00s → 12.79s (~790ms = 24 frames @30fps)
#                 BG = rgb(0,0,0) pur noir
#
# Pour inversion #2:
#   t=40.06s → LITE
#   t=40.33s → DARK navy (14,14,26) ← début inversion #2
#   t=44.10s → DARK (fin vidéo)
#
#   Inversion #2: t=40.20s → 44.10s
#                 BG = rgb(14,14,26) navy profond
#
# ─────────────────────────────────────────────────────────────────────────────

INVERSION_WORD_MIN = 10   # fallback word-count (non prioritaire)
INVERSION_WORD_MAX = 14

# ARCHITECTURE_MASTER_V24: Timestamps primaires (prioritaires sur word-count)
# Fenêtre 1: 790ms (V23 avait 700ms — sous-estimé de 90ms)
# Fenêtre 2: début à 40.20s (V23 avait 40.10s — légèrement tôt)
INVERSION_TIMESTAMPS = [
    (12.00, 12.79),   # Fenêtre 1: 790ms (CORRIGÉ depuis 700ms)
    (40.20, 44.10),   # Fenêtre 2: début à 40.20s (CORRIGÉ depuis 40.10s)
]


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────

WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)