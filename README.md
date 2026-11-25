# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-e7598a44` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `research-question-decomposition-search`
- Summary: 当科研任务给出复杂研究问题并要求拆解子问题、规划多轮检索、逐题给出证据覆盖与停止判断时使用；产出保留 case_id 与全部 output_contract 字段的 /app/output/result.json。

## Contents

| File |
|------|
| `SKILL.md` |
| `examples/demo-case/case.json` |
| `rules.json` |
| `scripts/deliver.py` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
