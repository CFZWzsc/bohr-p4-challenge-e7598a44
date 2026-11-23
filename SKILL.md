---
name: research-question-decomposition-search
description: 当科研任务给出复杂研究问题并要求拆解子问题、规划多轮检索、逐题给出证据覆盖与停止判断时使用；产出保留 case_id 与全部 output_contract 字段的 /app/output/result.json。
---

# 科研问题拆解与多轮检索规划

## 用途与适用条件

把同时包含对象、机制、方法、时间与证据要求的复杂科研问题拆成可检索子问题，安排有依赖关系的查询轮次，把输入中真实存在的候选文献映射到子问题，并给出逐子问题证据覆盖、缺口与显式停止理由。适用于输入含 `/input/case.json`（或 `task.md`）且提供候选文献记录、要求"拆解—检索—覆盖—收敛"闭环的任务。

不适用：实时联网检索、单篇精读、全文翻译、写作润色、开放式科研问答；本 Skill 不生成未提供的文献。

## 输入

- `/input/case.json`：读取 `case_id`、`output_contract`、研究问题、候选记录；字段按结构识别。
- `task.md`：`/input/task.md` 存在时作为问题补充上下文。
- `rules.json`：轮次预算、每轮最小边际增益、术语上限与同义词表。

依赖 CPython 3.9+ 标准库；参数 `--case`、`--output`、`--top-k`、`--rules`；不联网、无随机数。

## 处理流程（逐项覆盖评分维度）

1. **问题拆解（实际效果 / 创新增益）**：按句读与并列关系切分子句，用显式词表把子句归入 core/mechanism/method/comparison/population/evidence/time 七类 facet，输出 `SQ1..SQn`，每项含来源文本、检索词、查询式与依赖关系。
2. **查询规划（创新增益）**：第 1 轮覆盖 core/mechanism；第 2 轮只补无支持记录的子问题；第 3 轮做受控同义词扩展。轮次与顺序写入 `query_plan.rounds`，可复算。
3. **证据映射（实际效果）**：只把输入中真实存在的记录按词项重叠分配给子问题，记录 `overlap` 与 `source_locator`；未命中任何子问题的记录保留为 `review`，不删除。
4. **覆盖与缺口（结果完整性）**：逐子问题输出 `supporting_count`、`coverage_status`（covered/gap）、证据短引；缺口明确列为 `gaps`，不补造。
5. **停止判断（创新增益 / 可靠体验）**：所有子问题有支持记录 → `stop`；预算耗尽仍有缺口 → `stop_partial` 并列出缺口；无任何记录 → `escalate`。解释写在 `stop_decision.reason`。
6. **可核验性（实际效果）**：`candidates` 保留全量并附 rank、assigned_subquestions；`evidence` 按子问题组织，短引从标题/摘要真实截取。
7. **异常与状态（可靠体验）**：缺问题、空候选、运行异常分别结构化记录；脚本失败仍写出 `status: error` 与契约占位。

## 输出契约

写入 `/app/output/result.json`；必须保留 `case_id` 与**每个原始 `output_contract` 字段**（无法推断的字段保留键并用占位值，原因写入 `output_contract_fields.notes`）。

核心字段：`status`、`question`、`decomposition`、`subquestions`、`query_plan`（含 rounds）、`queries`、`candidates`、`results`/`ranked_results`、`subquestion_coverage`、`evidence`、`stop_decision`、`gaps`、`coverage`、`metrics`、`uncertainties`、`limitations`、`change_log`。

## 异常处理

| 情况 | 行为 |
|---|---|
| case 缺失/非法 JSON | `status: error`，`error.stage: load_case`，契约占位保留，退出码 2 |
| 问题为空 | 不做拆解；`uncertainties` 记录 `missing_question` |
| 候选为空 | `status: empty`；`stop_decision.decision: escalate` |
| 子问题无命中 | 标为 `gap`，不生成文献 |
| 输出不可写 | stderr 结构化错误，退出码 3 |

## 限制与不适用

- 词面分配无法处理语义改写与跨语言表达；覆盖只相对输入候选集，不是数据库召回率。
- 不判断文献质量或结论真伪；不做全文获取。
- 不声称官方案例结果或任何基准分数。

## 最小调用示例（示例，非官方结果）

```json
{
  "case_id": "example-002",
  "question": "Does pyroptosis mediate immunotherapy resistance in melanoma, and which biomarkers predict response?",
  "candidates": [
    {"title": "Pyroptosis and immunotherapy resistance in melanoma", "abstract": "Pyroptosis markers were associated with resistance.", "doi": "10.1000/ex.2", "year": 2023}
  ],
  "output_contract": {"subquestions": "decomposed sub-questions", "evidence": "per-subquestion evidence", "stop_decision": "stop rationale"}
}
```

```bash
python /skills/weekly-skill/scripts/run_skill.py --case /app/work/example.json --output /app/output/result.json
```

示意输出（**示例**）：`status: ok`，`subquestions` 含 SQ1（core）与 SQ2（mechanism），`subquestion_coverage` 中 SQ1=covered、SQ2=gap，`stop_decision.decision` 为 `stop_partial` 并列出 `["SQ2"]`。

## 自查清单

- [ ] frontmatter `name` 小写连字符、`description` 说明触发与产出。
- [ ] `py_compile` 通过，仅标准库。
- [ ] 合成试跑后结果含 `case_id` 与全部契约字段。
- [ ] 每个子问题有证据条目或明确 gap；`stop_decision` 有理由。
- [ ] 未声称联网、官方案例或官方分数。


## 交付保证与评分对齐

1. 在 Skill 安装目录执行：`cd /skills/weekly-skill && python scripts/run_skill.py --case /input/case.json --output /app/output/result.json --top-k 0`；`rules.json` 缺失时使用内置默认值，不要假定相对路径可用。
2. 必须产出**完整成品** `result.json`：所有子问题都有 `covered`/`gap` 判定，全部候选进入 `candidates` 并带证据映射；禁止 skeleton、`pending`、空占位或只写方法说明。
3. 脚本无法自动完成的实质判断（子问题拆分合理性、真实证据映射）由调用 Agent 依据实际材料补全并写回 `result.json`，不得编造文献。
4. 自检：`case_id` 与输入一致；`output_contract` 每个字段落位；`status` 取 `ok` / `partial` / `empty` / `error`（不得写 `completed`）；`stop_decision` 有理由；同输入重复运行一致。
5. 输入缺失、JSON 损坏或字段异常时仍写出结构化结果并说明缺口，不崩溃、不静默成功。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
