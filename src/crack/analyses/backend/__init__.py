"""Read a backend as the six layers every request flows through (ch10)."""

import os
import sys

from pocketflow import Flow

from crack.core import OverviewNode
from crack.core.render import Section, Theme, esc
from crack.core.runner import repo_name_of, run_analysis
from .nodes import BuildBundle, Pipeline, LayerCode, Trace

NAME = "backend"

# The pipeline and layer-code passes emit a card per layer with code excerpts,
# which is more output than the default cap allows.
ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}

SECTIONS = [
    Section("01", "The pipeline",
            "route · middleware · handler · service · database · response",
            "pipe", 400, "pipeline_md"),
    Section("02", "The code",
            "only the layers the team built in a non-standard way",
            "code", 520, "layercode_md"),
    Section("03", "The trace",
            "one request, all six layers, and where state changes",
            "trace", 460, "trace_md"),
]

def _subtitle(shared):
    from crack.core.render import md
    welcome = (shared.get("overview") or {}).get("welcome", "")
    endpoint = shared.get("trace_endpoint", "")
    return md(welcome) or (
        f"Every request flows through the same six layers. Core endpoint: {md(endpoint)}"
        if endpoint else "Every backend request flows through the same six layers.")

def _hero_prefix(shared):
    diagram = shared.get("pipeline_diagram", "")
    if not diagram:
        return ""
    return ('    <section class="hero-diagram">\n'
            '      <div class="hero-diagram-cap">The request pipeline &mdash; six layers, every time</div>\n'
            f'      <div class="diagram"><pre class="mermaid">{esc(diagram)}</pre></div>\n'
            '    </section>\n')

def _footer(shared):
    c = shared.get("layer_counts", {})
    return (f"Read as six layers &middot; {c.get('route', 0)} routes &middot; "
            f"{c.get('handler', 0)} handlers &middot; {c.get('service', 0)} services "
            f"&middot; {c.get('database', 0)} models.")

def _md_preamble(shared):
    endpoint = shared.get("trace_endpoint")
    return f"_Core endpoint: {endpoint}_\n" if endpoint else ""

THEME = Theme(
    title_suffix="backend", eyebrow="Backend",
    accent="#4f46e5", accent_soft="#eef2ff",
    hero_from="#1e1b4b", hero_to="#0f0d2b",
    eyebrow_color="#a5b4fc", eyebrow_bar="#818cf8",
    sub_color="#d6d8f5", card_top_from="#fafaff",
    subtitle=_subtitle, footer=_footer, md_preamble=_md_preamble,
    hero_prefix=_hero_prefix,
)

def init_shared(args):
    return {"repo_path": args.repo_path}

def build_flow():
    bundle, pipeline = BuildBundle(), Pipeline()
    layercode, trace = LayerCode(), Trace()
    overview = OverviewNode(overview_spec)
    bundle >> pipeline >> layercode >> trace >> overview
    return Flow(start=bundle)

def overview_spec(shared):
    name = repo_name_of(shared["repo_path"]) or shared["repo_path"]
    c = shared.get("layer_counts", {})
    return {
        "name": name,
        "what": "a backend as the six layers every request flows through",
        "sections": [
            ("The pipeline", "the six layers every request flows through, with a count for each"),
            ("The code", "the one or two layers the team built in an unusual way, worth reading closely"),
            ("The trace", "one real request walked through all six layers, and where its data becomes durable"),
        ],
        "facts": (f"Core endpoint: {shared.get('trace_endpoint', '')}. "
                  f"Layer file counts — route {c.get('route', 0)}, middleware {c.get('middleware', 0)}, "
                  f"handler {c.get('handler', 0)}, service {c.get('service', 0)}, "
                  f"database {c.get('database', 0)}, response {c.get('response', 0)}."),
    }

def add_arguments(parser) -> None:
    """The backend analysis takes no flags beyond the common repo_path/--out."""

def run(args) -> None:
    # Exit code 1, no usage line, matching tour's run(): run(args) has no
    # parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")
    run_analysis(sys.modules[__name__], args)
