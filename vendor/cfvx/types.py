from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Sequence

Vec2 = tuple[float, float]
CheckStatus = Literal["passed", "failed", "indeterminate", "not_applicable"]
Mode = Literal["faithful", "structural"]
EvidenceOrigin = Literal["observed", "inferred_relation", "inferred_hidden", "user_constraint"]
PrimitiveKind = Literal["line", "circle", "arc", "ellipse", "quadratic", "cubic"]
CandidateStatus = Literal["feasible", "infeasible_certified", "unknown"]


@dataclass(frozen=True)
class QualityContract:
    mode: Mode = "faithful"
    strict_vector_only: bool = True
    source_pixel_tolerance: float = 0.65
    fidelity_equivalence_margin: float = 0.02
    preserve_approved_topology: bool = True
    color_count: int = 22
    min_region_area: int = 5
    alpha_opaque: int = 250
    alpha_keep: int = 128
    time_budget_ms: int = 120_000


@dataclass
class LineSeg:
    kind: Literal["line"] = "line"
    start: Vec2 = (0.0, 0.0)
    end: Vec2 = (0.0, 0.0)


@dataclass
class ArcSeg:
    kind: Literal["arc"] = "arc"
    center: Vec2 = (0.0, 0.0)
    radius: float = 0.0
    start_angle: float = 0.0
    signed_sweep: float = 0.0
    start: Vec2 = (0.0, 0.0)
    end: Vec2 = (0.0, 0.0)


@dataclass
class CubicSeg:
    kind: Literal["cubic"] = "cubic"
    points: tuple[Vec2, Vec2, Vec2, Vec2] = (
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
    )


Segment = LineSeg | ArcSeg | CubicSeg


@dataclass
class CompoundPath:
    outer: list[Segment]
    holes: list[list[Segment]] = field(default_factory=list)
    area: float = 0.0


@dataclass
class ColorLayer:
    rgba: tuple[int, int, int, int]
    paths: list[CompoundPath]
    pixel_count: int
    origin: EvidenceOrigin = "observed"
    is_outline: bool = False


@dataclass
class Scene:
    width: int
    height: int
    layers: list[ColorLayer]
    view_box: tuple[float, float, float, float]


@dataclass
class ImageAnalysis:
    width: int
    height: int
    mode: str
    sha256: str
    opaque_pixels: int
    semi_pixels: int
    transparent_pixels: int
    unique_opaque_colors: int
    observation_model: str
    observation_notes: list[str]
    likely_outline: bool


@dataclass
class GeometricCertificate:
    status: CheckStatus
    reference_kind: str
    units: str = "source_pixel"
    requested_tolerance: float = 0.65
    sample_max_error: float | None = None
    verified_upper_bound: float | None = None
    numeric_method: str = ""


@dataclass
class QualityReport:
    overall: Literal["passed", "partial", "failed", "indeterminate"]
    contract: dict
    analysis: dict
    palette: list[list[int]]
    geometry: GeometricCertificate
    topology: CheckStatus
    native_rendering: CheckStatus
    latent_geometry_ground_truth_available: bool
    primitive_counts: dict[str, int]
    layer_count: int
    path_count: int
    segment_count: int
    raster_metrics: dict
    warnings: list[str]
    provenance: dict
    svg_hash: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["geometry"] = asdict(self.geometry)
        return d
