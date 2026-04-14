"""Route quality checker for SUMO .rou.xml files.

Standalone CLI script — no app imports, pure stdlib only.

Usage (from project root or backend/):
    python tests/check_routes.py --net b14e4a2c9df9be98
    python tests/check_routes.py --net b14e4a2c9df9be98.net.xml
    python tests/check_routes.py --net b14e4a2c9df9be98 --sim-dir /custom/simulation/networks

Exit codes:
    0 — all files GOOD (no warnings, no critical issues)
    1 — at least one WARNING, no CRITICAL
    2 — at least one CRITICAL issue found
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants mirrored from route_service.py — no app import needed
# ---------------------------------------------------------------------------

SCENARIO_RATES: dict[str, float] = {
    "light": 0.3,
    "moderate": 0.8,
    "heavy": 1.5,
    "rush_hour": 2.0,
}

JUNCTION_RATES: dict[str, float] = {
    "light": 0.08,
    "moderate": 0.15,
    "heavy": 0.25,
    "rush_hour": 0.35,
}

VEHICLE_DIST: dict[str, float] = {
    "motorbike": 0.80,
    "car": 0.15,
    "bus": 0.05,
}

DEFAULT_DURATION = 3600
KNOWN_SCENARIOS = list(SCENARIO_RATES.keys())  # order matters for detection


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

OK = "ok"
WARN = "warn"
CRIT = "crit"


def _status_icon(level: str) -> str:
    return {"ok": "✓", "warn": "⚠", "crit": "✗"}.get(level, "?")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _find_simulation_networks_dir(script_path: Path) -> Path:
    """Walk up from this script until a parent containing simulation/ is found."""
    for parent in script_path.resolve().parents:
        candidate = parent / "simulation" / "networks"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not locate simulation/networks/ directory. "
        "Run this script from within the project tree, or pass --sim-dir."
    )


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------

def _strip_net_suffix(name: str) -> str:
    """Normalise network argument to base ID (no extension)."""
    name = name.removesuffix(".net.xml")
    name = name.removesuffix(".net")
    name = name.removesuffix(".xml")
    return name


def _infer_scenario(stem: str) -> str | None:
    """Return scenario name found anywhere in the filename stem."""
    for sc in KNOWN_SCENARIOS:
        if f"_{sc}_" in stem or stem.endswith(f"_{sc}"):
            return sc
    return None


def _infer_tl_id(stem: str, net_base: str, scenario: str | None) -> str | None:
    """Extract tl_id from a junction route filename stem."""
    # stem: {net_base}_{tl_id}_{scenario}_jn
    prefix = f"{net_base}_"
    if not stem.startswith(prefix):
        return None
    rest = stem[len(prefix):]
    # Remove trailing _jn
    rest = rest.removesuffix("_jn")
    if scenario:
        suffix = f"_{scenario}"
        if rest.endswith(suffix):
            rest = rest[: -len(suffix)]
    return rest or None


def _discover_route_files(net_base: str, networks_dir: Path) -> list[Path]:
    """Return all .rou.xml files whose stem begins with net_base."""
    files = sorted(networks_dir.glob(f"{net_base}*.rou.xml"))
    return files


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_junction_route(path: Path) -> dict:
    """Parse a junction _jn.rou.xml file that uses <flow> elements."""
    tree = ET.parse(str(path))
    root = tree.getroot()

    flows = root.findall("flow")
    vtypes = root.findall("vType")

    flow_count = len(flows)
    vtype_count = len(vtypes)

    type_counter: Counter[str] = Counter()
    type_prob: dict[str, float] = {}  # probability sum per vehicle type
    from_edges: set[str] = set()
    to_edges: set[str] = set()
    probabilities: list[float] = []
    durations: list[tuple[float, float]] = []

    for f in flows:
        vtype = f.get("type", "unknown")
        type_counter[vtype] += 1

        from_e = f.get("from", "")
        to_e = f.get("to", "")
        if from_e:
            from_edges.add(from_e)
        if to_e:
            to_edges.add(to_e)

        prob_str = f.get("probability", "0")
        try:
            prob = float(prob_str)
        except ValueError:
            prob = 0.0
        probabilities.append(prob)
        type_prob[vtype] = type_prob.get(vtype, 0.0) + prob

        begin_str = f.get("begin", "0")
        end_str = f.get("end", "0")
        try:
            durations.append((float(begin_str), float(end_str)))
        except ValueError:
            durations.append((0.0, 0.0))

    total_prob = sum(probabilities)
    max_end = max((d[1] for d in durations), default=0.0)
    all_begin_zero = all(d[0] == 0.0 for d in durations)

    return {
        "flow_count": flow_count,
        "vtype_count": vtype_count,
        "type_counter": dict(type_counter),
        "type_prob": type_prob,       # probability-weighted distribution
        "from_edges": from_edges,
        "to_edges": to_edges,
        "total_prob": total_prob,
        "max_end": max_end,
        "all_begin_zero": all_begin_zero,
        "probabilities": probabilities,
    }


def _parse_network_route(path: Path) -> dict:
    """Parse a network-wide .rou.xml file that uses <vehicle> elements."""
    tree = ET.parse(str(path))
    root = tree.getroot()

    vehicles = root.findall("vehicle")
    vehicle_count = len(vehicles)

    ids: list[str] = []
    type_counter: Counter[str] = Counter()
    departs: list[float] = []
    edge_counts: list[int] = []

    for v in vehicles:
        vid = v.get("id", "")
        ids.append(vid)

        vtype = v.get("type", "unknown")
        type_counter[vtype] += 1

        depart_str = v.get("depart", "0")
        try:
            departs.append(float(depart_str))
        except ValueError:
            departs.append(0.0)

        route_elem = v.find("route")
        if route_elem is not None:
            edges_str = route_elem.get("edges", "")
            edges = edges_str.split() if edges_str else []
            edge_counts.append(len(edges))
        else:
            edge_counts.append(0)

    duplicate_ids = len(ids) - len(set(ids))
    min_depart = min(departs, default=0.0)
    max_depart = max(departs, default=0.0)
    avg_edges = sum(edge_counts) / max(len(edge_counts), 1)
    single_edge_count = sum(1 for c in edge_counts if c <= 1)

    early_cutoff = DEFAULT_DURATION * 0.10
    early_count = sum(1 for d in departs if d <= early_cutoff)
    early_pct = early_count / max(vehicle_count, 1)

    return {
        "vehicle_count": vehicle_count,
        "type_counter": dict(type_counter),
        "duplicate_ids": duplicate_ids,
        "min_depart": min_depart,
        "max_depart": max_depart,
        "avg_edges": avg_edges,
        "single_edge_count": single_edge_count,
        "single_edge_pct": single_edge_count / max(vehicle_count, 1),
        "early_pct": early_pct,
        "departs": departs,
    }


# ---------------------------------------------------------------------------
# Quality evaluators — return list of (level, message) tuples
# ---------------------------------------------------------------------------

def _eval_junction(data: dict, scenario: str | None) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []

    if data["flow_count"] == 0:
        issues.append((CRIT, "No <flow> elements found — file is empty or malformed"))
        return issues

    if data["vtype_count"] == 0:
        issues.append((CRIT, "No <vType> definitions embedded — SUMO will reject this file"))

    for vtype, target in VEHICLE_DIST.items():
        if data["type_counter"].get(vtype, 0) == 0:
            issues.append((WARN, f"No flows for vehicle type '{vtype}' (target {target * 100:.0f}%)"))
            continue
        # Check probability-weighted share deviates > 15pp from target
        if data["total_prob"] > 0:
            actual_share = data["type_prob"].get(vtype, 0.0) / data["total_prob"] * 100
            target_pct = target * 100
            if abs(actual_share - target_pct) > 15:
                issues.append((WARN,
                    f"'{vtype}' probability share {actual_share:.1f}% deviates >15pp "
                    f"from target {target_pct:.0f}%"))

    if len(data["from_edges"]) < 2:
        issues.append((WARN, f"Only {len(data['from_edges'])} unique incoming edge(s) — low traffic diversity"))

    if len(data["to_edges"]) < 2:
        issues.append((WARN, f"Only {len(data['to_edges'])} unique outgoing edge(s) — low traffic diversity"))

    if data["max_end"] == 0:
        issues.append((CRIT, "All flows have end=0 — no vehicles will be generated"))
    elif not data["all_begin_zero"]:
        issues.append((WARN, "Some flows have begin != 0 — check flow timing"))

    if scenario and data["total_prob"] > 0:
        target_rate = JUNCTION_RATES[scenario]
        ratio = data["total_prob"] / target_rate
        if ratio < 0.5:
            issues.append((WARN,
                f"Total probability {data['total_prob']:.4f} veh/s is much lower than "
                f"target {target_rate:.4f} veh/s for '{scenario}' (ratio {ratio:.2f}) — "
                "insufficient traffic for training"))
        elif ratio > 2.0:
            issues.append((WARN,
                f"Total probability {data['total_prob']:.4f} veh/s is much higher than "
                f"target {target_rate:.4f} veh/s for '{scenario}' (ratio {ratio:.2f}) — "
                "possible overload"))

    return issues


def _eval_network(data: dict, scenario: str | None) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []

    if data["vehicle_count"] < 50:
        issues.append((CRIT,
            f"Only {data['vehicle_count']} vehicles — too few for meaningful training "
            "(minimum recommended: 50)"))

    if scenario:
        estimated = int(SCENARIO_RATES[scenario] * DEFAULT_DURATION)
        yield_pct = data["vehicle_count"] / max(estimated, 1) * 100
        if yield_pct < 30:
            issues.append((CRIT,
                f"Very low route yield {yield_pct:.1f}% ({data['vehicle_count']}/{estimated}) — "
                "network topology is likely problematic"))
        elif yield_pct < 50:
            issues.append((WARN,
                f"Low route yield {yield_pct:.1f}% ({data['vehicle_count']}/{estimated}) — "
                "many trips dropped by duarouter; check network connectivity"))

    if data["duplicate_ids"] > 0:
        issues.append((CRIT,
            f"{data['duplicate_ids']} duplicate vehicle IDs — SUMO will reject or skip them"))

    for vtype, target in VEHICLE_DIST.items():
        actual_pct = data["type_counter"].get(vtype, 0) / max(data["vehicle_count"], 1) * 100
        target_pct = target * 100
        if abs(actual_pct - target_pct) > 15:
            issues.append((WARN,
                f"'{vtype}' distribution {actual_pct:.1f}% deviates >15pp from target {target_pct:.0f}%"))

    span = data["max_depart"] - data["min_depart"]
    span_pct = span / DEFAULT_DURATION * 100
    if span_pct < 50 and data["vehicle_count"] >= 50:
        issues.append((WARN,
            f"Departure span {span:.0f}s ({span_pct:.0f}% of {DEFAULT_DURATION}s) — "
            "traffic is clustered in a short window"))

    if data["single_edge_pct"] > 0.20:
        issues.append((WARN,
            f"{data['single_edge_count']} single-edge routes ({data['single_edge_pct'] * 100:.1f}%) — "
            "many vehicles traverse only 1 road; network may have dead-ends"))

    if data["early_pct"] > 0.50 and data["vehicle_count"] >= 50:
        issues.append((WARN,
            f"{data['early_pct'] * 100:.0f}% of vehicles depart in the first 10% of the simulation — "
            "heavy departure clustering at start"))

    return issues


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

WIDTH = 70


def _header(net_base: str) -> str:
    title = f" ROUTE QUALITY REPORT — {net_base} "
    pad = max(0, WIDTH - len(title))
    left = pad // 2
    right = pad - left
    return (
        "\n"
        + "╔" + "═" * (WIDTH - 2) + "╗\n"
        + "║" + " " * left + title + " " * right + "║\n"
        + "╚" + "═" * (WIDTH - 2) + "╝"
    )


def _section_sep(label: str) -> str:
    return "\n── " + label + " " + "─" * max(0, WIDTH - 5 - len(label))


def _summary_block(results: list[dict]) -> str:
    goods = sum(1 for r in results if r["severity"] == OK)
    warns = sum(1 for r in results if r["severity"] == WARN)
    crits = sum(1 for r in results if r["severity"] == CRIT)
    ready = crits == 0
    lines = [
        "\n" + "═" * WIDTH,
        "  SUMMARY",
        "  " + "─" * (WIDTH - 4),
        f"  Files checked   : {len(results)}",
        f"  GOOD            : {goods}",
        f"  WARNINGS only   : {warns}",
        f"  CRITICAL issues : {crits}",
        f"  Training ready  : {'YES ✓' if ready else 'NO ✗  (fix CRITICAL issues first)'}",
        "═" * WIDTH,
    ]
    return "\n".join(lines)


def _format_dist(type_counter: dict, total: int) -> str:
    parts = []
    for vtype, target in VEHICLE_DIST.items():
        count = type_counter.get(vtype, 0)
        pct = count / max(total, 1) * 100
        target_pct = target * 100
        diff = abs(pct - target_pct)
        icon = _status_icon(OK if diff <= 10 else WARN)
        parts.append(f"{vtype} {pct:.1f}%{icon}")
    return "  ".join(parts)


def _report_junction(
    path: Path,
    idx: int,
    total: int,
    data: dict,
    issues: list[tuple[str, str]],
    scenario: str | None,
    tl_id: str | None,
) -> tuple[str, str]:
    """Return (formatted_text, severity)."""
    lines = [_section_sep(f"[{idx}/{total}] {path.name}")]
    lines.append(f"  Type          : junction route")
    lines.append(f"  TL ID         : {tl_id or '(unknown)'}")
    lines.append(f"  Scenario      : {scenario or '(unknown)'}")
    lines.append(f"  Flows         : {data['flow_count']}  {_status_icon(OK if data['flow_count'] > 0 else CRIT)}")
    lines.append(f"  vTypes        : {'embedded ✓' if data['vtype_count'] > 0 else 'MISSING ✗'}"
                 f"  ({data['vtype_count']} defined)")

    # Probability-weighted vehicle type distribution
    total_prob = data["total_prob"]
    prob_parts = []
    for vtype, target in VEHICLE_DIST.items():
        vprob = data["type_prob"].get(vtype, 0.0)
        pct = vprob / max(total_prob, 1e-9) * 100
        target_pct = target * 100
        icon = _status_icon(OK if abs(pct - target_pct) <= 15 else WARN)
        prob_parts.append(f"{vtype} {pct:.1f}%{icon}")
    dist_str = "  ".join(prob_parts)
    lines.append(f"  Distribution  : {dist_str}  (probability-weighted)")

    lines.append(f"  Edge diversity: {len(data['from_edges'])} in / {len(data['to_edges'])} out"
                 f"  {_status_icon(OK if len(data['from_edges']) >= 2 and len(data['to_edges']) >= 2 else WARN)}")

    if scenario:
        target_rate = JUNCTION_RATES[scenario]
        rate_icon = _status_icon(OK if 0.5 <= data["total_prob"] / max(target_rate, 1e-9) <= 2.0 else WARN)
        lines.append(
            f"  Total rate     : {data['total_prob']:.4f} veh/s"
            f"  (target {target_rate:.4f} for '{scenario}')  {rate_icon}"
        )
    else:
        lines.append(f"  Total rate     : {data['total_prob']:.4f} veh/s  (scenario unknown)")

    duration = data["max_end"]
    est_vehicles = int(data["total_prob"] * duration) if duration > 0 else 0
    lines.append(f"  Duration       : 0 → {duration:.0f}s")
    lines.append(f"  Est. vehicles  : ~{est_vehicles} over {duration:.0f}s")

    severity = _severity_from_issues(issues)
    lines.extend(_format_issues(issues))
    lines.append(f"  → Assessment  : {_assessment_label(severity, issues)}")
    return "\n".join(lines), severity


def _report_network(
    path: Path,
    idx: int,
    total: int,
    data: dict,
    issues: list[tuple[str, str]],
    scenario: str | None,
) -> tuple[str, str]:
    """Return (formatted_text, severity)."""
    lines = [_section_sep(f"[{idx}/{total}] {path.name}")]
    lines.append(f"  Type          : network-wide route")
    lines.append(f"  Scenario      : {scenario or '(unknown)'}")

    if scenario:
        estimated = int(SCENARIO_RATES[scenario] * DEFAULT_DURATION)
        yield_pct = data["vehicle_count"] / max(estimated, 1) * 100
        yield_icon = _status_icon(OK if yield_pct >= 50 else (WARN if yield_pct >= 30 else CRIT))
        lines.append(
            f"  Vehicles      : {data['vehicle_count']:,}"
            f"  (estimated ~{estimated:,} → yield {yield_pct:.1f}%)  {yield_icon}"
        )
    else:
        lines.append(f"  Vehicles      : {data['vehicle_count']:,}")

    dist_str = _format_dist(data["type_counter"], data["vehicle_count"])
    lines.append(f"  Distribution  : {dist_str}")

    span = data["max_depart"] - data["min_depart"]
    span_pct = span / DEFAULT_DURATION * 100
    span_icon = _status_icon(OK if span_pct >= 50 else WARN)
    lines.append(
        f"  Departure span: {data['min_depart']:.1f}s – {data['max_depart']:.1f}s"
        f"  ({span_pct:.0f}% of {DEFAULT_DURATION}s)  {span_icon}"
    )

    se_pct = data["single_edge_pct"] * 100
    se_icon = _status_icon(OK if se_pct <= 20 else WARN)
    lines.append(
        f"  Route lengths : avg {data['avg_edges']:.1f} edges"
        f"  (1-edge routes: {se_pct:.1f}%)  {se_icon}"
    )

    dup_icon = _status_icon(OK if data["duplicate_ids"] == 0 else CRIT)
    lines.append(f"  Duplicate IDs : {data['duplicate_ids']}  {dup_icon}")

    severity = _severity_from_issues(issues)
    lines.extend(_format_issues(issues))
    lines.append(f"  → Assessment  : {_assessment_label(severity, issues)}")
    return "\n".join(lines), severity


def _severity_from_issues(issues: list[tuple[str, str]]) -> str:
    if any(lvl == CRIT for lvl, _ in issues):
        return CRIT
    if any(lvl == WARN for lvl, _ in issues):
        return WARN
    return OK


def _format_issues(issues: list[tuple[str, str]]) -> list[str]:
    lines = []
    for lvl, msg in issues:
        icon = _status_icon(lvl)
        tag = "WARN" if lvl == WARN else "CRIT"
        lines.append(f"  {icon} [{tag}] {msg}")
    return lines


def _assessment_label(severity: str, issues: list[tuple[str, str]]) -> str:
    warn_count = sum(1 for lvl, _ in issues if lvl == WARN)
    crit_count = sum(1 for lvl, _ in issues if lvl == CRIT)
    if severity == CRIT:
        return f"CRITICAL ✗  ({crit_count} critical, {warn_count} warning(s))"
    if severity == WARN:
        return f"GOOD with warnings  ({warn_count} warning(s))"
    return "GOOD ✓"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Force UTF-8 output so box-drawing and symbol characters render correctly
    # on all platforms (especially Windows with CP1252 default).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Check quality of SUMO .rou.xml scenario files for RL training.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--net",
        required=True,
        metavar="NETWORK_ID",
        help="Network base name or .net.xml filename (e.g. b14e4a2c9df9be98 or b14e4a2c9df9be98.net.xml)",
    )
    parser.add_argument(
        "--sim-dir",
        metavar="PATH",
        default=None,
        help="Path to simulation/networks/ directory (auto-detected if omitted)",
    )
    args = parser.parse_args()

    net_base = _strip_net_suffix(args.net)

    # Resolve simulation/networks/
    if args.sim_dir:
        networks_dir = Path(args.sim_dir).resolve()
    else:
        try:
            networks_dir = _find_simulation_networks_dir(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    net_file = networks_dir / f"{net_base}.net.xml"

    # Print header
    print(_header(net_base))
    print(f"  Network file : {net_file}  {'✓' if net_file.exists() else '✗ (not found)'}")
    print(f"  Networks dir : {networks_dir}")

    # Discover route files
    rou_files = _discover_route_files(net_base, networks_dir)
    if not rou_files:
        print(f"\n  No .rou.xml files found matching '{net_base}*.rou.xml' in {networks_dir}")
        print("  Nothing to check.\n")
        return 0

    print(f"  Route files  : {len(rou_files)} found\n")

    results: list[dict] = []

    for idx, path in enumerate(rou_files, start=1):
        # path.stem on "foo_jn.rou.xml" gives "foo_jn.rou", so strip manually
        stem = path.name.removesuffix(".rou.xml")
        is_junction = stem.endswith("_jn")
        scenario = _infer_scenario(stem)
        tl_id = _infer_tl_id(stem, net_base, scenario) if is_junction else None

        try:
            if is_junction:
                data = _parse_junction_route(path)
                issues = _eval_junction(data, scenario)
                text, severity = _report_junction(path, idx, len(rou_files), data, issues, scenario, tl_id)
            else:
                data = _parse_network_route(path)
                issues = _eval_network(data, scenario)
                text, severity = _report_network(path, idx, len(rou_files), data, issues, scenario)
        except ET.ParseError as exc:
            text = (
                _section_sep(f"[{idx}/{len(rou_files)}] {path.name}")
                + f"\n  ✗ [CRIT] XML parse error: {exc}"
                + "\n  → Assessment  : CRITICAL ✗"
            )
            severity = CRIT

        print(text)
        results.append({"path": path, "severity": severity})

    print(_summary_block(results))

    # Return exit code
    if any(r["severity"] == CRIT for r in results):
        return 2
    if any(r["severity"] == WARN for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
