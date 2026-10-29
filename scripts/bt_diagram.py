"""Reverse-engineer Mermaid diagrams and an architecture inventory from biosciences-temporal
source, and check them and the reverse-architecture (RA) docs against it.

Static analysis only (stdlib `ast` and text parsing); nothing is imported or executed from
the target repository, so it needs no Temporal server, biosciences-mcp checkout, or API keys.

Usage (from the repo root):
    python scripts/bt_diagram.py [ROOT] [flow|sequence|facts|inventory|check|drift|write]

    flow, sequence  print a Mermaid diagram of each workflow
    facts           print the extracted facts as JSON (with line numbers, for debugging)
    inventory       print the committed architecture inventory: workflows, worker
                    registration, activities, and AgentRunner/AgentMetadata definitions
    check           rule check: worker registration, activity timeouts, AgentMetadata vs metadata-spec.md
    drift           compare the generated files with the committed ones, and check that
                    the RA docs mention every name in the inventory and in docs/inspect.json
    write           regenerate the committed generated files (UTF-8, LF), the fix for a
                    stale file; it also runs scripts/document_architecture.py when present,
                    which regenerates docs/inspect.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PKG = "src/biosciences_temporal"
GENERATED = {
    "inventory": "docs/ra_architecture/architecture_inventory.generated.json",
}
RA_DIR = "docs/ra_architecture"
INSPECT = "docs/inspect.json"
INSPECT_SCRIPT = "scripts/document_architecture.py"
METADATA_SPEC = "docs/metadata-spec.md"
REGENERATE = "regenerate with: uv run python scripts/bt_diagram.py . write"
RA_DIAGRAMS = "docs/ra_architecture/02_architecture_diagrams.md"
BEGIN = "<!-- BEGIN GENERATED: scripts/bt_diagram.py write; do not edit by hand -->"
END = "<!-- END GENERATED -->"


def _name(node: ast.AST | None) -> str:
    """Dotted name for Name/Attribute nodes, string value for Constant str, else ''."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _src(node: ast.AST | None) -> str | None:
    return ast.unparse(node) if node is not None else None


def _config_dicts(timeouts_path: Path) -> dict[str, dict[str, str]]:
    """Extract top-level dict literals (SHORT_ACTIVITY_CONFIG, LONG_ACTIVITY_CONFIG)."""
    if not timeouts_path.exists():
        return {}
    tree = ast.parse(timeouts_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Dict)
        ):
            entries: dict[str, str] = {}
            for k, v in zip(stmt.value.keys, stmt.value.values, strict=True):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    entries[k.value] = _src(v) or ""
            out[stmt.targets[0].id] = entries
    return out


def _kw_str(
    call: ast.Call, key: str, consts: dict[str, dict[str, str]] | None = None
) -> str | None:
    """Lookup keyword argument value as unparsed source, including `**CONFIG` splats."""
    for k in call.keywords:
        if k.arg == key:
            return _src(k.value)
        if k.arg is None and isinstance(k.value, ast.Name) and consts:
            splat_dict = consts.get(k.value.id, {})
            if key in splat_dict:
                return splat_dict[key]
    return None


@dataclass
class Step:
    kind: str  # "activity" | "fanout"
    name: str
    line: int
    phase_comment: str | None = None
    args: list[str] = field(default_factory=list)
    result: str | None = None
    timeout: str | None = None
    schedule_to_close_timeout: str | None = None
    config_name: str | None = None
    catches_exceptions: bool = False


@dataclass
class ActivityInfo:
    name: str
    module: str
    params: list[str]
    returns: str | None
    wraps_agent_fn: str | None


@dataclass
class AgentRunnerInfo:
    variable: str
    name: str
    module: str
    output_type: str | None
    phase: str
    action: str
    entity_type: str
    source: str
    model_factory: str = "create_model()"
    model_override_env: str = ""


def _nearest_phase_comment(lines: list[str], line: int) -> str | None:
    for i in range(line - 2, -1, -1):
        text = lines[i].strip()
        if text.startswith("# Phase"):
            return text.lstrip("# ").strip()
    return None


def _extract_activity_step(
    call: ast.Call,
    lines: list[str],
    consts: dict[str, dict[str, str]],
    target: str | None,
    lineno: int,
    kind: str,
    catches_exceptions: bool,
) -> Step:
    act_name = _name(call.args[0]) if call.args else ""
    args_kw = next((k.value for k in call.keywords if k.arg == "args"), None)
    if isinstance(args_kw, ast.List):
        args = [_src(a) or "" for a in args_kw.elts]
    else:
        args = [_src(a) or "" for a in call.args[1:]]
    splat_name = next(
        (
            k.value.id
            for k in call.keywords
            if k.arg is None and isinstance(k.value, ast.Name)
        ),
        None,
    )
    return Step(
        kind=kind,
        name=act_name,
        line=lineno,
        phase_comment=_nearest_phase_comment(lines, lineno),
        args=args,
        result=target,
        timeout=_kw_str(call, "start_to_close_timeout", consts),
        schedule_to_close_timeout=_kw_str(call, "schedule_to_close_timeout", consts),
        config_name=splat_name,
        catches_exceptions=catches_exceptions,
    )


def workflow_facts(path: Path, consts: dict[str, dict[str, str]]) -> dict:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    out: dict = {"workflows": []}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        decos = {
            _name(d.func if isinstance(d, ast.Call) else d) for d in cls.decorator_list
        }
        if "workflow.defn" not in decos:
            continue
        wf: dict = {"name": cls.name, "handlers": {}, "steps": []}
        for fn in [
            n
            for n in cls.body
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
        ]:
            for d in fn.decorator_list:
                dn = _name(d.func if isinstance(d, ast.Call) else d)
                if dn in {"workflow.query", "workflow.signal", "workflow.update"}:
                    wf["handlers"].setdefault(dn.split(".")[1], []).append(fn.name)
                if dn == "workflow.run":
                    wf["run"] = fn.name
                    wf["input"] = [
                        f"{a.arg}: {_src(a.annotation)}" for a in fn.args.args[1:]
                    ]
                    wf["returns"] = _src(fn.returns)
                    wf["steps"] = _run_steps(fn, lines, consts)
        out["workflows"].append(wf)
    return out


def _run_steps(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    consts: dict[str, dict[str, str]],
) -> list[Step]:
    # Track try-block statements to mark exception-tolerant steps
    in_try_ids: set[int] = set()
    for try_node in [n for n in ast.walk(fn) if isinstance(n, ast.Try)]:
        for stmt in try_node.body:
            for sub in ast.walk(stmt):
                in_try_ids.add(id(sub))

    # Track `task_var = workflow.execute_activity(...)` and `tasks_list.append(workflow.execute_activity(...))`
    single_tasks: dict[str, tuple[ast.Call, int]] = {}
    list_tasks: dict[str, list[tuple[ast.Call, int]]] = {}
    steps: list[Step] = []

    for node in ast.walk(fn):
        # 1. `gene_a_task = workflow.execute_activity(...)`
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _name(node.value.func)
            in {"workflow.execute_activity", "workflow.start_activity"}
        ):
            single_tasks[node.targets[0].id] = (node.value, node.lineno)

        # 2. `enrich_tasks.append(workflow.execute_activity(...))`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.args
            and isinstance(node.args[0], ast.Call)
            and _name(node.args[0].func)
            in {"workflow.execute_activity", "workflow.start_activity"}
        ):
            list_tasks.setdefault(node.func.value.id, []).append(
                (node.args[0], node.lineno)
            )

    # Walk statements in source order for await calls
    all_stmts = sorted(
        [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Assign | ast.AnnAssign | ast.Expr)
        ],
        key=lambda n: n.lineno,
    )
    for stmt in all_stmts:
        target: str | None = None
        value: ast.AST | None = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = _name(stmt.targets[0]), stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            target, value = _name(stmt.target), stmt.value
        elif isinstance(stmt, ast.Expr):
            value = stmt.value

        if isinstance(value, ast.Await) and isinstance(value.value, ast.Call):
            call = value.value
            fname = _name(call.func)
            if fname in {"workflow.execute_activity", "workflow.start_activity"}:
                steps.append(
                    _extract_activity_step(
                        call,
                        lines,
                        consts,
                        target,
                        stmt.lineno,
                        kind="activity",
                        catches_exceptions=id(stmt) in in_try_ids,
                    )
                )
            elif fname == "asyncio.gather":
                ret_exc = any(
                    k.arg == "return_exceptions"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value is True
                    for k in call.keywords
                )
                gathered_calls: list[tuple[ast.Call, int]] = []
                for arg in call.args:
                    if isinstance(arg, ast.Name) and arg.id in single_tasks:
                        gathered_calls.append(single_tasks[arg.id])
                    elif (
                        isinstance(arg, ast.Starred)
                        and isinstance(arg.value, ast.Name)
                        and arg.value.id in list_tasks
                    ):
                        gathered_calls.extend(list_tasks[arg.value.id])
                # Deduplicate consecutive identical activity names within the same gather
                seen_names: set[str] = set()
                for c_node, c_line in gathered_calls:
                    act_name = _name(c_node.args[0]) if c_node.args else ""
                    if act_name in seen_names:
                        continue
                    seen_names.add(act_name)
                    steps.append(
                        _extract_activity_step(
                            c_node,
                            lines,
                            consts,
                            target,
                            c_line,
                            kind="fanout",
                            catches_exceptions=ret_exc,
                        )
                    )
    return sorted(steps, key=lambda s: s.line)


def _activity_list_symbols(activities_path: Path) -> dict[str, list[str]]:
    if not activities_path.exists():
        return {}
    tree = ast.parse(activities_path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.List)
        ):
            out[stmt.targets[0].id] = [
                _name(e) for e in stmt.value.elts if _name(e)
            ]
    return out


def plugin_facts(conn_path: Path) -> list[str]:
    if not conn_path.exists():
        return []
    tree = ast.parse(conn_path.read_text(encoding="utf-8"))
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        if _name(call.func) == "Client.connect":
            plug = next((k.value for k in call.keywords if k.arg == "plugins"), None)
            if isinstance(plug, ast.List):
                return [_src(e) or "" for e in plug.elts]
    return []


def worker_facts(worker_path: Path, activities_path: Path) -> dict:
    tree = ast.parse(worker_path.read_text(encoding="utf-8"))
    list_symbols = _activity_list_symbols(activities_path)
    plugins = plugin_facts(worker_path.parent / "connection.py")
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        if _name(call.func) == "Worker":
            acts_node = next(
                (k.value for k in call.keywords if k.arg == "activities"), None
            )
            wfs_node = next(
                (k.value for k in call.keywords if k.arg == "workflows"), None
            )
            tq_node = next(
                (k.value for k in call.keywords if k.arg == "task_queue"), None
            )
            runner_node = next(
                (k.value for k in call.keywords if k.arg == "workflow_runner"), None
            )
            if isinstance(acts_node, ast.List):
                activities = [_name(e) for e in acts_node.elts]
            elif isinstance(acts_node, ast.Name) and acts_node.id in list_symbols:
                activities = list_symbols[acts_node.id]
            else:
                activities = []
            workflows = (
                [_name(e) for e in wfs_node.elts]
                if isinstance(wfs_node, ast.List)
                else []
            )
            return {
                "task_queue": _src(tq_node),
                "workflows": workflows,
                "activities": activities,
                "workflow_runner": _src(runner_node),
                "plugins": plugins,
            }
    return {}


def activity_facts(pkg: Path) -> list[ActivityInfo]:
    found: list[ActivityInfo] = []
    for path in sorted(pkg.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Map imported aliases (`from ..agents.resolve import resolve_gene as _resolve_gene`)
        import_map: dict[str, str] = {}
        for n in tree.body:
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    import_map[a.asname or a.name] = a.name
        for fn in [
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
        ]:
            if not any(
                _name(d.func if isinstance(d, ast.Call) else d) == "activity.defn"
                for d in fn.decorator_list
            ):
                continue
            wrapped: str | None = None
            for node in ast.walk(fn):
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                    callee = _name(node.value.func)
                    if callee in import_map:
                        wrapped = import_map[callee]
                        break
            found.append(
                ActivityInfo(
                    name=fn.name,
                    module=path.relative_to(pkg).with_suffix("").as_posix(),
                    params=[f"{a.arg}: {_src(a.annotation)}" for a in fn.args.args],
                    returns=_src(fn.returns),
                    wraps_agent_fn=wrapped,
                )
            )
    return found


def agent_runner_facts(pkg: Path) -> list[AgentRunnerInfo]:
    found: list[AgentRunnerInfo] = []
    agents_dir = pkg / "agents"
    if not agents_dir.exists():
        return found
    for path in sorted(agents_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for stmt in tree.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Call)
                and _name(stmt.value.func) == "AgentRunner"
            ):
                call = stmt.value
                name_val = next(
                    (_name(k.value) for k in call.keywords if k.arg == "name"),
                    stmt.targets[0].id,
                )
                out_type = next(
                    (_src(k.value) for k in call.keywords if k.arg == "output_type"),
                    None,
                )
                model_src = next(
                    (_src(k.value) for k in call.keywords if k.arg == "model"),
                    None,
                )
                meta_node = next(
                    (k.value for k in call.keywords if k.arg == "metadata"),
                    None,
                )
                meta_fields: dict[str, str] = {}
                if isinstance(meta_node, ast.Call) and _name(meta_node.func) == "AgentMetadata":
                    for mk in meta_node.keywords:
                        if mk.arg is not None:
                            meta_fields[mk.arg] = _name(mk.value)
                found.append(
                    AgentRunnerInfo(
                        variable=stmt.targets[0].id,
                        name=name_val,
                        module=path.relative_to(pkg).with_suffix("").as_posix(),
                        output_type=out_type,
                        phase=meta_fields.get("phase", ""),
                        action=meta_fields.get("action", ""),
                        entity_type=meta_fields.get("entity_type", ""),
                        source=meta_fields.get("source", ""),
                        model_factory=model_src or f"create_model(agent_name={name_val!r})",
                        model_override_env=f"BIOSCIENCES_MODEL_{name_val.upper()}",
                    )
                )
    return found


def parse_metadata_spec(spec_path: Path) -> dict[str, set[str]]:
    """Parse allowed values for phase, action, entity_type, source from docs/metadata-spec.md."""
    if not spec_path.exists():
        return {}
    text = spec_path.read_text(encoding="utf-8")
    allowed: dict[str, set[str]] = {}
    current_field: str | None = None
    for line in text.splitlines():
        m_hdr = re.match(r"^###\s+`(\w+)`", line.strip())
        if m_hdr:
            current_field = m_hdr.group(1)
            allowed.setdefault(current_field, set())
            continue
        if current_field and line.strip().startswith("| `"):
            m_row = re.match(r"^\|\s*`([^`]+)`\s*\|", line.strip())
            if m_row:
                allowed[current_field].add(m_row.group(1))
    return allowed


def mermaid_flow(wf: dict, acts: dict[str, ActivityInfo]) -> str:
    out = [
        "flowchart TD",
        f'    start(["{wf["name"]}.{wf["run"]}({", ".join(wf["input"])})"])',
    ]
    prev = "start"
    for i, s in enumerate(wf["steps"]):
        nid = f"s{i}"
        phase_hdr = f"{s.phase_comment.split('-')[0].strip()}<br/>" if s.phase_comment else ""
        a = acts.get(s.name)
        tags = []
        if s.kind == "fanout":
            tags.append("asyncio.gather")
        if a and a.wraps_agent_fn:
            tags.append(f"agent:{a.wraps_agent_fn}")
            tags.append("model:create_model()")
        if s.catches_exceptions:
            tags.append("fault-tolerant")
        tag_str = f"<br/><i>{' · '.join(tags)}</i>" if tags else ""
        label = f"{phase_hdr}<b>{s.name}</b><br/>timeout {s.timeout}{tag_str}"
        cls_tag = "fanout" if s.kind == "fanout" else "activity"
        out.append(f'    {nid}["{label}"]:::{cls_tag}')
        out.append(f"    {prev} --> {nid}")
        prev = nid
    out.append('    done(["return CQ14Result JSON"])')
    out.append(f"    {prev} -->|complete| done")
    out.append("    classDef activity fill:#e8f0fe,stroke:#3b6fd8")
    out.append("    classDef fanout fill:#e6f4ea,stroke:#137333,stroke-width:2px")
    return "\n".join(out)


def mermaid_sequence(wf: dict, acts: dict[str, ActivityInfo]) -> str:
    out = [
        "sequenceDiagram",
        "    participant C as run_workflow / Client",
        f"    participant W as {wf['name']}",
        "    participant A as Activities (one-shot MCP)",
        "    participant AG as PydanticAI AgentRunner (OpenRouter / TypeSafe)",
        "    participant MCP as biosciences-mcp (stdio)",
        f"    C->>W: {wf['run']}({', '.join(wf['input'])})",
    ]
    last_phase = None
    for s in wf["steps"]:
        phase_title = s.phase_comment.split("-")[0].strip() if s.phase_comment else None
        if phase_title and phase_title != last_phase:
            out.append(f"    Note over W: {s.phase_comment}")
            last_phase = phase_title
        a = acts.get(s.name)
        if s.kind == "fanout":
            out.append(f"    par asyncio.gather({s.name})")
            out.append(f"        W->>A: {s.name}({', '.join(s.args)})")
            if a and a.wraps_agent_fn:
                out.append(f"        A->>AG: {a.wraps_agent_fn}(...)")
                out.append("        AG->>MCP: MCPServerStdio tool calls")
                out.append("        MCP-->>AG: CURIE / Biolink records")
            out.append(f"        A-->>W: {a.returns if a else 'dict'}")
            out.append("    end")
        else:
            out.append(f"    W->>A: {s.name}({', '.join(s.args)})")
            if a and a.wraps_agent_fn:
                out.append(f"    A->>AG: {a.wraps_agent_fn}(...)")
                out.append("    AG->>MCP: MCPServerStdio tool calls")
                out.append("    MCP-->>AG: CURIE / Biolink records")
            out.append(f"    A-->>W: {a.returns if a else 'dict'}")
    out.append("    W-->>C: CQ14Result JSON")
    return "\n".join(out)


def _facts(
    root: Path,
) -> tuple[dict, dict, list[ActivityInfo], list[AgentRunnerInfo]]:
    pkg = root / PKG
    consts = _config_dicts(pkg / "config" / "timeouts.py")
    return (
        workflow_facts(pkg / "temporal" / "workflows.py", consts),
        worker_facts(
            pkg / "temporal" / "worker.py", pkg / "temporal" / "activities.py"
        ),
        activity_facts(pkg),
        agent_runner_facts(pkg),
    )


def drift_checks(
    root: Path,
    wf_facts: dict,
    worker: dict,
    acts: list[ActivityInfo],
    agents: list[AgentRunnerInfo],
) -> list[str]:
    problems: list[str] = []
    defined = {a.name for a in acts}
    registered = set(worker.get("activities", []))
    called = {
        s.name
        for w in wf_facts["workflows"]
        for s in w["steps"]
        if s.kind in {"activity", "fanout"}
    }
    for name in sorted(called - registered):
        problems.append(f"called by workflow but not in ALL_ACTIVITIES: {name}")
    for name in sorted(registered - called):
        problems.append(f"registered in ALL_ACTIVITIES but never called: {name}")
    for name in sorted(defined - registered):
        problems.append(f"@activity.defn but not in ALL_ACTIVITIES: {name}")
    for name in sorted(registered - defined):
        problems.append(
            f"in ALL_ACTIVITIES but no @activity.defn in the package: {name}"
        )
    for w in wf_facts["workflows"]:
        for s in w["steps"]:
            if (
                s.kind in {"activity", "fanout"}
                and s.timeout is None
                and s.schedule_to_close_timeout is None
            ):
                problems.append(
                    f"{w['name']}: {s.name} has neither start_to_close_timeout "
                    "nor schedule_to_close_timeout"
                )
    spec = parse_metadata_spec(root / METADATA_SPEC)
    if spec:
        for ag in agents:
            for field_name in ("phase", "action", "entity_type"):
                val = getattr(ag, field_name)
                if val not in spec.get(field_name, set()):
                    problems.append(
                        f"AgentRunner {ag.name} ({ag.module}.py): metadata.{field_name}={val!r} "
                        f"not in {METADATA_SPEC}"
                    )
            for src_part in [p.strip() for p in ag.source.split(",") if p.strip()]:
                if src_part not in spec.get("source", set()):
                    problems.append(
                        f"AgentRunner {ag.name} ({ag.module}.py): metadata.source={src_part!r} "
                        f"not in {METADATA_SPEC}"
                    )
    return problems


def inventory(root: Path) -> dict:
    wf, worker, acts, agents = _facts(root)
    return {
        "workflows": [
            {
                "name": w["name"],
                "run": w.get("run"),
                "input": w.get("input", []),
                "returns": w.get("returns"),
                "handlers": w["handlers"],
                "activities": [
                    {
                        "name": s.name,
                        "dispatch": s.kind,
                        "config": s.config_name,
                        "timeout": s.timeout,
                        "schedule_to_close_timeout": s.schedule_to_close_timeout,
                    }
                    for s in w["steps"]
                    if s.kind in {"activity", "fanout"}
                ],
            }
            for w in wf["workflows"]
        ],
        "worker": worker,
        "activities": [dict(a.__dict__) for a in acts],
        "agents": [dict(ag.__dict__) for ag in agents],
    }


def render(root: Path, mode: str) -> str:
    if mode == "inventory":
        return json.dumps(inventory(root), indent=2) + "\n"
    wf, worker, acts, agents = _facts(root)
    if mode == "facts":
        facts = {
            "workflows": wf,
            "worker": worker,
            "activities": acts,
            "agents": agents,
        }
        return json.dumps(facts, default=lambda o: o.__dict__, indent=2) + "\n"
    draw = mermaid_flow if mode == "flow" else mermaid_sequence
    by_name = {a.name: a for a in acts}
    return "".join(draw(w, by_name) + "\n" for w in wf["workflows"])


def check(root: Path) -> list[str]:
    wf, worker, acts, agents = _facts(root)
    return drift_checks(root, wf, worker, acts, agents)


def coverage(root: Path) -> list[str]:
    docs = [p for p in sorted((root / RA_DIR).glob("*.md")) if p.name != "AGENTS.md"]
    if not docs:
        return []
    text = "\n".join(p.read_text(encoding="utf-8") for p in docs)
    text = re.sub(f"{re.escape(BEGIN)}.*?{re.escape(END)}", "", text, flags=re.DOTALL)
    inv = inventory(root)
    names = [("workflow", w["name"]) for w in inv["workflows"]]
    names += [("activity", a["name"]) for a in inv["activities"]]
    names += [("agent", ag["name"]) for ag in inv["agents"]]
    inspect_path = root / INSPECT
    if inspect_path.exists():
        contract = json.loads(inspect_path.read_text(encoding="utf-8"))
        names += [("CLI script", c["script"]) for c in contract.get("cli_scripts", [])]
    return [
        f"{RA_DIR} doesn't mention {kind} {name}"
        for kind, name in names
        if not re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text)
    ]


def ra_diagram_section(root: Path) -> str:
    wf, _, acts, _ = _facts(root)
    by_name = {a.name: a for a in acts}
    parts = [
        f"### `{w['name']}`\n\n```mermaid\n{mermaid_flow(w, by_name)}\n```\n\n"
        f"```mermaid\n{mermaid_sequence(w, by_name)}\n```"
        for w in wf["workflows"]
    ]
    return "\n" + "\n\n".join(parts) + "\n"


def _with_section(text: str, section: str) -> str | None:
    if (
        text.count(BEGIN) != 1
        or text.count(END) != 1
        or text.index(BEGIN) > text.index(END)
    ):
        return None
    head, rest = text.split(BEGIN, 1)
    tail = rest.split(END, 1)[1]
    return f"{head}{BEGIN}{section}{END}{tail}"


def ra_diagram_problems(root: Path) -> list[str]:
    path = root / RA_DIAGRAMS
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    updated = _with_section(text, ra_diagram_section(root))
    if updated is None:
        return [f"{RA_DIAGRAMS} lacks the {BEGIN} / {END} markers"]
    if updated != text:
        return [f"{RA_DIAGRAMS} has a stale generated section; {REGENERATE}"]
    return []


def drift(root: Path) -> list[str]:
    problems = []
    for mode, rel in GENERATED.items():
        path = root / rel
        if not path.exists():
            problems.append(f"{rel} is missing; {REGENERATE}")
        elif path.read_text(encoding="utf-8") != render(root, mode):
            problems.append(f"{rel} is stale; {REGENERATE}")
    return problems + ra_diagram_problems(root) + coverage(root)


def write(root: Path) -> list[Path]:
    written = []
    for mode, rel in GENERATED.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(root, mode), encoding="utf-8", newline="\n")
        written.append(path)
    ra_diagrams = root / RA_DIAGRAMS
    if ra_diagrams.exists():
        text = ra_diagrams.read_text(encoding="utf-8")
        updated = _with_section(text, ra_diagram_section(root))
        if updated is not None:
            ra_diagrams.write_text(updated, encoding="utf-8", newline="\n")
            written.append(ra_diagrams)
    if (root / INSPECT_SCRIPT).exists():
        subprocess.run([sys.executable, INSPECT_SCRIPT], cwd=root, check=True)
        written.append(root / INSPECT)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "root", nargs="?", default=".", type=Path, help="repository root"
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="flow",
        choices=["flow", "sequence", "facts", "inventory", "check", "drift", "write"],
    )
    args = parser.parse_args(argv)
    if args.mode == "write":
        for path in write(args.root):
            print(f"wrote {path}")
        return 0
    if args.mode in {"check", "drift"}:
        problems = (check if args.mode == "check" else drift)(args.root)
        print("\n".join(problems) or f"{args.mode}: ok")
        return 1 if problems else 0
    print(render(args.root, args.mode), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
