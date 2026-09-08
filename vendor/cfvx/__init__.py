"""CFV-X: circle-first raster-to-vector engine.

Implements the pipeline in raster_to_vector_theory_review.md as a
practical tool: observation analysis, palette/region proposals,
circle/arc/line/Bezier model selection, SVG export, and verification.

This is a working engine, not a certified commercial implementation of
every guarantee in the review. Reports distinguish passed / failed /
indeterminate instead of silent success.
"""

from .pipeline import vectorize

__version__ = "0.1.0"
__all__ = ["vectorize", "__version__"]
