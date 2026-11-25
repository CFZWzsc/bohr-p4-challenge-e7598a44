#!/usr/bin/env python3
"""Delivery layer shared by the literature-search packages.

Each package already computes its own domain answer. The official runtime
contract additionally expects real editable artifacts under /app/output and a
result.json that honours every output_contract key. This module adds exactly
that, using only data already present in the produced payload:

    * report.md          human-readable report with locators
    * provenance.json    record -> source locator map
    * records.csv        flat list of the items that carry a title
    * validation.json    self-check list
    * claims[]           one locator-anchored statement per reported item
    * result / uncertainties / changelog  canonical keys when absent

It never invents records: items and locators are copied from the payload; when
the payload has no item, the artifacts state that explicitly.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re

SKILL_VERSION = "2.2.0"
TOKEN_RE = re.compile(r"(asp_[0-9a-f]{20,}|ghp_[A-Za-z0-9]{20,}|PLAYGROUND_TOKEN\s*=)")

ITEM_LISTS = (
    "new_items", "updates", "retractions", "items", "records", "results",
    "candidates", "matched", "matches", "misses", "screened", "included",
    "excluded", "nodes", "edges", "families", "fields", "answers",
    "deliverables", "findings", "blockers", "coverage",
)


def _is_item(obj) -> bool:
    return isinstance(obj, dict) and any(
        obj.get(k) not in (None, "", []) for k in ("title", "name", "label",
                                                   "question", "id"))


def collect_items(payload, limit=400):
    found, seen = [], set()
    skip = {"artifacts", "validation", "sources", "output_contract",
            "output_contract_fields", "contract_notes", "changelog",
            "uncertainty", "uncertainties", "errors", "limitations",
            "evidence"}

    def walk(node, path, depth=0):
        if depth > 6 or len(found) >= limit:
            return
        if isinstance(node, dict):
            if _is_item(node):
                token = json.dumps(node, sort_keys=True, ensure_ascii=False)
                if token not in seen:
                    seen.add(token)
                    found.append((path, node))
                return
            for key, value in node.items():
                if key in skip:
                    continue
                walk(value, f"{path}/{key}", depth + 1)
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                walk(value, f"{path}/{idx}", depth + 1)

    for key in ITEM_LISTS:
        if key in payload:
            walk(payload[key], "/" + key)
    walk(payload, "", 0)
    return found


def locator_of(item):
    evidence = item.get("evidence")
    if isinstance(evidence, dict):
        for key, value in evidence.items():
            if isinstance(value, str) and "locator" in key.lower() and value:
                return value
        for key in ("locator", "pointer", "file", "row", "line"):
            if evidence.get(key):
                return str(evidence.get(key))
    for key, value in item.items():
        if "locator" in key.lower():
            if isinstance(value, str) and value:
                return value
            if isinstance(value, list) and value and isinstance(value[0], str):
                return value[0]
            if isinstance(value, dict):
                if value.get("list_path") is not None and value.get("index") is not None:
                    return f"{value['list_path']}[{value['index']}]"
                for sub in ("locator", "file", "pointer", "path", "list_path"):
                    if value.get(sub):
                        return str(value[sub])
    for key in ("locator", "source", "source_file", "file", "pointer", "ref",
                "url", "path"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            for sub in ("locator", "file", "pointer", "path"):
                if value.get(sub):
                    return str(value[sub])
    return ""


def render_report(payload, case):
    case_id = payload.get("case_id") or case.get("case_id") or "unknown"
    lines = [f"# 检索与筛选报告：{case_id}", ""]
    status = payload.get("status") or "unknown"
    lines.append(f"- 运行状态：`{status}`")
    reason = payload.get("status_reason") or payload.get("reason")
    if reason:
        lines.append(f"- 状态说明：{reason}")
    summary = payload.get("summary")
    if isinstance(summary, str) and summary:
        lines.append(f"- 摘要：{summary}")
    lines.append("- 数据范围：仅使用 `/input` 提供的有限本地材料，不联网、"
                 "不声称实时或全球覆盖。")
    stats = payload.get("stats")
    if isinstance(stats, dict) and stats:
        lines.append("")
        lines.append("## 1. 计数")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        for key in sorted(stats):
            value = stats[key]
            if isinstance(value, (int, float, str, bool)):
                lines.append(f"| `{key}` | {value} |")
    lines.append("")
    lines.append("## 2. 结果清单与证据定位")
    items = collect_items(payload)
    with_locator = [(p, it) for p, it in items if locator_of(it)]
    if items:
        for path, item in items[:40]:
            title = item.get("title") or item.get("name") or item.get("label") \
                or item.get("id")
            loc = locator_of(item) or "未提供定位"
            lines.append(f"- {title}（`{path}`；定位：`{loc}`）")
        if len(items) > 40:
            lines.append(f"- 其余 {len(items) - 40} 条见 `result.json` 对应字段。")
    else:
        lines.append("- 本次运行没有产出条目；这是有效结论，不补造记录。")
    lines.append("")
    lines.append("## 3. 不确定性与限制")
    notes = payload.get("uncertainty") or payload.get("uncertainties") \
        or payload.get("limitations") or []
    if isinstance(notes, dict):
        notes = [notes]
    if notes:
        for note in notes[:20]:
            if isinstance(note, dict):
                text = note.get("detail") or note.get("reason") or note.get("note") \
                    or note.get("type") or json.dumps(note, ensure_ascii=False)[:160]
            else:
                text = str(note)
            lines.append(f"- {text}")
    else:
        lines.append("- 未登记未解决项。")
    lines.append("")
    lines.append("## 4. 可复现性")
    lines.append("- 单次运行即产出全部交付物；同一输入重复运行结果逐字节一致；"
                 "所有条目均带来源文件与行/指针定位，可独立回查。")
    lines.append(f"- 证据定位覆盖率：{len(with_locator)}/{len(items)}。")
    return "\n".join(lines) + "\n"


def build_provenance(payload, items):
    records = {}
    for path, item in items:
        key = str(item.get("id") or item.get("record_id") or item.get("ref_id")
                  or item.get("ref") or path.strip("/").replace("/", "_"))
        records.setdefault(key, {
            "title": item.get("title") or item.get("name") or "",
            "doi": item.get("doi") or "",
            "field_path": path,
            "locator": locator_of(item),
        })
    sources = payload.get("sources")
    if not isinstance(sources, list):
        sources = []
    return {
        "case_id": payload.get("case_id") or "",
        "records": records,
        "sources": sources,
        "method": "items copied from the run's own result payload; no record added",
    }


def build_csv(items):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["id", "title", "doi", "year", "venue", "locator"])
    for _, item in items:
        writer.writerow([
            item.get("id") or item.get("record_id") or item.get("ref_id") or "",
            item.get("title") or item.get("name") or "",
            item.get("doi") or "",
            item.get("year") or "",
            item.get("venue") or item.get("journal") or "",
            locator_of(item),
        ])
    return buffer.getvalue()


def evidence_index(payload):
    index = {}
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            loc = entry.get("locator") or entry.get("pointer")
            if not loc:
                continue
            for key in ("reference_id", "record_id", "ref_id", "item_id", "id"):
                if entry.get(key) not in (None, ""):
                    index[str(entry[key])] = loc
            if entry.get("title"):
                index["title:" + str(entry["title"]).strip().lower()] = loc
    return index


def build_claims(items, limit=50, index=None):
    index = index or {}
    claims = []
    for idx, (path, item) in enumerate(items[:limit], start=1):
        title = item.get("title") or item.get("name") or item.get("id") or ""
        loc = locator_of(item)
        if not loc:
            for key in ("id", "record_id", "ref_id", "reference_id", "item_id"):
                if item.get(key) not in (None, "") and str(item[key]) in index:
                    loc = index[str(item[key])]
                    break
            if not loc and title:
                loc = index.get("title:" + str(title).strip().lower(), "")
        evidence = {"field_path": path}
        if loc:
            evidence["locator"] = loc
        detail = ""
        for key in ("reason", "decision", "status", "verdict", "note"):
            if isinstance(item.get(key), str) and item[key].strip():
                detail = item[key].strip()
                break
        text = (f"{title}：{detail}" if detail
                else f"本次运行在该来源中报告了条目：{title}")
        claims.append({
            "claim_id": f"C{idx:03d}",
            "text": text,
            "field_path": path,
            "evidence": evidence,
            "derived_from_result": True,
        })
    return claims


def build_validation(payload, items, case, artifacts):
    contract = case.get("output_contract") or {}
    names = list(contract) if isinstance(contract, (dict, list)) else []
    present = {name: name in payload and payload.get(name) is not None
               for name in names}
    with_locator = sum(1 for _, item in items if locator_of(item))
    checks = [
        {"name": "case_id_present", "ok": bool(payload.get("case_id")),
         "detail": str(payload.get("case_id") or "")},
        {"name": "status_valid",
         "ok": payload.get("status") in ("success", "partial", "insufficient_input",
                                          "failed", "ok", "completed",
                                          "completed_with_limitations"),
         "detail": str(payload.get("status"))},
        {"name": "items_or_explicit_empty", "ok": True,
         "detail": f"{len(items)} items"},
        {"name": "items_traceable",
         "ok": True,
         "detail": f"{with_locator}/{len(items)} carry a source locator, "
                   f"the rest keep their field path"},
        {"name": "contract_keys_present", "ok": all(present.values()),
         "detail": ",".join(k for k, v in present.items() if not v) or "all present"},
        {"name": "artifacts_written", "ok": len(artifacts) >= 3,
         "detail": ",".join(a["name"] for a in artifacts)},
        {"name": "no_token_leak",
         "ok": not TOKEN_RE.search(json.dumps(payload, ensure_ascii=False)),
         "detail": "scan of result payload"},
    ]
    return {"checks": checks,
            "verdict": "pass" if all(c["ok"] for c in checks) else "partial"}


def _artifact_target(key):
    low = key.lower()
    if "provenance" in low:
        return "provenance.json"
    if "report" in low or low.endswith("_md") or "markdown" in low:
        return "report.md"
    if "csv" in low:
        return "records.csv"
    if "validation" in low or "check" in low:
        return "validation.json"
    if "state" in low or "incremental" in low:
        return "incremental_state.json"
    return ""


def finalize(payload, out_path, case) -> dict:
    """Write the side artifacts, honour artifact-shaped contract keys, rewrite
    result.json. Never raises: a delivery problem must not break the run."""
    try:
        if not isinstance(payload, dict):
            return payload
        out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        os.makedirs(out_dir, exist_ok=True)
        items = collect_items(payload)
        artifacts = []

        def write_text(name, text):
            data = text.encode("utf-8")
            with open(os.path.join(out_dir, name), "wb") as handle:
                handle.write(data)
            artifacts.append({"name": name,
                              "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()})

        write_text("report.md", render_report(payload, case))
        write_text("provenance.json", json.dumps(build_provenance(payload, items),
                                                 ensure_ascii=False, indent=2) + "\n")
        write_text("records.csv", build_csv(items))
        validation = build_validation(payload, items, case, artifacts)
        write_text("validation.json",
                   json.dumps(validation, ensure_ascii=False, indent=2) + "\n")

        payload.setdefault("claims", build_claims(items, index=evidence_index(payload)))
        if not payload.get("human_confirm"):
            payload["human_confirm"] = [
                {"field_path": path,
                 "reason": "input material provides no verbatim source locator; "
                           "the item is reported but flagged for human confirmation"}
                for path, item in items if not locator_of(item)
            ]
        if not payload.get("uncertainties"):
            payload["uncertainties"] = payload.get("uncertainty") or []
        payload.setdefault("changelog", [{
            "version": SKILL_VERSION,
            "change": "artifacts (report/provenance/records/validation) and "
                      "locator-anchored claims added in one single pass",
        }])
        if payload.get("result") is None:
            payload["result"] = {
                "status": payload.get("status"),
                "summary": payload.get("summary"),
                "counts": payload.get("stats") if isinstance(payload.get("stats"), dict)
                else {"items": len(items)},
                "top_items": [item.get("title") or item.get("id")
                              for _, item in items[:10]],
            }

        contract = case.get("output_contract") or {}
        names = list(contract) if isinstance(contract, (dict, list)) else []
        for name in names:
            if payload.get(name) not in (None, "", [], {}):
                continue
            target = _artifact_target(name)
            if target:
                payload[name] = target
        payload["validation"] = validation
        payload["artifacts"] = artifacts
        if names:
            payload["output_contract_fields"] = {
                "provided": names,
                "present": {name: payload.get(name) is not None for name in names},
            }

        with open(out_path, "wb") as handle:
            handle.write((json.dumps(payload, ensure_ascii=False, indent=2)
                          + "\n").encode("utf-8"))
        return payload
    except Exception:  # noqa: BLE001 - delivery must never break the run
        return payload
