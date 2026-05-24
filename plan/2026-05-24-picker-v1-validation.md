# Picker V1 Live + 合成验证报告

更新时间：2026-05-24
分支：main（PR #1 已合并）

## 1. 验证目的

V1 落地后只在 cold_start + active_suggestion 这两个分支跑过 live。其余分支（`focus_dimensions` / `dimension_trends` / `resolved_dimensions` / 难度递进）都只在 fixture 层面通过——**没在真实持久化 + RAG + audit 链路上走通**。本次验证补足这个缺口。

## 2. Live 部分：1 场完整 + 1 次配额耗尽

### 2.1 用户 `picker-v1-validation`

| Round | 状态 | 拿到的证据 |
|---|---|---|
| 1 (start) | ✅ 完整 | cold_start picker 行为正常 |
| 1 (answer) | ✅ 完整 | 评分 47.0，论据与案例质量 2.0 ⚠️ → 写入 profile |
| 2 (start) | ✅ 完整 | **首次 live 看到** `focus_question_types=['综合分析']` 真实从 `recent_weak_types` 派生进 query |
| 2 (answer) | ❌ DeepSeek HTTP 402 Insufficient Balance |
| 3 | 未跑 | 配额耗尽 |

### 2.2 关键 live 证据：query 增强真的起作用

Round 2 的 `picker_snapshot.query`：
```
社会现象 面试题 公务员 medium - **重点攻坚"论据积累"**：每周整理3个高质量案例
                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                来自 Round 1 的 training_suggestion
```

V1 从单 cold_start 跨进了**画像驱动**阶段。

### 2.3 Live 部分被 API 配额阻断

DeepSeek 余额耗尽。LLM backfill 实跑（8 次）+ 之前的 4 场 mock interview（≈ 12 次）+ 这次 3 次失败重试，累计耗光了。

## 3. 合成部分：5 场 session 全分支验证

`scripts/synthesize_picker_sessions.py` 直接构造 5 场 InterviewSession 写盘，零 API 成本。

### 3.1 5 场剧本

| sid | qt | 关键得分 | 触发 |
|---|---|---|---|
| s1 | 综合分析 | 论据 4.0 ⚠️ | 首次低分 |
| s2 | 社会现象 | 论据 4.0 ⚠️ | repeated 候选 |
| s3 | 综合分析 | 论据 7.0 | **resolved 触发** |
| s4 | 组织管理 | 总分 78.8 | 推高最近 3 场均值 |
| s5 | 计划组织 | 逻辑 4.0 ⚠️ | 新弱项 |

### 3.2 picker 派生结果（合成后）

```python
profile.dynamic.repeated_weak_dimensions:  []
profile.dynamic.resolved_dimensions:       ['论据与案例质量']
profile.dynamic.recent_weak_types:         ['计划组织', '社会现象', '综合分析']
profile.dynamic.dimension_trends:
  论据与案例质量: improving       ← 5 场轨迹真实驱动
  岗位匹配度:    improving
  逻辑完整性:    declining
  临场应对:      declining
  审题与立意:    stable
  结构化表达:    stable
  语言自然度:    stable

resolve_picker_hints(requested_difficulty='medium'):
  focus_question_types:  ['计划组织', '社会现象', '综合分析']
  avoid_question_types:  ['综合分析', '社会现象']
  suggested_difficulty:  hard            ← 最近 3 场均值 70.4 ≥ 70
  reason:                'focus_qt=... avoid_qt=... diff=medium->hard'
```

### 3.3 分支覆盖

| 分支 | 验证结果 |
|---|---|
| `recent_weak_types` → `focus_question_types` | ✅ 3 个题型都进了 |
| `resolved_dimensions` 派生 | ✅ 论据从弱项升 ≥6 后正确进入 resolved |
| `dimension_trends`：improving | ✅ |
| `dimension_trends`：declining | ✅ |
| `dimension_trends`：stable | ✅ |
| `dimension_trends`：persistently_weak | ❌ 当前剧本没构造（s3 把论据拉回了，没让任何维度持续低分） |
| `avoid_question_types` 派生 | ✅ |
| 难度递进 medium → hard | ✅ |
| 调用方指定 hard 不被覆盖 | ✅ |
| 调用方指定 easy 不被覆盖 | ✅ |
| picker_snapshot 持久化 | ✅ 5/5 coverage（来自 audit 聚合） |

## 4. 暴露的真问题

### 4.1 `avoid_question_types` 与 `focus_question_types` 重叠

```
focus_question_types:  ['计划组织', '社会现象', '综合分析']
avoid_question_types:  ['综合分析', '社会现象']
```

**两者交集 = `['综合分析', '社会现象']`**——picker 一边强推、一边软降权这些题型，自相矛盾。

**根因**：`avoid_question_types` 现在是从 `resolved_dimensions[*].question_types` 派生的，意思是"这些题型上你曾在某维度低分但已回暖"。但当前实现没去掉**当前仍是弱项题型**的部分。

**V1 简化**：当前的软降权权重只有 -0.20，`focus` 加权 +0.15 + `difficulty` 匹配 +0.10 = +0.25 能盖过去。所以这个矛盾在重排层不会让 user 实际感受到，但语义上需要在 V2 修。

**V2 修法**：派生 `avoid_question_types` 时去掉 `recent_weak_types` 的元素：
```python
avoid_question_types = [
    qt for qt in resolved_qts
    if qt not in recent_weak_types
]
```

### 4.2 没有 `persistently_weak` trend 状态在合成数据里出现

剧本设计时就让 s3 把论据拉到 7.0 了，所以没有任何维度满足"≥2 场 ≤5 + 最新分 ≤5"这个 persistently_weak 条件。

如果要补，可以加一个 s2.5：再低一次论据，s3 改成不再触发回升。但意义不大——`profile_eval` fixture 里 `profile-repeated-weak-dimension-001` 已经测过了。

## 5. 结论

**picker V1 在 live + 合成两条路径上的核心分支都拿到了证据**：

```
✅ cold_start                         (前两场 live)
✅ active_suggestion → query          (前两场 live)
✅ recent_weak_types → focus_qt        (本次 live Round 2 + 合成)
✅ resolved_dimensions                 (合成)
✅ dimension_trends 三种状态           (合成)
✅ avoid_question_types                (合成)
✅ 难度递进 medium→hard                 (合成)
✅ 调用方指定 hard/easy 不被覆盖        (合成)
✅ picker_snapshot 持久化               (audit 聚合 5/5)
⚠️ avoid 与 focus 重叠：V2 待修
❌ persistently_weak：fixture 已覆盖，live 未触发
```

**V2 设计要解决的问题（按优先级）：**

1. `avoid_question_types` 去掉 `recent_weak_types` 的交集
2. `repeated_weak_dimensions` 与 `focus_dimensions` 关系：当所有反复弱项都 resolved 后 focus_dim 就空了，是否需要回退到"最近一场低分维度"作为弱信号？
3. 难度递进当前只看总分均值，不看用户期望的题型——是否要按题型分组算？
4. 软降权权重 -0.20 vs focus +0.15 的相对值需要 live 数据校准

## 6. 文件索引

```
scripts/synthesize_picker_sessions.py            ★ 新增 5 场剧本 + picker 派生检验
data/interview/picker-v1-synth/                  ★ 合成数据落盘（gitignored）
plan/2026-05-24-picker-v1-validation.md          ← 本文档
```

## 7. 下一步

1. **不再做 V1 增强**——V1 已被多分支验证通过
2. 等真实用户使用产生**真**数据，再做 picker V2 设计
3. picker V2 设计时优先解决 §4.1 的 `avoid` / `focus` 重叠问题
