# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-e7598a44` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `research-question-decomposition-search`
- Summary: 当科研任务给出复杂研究问题并要求拆解子问题、规划多轮检索、逐题给出证据覆盖与停止判断时使用；产出保留 case_id 与全部 output_contract 字段的 /app/output/result.json。

## Contents

| File |
|------|
| `SKILL.md` |
| `rules.json` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
