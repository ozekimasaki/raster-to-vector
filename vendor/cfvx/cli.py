"""CLI for the CFV-X raster-to-vector tool."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import __version__
from .pipeline import synthesize_circle_png, vectorize
from .raster import load_rgba
from .types import QualityContract


def _contract_from_args(args: argparse.Namespace) -> QualityContract:
    return QualityContract(
        mode=args.mode,
        source_pixel_tolerance=args.tolerance,
        color_count=args.colors,
        min_region_area=args.min_area,
        strict_vector_only=True,
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    _rgba, analysis = load_rgba(Path(args.input))
    print(json.dumps(analysis.__dict__, indent=2, ensure_ascii=False))
    return 0


def cmd_vectorize(args: argparse.Namespace) -> int:
    result = vectorize(
        args.input,
        output_svg=args.output,
        contract=_contract_from_args(args),
        write_preview=not args.no_preview,
        write_report=not args.no_report,
    )
    summary = {
        "svg_path": result["svg_path"],
        "report_path": result["report_path"],
        "preview_path": result["preview_path"],
        "overall": result["report"]["overall"],
        "primitive_counts": result["report"]["primitive_counts"],
        "raster_metrics": result["report"]["raster_metrics"],
        "elapsed_ms": result["elapsed_ms"],
        "warnings": result["report"]["warnings"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if result["report"]["overall"] in ("passed", "partial", "indeterminate") else 1


def cmd_selftest(args: argparse.Namespace) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cfvx-selftest-"))
    png = tmp / "circle.png"
    synthesize_circle_png(png)
    contract = QualityContract(
        mode="structural", source_pixel_tolerance=0.75, color_count=4, min_region_area=4
    )
    result = vectorize(png, output_svg=tmp / "circle.svg", contract=contract, write_preview=True)
    counts = result["report"]["primitive_counts"]
    print(json.dumps({"tmpdir": str(tmp), "counts": counts, "report": result["report"]}, indent=2))
    if counts.get("circle", 0) + counts.get("arc", 0) < 1:
        print("selftest: expected at least one arc/circle for a synthetic disk", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="cfvx",
        description=(
            "CFV-X raster-to-vector: circle-first primitive selection, "
            "observation-aware quantization, SVG export, and verification reports."
        ),
    )
    p.add_argument("--version", action="version", version=f"cfvx {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Inspect an image without vectorizing")
    a.add_argument("input")
    a.set_defaults(func=cmd_analyze)

    v = sub.add_parser("vectorize", help="Convert a raster image to SVG")
    v.add_argument("input")
    v.add_argument("-o", "--output", help="Output SVG path")
    v.add_argument(
        "--mode",
        choices=["faithful", "structural"],
        default="faithful",
        help="faithful keeps AA/noise; structural prefers simpler geometry",
    )
    v.add_argument("--tolerance", type=float, default=0.65, help="Source-pixel geometry tolerance")
    v.add_argument("--colors", type=int, default=22, help="Palette k before boundary-cluster merge")
    v.add_argument("--min-area", type=int, default=5, help="Merge components smaller than this")
    v.add_argument("--no-preview", action="store_true")
    v.add_argument("--no-report", action="store_true")
    v.set_defaults(func=cmd_vectorize)

    t = sub.add_parser("selftest", help="Synthetic circle round-trip")
    t.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return int(args.func(args))
