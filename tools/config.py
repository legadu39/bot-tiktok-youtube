# -*- coding: utf-8 -*-
# NEXUS_MASTER_V38: Configuration centrale — PROPORTIONAL TIMESTAMPS + FONT GUARD.
#
# DELTA V38 vs V35:
#
#   FIX #1 — INVERSION TIMESTAMPS PROPORTIONNELS (NOUVEAU):
#     V35: Hardcodé à (12.000, 12.733) et (40.033, 44.033) — basé sur 44s.
#          → Si la vidéo fait 32s, l'inversion #2 n'arrive JAMAIS.
#     V38: compute_dynamic_inversion_timestamps(duration) retourne des timestamps
#          proportionnels à la durée effective. Ratios constants par rapport à
#          la référence 44.033s.
#
#   FIX #2 — FS_BASE_FALLBACK (NOUVEAU):
#     V35: FS_BASE=70 toujours, même avec font fallback → cap-height +70% trop grand.
#     V38: FS_BASE_FALLBACK=50 utilisé quand _USING_FALLBACK_FONTS=True.
#          Flag mis à jour automatiquement par find_font_compensated() dans graphics.py.
#
#   FIX #3 — KEYWORDS_ACCENT ÉTENDU (NOUVEAU):
#     V35: vocabulaire Finance/PropFirm ajouté.
#     V38: ajout iPhone/tech/produit pour couvrir le topic de la vidéo référence.
#
#   CONSERVÉ V35 (inchangé):
#     Couleurs, gradient, spring physics, B-Roll card ratios, sparkles, CTA.
#
# ═══════════════════════════════════════════════════════════════════════════════

import re
from pathlib import Path


# ── Couleurs thème NORMAL (fond blanc) ────────────────────────────────────────

TEXT_RGB      = (25,  25,  25)
TEXT_DIM_RGB  = (150, 150, 150)
ACCENT_RGB    = (0,   208, 132)
MUTED_RGB     = (220,  40,  35)

ACCENT_GRADIENT_LEFT  = (105, 228, 220)
ACCENT_GRADIENT_RIGHT = (208, 122, 148)


# ── Couleurs thème INVERSÉ (fond sombre) ─────────────────────────────────────

TEXT_RGB_INV   = (235, 235, 235)
TEXT_DIM_INV   = (155, 155, 155)
ACCENT_RGB_INV = (248,  18,  90)
MUTED_RGB_INV  = (255,  70,  60)

ACCENT_GRADIENT_LEFT_INV  = (45,  175, 168)
ACCENT_GRADIENT_RIGHT_INV = (190,  85, 115)


# ── Couleurs de fond inversion ────────────────────────────────────────────────

INVERSION_BG_COLOR_1 = (0,    0,   0)
INVERSION_BG_COLOR_2 = (14,  14,  26)


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

# NEXUS_MASTER_V38: FIX #3 — KEYWORDS_ACCENT étendu avec tech/produit
KEYWORDS_ACCENT = {
    # ── Existants V35 (inchangés) ──────────────────────────────────────────
    "argent","succès","secret","outil","profit","gain","winner",
    "croissance","million","stratégie","champion","payout","valide",
    "marché","produit","client","vendre","vente","commerce","créer",
    "révèle","découverte","clé","maîtrise","excellence","unique",
    "trading","trader","funded","challenge","ftmo","apex","capital",
    "opportunité","résultat","performance","système","méthode","règle",
    "powerful","amazing","incredible","secret","reveal","master",
    "iphone","apple","samsung","pro","ultra","max",
    # ── Finance / PropFirm / Comptabilité ──────────────────────────────────
    "revenu","revenus","bénéfice","bénéfices","fiscal","fiscale",
    "impôt","impôts","tva","déclaration","optimisation","optimiser",
    "patrimoine","dividende","dividendes","plus-value","rentable",
    "rentabilité","cashflow","trésorerie","liquidité","solvabilité",
    "holding","sas","sarl","eurl","lmnp","statut","société","entreprise",
    "siret","urssaf","fisc","régime","structure","financement",
    "propfirm","évaluation","compte","levier","investissement","actif",
    "passif","compte-rendu","financer",
    "comptable","bugue","bug","comprend","comprendre","conseil","expert",
    "vérité","réalité","vraie","récupérer",
    # ── NEXUS_MASTER_V38: Tech / Produit / iPhone ref ─────────────────────
    "écran","caméra","batterie","puce","processeur","design",
    "innovation","lancement","premium","tarif","prix","offre",
    "meilleur","nouveau","nouvelle","révolution","upgrade",
    "fonctionnalité","feature","technologie","intelligence",
    "autonomie","puissance","capacité","stockage","mémoire",
    "titane","titanium","céramique","acier","aluminium",
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

TEXT_ANCHOR_Y_RATIO = 0.4990

SAFE_LEFT  = 80
SAFE_RIGHT = 80


# ── B-Roll Card ───────────────────────────────────────────────────────────────

BROLL_CARD_WIDTH_RATIO    = 0.530
BROLL_CARD_CENTER_Y_RATIO = 0.474
BROLL_TEXT_STAYS_PUT      = True
BROLL_SHADOW_EXPAND_PX    = 40
BROLL_CARD_RADIUS_RATIO   = 0.036
BROLL_SHADOW_BLUR         = 18
BROLL_SHADOW_OPACITY      = 0.33


# ── Spring physics ────────────────────────────────────────────────────────────

SPRING_STIFFNESS     = 900
SPRING_DAMPING       = 30
SPRING_SLIDE_PX      = 8
SPRING_SETTLE_FRAMES = 6
SPRING_SETTLE_MS     = 200


# ── Police ───────────────────────────────────────────────────────────────────

FS_BASE         = 70
FS_MIN          = 32
FS_ACCENT_SCALE = 1.45
FS_STOP_SCALE   = 0.85
FS_MUTED_SCALE  = 1.10
FS_BADGE_SCALE  = 1.25
FS_BOLD_SCALE   = 1.15
FS_SUPER_SCALE  = 1.60

# NEXUS_MASTER_V38: FIX #2 — Taille réduite pour fonts fallback (non-Inter)
# Quand DejaVuSans/LiberationSans est utilisé, le cap-height est ~70% trop grand
# car ces fonts ont un ratio cap/em plus élevé et un design plus large.
# Ce fallback sera activé par graphics.py si Inter n'est pas trouvée.
FS_BASE_FALLBACK = 50

# NEXUS_MASTER_V38: Flag global mis à jour par graphics.py
# True = on utilise une font dégradée (pas Inter) → appliquer FS_BASE_FALLBACK
_USING_FALLBACK_FONTS = False


def get_effective_fs_base() -> int:
    """
    NEXUS_MASTER_V38: Retourne FS_BASE ou FS_BASE_FALLBACK selon la font active.
    Appelé par text_engine.py et burner.py pour le dimensionnement du texte.
    """
    if _USING_FALLBACK_FONTS:
        return FS_BASE_FALLBACK
    return FS_BASE


# ── Timing & Animation ────────────────────────────────────────────────────────
ENTRY_DUR  = 0.033
EXIT_DUR   = 0.0
PRE_ROLL   = 0.033

GLOBAL_ZOOM_START = 1.00
GLOBAL_ZOOM_END   = 1.03

SLIDE_OUT_PX = 500


# ── Inversion timestamps ──────────────────────────────────────────────────────
#
# NEXUS_MASTER_V38: FIX #1 — PROPORTIONAL TIMESTAMPS
#
# V35 hardcodait ces valeurs pour une vidéo de 44.033s exactement.
# Si la vidéo fait 32s, l'inversion #2 (CTA) à 40s n'arrive jamais.
#
# V38: Les constantes INVERSION_TIMESTAMPS restent comme RÉFÉRENCE ABSOLUE
# pour la vidéo de calibration (576×1024, 44.033s). Mais le code utilise
# compute_dynamic_inversion_timestamps(duration) pour calculer les timestamps
# proportionnels à la durée réelle.
#
# Les ratios sont constants:
#   Inv#1 start : 12.000 / 44.033 = 0.27253
#   Inv#1 end   : 12.733 / 44.033 = 0.28918
#   Inv#2 start : 40.033 / 44.033 = 0.90918
#   Inv#2 end   : 44.033 / 44.033 = 1.00000
#

INVERSION_WORD_MIN  = 10
INVERSION_WORD_MAX  = 14

# Référence absolue (vidéo calibration 44.033s) — conservé pour rétrocompatibilité
INVERSION_TIMESTAMPS = [
    (12.000, 12.733),
    (40.033, 44.033),
]

# NEXUS_MASTER_V38: Ratios proportionnels dérivés de la référence
_REF_DURATION = 44.033
_INVERSION_RATIOS = [
    (12.000 / _REF_DURATION, 12.733 / _REF_DURATION),   # Inv#1: ~27.3% → ~28.9%
    (40.033 / _REF_DURATION, 44.033 / _REF_DURATION),    # Inv#2: ~90.9% → 100%
]

# Durées minimales absolues pour chaque inversion (empêche les micro-inversions)
_INVERSION_MIN_DURATION = [
    0.500,   # Inv#1: au moins 500ms (sparkles)
    2.000,   # Inv#2: au moins 2s (CTA card doit être lisible)
]


def compute_dynamic_inversion_timestamps(
    duration: float,
) -> list:
    """
    NEXUS_MASTER_V38: Calcule les timestamps d'inversion proportionnels.

    Pour une vidéo de 32s:
        Inv#1: 32 × 0.2725 = 8.72s → 32 × 0.2892 = 9.25s (0.53s)
        Inv#2: 32 × 0.9092 = 29.09s → 32 × 1.0 = 32.0s (2.91s)

    Pour une vidéo de 44s (référence):
        Inv#1: 12.000s → 12.733s (0.733s) — identique à INVERSION_TIMESTAMPS
        Inv#2: 40.033s → 44.033s (4.000s) — identique à INVERSION_TIMESTAMPS

    Retourne une liste de tuples (t_start, t_end) ou une liste vide si
    la durée est trop courte pour supporter des inversions.
    """
    if duration < 10.0:
        return []

    result = []
    for i, (ratio_start, ratio_end) in enumerate(_INVERSION_RATIOS):
        t_start = duration * ratio_start
        t_end   = min(duration, duration * ratio_end)

        # Vérifier la durée minimale
        if (t_end - t_start) < _INVERSION_MIN_DURATION[i]:
            # Étendre jusqu'à la durée minimale si possible
            t_end = min(duration, t_start + _INVERSION_MIN_DURATION[i])

        # Ne pas ajouter si toujours trop court
        if (t_end - t_start) >= _INVERSION_MIN_DURATION[i] * 0.8:
            result.append((round(t_start, 3), round(t_end, 3)))

    return result


# ── CTA Card ───────────────────────────────────────────────────────────────────

CTA_BG_COLOR               = (14,   14,  26)
CTA_LOGO_CENTER_Y_RATIO    = 0.374
CTA_TIKTOK_TEXT_Y_RATIO    = 0.459
CTA_SEARCH_CENTER_Y_RATIO  = 0.571
CTA_SEARCH_WIDTH_RATIO     = 0.618
CTA_SEARCH_HEIGHT_RATIO    = 0.051
CTA_SEARCH_RADIUS          = 26

CTA_TIKTOK_HANDLE = "@tekiyo_"


# ── Sparkles ─────────────────────────────────────────────────────────────────

SPARKLE_ENABLED          = True
SPARKLE_COUNT            = 5
SPARKLE_ORBIT_RX_RATIO   = 0.16
SPARKLE_ORBIT_RY_RATIO   = 0.08
SPARKLE_SPEED_BASE       = 1.2
SPARKLE_RADIUS_PX        = 6
SPARKLE_ALPHA            = 0.75
SPARKLE_ACTIVE_INVERSION = 0

SPARKLE_COLOR_PRIMARY   = (39,   0,  67)
SPARKLE_COLOR_SECONDARY = (80,  15, 130)
SPARKLE_COLOR_ACCENT    = (150, 40, 200)


# ── Aliases rétrocompatibilité ────────────────────────────────────────────────
WHITE_BG_COLOR = (255, 255, 255)
CREAM_BG_COLOR = (245, 245, 247)