"""
Tests pour tools/timeline.py — TimelineObject et TimelineEngine.

Pourquoi c'est critique : TimelineEngine est le compositeur central de toutes les
frames vidéo. Une erreur d'activation (is_active retourne vrai au mauvais moment)
produit des objets qui disparaissent trop tôt ou qui restent affichés trop longtemps.
Un objet à durée négative silencieux n'est jamais rendu mais empoisonne le debug.

Tests couverts :
- TimelineEngine vide : aucun objet actif, durée totale = 0
- Durées de scènes : t_end - t_start somme correctement
- Scènes en overlap : les deux sont actives pendant la zone de chevauchement
  (comportement voulu selon l'architecture V22 — overlapping contrôlé)
- Durée négative (t_end < t_start) : lève ValueError via __post_init__
- is_active : sémantique [t_start, t_end) exacte (hard cut à t_end)
"""

import numpy as np
import pytest
from tools.timeline import TimelineEngine, TimelineObject


# ─── Fixtures ────────────────────────────────────────────────────────────────

def dummy_frame():
    """Frame 10×10 RGB noire — suffisant pour les tests de composition."""
    return np.zeros((10, 10, 3), dtype=np.uint8)


def make_obj(t_start: float, t_end: float, tag: str = "") -> TimelineObject:
    """Crée un TimelineObject minimal pour les tests."""
    return TimelineObject(
        t_start   = t_start,
        t_end     = t_end,
        render_fn = lambda t: dummy_frame(),
        tag       = tag,
    )


# ─── Engine vide ─────────────────────────────────────────────────────────────

class TestEmptyEngine:
    def test_no_active_objects_at_zero(self):
        """Engine sans objet : aucun actif à t=0."""
        engine = TimelineEngine()
        assert engine.active_at(0.0) == []

    def test_no_active_objects_at_any_time(self):
        """Engine sans objet : aucun actif à n'importe quel t."""
        engine = TimelineEngine()
        for t in [0.0, 0.5, 1.0, 10.0, 100.0]:
            assert engine.active_at(t) == []

    def test_total_duration_is_zero(self):
        """Engine vide : durée totale calculée = 0."""
        engine = TimelineEngine()
        total = max((o.t_end for o in engine._objects), default=0.0)
        assert total == 0.0


# ─── Durées de scènes ─────────────────────────────────────────────────────────

class TestSceneDurations:
    def test_single_scene_duration(self):
        """t_end - t_start = durée exacte d'une scène."""
        obj = make_obj(1.0, 3.5)
        assert (obj.t_end - obj.t_start) == pytest.approx(2.5)

    def test_sequential_scenes_sum(self):
        """Trois scènes séquentielles : leur span individuel somme correctement."""
        spans = [(0.0, 1.0), (1.0, 2.5), (2.5, 4.0)]
        objs  = [make_obj(s, e) for s, e in spans]
        engine = TimelineEngine()
        engine.add_all(objs)

        total_from_objects = sum(o.t_end - o.t_start for o in engine._objects)
        total_span         = max(o.t_end for o in engine._objects)

        assert total_from_objects == pytest.approx(4.0)
        assert total_span         == pytest.approx(4.0)

    def test_active_at_boundaries(self):
        """Objet actif à t_start, inactif à t_end (hard cut [t_start, t_end))."""
        obj = make_obj(1.0, 2.0)
        assert obj.is_active(1.0)         # inclus
        assert obj.is_active(1.5)         # milieu
        assert not obj.is_active(2.0)     # exclu (hard cut)
        assert not obj.is_active(0.999)   # avant
        assert not obj.is_active(2.001)   # après

    def test_engine_returns_correct_count(self):
        """active_at retourne exactement les objets actifs à l'instant t."""
        engine = TimelineEngine()
        engine.add(make_obj(0.0, 1.0, "a"))
        engine.add(make_obj(1.0, 2.0, "b"))
        engine.add(make_obj(2.0, 3.0, "c"))

        assert len(engine.active_at(0.5))  == 1
        assert len(engine.active_at(1.0))  == 1  # "b" commence, "a" finit
        assert len(engine.active_at(1.5))  == 1
        assert len(engine.active_at(3.0))  == 0  # tous terminés


# ─── Overlapping (comportement voulu V22) ────────────────────────────────────

class TestOverlappingScenes:
    """
    V22 supporte explicitement le chevauchement temporel.
    Deux objets qui se chevauchent doivent TOUS LES DEUX être retournés
    par active_at pendant la zone d'overlap.
    """

    def test_overlapping_both_active(self):
        """Deux scènes en overlap : les deux actives pendant le chevauchement."""
        engine = TimelineEngine()
        engine.add(make_obj(0.0, 2.0, "premier"))
        engine.add(make_obj(1.0, 3.0, "second"))

        # Avant l'overlap : seulement "premier"
        actifs_avant = engine.active_at(0.5)
        assert len(actifs_avant) == 1
        assert actifs_avant[0].tag == "premier"

        # Pendant l'overlap : les deux
        actifs_pendant = engine.active_at(1.5)
        assert len(actifs_pendant) == 2
        tags = {o.tag for o in actifs_pendant}
        assert "premier" in tags
        assert "second"  in tags

        # Après l'overlap : seulement "second"
        actifs_apres = engine.active_at(2.5)
        assert len(actifs_apres) == 1
        assert actifs_apres[0].tag == "second"

    def test_overlapping_z_order(self):
        """active_at trie par z_index croissant (derrière → devant)."""
        engine = TimelineEngine()
        engine.add(TimelineObject(t_start=0.0, t_end=2.0,
                                  render_fn=lambda t: dummy_frame(),
                                  z_index=10, tag="devant"))
        engine.add(TimelineObject(t_start=0.0, t_end=2.0,
                                  render_fn=lambda t: dummy_frame(),
                                  z_index=0, tag="derriere"))

        actifs = engine.active_at(1.0)
        assert len(actifs) == 2
        assert actifs[0].tag == "derriere"
        assert actifs[1].tag == "devant"


# ─── Durée négative → ValueError ─────────────────────────────────────────────

class TestNegativeDuration:
    def test_negative_duration_raises(self):
        """t_end < t_start : durée négative → ValueError."""
        with pytest.raises(ValueError, match="t_end"):
            make_obj(t_start=2.0, t_end=1.0)

    def test_strictly_negative_various(self):
        """Plusieurs cas de durée négative : tous lèvent ValueError."""
        invalid_pairs = [(1.0, 0.0), (5.0, 3.0), (0.1, 0.0), (100.0, 99.9)]
        for t_start, t_end in invalid_pairs:
            with pytest.raises(ValueError):
                make_obj(t_start=t_start, t_end=t_end)

    def test_zero_duration_raises(self):
        """t_end == t_start : durée nulle → ValueError (objet invisible, invalide)."""
        with pytest.raises(ValueError):
            make_obj(t_start=1.0, t_end=1.0)

    def test_valid_duration_does_not_raise(self):
        """t_end > t_start : aucune exception."""
        obj = make_obj(t_start=0.0, t_end=0.001)
        assert obj is not None


# ─── add / add_all / clear ───────────────────────────────────────────────────

class TestEngineAPI:
    def test_add_returns_self(self):
        """add() est chaînable (retourne l'engine)."""
        engine = TimelineEngine()
        result = engine.add(make_obj(0.0, 1.0))
        assert result is engine

    def test_clear_empties_objects(self):
        """clear() supprime tous les objets."""
        engine = TimelineEngine()
        engine.add(make_obj(0.0, 1.0))
        engine.clear()
        assert engine.active_at(0.5) == []

    def test_objects_by_tag(self):
        """objects_by_tag filtre correctement par tag."""
        engine = TimelineEngine()
        engine.add(make_obj(0.0, 1.0, "mot"))
        engine.add(make_obj(0.0, 1.0, "broll"))
        engine.add(make_obj(0.0, 1.0, "mot"))

        assert len(engine.objects_by_tag("mot"))   == 2
        assert len(engine.objects_by_tag("broll"))  == 1
        assert len(engine.objects_by_tag("absent")) == 0
