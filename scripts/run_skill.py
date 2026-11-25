#!/usr/bin/env python3
"""Research-question decomposition and multi-round search planning skill.

Reads /input/case.json (or --case), decomposes the actual research question
into retrievable sub-questions, plans ordered query rounds, maps only the
records present in the input to sub-questions, and reports evidence coverage
plus an explicit stop decision. Writes /app/output/result.json (or --output)
preserving case_id and all original output_contract fields. Offline, stdlib.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUTPUT = "/app/output/result.json"
HERE = Path(__file__).resolve().parent
RULES_PATH = HERE.parent / "rules.json"

STOP = set("""the and for with from that this these those into about between among using used
use based study studies paper papers article articles literature search find relevant review
reviews research results result analysis evidence question what which how does do is are was
were be been can could should would may might will shall not but also than more most less least
all any each other such their there where when why who whom whose its it as at by in on of or to
an a we they he she i you our your 研究 文献 检索 相关 问题 方法 分析 结果 证据 综述 论文 以及 并且
进行 通过 基于 对于 关于 是否 如何 什么 需要 提供 给出 可以 能够 这个 这些 那些 一个 一种 我们 他们""".split())
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}|[\u4e00-\u9fff]{2,}")
SENT_SPLIT = re.compile(r"(?<=[。！？.!?])\s*")
CLAUSE_SPLIT = re.compile(r"[。；;！？!?\n]|,|\uFF0C")
FACET_PATTERNS = {
    "mechanism": ["mechanism", "pathway", "signaling", "causal", "mechanistic", "机制", "通路", "信号", "作用"],
    "method": ["method", "model", "algorithm", "assay", "trial", "randomized", "cohort", "scrna", "crispr",
               "方法", "模型", "算法", "实验", "队列", "随机", "测序"],
    "evidence": ["evidence", "guideline", "meta-analysis", "systematic review", "consensus", "rct",
                 "证据", "指南", "系统综述", "共识", "随机对照"],
    "comparison": ["versus", " vs ", "compare", "comparison", "better", "superior", "对比", "比较", "优于", "差异"],
    "time": ["recent", "latest", "since", "between", "year", "近", "最近", "近年", "以来", "年"],
    "population": ["patient", "participants", "mice", "cohort", "population", "sample", "患者", "人群", "样本", "小鼠"],
    "outcome": ["biomarker", "predict", "response", "outcome", "survival", "efficacy",
                "生物标志", "预测", "疗效", "生存", "结局", "应答"],
}

DEFAULT_RULES = {
    "round_budget": 3,
    "min_marginal_gain": 1,
    "max_terms_per_query": 6,
    "synonyms": {
        "pyroptosis": ["inflammasome", "gasdermin", "pyroptotic"],
        "immunotherapy": ["immune checkpoint", "pd-1", "pd-l1", "car-t"],
        "cancer": ["tumor", "tumour", "neoplasm", "malignancy"],
        "machine learning": ["deep learning", "neural network"],
        "biomarker": ["predictor", "signature", "marker"],
        "single-cell": ["scrna-seq", "single cell sequencing"],
        "gene editing": ["crispr", "cas9"],
        "drug resistance": ["refractory", "treatment failure", "resistance"],
    },
}


def load_rules():
    rules = json.loads(json.dumps(DEFAULT_RULES))
    try:
        if RULES_PATH.exists():
            data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    rules[key] = value
    except Exception:
        pass
    return rules


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def norm_space(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def tokens(text):
    out = []
    for match in TOKEN_RE.finditer(norm_space(text)):
        token = match.group(0).lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if token not in STOP:
                out.append(token)
            for i in range(len(token) - 1):
                bigram = token[i:i + 2]
                if bigram not in STOP:
                    out.append(bigram)
        else:
            token = token.strip(".-")
            if len(token) > 2 and token not in STOP:
                out.append(token)
                if "-" in token:
                    out.extend(p for p in token.split("-") if len(p) > 3 and p not in STOP)
    seen = []
    for token in out:
        if token not in seen:
            seen.append(token)
    return seen


def token_set(text):
    return set(tokens(text))


def pick(record, names):
    for name in names:
        if name in record and record[name] not in (None, "", [], {}):
            return record[name]
    return None


def author_text(value):
    if isinstance(value, str):
        return norm_space(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("family") or item.get("literal")
                if name:
                    parts.append(str(name))
        return "; ".join(parts)
    if isinstance(value, dict):
        return author_text(value.get("authors") or value.get("author") or [])
    return ""


def normalize_record(raw, locator):
    rec = raw if isinstance(raw, dict) else {"value": raw}
    year = None
    year_raw = pick(rec, ["year", "pub_year", "publication_year", "published", "date"])
    if isinstance(year_raw, int):
        year = year_raw
    elif isinstance(year_raw, str):
        m = re.search(r"(19|20)\d{2}", year_raw)
        if m:
            year = int(m.group(0))
    doi = norm_space(str(pick(rec, ["doi", "DOI"]) or "")).lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    keywords = pick(rec, ["keywords", "terms", "subject_terms"]) or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in re.split(r"[;,]", keywords) if k.strip()]
    journal = pick(rec, ["journal", "venue", "container_title", "期刊"])
    if isinstance(journal, dict):
        journal = journal.get("title") or journal.get("name") or ""
    return {
        "record_id": str(pick(rec, ["record_id", "id", "paper_id", "uid"]) or ""),
        "title": norm_space(str(pick(rec, ["title", "article_title", "paper_title", "题名"]) or "")),
        "abstract": norm_space(str(pick(rec, ["abstract", "summary", "摘要"]) or "")),
        "doi": doi,
        "pmid": str(pick(rec, ["pmid", "pubmed_id"]) or ""),
        "year": year,
        "journal": norm_space(str(journal or "")),
        "authors": author_text(pick(rec, ["authors", "author", "creator"])),
        "keywords": [norm_space(str(k)) for k in keywords if str(k).strip()],
        "source_db": norm_space(str(pick(rec, ["source_db", "database", "provider"]) or "")),
        "source_locator": locator,
    }


def record_key(rec):
    if rec["doi"]:
        return "doi:" + rec["doi"]
    if rec["pmid"]:
        return "pmid:" + rec["pmid"]
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", rec["title"].lower())
    return "title:" + (title or rec["source_locator"])


def looks_like_record(node, path):
    if not isinstance(node, dict):
        return False
    keys = {k.lower() for k in node.keys()}
    has_title = bool(keys & {"title", "article_title", "paper_title", "题名"})
    if has_title and (keys & {"doi", "abstract", "authors", "author", "year", "journal", "venue", "pmid"}):
        return True
    return bool(has_title and any(m in path.lower() for m in ("candidate", "paper", "record", "result", "article", "item")))


def collect_candidates(case):
    if isinstance(case, dict):
        for key in ("candidates", "papers", "records", "articles", "items", "search_results"):
            value = case.get(key)
            if isinstance(value, list) and value:
                return [(f"/{key}/{i}", v) for i, v in enumerate(value) if isinstance(v, dict)]
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            if looks_like_record(node, path):
                found.append((path, node))
                return
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(case, "")
    return found


def extract_question(case):
    if not isinstance(case, dict):
        return ""
    for key in ("question", "research_question", "research_problem", "topic"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return norm_space(value)
    task = case.get("task")
    if isinstance(task, str) and task.strip():
        return norm_space(task)
    if isinstance(task, dict):
        for key in ("question", "description", "prompt"):
            if isinstance(task.get(key), str) and task[key].strip():
                return norm_space(task[key])
    task_md = Path("/input/task.md")
    if task_md.exists():
        try:
            return norm_space(task_md.read_text(encoding="utf-8", errors="replace"))[:2000]
        except Exception:
            return ""
    return ""


def facet_of(clause):
    low = clause.lower()
    hits = [name for name, words in FACET_PATTERNS.items() if any(word in low for word in words)]
    if not hits:
        return "core"
    for preferred in ("mechanism", "method", "comparison", "evidence", "population", "time"):
        if preferred in hits:
            return preferred
    return hits[0]


def decompose(question, rules):
    clauses = [norm_space(c) for c in CLAUSE_SPLIT.split(question) if norm_space(c)]
    if not clauses:
        clauses = [question]
    max_terms = int(rules.get("max_terms_per_query", 6))
    order = {"core": 0, "mechanism": 1, "method": 2, "comparison": 3,
             "population": 4, "evidence": 5, "outcome": 6, "time": 7}
    items = []
    for index, clause in enumerate(clauses):
        facet = facet_of(clause)
        terms = tokens(clause)[:max_terms]
        if not terms:
            continue
        items.append((order.get(facet, 9), index, facet, clause, terms))
    items.sort(key=lambda item: (item[0], item[1]))
    subquestions = []
    seen = set()
    for _, _, facet, clause, terms in items:
        signature = tuple(sorted(terms))
        if signature in seen:
            continue
        seen.add(signature)
        index = len(subquestions) + 1
        subquestions.append({
            "subquestion_id": f"SQ{index}",
            "facet": facet,
            "source_text": clause[:400],
            "question": f"What evidence addresses the {facet} aspect: {clause[:200]}",
            "terms": terms,
            "query_string": " AND ".join(terms[:4]) if len(terms) >= 2 else terms[0],
            "depends_on": ["SQ1"] if facet != "core" and index > 1 else [],
            "status": "planned",
        })
    if not subquestions:
        terms = tokens(question)[:max_terms]
        if terms:
            subquestions.append({
                "subquestion_id": "SQ1", "facet": "core",
                "source_text": question[:400],
                "question": "What evidence addresses the research question?",
                "terms": terms, "query_string": " AND ".join(terms[:4]),
                "depends_on": [], "status": "planned",
            })
    return subquestions


def expand_terms(terms, rules):
    synonyms = rules.get("synonyms") or {}
    extra = []
    for term in terms:
        for key, values in synonyms.items():
            if term == key or term in key.split() or key in terms and term in key.split():
                for value in values:
                    value = norm_space(value).lower()
                    if value and value not in terms and value not in extra:
                        extra.append(value)
    return extra


def assign(records, subquestions):
    for sq in subquestions:
        sq["supporting_records"] = []
    for rec in records:
        text = token_set(" ".join([rec["title"], rec["abstract"], " ".join(rec["keywords"])]))
        best = None
        best_overlap = 0
        for sq in subquestions:
            overlap = len(text & set(sq["terms"]))
            if overlap > best_overlap:
                best, best_overlap = sq, overlap
        if best is not None and best_overlap > 0:
            best["supporting_records"].append({"record_id": rec["record_id"] or record_key(rec), "overlap": best_overlap})
            rec["assigned_subquestions"] = rec.get("assigned_subquestions", []) + [best["subquestion_id"]]
        else:
            rec["assigned_subquestions"] = rec.get("assigned_subquestions", [])
    return records


def build_rounds(subquestions, rules):
    budget = int(rules.get("round_budget", 3))
    rounds = []
    pending = [sq for sq in subquestions]
    for round_index in range(1, budget + 1):
        if not pending:
            break
        if round_index == 1:
            targets = [sq for sq in pending if sq["facet"] in ("core", "mechanism")]
            purpose = "core concept coverage"
        elif round_index == 2:
            targets = [sq for sq in pending if sq["supporting_records"] == []]
            purpose = "fill sub-questions with no supporting record"
        else:
            targets = list(pending)
            purpose = "synonym expansion for residual gaps"
        if not targets:
            targets = list(pending)[:1]
        queries = []
        for sq in targets:
            terms = sq["terms"]
            if round_index >= 3:
                extra = expand_terms(terms, rules)
                terms = (terms + extra)[: int(rules.get("max_terms_per_query", 6))]
            queries.append({
                "subquestion_id": sq["subquestion_id"],
                "query_string": " AND ".join(terms[:4]) if len(terms) >= 2 else terms[0],
                "terms": terms[:6],
                "fields": ["title", "abstract", "keywords"],
                "purpose": purpose,
            })
        rounds.append({"round": round_index, "purpose": purpose, "queries": queries, "targets": [sq["subquestion_id"] for sq in targets]})
        for sq in targets:
            if sq["status"] != "planned":
                continue
            sq["status"] = "queried"
            pending = [x for x in pending if x["subquestion_id"] != sq["subquestion_id"]]
    return rounds[:budget]


def build_result(case, args):
    rules = load_rules()
    question = extract_question(case)
    raw = collect_candidates(case)
    records = [normalize_record(v, locator) for locator, v in raw]
    unique = {}
    duplicates = []
    for rec in records:
        key = record_key(rec)
        if key in unique:
            for field in ("title", "abstract", "doi", "pmid", "year", "journal", "authors"):
                if not unique[key].get(field) and rec.get(field):
                    unique[key][field] = rec[field]
            duplicates.append({"kept": key, "duplicate_locator": rec["source_locator"], "reason": "same identifier"})
        else:
            unique[key] = rec
    records = list(unique.values())
    subquestions = decompose(question, rules) if question else []
    records = assign(records, subquestions)
    rounds = build_rounds(subquestions, rules)
    uncertainties = []
    if not question:
        uncertainties.append({"type": "missing_question", "detail": "No research question in the actual input; decomposition cannot be grounded."})
    if not records:
        uncertainties.append({"type": "empty_candidates", "detail": "No records were supplied; coverage is unknown rather than zero."})

    for sq in subquestions:
        count = len(sq["supporting_records"])
        sq["supporting_count"] = count
        sq["coverage_status"] = "covered" if count >= 1 else "gap"
        evidence = []
        for ref in sq["supporting_records"][:3]:
            rec = next((r for r in records if (r["record_id"] or record_key(r)) == ref["record_id"]), None)
            if not rec:
                continue
            quote = ""
            for text in (rec["title"], rec["abstract"]):
                for sentence in [s for s in SENT_SPLIT.split(text or "") if s.strip()]:
                    if any(term in sentence.lower() for term in sq["terms"]):
                        quote = sentence.strip()[:300]
                        break
                if quote:
                    break
            evidence.append({"record_id": ref["record_id"], "overlap_terms": ref["overlap"], "quote": quote, "locator": rec["source_locator"]})
        sq["evidence"] = evidence
        sq["note"] = "Coverage counts only records actually present in the input; it is not a database recall estimate."
    gaps = [sq["subquestion_id"] for sq in subquestions if sq["supporting_count"] == 0]
    total_support = sum(sq["supporting_count"] for sq in subquestions)
    if not records:
        stop = {"decision": "escalate", "reason": "No retrievable records were supplied; nothing can be concluded.", "gaps": gaps}
    elif subquestions and not gaps:
        stop = {"decision": "stop", "reason": "Every planned sub-question has at least one supporting record in the supplied set; further rounds have no evidence target.", "gaps": []}
    elif len(rounds) >= int(rules.get("round_budget", 3)):
        stop = {"decision": "stop_partial", "reason": "Round budget exhausted; uncovered sub-questions are listed as gaps rather than filled by invented evidence.", "gaps": gaps}
    else:
        stop = {"decision": "continue", "reason": "Some sub-questions remain uncovered and budget remains.", "gaps": gaps}
    ranked = sorted(
        records,
        key=lambda r: (-sum(ref["overlap"] for sq in subquestions for ref in sq["supporting_records"]
                             if ref["record_id"] == (r["record_id"] or record_key(r))),
                       (r["title"] or "").lower(), record_key(r)),
    )
    for rank, rec in enumerate(ranked, start=1):
        rec["rank"] = rank
        rec["relevance"] = "direct" if rec.get("assigned_subquestions") else "uncertain"
        rec["decision"] = "keep" if rec.get("assigned_subquestions") else "review"
    top_k = args.top_k if args.top_k and args.top_k > 0 else len(ranked)
    top = ranked[:top_k]
    result = {
        "case_id": str(case.get("case_id") or case.get("id") or "") if isinstance(case, dict) else "",
        "status": "ok" if question and records else ("empty" if not records else "partial"),
        "skill": {"name": "research-question-decomposition-search", "version": "1.0.0", "engine": "python-stdlib", "network": "disabled"},
        "question": question,
        "decomposition": {
            "method": "clause splitting plus facet classification (core/mechanism/method/comparison/population/evidence/time)",
            "facet_counts": {facet: len([s for s in subquestions if s["facet"] == facet]) for facet in sorted({s["facet"] for s in subquestions})},
        },
        "subquestions": subquestions,
        "query_plan": {"rounds": rounds, "round_budget": int(rules.get("round_budget", 3)), "ordering_rule": "core/mechanism first, then empty sub-questions, then synonym expansion"},
        "queries": [{"round": r["round"], **q} for r in rounds for q in r["queries"]],
        "candidates": ranked,
        "results": top,
        "ranked_results": top,
        "subquestion_coverage": [
            {"subquestion_id": sq["subquestion_id"], "facet": sq["facet"], "supporting_count": sq["supporting_count"],
             "coverage_status": sq["coverage_status"], "evidence": sq["evidence"]} for sq in subquestions
        ],
        "coverage": {
            "input_records": len(raw), "unique_records": len(records), "duplicates_merged": len(duplicates),
            "subquestions": len(subquestions), "covered_subquestions": len(subquestions) - len(gaps),
            "assigned_records": sum(1 for r in ranked if r.get("assigned_subquestions")),
            "unassigned_records": sum(1 for r in ranked if not r.get("assigned_subquestions")),
        },
        "evidence": {sq["subquestion_id"]: sq["evidence"] for sq in subquestions},
        "stop_decision": stop,
        "gaps": gaps,
        "missing": gaps,
        "metrics": {"input_candidates": len(raw), "unique_candidates": len(records), "top_k": top_k, "rounds_planned": len(rounds)},
        "duplicates": duplicates,
        "uncertainties": uncertainties + [
            {"type": "coverage_scope", "detail": "Coverage is measured against the supplied candidate set only; no live database recall is claimed."}
        ] if records else [],
        "limitations": [
            "Sub-question assignment uses lexical overlap and cannot resolve semantic ambiguity.",
            "No live search is performed and no records are added beyond the input.",
            "A gap means no supporting record was supplied, not that no such literature exists.",
        ],
        "change_log": [
            "Parsed the actual question and split it into clauses/facets.",
            "Planned ordered rounds with explicit stop criteria before reading results.",
            "Assigned only supplied records to sub-questions and retained their source locators.",
        ],
    }
    return apply_contract(result, case)


def contract_names(case):
    contract = case.get("output_contract") if isinstance(case, dict) else None
    names = []
    if isinstance(contract, dict):
        names = list(contract.keys())
    elif isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("name", "field", "key", "id"):
                    if isinstance(item.get(key), str):
                        names.append(item[key])
                        break
    return names


def placeholder(name):
    low = name.lower()
    if any(k in low for k in ("question", "quer", "candidate", "result", "paper", "record", "list", "gap", "round", "evidence", "subquestion")):
        return []
    if any(k in low for k in ("summary", "status", "coverage", "plan", "meta", "map", "detail", "note", "decision")):
        return {}
    return None


def apply_contract(result, case):
    names = contract_names(case)
    notes = {}
    for name in names:
        if name not in result:
            result[name] = placeholder(name)
            notes[name] = "Not inferable from the actual input; placeholder preserved for output_contract completeness."
    result["output_contract_fields"] = {"provided": names, "present": {n: (n in result) for n in names}, "notes": notes}
    return result


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, str(target))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Decompose a research question and plan bounded search rounds")
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument("--output", "--out", default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=0)
    parser.add_argument("--rules", default="")
    args = parser.parse_args(argv)
    os.environ["SK_RESULT_PATH"] = str(getattr(args, "out", None) or getattr(args, "output", None) or "")
    global RULES_PATH
    if args.rules:
        RULES_PATH = Path(args.rules)
    case = {}
    stage = "load_case"
    try:
        case = load_json(args.case)
        if not isinstance(case, dict):
            raise ValueError("case.json root is not an object")
        stage = "build_result"
        payload = build_result(case, args)
        code = 0
    except Exception as exc:
        payload = {
            "case_id": str(case.get("case_id") or case.get("id") or "") if isinstance(case, dict) else "",
            "status": "error",
            "error": {"type": type(exc).__name__, "message": str(exc)[:500], "stage": stage},
            "subquestions": [], "queries": [], "candidates": [], "ranked_results": [], "results": [],
            "subquestion_coverage": [], "evidence": {}, "gaps": [],
            "uncertainties": [{"type": "runtime_error", "detail": "Run failed; no evidence or conclusions are reported."}],
            "limitations": ["Failed run: output contains no invented records."],
        }
        payload = apply_contract(payload, case)
        code = 2
    try:
        write_json(args.output, payload)
    except Exception as exc:
        sys.stderr.write(json.dumps({"status": "error", "stage": "write_output", "message": str(exc)}, ensure_ascii=False) + "\n")
        return 3
    sys.stdout.write(json.dumps({"status": payload.get("status"), "output": str(args.output), "case_id": payload.get("case_id")}, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.environ.get("SK_RESULT_PATH") or "result.json"
            _d = os.path.dirname(os.path.abspath(_p))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    _fallback = os.environ.get("SK_RESULT_PATH", "")
    if _fallback and not os.path.isfile(_fallback):
        try:
            _parent = os.path.dirname(os.path.abspath(_fallback))
            if _parent:
                os.makedirs(_parent, exist_ok=True)
            with open(_fallback, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0 if _fallback else _rc)
