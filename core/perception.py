"""
core/perception.py
==================
L1 Perception & World Model Layer (Decision C4 AI / L1).

AMR onboard vision perception module simulating a lightweight edge object detector
(e.g. YOLOv8-nano running on an onboard Hailo-8 / Jetson Nano NPU).

Responsibilities:
  1. FOV scanning: Projects front-facing sensor cone (1-3 cells ahead).
  2. Confidence scoring & temporal filtering: Filters noise and false positives
     (requires consecutive frames above detection threshold).
  3. World Model updates: Translates confirmed visual detections into
     local map blockages and alerts L0 communication fabric.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import random
from core.planner import Cell, WarehouseMap


@dataclass
class DetectionResult:
    cell: Cell
    object_type: str  # "dropped_pallet", "debris", "forklift", "spill"
    confidence: float
    confirmed: bool


class EdgePerceptionModel:
    """Simulated edge-AI vision detector (YOLO-nano) with temporal hysteresis."""

    CONFIDENCE_THRESHOLD = 0.75
    MIN_CONSECUTIVE_FRAMES = 2

    def __init__(self, rng_seed: int = 42):
        self.rng = random.Random(rng_seed)
        # cell -> consecutive detection count
        self._detection_history: Dict[Cell, int] = {}
        self._known_confirmed: Set[Cell] = set()

    def scan_fov(
        self,
        current_pos: Cell,
        heading_dir: Tuple[int, int],
        wmap: WarehouseMap,
        simulated_ground_truth_obstacles: Optional[Set[Cell]] = None,
        fov_depth: int = 2,
    ) -> List[DetectionResult]:
        """Scans cells along heading vector within fov_depth.
        Evaluates simulated optical detection with noise and confidence scores.
        """
        results: List[DetectionResult] = []
        r, c = current_pos
        dr, dc = heading_dir

        if dr == 0 and dc == 0:
            return results

        scanned_cells = set()
        for depth in range(1, fov_depth + 1):
            target = (r + dr * depth, c + dc * depth)
            if not (0 <= target[0] < wmap.rows and 0 <= target[1] < wmap.cols):
                break
            scanned_cells.add(target)

            is_physically_blocked = (
                (simulated_ground_truth_obstacles and target in simulated_ground_truth_obstacles)
                or target in wmap.dynamic_blocks
            )

            if is_physically_blocked:
                # True positive detection with high confidence
                conf = self.rng.uniform(0.82, 0.98)
                self._detection_history[target] = self._detection_history.get(target, 0) + 1
                confirmed = self._detection_history[target] >= self.MIN_CONSECUTIVE_FRAMES
                results.append(DetectionResult(
                    cell=target,
                    object_type="dropped_pallet",
                    confidence=conf,
                    confirmed=confirmed
                ))
                if confirmed:
                    self._known_confirmed.add(target)
            else:
                # Clear or occasional transient optical noise (< threshold)
                if self.rng.random() < 0.02:
                    # Rare noisy flare, low confidence
                    results.append(DetectionResult(
                        cell=target,
                        object_type="noise_glare",
                        confidence=self.rng.uniform(0.20, 0.45),
                        confirmed=False
                    ))
                self._detection_history[target] = max(0, self._detection_history.get(target, 0) - 1)

        # Decay history for unobserved cells
        for cell in list(self._detection_history.keys()):
            if cell not in scanned_cells:
                self._detection_history[cell] = max(0, self._detection_history[cell] - 1)
                if self._detection_history[cell] == 0:
                    del self._detection_history[cell]

        return results
