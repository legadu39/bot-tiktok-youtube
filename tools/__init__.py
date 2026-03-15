# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Package tools — exports publics.
from .physics       import SpringPhysics, wiggle_offset
from .easing        import EasingLibrary
from .effects       import (
    EffectBase, EffectContinuousZoom, EffectSpringOvershoot,
    EffectWiggle, EffectHardCut, EffectSlideExit,
)
from .timeline      import TimelineObject, TimelineEngine
from .compositor    import WordClip, compose_frame, apply_continuous_zoom
from .text_engine   import (
    WordClass, classify_word, get_word_style,
    split_to_single_words, group_into_phrases,
)
from .graphics      import (
    find_font, measure_text,
    render_text_solid, render_text_gradient,
    load_asset_image, render_broll_card,
)
from .layout        import SmartLayoutManager
from .context       import SceneContext
from .burner        import SubtitleBurner
from .scene_animator import SceneAnimator

__all__ = [
    "SpringPhysics", "wiggle_offset",
    "EasingLibrary",
    "EffectBase", "EffectContinuousZoom", "EffectSpringOvershoot",
    "EffectWiggle", "EffectHardCut", "EffectSlideExit",
    "TimelineObject", "TimelineEngine",
    "WordClip", "compose_frame", "apply_continuous_zoom",
    "WordClass", "classify_word", "get_word_style",
    "split_to_single_words", "group_into_phrases",
    "find_font", "measure_text",
    "render_text_solid", "render_text_gradient",
    "load_asset_image", "render_broll_card",
    "SmartLayoutManager", "SceneContext",
    "SubtitleBurner", "SceneAnimator",
]