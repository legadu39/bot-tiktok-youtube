# -*- coding: utf-8 -*-
import re
from pathlib import Path

# Thème NORMAL — fond blanc
TEXT_RGB      = (17,  17,  17)
TEXT_DIM_RGB  = (120, 120, 120)
ACCENT_RGB    = (0,   208, 132)
MUTED_RGB     = (230,  45,  35)

# Thème INVERSÉ — fond noir
TEXT_RGB_INV   = (238, 238, 238)
TEXT_DIM_INV   = (150, 150, 150)
ACCENT_RGB_INV = (50,  235, 140)
MUTED_RGB_INV  = (255,  80,  70)

# Regex numérique
RE_NUMERIC = re.compile(r'[\d\$€%]')

IMPACT_WORDS = {
    "secret","argent","profit","gain","succès","winner","champion","million",
    "stratégie","risque","danger","crash","stop","alerte","révèle","jamais",
    "toujours","maintenant","gratuit","payant","payout","funded","ftmo","apex",
    "incroyable","impossible","réel","vrai","faux","piège","erreur","règle",
}

STOP_WORDS = {
    "le","la","les","un","une","des","ce","ces","de","du","à","au",
    "et","en","ne","se","sa","son","ses","on","y","il","elle","ils",
    "elles","je","tu","nous","vous","qui","que","quoi","dont","où",
    "si","or","ni","car","mais","ou","donc","par","sur","sous","avec",
    "pour","dans","vers","chez","c'est","the","a","an","in","on","at",
    "to","for","of","and","is","it","be","as","by","we","he","they","you"
}

KEYWORDS_ACCENT = {
    "argent","succès","secret","outil","profit","gain","winner",
    "croissance","million","stratégie","champion","payout","valide",
}

KEYWORDS_MUTED = {
    "perdre","perte","crash","danger","scam","arnaque","échec",
    "chute","stop","alerte","attention","faillite","erreur",
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

_asset_dir_path = Path(__file__).parent / "assets" if "__file__" in dir() else Path("assets")
ASSET_DIR = _asset_dir_path