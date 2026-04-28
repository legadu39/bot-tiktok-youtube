import sys
import os

# Ajoute la racine du projet au PATH Python pour que tous les imports fonctionnent
# que pytest soit lancé depuis la racine ou depuis tests/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
