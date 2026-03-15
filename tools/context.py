# -*- coding: utf-8 -*-
class SceneContext:
    def __init__(self):
        self.last_motion       = "NONE"
        self.consecutive_count = 0
        self.scene_index       = 0

    def update(self, motion_type: str):
        self.scene_index += 1
        if self.last_motion == motion_type:
            self.consecutive_count += 1
        else:
            self.last_motion       = motion_type
            self.consecutive_count = 1