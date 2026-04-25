#!/usr/bin/env python3
"""
Skill Dashboard

Web dashboard for managing Kimi CLI skills and MCP servers.
Scans ~/.kimi/skills/ and ~/.kimi/mcp.json, displays metadata,
usage stats, health status. Supports activation/deactivation.

Usage:
    python3 skill_dashboard.py [--port 8080] [--open]
"""

import argparse
import json
import os
import re
import shutil
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SKILLS_DIR = Path.home() / ".kimi" / "skills"
USAGE_LOG = SKILLS_DIR / ".usage_log.jsonl"
REGISTRY_FILE = SKILLS_DIR / ".skill-registry.json"
MCP_JSON = Path.home() / ".kimi" / "mcp.json"


# ---------------------------------------------------------------------------
# Skill helpers
# ---------------------------------------------------------------------------

def parse_skill_metadata(skill_dir: Path) -> dict:
    """Parse SKILL.md frontmatter and content."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    content = skill_md.read_text()
    meta = {"name": skill_dir.name, "dir": str(skill_dir), "health": "unknown", "type": "skill"}

    # Parse YAML frontmatter
    if content.startswith("---"):
        try:
            end = content.find("---", 3)
            if end != -1:
                fm_text = content[3:end].strip()
                lines = fm_text.splitlines()
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if ":" in line and not line.strip().startswith("-"):
                        k, v = line.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k == "description" and v in ("|", "|-", "|+"):
                            i += 1
                            desc_lines = []
                            while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t") or not lines[i].strip()):
                                if lines[i].strip():
                                    desc_lines.append(lines[i].strip())
                                i += 1
                            meta["description"] = " ".join(desc_lines)
                            continue
                        elif k in ("name", "description", "version", "author", "license", "url", "category"):
                            meta[k] = v
                        elif k in ("metadata", "hermes"):
                            pass
                    i += 1
        except Exception:
            pass

    if "description" not in meta or not meta["description"]:
        desc_match = re.search(r"## Description\s*\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
        if desc_match:
            meta["description"] = desc_match.group(1).strip()[:200]

    meta["has_references"] = (skill_dir / "references").exists()
    meta["has_scripts"] = (skill_dir / "scripts").exists()
    refs_dir = skill_dir / "references"
    meta["reference_count"] = len(list(refs_dir.rglob("*"))) if refs_dir.exists() else 0

    health_issues = []
    if not meta.get("description"):
        health_issues.append("Missing description")
    if not content.startswith("---"):
        health_issues.append("Missing YAML frontmatter")

    meta["health"] = "healthy" if not health_issues else "issues"
    meta["health_issues"] = health_issues
    return meta


def load_registry() -> dict:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text())
        except Exception:
            pass
    return {"skills": {}, "mcp_servers": {}, "mcp_backups": {}, "last_scan": None}


def save_registry(registry: dict):
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2))


def infer_category(name: str) -> str:
    mapping = {
        "clarification": "workflow",
        "plan-crafting": "workflow",
        "plan-first": "workflow",
        "milestone-planning": "workflow",
        "long-run": "workflow",
        "run-plan": "workflow",
        "orchestrator": "system",
        "skill-manager": "system",
        "mcp-builder": "system",
        "git-workflow": "devops",
        "test-driven-development": "quality",
        "clean-ai-slop": "quality",
        "comment-check": "quality",
        "quality-gate": "quality",
        "design-studio": "creative",
        "frontend-design": "creative",
        "web-artifacts-builder": "creative",
        "imagegen": "creative",
        "sora": "creative",
        "pptx": "creative",
        "karpathy": "knowledge",
        "llm-wiki": "knowledge",
        "user-memory": "knowledge",
        "systematic-debugging": "debug",
        "webapp-testing": "testing",
        "claude-tone": "style",
        "rob-pike": "style",
        "simplify": "style",
        "smart-compact": "style",
        "xlsx": "data",
        "docx": "data",
        "codex-imagegen-2-skill-for-kimi": "deploy",
    }
    return mapping.get(name, "uncategorized")


def infer_tags(name: str) -> list[str]:
    tags = []
    if "test" in name or "quality" in name or "clean" in name:
        tags.extend(["quality", "testing"])
    if "plan" in name or "milestone" in name or "run" in name:
        tags.extend(["planning", "workflow"])
    if "design" in name or "image" in name or "sora" in name or "artifact" in name:
        tags.extend(["creative", "visual"])
    if "wiki" in name or "memory" in name or "karpathy" in name:
        tags.extend(["knowledge", "memory"])
    if "debug" in name or "systematic" in name:
        tags.extend(["debug", "troubleshoot"])
    if "git" in name:
        tags.extend(["git", "devops"])
    if "orchestrator" in name or "skill-manager" in name or "mcp" in name:
        tags.extend(["system", "management"])
    if "webapp" in name or "testing" in name:
        tags.extend(["testing", "playwright"])
    if "xlsx" in name or "docx" in name or "pptx" in name:
        tags.extend(["document", "office"])
    return tags or ["general"]


def scan_skills() -> list[dict]:
    skills = []
    registry = load_registry()

    for item in sorted(SKILLS_DIR.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        meta = parse_skill_metadata(item)
        if meta:
            reg_entry = registry.get("skills", {}).get(item.name, {})
            meta["active"] = reg_entry.get("active", True)
            meta["usage_count"] = reg_entry.get("usage_count", 0)
            meta["last_used"] = reg_entry.get("last_used", None)
            skill_md = item / "SKILL.md"
            if skill_md.exists():
                meta["last_updated"] = datetime.fromtimestamp(skill_md.stat().st_mtime).isoformat()[:10]
            else:
                meta["last_updated"] = "-"
            # Registry overrides SKILL.md for editable fields
            meta["category"] = reg_entry.get("category") or meta.get("category") or infer_category(item.name)
            meta["description"] = reg_entry.get("description") or meta.get("description") or ""
            meta["url"] = reg_entry.get("url") or meta.get("url") or ""
            meta["tags"] = reg_entry.get("tags", infer_tags(item.name))
            skills.append(meta)
    return skills


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------

def load_mcp_json() -> dict:
    if MCP_JSON.exists():
        try:
            return json.loads(MCP_JSON.read_text())
        except Exception:
            pass
    return {"mcpServers": {}}


def save_mcp_json(data: dict):
    MCP_JSON.write_text(json.dumps(data, indent=2) + "\n")


def scan_mcp_servers() -> list[dict]:
    """Return MCP servers as pseudo-skills."""
    registry = load_registry()
    mcp_data = load_mcp_json()
    servers = []
    backups = registry.get("mcp_backups", {})

    # Active servers from mcp.json
    for name, config in mcp_data.get("mcpServers", {}).items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        path = args[0] if args else ""
        desc = f"MCP server: {cmd} {Path(path).name}" if path else f"MCP server: {cmd}"
        servers.append({
            "name": name,
            "type": "mcp",
            "dir": str(Path(path).parent) if path else "",
            "description": desc,
            "health": "healthy",
            "health_issues": [],
            "active": True,
            "category": "mcp",
            "tags": ["mcp", "server"],
            "usage_count": registry.get("mcp_servers", {}).get(name, {}).get("usage_count", 0),
            "last_used": registry.get("mcp_servers", {}).get(name, {}).get("last_used", None),
            "last_updated": datetime.fromtimestamp(MCP_JSON.stat().st_mtime).isoformat()[:10],
            "reference_count": 0,
            "has_references": False,
            "has_scripts": False,
            "config": config,
        })

    # Inactive servers from backups
    for name, config in backups.items():
        if name not in mcp_data.get("mcpServers", {}):
            cmd = config.get("command", "")
            args = config.get("args", [])
            path = args[0] if args else ""
            desc = f"MCP server (disabled): {cmd} {Path(path).name}" if path else f"MCP server (disabled): {cmd}"
            servers.append({
                "name": name,
                "type": "mcp",
                "dir": str(Path(path).parent) if path else "",
                "description": desc,
                "health": "healthy",
                "health_issues": [],
                "active": False,
                "category": "mcp",
                "tags": ["mcp", "server"],
                "usage_count": registry.get("mcp_servers", {}).get(name, {}).get("usage_count", 0),
                "last_used": registry.get("mcp_servers", {}).get(name, {}).get("last_used", None),
                "last_updated": datetime.fromtimestamp(MCP_JSON.stat().st_mtime).isoformat()[:10],
                "reference_count": 0,
                "has_references": False,
                "has_scripts": False,
                "config": config,
            })

    return servers


def toggle_mcp_server(name: str) -> bool:
    """Enable or disable an MCP server by mutating mcp.json and registry."""
    registry = load_registry()
    mcp_data = load_mcp_json()
    servers = mcp_data.get("mcpServers", {})
    backups = registry.setdefault("mcp_backups", {})

    if name in servers:
        # Disable: move to backup and remove from mcp.json
        backups[name] = servers.pop(name)
        save_mcp_json(mcp_data)
        registry["mcp_backups"] = backups
        save_registry(registry)
        return False
    elif name in backups:
        # Enable: restore from backup
        servers[name] = backups.pop(name)
        save_mcp_json(mcp_data)
        registry["mcp_backups"] = backups
        save_registry(registry)
        return True
    else:
        raise ValueError(f"Unknown MCP server: {name}")


# ---------------------------------------------------------------------------
# Usage sync
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(skills: list[dict], mcps: list[dict]) -> str:
    total_skills = len(skills)
    total_mcps = len(mcps)
    total = total_skills + total_mcps
    active = sum(1 for s in skills if s.get("active", True)) + sum(1 for m in mcps if m.get("active", True))
    inactive = total - active
    healthy = sum(1 for s in skills if s.get("health") == "healthy") + sum(1 for m in mcps if m.get("health") == "healthy")

    categories = {}
    for s in skills + mcps:
        cat = s.get("category", "uncategorized")
        categories[cat] = categories.get(cat, 0) + 1

    import html as _html
    rows = []
    all_items = sorted(skills + mcps, key=lambda x: x.get("name", "").lower())
    for s in all_items:
        status_badge = "🟢" if s.get("active", True) else "⚫"
        health_badge = "✅" if s.get("health") == "healthy" else "⚠️"
        usage = 0
        usage_display = "-"
        last_used = s.get("last_used", "Never")[:10] if s.get("last_used") else "Never"
        last_updated = s.get("last_updated", "-") or "-"
        type_badge = "🤖" if s.get("type") == "mcp" else "📦"
        desc = s.get("description", "")
        desc_short = desc[:90] + ("..." if len(desc) > 90 else "")
        name_escaped = _html.escape(s["name"])
        url = s.get("url", "")
        url_link = f' <a href="{_html.escape(url)}" target="_blank" style="color:#58a6ff;text-decoration:none;">🔗</a>' if url else ""
        active = s.get('active', True)
        btn_class = '' if active else 'btn-inactive'
        is_skill = s.get('type') != 'mcp'
        item_type = s.get('type', 'skill')
        remove_btn = f'<button class="btn-remove" onclick="confirmRemove(\'{name_escaped}\', \'{item_type}\')">Remove</button>'
        rows.append(f"""
        <tr data-name="{name_escaped}" data-category="{_html.escape(s.get('category',''))}" data-active="{active}" data-type="{s.get('type','skill')}" data-lastused="{last_updated}" data-lastupdated="{last_updated}">
            <td><input type="checkbox" class="row-check" data-name="{name_escaped}"></td>
            <td>{type_badge} {status_badge}</td>
            <td><strong>{name_escaped}</strong></td>
            <td><span class="cat cat-{s.get('category','')}">{_html.escape(s.get('category',''))}</span></td>
            <td class="desc">{_html.escape(desc_short)}{url_link}</td>
            <td>{health_badge}</td>
            <td>{last_updated}</td>
            <td>
                <button class="{btn_class}" onclick="toggleItem('{name_escaped}', '{s.get('type','skill')}', this)">{'Disable' if active else 'Enable'}</button>
                <button onclick="showDetail('{name_escaped}')">Detail</button>
                {remove_btn}
            </td>
        </tr>
        """)

    cat_bars = ""
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        cat_bars += f'<div class="bar" onclick="filterCategory(\'{cat}\')"><div class="bar-fill" style="width:{pct}%"></div><span>{cat} ({count})</span></div>'

    html_prefix = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Skill &amp; MCP Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
        h1 {{ color: #58a6ff; margin-bottom: 10px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; }}
        .stat-card h3 {{ font-size: 12px; color: #8b949e; text-transform: uppercase; }}
        .stat-card .num {{ font-size: 28px; font-weight: bold; color: #58a6ff; }}
        .filters {{ margin-bottom: 15px; display: flex; gap: 10px; flex-wrap: wrap; }}
        .filters input, .filters select {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 12px; border-radius: 6px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th {{ text-align: left; padding: 10px; background: #161b22; color: #8b949e; font-weight: 600; border-bottom: 1px solid #30363d; }}
        td {{ padding: 10px; border-bottom: 1px solid #21262d; }}
        tr:hover {{ background: #161b22; }}
        .cat {{ color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; }}
        .cat-mcp {{ background: #8957e5; }}
        .cat-system {{ background: #1f6feb; }}
        .cat-workflow {{ background: #238636; }}
        .cat-quality {{ background: #d29922; }}
        .cat-creative {{ background: #db61a2; }}
        .cat-knowledge {{ background: #2ea043; }}
        .cat-debug {{ background: #f85149; }}
        .cat-testing {{ background: #3fb950; }}
        .cat-style {{ background: #8b949e; }}
        .cat-data {{ background: #79c0ff; color: #0d1117; }}
        .cat-devops {{ background: #a371f7; }}
        .cat-uncategorized {{ background: #484f58; }}
        .cat-deploy {{ background: #2f81f7; }}
        .desc {{ color: #8b949e; }}
        button {{ background: #1f6feb; color: white; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; margin-right: 4px; }}
        button:hover {{ background: #388bfd; }}
        button.secondary {{ background: #21262d; border: 1px solid #30363d; }}
        button.secondary:hover {{ background: #30363d; }}
        button.btn-inactive {{ background: #484f58; color: #8b949e; }}
        button.btn-inactive:hover {{ background: #6e7681; }}
        button.btn-remove {{ background: #da3633; }}
        button.btn-remove:hover {{ background: #f85149; }}
        button.btn-remove:disabled {{ background: #484f58; color: #8b949e; cursor: not-allowed; }}
        th.sortable {{ cursor: pointer; user-select: none; }}
        th.sortable:hover {{ color: #58a6ff; }}
        th.sort-asc::after {{ content: ' ▲'; font-size: 10px; color: #58a6ff; }}
        th.sort-desc::after {{ content: ' ▼'; font-size: 10px; color: #58a6ff; }}
        .edit-field {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 10px; border-radius: 4px; width: 100%; font-size: 14px; margin-top: 4px; }}
        .edit-field:focus {{ outline: none; border-color: #58a6ff; }}
        .detail-row {{ margin-bottom: 12px; }}
        .detail-row label {{ display: block; font-size: 12px; color: #8b949e; margin-bottom: 2px; }}
        .detail-row .readonly {{ background: #0d1117; padding: 6px 10px; border-radius: 4px; border: 1px solid #21262d; font-size: 14px; word-break: break-all; }}
        .save-btn {{ background: #238636; }}
        .save-btn:hover {{ background: #2ea043; }}
        .detail-actions {{ display: flex; gap: 8px; margin-top: 16px; }}
        #remove-modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); justify-content: center; align-items: center; z-index: 100; }}
        #remove-content {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 24px; max-width: 400px; width: 90%; }}
        #remove-input {{ margin: 12px 0; }}
        .remove-actions {{ display: flex; gap: 10px; justify-content: flex-end; margin-top: 16px; }}
        .chart {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 20px; }}
        .bar {{ margin: 5px 0; position: relative; cursor: pointer; }}
        .bar:hover .bar-fill {{ opacity: 0.8; }}
        .bar-fill {{ height: 20px; background: #238636; border-radius: 4px; }}
        .bar span {{ position: absolute; left: 5px; top: 2px; font-size: 12px; }}
        #detail-modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); justify-content: center; align-items: center; }}
        #detail-content {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; }}
        .close {{ float: right; cursor: pointer; font-size: 20px; }}
        .tabs {{ display: flex; gap: 10px; margin-bottom: 15px; }}
        .tab {{ cursor: pointer; padding: 6px 12px; border-radius: 6px; background: #21262d; }}
        .tab.active {{ background: #1f6feb; }}
        mark {{ background: #d29922; color: #0d1117; padding: 1px 3px; border-radius: 3px; font-weight: 600; }}
        #toast-container {{ position: fixed; top: 20px; right: 20px; z-index: 200; display: flex; flex-direction: column; gap: 8px; }}
        .toast {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px 16px; color: #c9d1d9; font-size: 14px; animation: toastIn 0.3s ease; min-width: 200px; border-left: 4px solid #30363d; }}
        .toast.success {{ border-left-color: #238636; }}
        .toast.error {{ border-left-color: #f85149; }}
        .toast.warning {{ border-left-color: #d29922; }}
        @keyframes toastIn {{ from {{ transform: translateX(100%); opacity: 0; }} to {{ transform: translateX(0); opacity: 1; }} }}
        .bulk-actions {{ display: none; gap: 8px; align-items: center; margin-bottom: 12px; padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; }}
        .bulk-actions.visible {{ display: flex; }}
        .bulk-count {{ color: #8b949e; font-size: 12px; margin-right: 8px; }}
        .row-check {{ cursor: pointer; }}
        #selectAll {{ cursor: pointer; }}
        .shortcuts {{ color: #8b949e; font-size: 11px; margin-left: auto; }}
        kbd {{ background: #21262d; border: 1px solid #30363d; padding: 1px 5px; border-radius: 4px; font-family: monospace; font-size: 11px; }}
    </style>
</head>
<body>
    <h1>🔧 Skill &amp; MCP Dashboard <span style="font-size:14px;color:#8b949e;font-weight:400">(crafted by <a href="https://github.com/ktkarchive" target="_blank" style="color:#58a6ff;text-decoration:none;">@ktk.archive</a>)</span></h1>
    <p style="color:#8b949e;margin-bottom:20px;">Managing {total} items · {total_skills} skills · {total_mcps} MCP servers · {active} active · {inactive} inactive · {healthy} healthy</p>

    <div class="stats">
        <div class="stat-card"><h3>Total</h3><div class="num">{total}</div></div>
        <div class="stat-card"><h3>Skills</h3><div class="num">{total_skills}</div></div>
        <div class="stat-card"><h3>MCP Servers</h3><div class="num" style="color:#a371f7">{total_mcps}</div></div>
        <div class="stat-card"><h3>Active</h3><div class="num" style="color:#3fb950">{active}</div></div>
        <div class="stat-card"><h3>Inactive</h3><div class="num" style="color:#8b949e">{inactive}</div></div>
        <div class="stat-card"><h3>Healthy</h3><div class="num" style="color:#3fb950">{healthy}</div></div>
    </div>

    <div class="chart">
        <h3 style="margin-bottom:10px">Categories</h3>
        {cat_bars}
    </div>

    <div class="bulk-actions" id="bulkActions">
        <span class="bulk-count" id="bulkCount">0 selected</span>
        <button onclick="bulkToggle(true)">Enable</button>
        <button onclick="bulkToggle(false)">Disable</button>
        <button class="btn-remove" onclick="bulkRemove()">Remove</button>
        <span class="shortcuts"><kbd>/</kbd> search <kbd>esc</kbd> close <kbd>r</kbd> refresh</span>
    </div>

    <div class="filters">
        <input type="text" id="search" placeholder="Search..." onkeyup="filterTable()">
        <select id="catFilter" onchange="filterTable()">
            <option value="">All Categories</option>
            {''.join(f'<option value="{c}">{c}</option>' for c in sorted(categories.keys()))}
        </select>
        <select id="statusFilter" onchange="filterTable()">
            <option value="">All Status</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
        </select>
        <select id="typeFilter" onchange="filterTable()">
            <option value="">All Types</option>
            <option value="skill">Skills</option>
            <option value="mcp">MCP Servers</option>
        </select>
        <button onclick="location.reload()">Refresh</button>
    </div>

    <table>
        <thead>
            <tr>
                <th><input type="checkbox" id="selectAll" onclick="toggleSelectAll(this)"></th>
                <th class="sortable" data-col="1" onclick="sortTable(1)">Type/Status</th>
                <th class="sortable" data-col="2" onclick="sortTable(2)">Name</th>
                <th class="sortable" data-col="3" onclick="sortTable(3)">Category</th>
                <th class="sortable" data-col="4" onclick="sortTable(4)">Description</th>
                <th class="sortable" data-col="5" onclick="sortTable(5)">Health</th>
                <th class="sortable" data-col="6" onclick="sortTable(6)">Last Updated</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="skillTable">
            {''.join(rows)}
        </tbody>
    </table>

    <div id="detail-modal" onclick="closeDetail(event)">
        <div id="detail-content" onclick="event.stopPropagation()">
            <span class="close" onclick="document.getElementById('detail-modal').style.display='none'">&times;</span>
            <div id="detail-body"></div>
        </div>
    </div>

    <div id="remove-modal" onclick="closeRemoveModal(event)">
        <div id="remove-content" onclick="event.stopPropagation()">
            <h3 style="color:#f85149;margin-bottom:8px">⚠️ Delete Skill</h3>
            <p style="color:#8b949e;font-size:14px">This action cannot be undone. To permanently delete <strong id="remove-target-name" style="color:#c9d1d9"></strong>, type <code style="background:#0d1117;padding:2px 6px;border-radius:4px">remove</code> below:</p>
            <input type="text" id="remove-input" class="edit-field" placeholder="Type 'remove' to confirm" oninput="checkRemoveInput()">
            <div class="remove-actions">
                <button class="secondary" onclick="document.getElementById('remove-modal').style.display='none'">Cancel</button>
                <button id="remove-confirm-btn" class="btn-remove" disabled onclick="executeRemove()">Confirm Remove</button>
            </div>
        </div>
    </div>
"""

    js_template = """
    <script>
        const allItems = %s;
        function showToast(message, type) {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast ' + (type || 'success');
            toast.textContent = message;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        function highlightText(text, query) {
            if (!query) return text;
            const lt = text.toLowerCase();
            const lq = query.toLowerCase();
            let result = "";
            let last = 0;
            let idx = lt.indexOf(lq);
            while (idx !== -1) {
                result += text.slice(last, idx);
                result += "<mark>" + text.slice(idx, idx + query.length) + "</mark>";
                last = idx + query.length;
                idx = lt.indexOf(lq, last);
            }
            result += text.slice(last);
            return result;
        }
        function filterTable() {
            const search = document.getElementById('search').value.toLowerCase();
            const cat = document.getElementById('catFilter').value;
            const status = document.getElementById('statusFilter').value;
            const type = document.getElementById('typeFilter').value;
            const rows = document.querySelectorAll('#skillTable tr');
            saveState();
            rows.forEach(row => {
                const name = row.dataset.name.toLowerCase();
                const rowCat = row.dataset.category;
                const rowStatus = row.dataset.active;
                const rowType = row.dataset.type;
                const matchSearch = !search || name.includes(search);
                const matchCat = !cat || rowCat === cat;
                const matchStatus = !status || rowStatus === status;
                const matchType = !type || rowType === type;
                const show = matchSearch && matchCat && matchStatus && matchType;
                row.style.display = show ? '' : 'none';
                const nameCell = row.cells[2];
                const descCell = row.cells[4];
                if (!nameCell.dataset.original) nameCell.dataset.original = nameCell.innerHTML;
                if (!descCell.dataset.original) descCell.dataset.original = descCell.innerHTML;
                if (show && search) {
                    nameCell.innerHTML = highlightText(nameCell.dataset.original, search);
                    const origDesc = descCell.dataset.original;
                    if (origDesc.includes('<a')) {
                        const parts = origDesc.split('<a');
                        descCell.innerHTML = highlightText(parts[0], search) + (parts[1] ? '<a' + parts[1] : '');
                    } else {
                        descCell.innerHTML = highlightText(origDesc, search);
                    }
                } else {
                    nameCell.innerHTML = nameCell.dataset.original;
                    descCell.innerHTML = descCell.dataset.original;
                }
            });
        }
        function filterCategory(category) {
            document.getElementById('catFilter').value = category;
            filterTable();
            showToast('Filtered by category: ' + category, 'success');
        }
        function saveState() {
            localStorage.setItem('dashboard_state', JSON.stringify({
                catFilter: document.getElementById('catFilter').value,
                statusFilter: document.getElementById('statusFilter').value,
                typeFilter: document.getElementById('typeFilter').value,
                search: document.getElementById('search').value
            }));
        }
        function restoreState() {
            try {
                const s = JSON.parse(localStorage.getItem('dashboard_state') || '{}');
                if (s.catFilter) document.getElementById('catFilter').value = s.catFilter;
                if (s.statusFilter) document.getElementById('statusFilter').value = s.statusFilter;
                if (s.typeFilter) document.getElementById('typeFilter').value = s.typeFilter;
                if (s.search) document.getElementById('search').value = s.search;
                filterTable();
            } catch (e) {}
        }
        function toggleItem(name, type, btn) {
            btn.disabled = true;
            btn.textContent = '...';
            const endpoint = type === 'mcp' ? '/api/mcp/' + name + '/toggle' : '/api/skills/' + name + '/toggle';
            fetch(endpoint, {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    showToast(name + ' ' + (data.active ? 'enabled' : 'disabled'), 'success');
                    location.reload();
                })
                .catch(err => {
                    showToast('Error: ' + err, 'error');
                    btn.disabled = false;
                    btn.textContent = 'Toggle';
                });
        }
        function showDetail(name) {
            const item = allItems.find(s => s.name === name);
            if (!item) return;
            const isSkill = item.type !== 'mcp';
            const healthIssues = (item.health_issues || []).length
                ? '<ul>' + item.health_issues.map(i => '<li>' + i + '</li>').join('') + '</ul>'
                : '<span style="color:#3fb950">None</span>';
            let html = '<h2>' + (isSkill ? '📦 ' : '🤖 ') + item.name + '</h2>';
            html += '<div class="detail-row"><label>Type</label><div class="readonly">' + (item.type || 'skill') + '</div></div>';
            html += '<div class="detail-row"><label>Category</label><input type="text" id="edit-category" class="edit-field" value="' + (item.category || '') + '"></div>';
            html += '<div class="detail-row"><label>Description</label><textarea id="edit-description" class="edit-field" rows="4">' + (item.description || '') + '</textarea></div>';
            html += '<div class="detail-row"><label>URL</label><input type="text" id="edit-url" class="edit-field" placeholder="https://..."></div>';
            html += '<div class="detail-row"><label>Health</label><div class="readonly">' + item.health + '</div></div>';
            html += '<div class="detail-row"><label>Health Issues</label><div class="readonly">' + healthIssues + '</div></div>';
            if (!isSkill) {
                var cfg = item.config || {};
                var envKeys = Object.keys(cfg.env || {});
                var envMasked = envKeys.map(function(k) { return k + '=***'; });
                html += '<div class="detail-row"><label>Command</label><div class="readonly"><code>' + (cfg.command || 'N/A') + '</code></div></div>';
                html += '<div class="detail-row"><label>Args</label><div class="readonly"><code>' + JSON.stringify(cfg.args || []) + '</code></div></div>';
                html += '<div class="detail-row"><label>Env vars</label><div class="readonly"><code>' + JSON.stringify(envMasked) + '</code></div></div>';
            } else {
                html += '<div class="detail-row"><label>References</label><div class="readonly">' + item.reference_count + ' files</div></div>';
            }
            html += '<div class="detail-row"><label>Tags</label><div class="readonly">' + (item.tags || []).join(', ') + '</div></div>';
            html += '<div class="detail-row"><label>Path</label><div class="readonly"><code>' + (item.dir || '') + '</code></div></div>';
            html += '<div class="detail-actions">';
            html += '<button class="save-btn" id="detail-save-btn">Save</button>';
            html += '<button class="secondary" id="detail-close-btn">Close</button>';
            html += '</div>';
            document.getElementById('detail-body').innerHTML = html;
            document.getElementById('edit-url').value = item.url || '';
            document.getElementById('detail-modal').style.display = 'flex';
            document.getElementById('detail-save-btn').onclick = function() { saveDetail(item.name, item.type || 'skill'); };
            document.getElementById('detail-close-btn').onclick = function() { document.getElementById('detail-modal').style.display = 'none'; };
        }
        function saveDetail(name, type) {
            const category = document.getElementById('edit-category').value;
            const description = document.getElementById('edit-description').value;
            const url = document.getElementById('edit-url').value;
            const endpoint = type === 'mcp' ? '/api/mcp/' + name + '/update' : '/api/skills/' + name + '/update';
            fetch(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({category, description, url})
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('Error: ' + data.error, 'error'); return; }
                const item = allItems.find(s => s.name === name);
                if (item) { item.category = category; item.description = description; item.url = url; }
                const row = document.querySelector('#skillTable tr[data-name="' + name + '"]');
                if (row) {
                    row.dataset.category = category;
                    row.cells[3].innerHTML = '<span class="cat cat-' + category + '">' + category + '</span>';
                    const descShort = description.length > 90 ? description.substring(0, 90) + '...' : description;
                    if (url) {
                        row.cells[4].innerHTML = descShort + ' <a href="' + url + '" target="_blank" style="color:#58a6ff;text-decoration:none;">🔗</a>';
                    } else {
                        row.cells[4].textContent = descShort;
                    }
                }
                document.getElementById('detail-modal').style.display = 'none';
                showToast(name + ' saved', 'success');
            })
            .catch(err => showToast('Error: ' + err, 'error'));
        }
        let sortDir = {};
        function sortTable(colIndex) {
            const tbody = document.getElementById('skillTable');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const th = document.querySelector('th[data-col="' + colIndex + '"]');
            if (!th) return;
            const key = th.textContent.trim();
            const currentDir = sortDir[key] || 'asc';
            const newDir = currentDir === 'asc' ? 'desc' : 'asc';
            sortDir = {}; sortDir[key] = newDir;
            document.querySelectorAll('th.sortable').forEach(h => h.classList.remove('sort-asc','sort-desc'));
            th.classList.add(newDir === 'asc' ? 'sort-asc' : 'sort-desc');
            rows.sort((a, b) => {
                let av = a.cells[colIndex] ? a.cells[colIndex].textContent.trim() : '';
                let bv = b.cells[colIndex] ? b.cells[colIndex].textContent.trim() : '';
                if (colIndex === 6) {
                    av = av === 'Never' || av === '-' ? '' : av;
                    bv = bv === 'Never' || bv === '-' ? '' : bv;
                }
                if (av < bv) return newDir === 'asc' ? -1 : 1;
                if (av > bv) return newDir === 'asc' ? 1 : -1;
                return 0;
            });
            rows.forEach(r => tbody.appendChild(r));
        }
        function closeDetail(e) {
            if (e.target.id === 'detail-modal') {
                document.getElementById('detail-modal').style.display = 'none';
            }
        }
        let removeTargetName = '';
        let removeTargetType = 'skill';
        function confirmRemove(name, type) {
            removeTargetName = name;
            removeTargetType = type || 'skill';
            document.getElementById('remove-target-name').textContent = name;
            document.getElementById('remove-input').value = '';
            document.getElementById('remove-confirm-btn').disabled = true;
            document.getElementById('remove-modal').style.display = 'flex';
        }
        function checkRemoveInput() {
            const val = document.getElementById('remove-input').value.trim();
            document.getElementById('remove-confirm-btn').disabled = val !== 'remove';
        }
        function executeRemove() {
            const btn = document.getElementById('remove-confirm-btn');
            btn.disabled = true; btn.textContent = 'Removing...';
            const endpoint = removeTargetType === 'mcp' ? '/api/mcp/' + removeTargetName + '/remove' : '/api/skills/' + removeTargetName + '/remove';
            fetch(endpoint, {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.error) { showToast('Error: ' + data.error, 'error'); btn.disabled = false; btn.textContent = 'Confirm Remove'; return; }
                    const row = document.querySelector('#skillTable tr[data-name="' + removeTargetName + '"]');
                    if (row) row.remove();
                    document.getElementById('remove-modal').style.display = 'none';
                    btn.textContent = 'Confirm Remove';
                    showToast(removeTargetName + ' removed', 'success');
                })
                .catch(err => { showToast('Error: ' + err, 'error'); btn.disabled = false; btn.textContent = 'Confirm Remove'; });
        }
        function closeRemoveModal(e) {
            if (e.target.id === 'remove-modal') {
                document.getElementById('remove-modal').style.display = 'none';
            }
        }
        function toggleSelectAll(cb) {
            document.querySelectorAll('.row-check').forEach(c => c.checked = cb.checked);
            updateBulkActions();
        }
        document.getElementById('skillTable').addEventListener('change', function(e) {
            if (e.target.classList.contains('row-check')) updateBulkActions();
        });
        function updateBulkActions() {
            const checked = document.querySelectorAll('.row-check:checked');
            const bulk = document.getElementById('bulkActions');
            if (checked.length > 0) {
                bulk.classList.add('visible');
                document.getElementById('bulkCount').textContent = checked.length + ' selected';
            } else {
                bulk.classList.remove('visible');
            }
        }
        function getCheckedRows() {
            return Array.from(document.querySelectorAll('.row-check:checked')).map(c => ({
                name: c.dataset.name,
                row: c.closest('tr')
            }));
        }
        function bulkToggle(enable) {
            const items = getCheckedRows();
            let done = 0;
            items.forEach(item => {
                const type = item.row.dataset.type;
                fetch('/api/' + (type === 'mcp' ? 'mcp/' : 'skills/') + item.name + '/toggle', {method: 'POST'})
                    .then(r => r.json())
                    .then(() => {
                        done++;
                        if (done === items.length) { location.reload(); }
                    })
                    .catch(err => showToast(item.name + ' toggle failed', 'error'));
            });
        }
        function bulkRemove() {
            const items = getCheckedRows();
            if (!items.length) { showToast('No items selected', 'warning'); return; }
            removeTargetName = items.map(i => i.name).join(', ');
            document.getElementById('remove-target-name').textContent = removeTargetName;
            document.getElementById('remove-input').value = '';
            document.getElementById('remove-confirm-btn').disabled = true;
            document.getElementById('remove-modal').style.display = 'flex';
            const origOnclick = document.getElementById('remove-confirm-btn').onclick;
            document.getElementById('remove-confirm-btn').onclick = function() {
                const btn = document.getElementById('remove-confirm-btn');
                btn.disabled = true; btn.textContent = 'Removing...';
                let done = 0;
                items.forEach(item => {
                    const endpoint = item.row.dataset.type === 'mcp' ? '/api/mcp/' + item.name + '/remove' : '/api/skills/' + item.name + '/remove';
                    fetch(endpoint, {method: 'POST'})
                        .then(r => r.json())
                        .then(data => {
                            if (!data.error && item.row) item.row.remove();
                            done++;
                            if (done === items.length) {
                                document.getElementById('remove-modal').style.display = 'none';
                                btn.textContent = 'Confirm Remove';
                                document.getElementById('remove-confirm-btn').onclick = origOnclick;
                                showToast(items.length + ' skills removed', 'success');
                            }
                        })
                        .catch(() => { done++; });
                });
            };
        }
        document.addEventListener('keydown', function(e) {
            if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
                e.preventDefault();
                document.getElementById('search').focus();
            }
            if (e.key === 'Escape') {
                document.getElementById('detail-modal').style.display = 'none';
                document.getElementById('remove-modal').style.display = 'none';
            }
            if ((e.key === 'r' || e.key === 'R') && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
                e.preventDefault();
                location.reload();
            }
        });
        restoreState();
    </script>
    """

    html_suffix = """
    <div id="toast-container"></div>
</body>
</html>
    """

    return html_prefix + (js_template % json.dumps(skills + mcps, default=str)) + html_suffix


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DashboardHandler(SimpleHTTPRequestHandler):
    allow_reuse_address = True
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            skills = scan_skills()
            mcps = scan_mcp_servers()
        
            html = generate_html(skills, mcps)
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        elif parsed.path == "/api/skills":
            skills = scan_skills()
            self.send_json(skills)

        elif parsed.path == "/api/mcp":
            mcps = scan_mcp_servers()
            self.send_json(mcps)

        elif parsed.path.startswith("/api/skills/") and parsed.path.endswith("/detail"):
            name = parsed.path.split("/")[3]
            skill_dir = SKILLS_DIR / name
            meta = parse_skill_metadata(skill_dir) if skill_dir.exists() else None
            self.send_json(meta or {"error": "Not found"})

        elif parsed.path == "/api/stats":
            skills = scan_skills()
            mcps = scan_mcp_servers()
        
            self.send_json({
                "total_skills": len(skills),
                "total_mcps": len(mcps),
                "total": len(skills) + len(mcps),
                "active_skills": sum(1 for s in skills if s.get("active", True)),
                "active_mcps": sum(1 for m in mcps if m.get("active", True)),
                "healthy": sum(1 for s in skills if s.get("health") == "healthy") + sum(1 for m in mcps if m.get("health") == "healthy"),
                "categories": {cat: sum(1 for x in skills + mcps if x.get("category") == cat) for cat in set(s.get("category", "unknown") for s in skills + mcps)},

            })

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path.startswith("/api/skills/") and parsed.path.endswith("/toggle"):
            name = parsed.path.split("/")[3]
            registry = load_registry()
            if "skills" not in registry:
                registry["skills"] = {}
            if name not in registry["skills"]:
                registry["skills"][name] = {}
            current = registry["skills"][name].get("active", True)
            registry["skills"][name]["active"] = not current
            save_registry(registry)
            self.send_json({"name": name, "active": not current, "type": "skill"})

        elif parsed.path.startswith("/api/mcp/") and parsed.path.endswith("/toggle"):
            name = parsed.path.split("/")[3]
            try:
                new_active = toggle_mcp_server(name)
                self.send_json({"name": name, "active": new_active, "type": "mcp"})
            except ValueError as e:
                self.send_json({"error": str(e)}, status=400)

        elif parsed.path.startswith("/api/skills/") and parsed.path.endswith("/update"):
            name = parsed.path.split("/")[3]
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()
            data = json.loads(body)
            registry = load_registry()
            if "skills" not in registry:
                registry["skills"] = {}
            if name not in registry["skills"]:
                registry["skills"][name] = {}
            if "category" in data:
                registry["skills"][name]["category"] = data["category"]
            if "description" in data:
                registry["skills"][name]["description"] = data["description"]
            if "url" in data:
                registry["skills"][name]["url"] = data["url"]
            save_registry(registry)
            self.send_json({"name": name, "updated": True})

        elif parsed.path.startswith("/api/mcp/") and parsed.path.endswith("/update"):
            name = parsed.path.split("/")[3]
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()
            data = json.loads(body)
            registry = load_registry()
            if "mcp_servers" not in registry:
                registry["mcp_servers"] = {}
            if name not in registry["mcp_servers"]:
                registry["mcp_servers"][name] = {}
            if "category" in data:
                registry["mcp_servers"][name]["category"] = data["category"]
            if "description" in data:
                registry["mcp_servers"][name]["description"] = data["description"]
            if "url" in data:
                registry["mcp_servers"][name]["url"] = data["url"]
            save_registry(registry)
            self.send_json({"name": name, "updated": True})

        elif parsed.path.startswith("/api/skills/") and parsed.path.endswith("/remove"):
            name = parsed.path.split("/")[3]
            skill_dir = SKILLS_DIR / name
            if not skill_dir.exists():
                self.send_json({"error": f"Skill not found: {name}"}, status=404)
            else:
                shutil.rmtree(skill_dir)
                registry = load_registry()
                if "skills" in registry and name in registry["skills"]:
                    del registry["skills"][name]
                    save_registry(registry)
                self.send_json({"name": name, "removed": True})

        elif parsed.path.startswith("/api/mcp/") and parsed.path.endswith("/remove"):
            name = parsed.path.split("/")[3]
            mcp_data = load_mcp_json()
            servers = mcp_data.get("mcpServers", {})
            if name not in servers:
                self.send_json({"error": f"MCP server not found: {name}"}, status=404)
            else:
                del servers[name]
                save_mcp_json(mcp_data)
                registry = load_registry()
                if "mcp_servers" in registry and name in registry["mcp_servers"]:
                    del registry["mcp_servers"][name]
                if "mcp_backups" in registry and name in registry["mcp_backups"]:
                    del registry["mcp_backups"][name]
                save_registry(registry)
                self.send_json({"name": name, "removed": True})

        else:
            self.send_error(404)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def log_message(self, format, *args):
        log_dir = Path.home() / ".kimi" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "dashboard.log", "a") as f:
            f.write(f"{datetime.now().isoformat()} {format % args}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kimi Skill & MCP Dashboard")
    parser.add_argument("--port", type=int, default=8076)
    parser.add_argument("--open", action="store_true", help="Open browser automatically")
    parser.add_argument("--scan", action="store_true", help="Scan skills and MCP servers, then exit")
    parser.add_argument("--health", action="store_true", help="Run health check and exit")

    args = parser.parse_args()

    if args.scan:
        skills = scan_skills()
        mcps = scan_mcp_servers()
        for s in skills:
            print(f"{s['name']:<30} {s.get('category',''):<15} {s['health']:<10} {s.get('description','')[:50]}")
        for m in mcps:
            status = "active" if m.get("active") else "inactive"
            print(f"{m['name']:<30} {'mcp':<15} {status:<10} {m.get('description','')[:50]}")
        return

    if args.health:
        skills = scan_skills()
        mcps = scan_mcp_servers()
        issues = []
        for s in skills:
            if s.get("health") != "healthy":
                issues.append((s["name"], s.get("health_issues", [])))
        for m in mcps:
            if m.get("health") != "healthy":
                issues.append((m["name"], m.get("health_issues", [])))
        if issues:
            print(f"[health] {len(issues)} items with issues:")
            for name, problems in issues:
                print(f"  {name}: {', '.join(problems)}")
        else:
            print("[health] All items healthy!")
        return

    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True

    server = ReusableHTTPServer(("localhost", args.port), DashboardHandler)
    print(f"[dashboard] Server running at http://localhost:{args.port}")

    if args.open:
        webbrowser.open(f"http://localhost:{args.port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
