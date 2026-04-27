# 公考 / 事业编面试平台技术方案

## 1. 产品定位

本项目不是通用学习平台，也不是笔试刷题平台，而是一个面向公考 / 事业编面试训练的智能平台。

平台目标非常明确：

- 帮助考生学习面试真题
- 学习高分学生的作答方式
- 学习老师总结的不同题型解题思路与方法
- 进行模拟面试考试
- 接受追问、评分与复盘
- 长期积累个人面试表现画像

因此，平台核心不是“知识点教学”，而是“面试题训练、答题表达训练、追问应对训练、评分复盘训练”。

## 2. 输入资料范围

本项目只聚焦面试场景，输入资料不需要行测、申论、笔试题库等内容。

核心输入资料包括：

- 往年面试真题
- 往年高分学生作答
- 老师针对不同题型总结的方法论
- 热点话题材料
- 政策案例材料
- 岗位相关面试素材
- 面试示范视频 / 音频

可以把这些资料再进一步分为三类：

### 2.1 真题资料

- 结构化面试真题
- 无领导小组题目
- 岗位匹配题
- 计划组织题
- 综合分析题
- 人际沟通题
- 应急应变题

### 2.2 高分作答资料

- 往年高分学生的完整答题文本
- 高分作答拆解版
- 优秀答题结构模板
- 高分作答的亮点总结

### 2.3 老师方法论资料

- 不同题型的答题思路
- 不同题型的结构模板
- 审题方法
- 立意方法
- 展开方法
- 追问应对方法
- 常见失分点总结

## 3. 平台核心能力

平台需要具备三类核心能力。

### 3.1 资料学习能力

系统应能够：

- 管理面试真题库
- 管理高分作答库
- 管理老师方法论资料库
- 对资料进行检索、引用和对比
- 在回答时引用对应题型的作答方法

### 3.2 个性化训练能力

系统应能够：

- 根据考生过往表现建立个人画像
- 判断其常见问题
- 推荐适合的题型训练
- 提供个性化改进建议
- 给出更适合该考生的答题结构提示

### 3.3 模拟面试考试能力

系统应能够：

- 抽取或生成面试题
- 组织完整面试流程
- 控制答题阶段和追问阶段
- 支持真实考生答题
- 支持 AI 考生模拟答题
- 支持 AI 面试考官追问
- 支持结构化评分
- 输出复盘报告

## 4. 当前 DeepTutor 可复用能力

虽然当前 DeepTutor 不是专门为面试平台设计的，但有几块底座可以直接复用。

### 4.1 文档型资料输入

当前知识库系统已经支持把文档资料导入为可检索知识库。

对本项目直接有价值的资料包括：

- 面试真题整理稿
- 高分作答文本
- 老师方法论文档
- 热点材料
- 政策案例材料

当前主要支持：

- `.pdf`
- `.txt`
- `.md`
- 其他纯文本格式

代码位置：

- `deeptutor_cli/kb.py`
- `deeptutor/services/rag/components/routing.py`
- `deeptutor/knowledge/initializer.py`
- `deeptutor/knowledge/add_documents.py`

结论：

面试文本资料导入能力基本具备，可以直接作为真题库、高分作答库、方法论资料库的基础。

建议进一步补充一个独立资料导入能力：

- `pdf_to_markdown_ingest`

该能力用于把 PDF 类面试资料先转成 Markdown，再交给后续 LLM API 做结构化整理。

这里建议明确采用：

- `MinerU`

建议处理链路：

```text
PDF -> MinerU -> Markdown -> Markdown 清洗 -> LLM API 整理 -> 分类入库
```

适用资料：

- 面试真题 PDF
- 高分学生作答 PDF
- 老师方法论文档 PDF
- 热点材料 PDF

建议输出：

- 原始 Markdown
- 清洗后 Markdown
- 结构化段落
- 题型标签
- 方法论标签
- 摘要
- 可入库版本

当前仓库中已经存在 MinerU 解析 PDF 的基础能力，主要在：

- `deeptutor/tools/question/pdf_parser.py`
- `deeptutor/tools/question/question_extractor.py`

现有实现更偏试卷 / 题目解析，后续需要针对“面试资料导入”再包装一层专门的 ingest 能力。

### 4.2 TutorBot 角色化能力

当前 TutorBot 已支持：

- 独立 workspace
- 独立 persona
- 独立配置
- 共享 memory
- 独立会话历史

代码位置：

- `deeptutor/services/tutorbot/manager.py`
- `deeptutor/api/routers/tutorbot.py`
- `deeptutor_cli/bot.py`
- `deeptutor/tutorbot/templates/SOUL.md`
- `deeptutor/tutorbot/templates/USER.md`

结论：

可以直接用于构建：

- 面试考官
- 面试陪练官
- 方法论老师
- 复盘点评老师

### 4.3 Memory 长期记忆基础

当前 Memory 系统维护：

- `SUMMARY.md`
- `PROFILE.md`

可用于沉淀：

- 用户面试表现历史
- 个性化偏好
- 表达问题
- 长期改进方向

代码位置：

- `deeptutor/services/memory/service.py`

结论：

Memory 可以作为考生面试画像的基础，但需要更结构化的面试 learner profile。

## 5. 当前缺口

当前 DeepTutor 并不是完整的面试平台，还缺少几块关键能力。

### 5.1 缺少面试专用数据模型

当前系统没有面试专用的结构化数据层。

缺失内容：

- 面试题数据模型
- 高分作答数据模型
- 老师方法论数据模型
- 面试评分 rubric
- 面试 session 数据模型
- 面试追问记录模型
- PDF -> Markdown -> LLM 整理的数据清洗模型

### 5.2 缺少模拟面试考试平台

当前系统虽然有流式对话和 TutorBot，但还不是完整的模拟面试平台。

缺失能力：

- 面试 session 状态机
- 抽题组卷
- 限时答题
- 多轮追问
- 分维度评分
- 结构化复盘
- 历史成绩趋势
- 双 Agent 角色协同机制

### 5.3 视频资料输入链路不完整

如果后续需要使用：

- 面试示范视频
- 面试示范音频
- 名师讲解视频

当前系统还缺少：

- 视频转写
- 音频转写
- 时间戳对齐
- 面试片段切分
- 视频内容与题型 / 方法论绑定

## 6. 平台目标架构

建议平台在 DeepTutor 底座上按下面方式组织。

```text
用户入口
  Web / CLI / API
      ↓
DeepTutor Orchestrator
      ↓
Capabilities
  mock_interview        ← 核心能力，内部局部使用 LangGraph
  answer_analysis       ← 可选，做答题拆解和改写
  material_consult      ← 可选，查方法论、真题和高分作答
  pdf_to_markdown_ingest ← 可选，使用 MinerU 做 PDF 资料导入
      ↓
业务 Agent 层
  candidate_agent
  examiner_agent
  evaluator_agent
  report_agent
      ↓
数据层
  Interview Bank
  High Score Answer Bank
  Methodology Bank
  Learner Profile
  Interview Session Store
  Material Ingest Store
```

关键原则：

- 不改造全局 orchestrator。
- 不把 LangGraph 引入全项目。
- 只在 `mock_interview` capability 内部使用 LangGraph 实现状态机。
- 其他功能仍然走 DeepTutor 现有 capability / stream / registry 机制。

## 7. PDF 资料导入能力

建议新增独立能力：

- `pdf_to_markdown_ingest`

该能力专门处理面试资料 PDF，不与 `mock_interview` 状态机混在一起。

### 7.1 能力目标

将 PDF 资料处理成可入库、可检索、可供 LLM 整理的标准化 Markdown。

### 7.2 实现链路

建议链路：

```text
PDF 文件
  ↓
MinerU 解析
  ↓
原始 Markdown
  ↓
Markdown 清洗
  ↓
LLM API 结构化整理
  ↓
分类入库
```

### 7.3 建议新增模块

```text
deeptutor/capabilities/pdf_to_markdown_ingest.py
deeptutor/agents/material_ingest/
  mineru_adapter.py
  markdown_cleaner.py
  llm_structurer.py
  material_classifier.py
```

### 7.4 建议输出结构

建议输出字段：

- `source_file`
- `raw_markdown`
- `clean_markdown`
- `material_type`
- `question_type`
- `summary`
- `methodology_points`
- `high_score_features`
- `tags`
- `ingest_status`

其中 `material_type` 建议支持：

- `interview_question`
- `high_score_answer`
- `methodology_note`
- `hot_topic_material`

### 7.5 为什么使用 MinerU

选择 MinerU 的原因：

- 当前仓库已有基础接入
- 对 PDF 转 Markdown 场景更直接
- 便于后续交给 LLM API 做结构化整理

但要注意：

- MinerU 输出仍需要清洗
- 表格、分页、段落断裂需要二次处理
- 需要面向面试资料增加分类逻辑

## 8. 局部引入 LangGraph 的设计

### 8.1 为什么只在 mock_interview 内部使用 LangGraph

模拟面试天然是一个阶段明确的流程：

```text
出题 → 答题 → 判断是否追问 → 追问 → 再答题 → 评分 → 复盘
```

这个流程的特点是：

- 有明确状态
- 有阶段转换
- 有条件分支
- 有循环追问
- 有终止节点
- 需要保存中间状态

LangGraph 的有向图模型适合表达这种流程。`StateGraph` 节点负责读写共享 state，边负责控制流，条件边负责“是否追问”“是否结束”等判断。

因此建议：

- LangGraph 只在 `mock_interview` capability 内部使用
- 外层仍然是 DeepTutor 的 `BaseCapability`
- 对外仍然输出 DeepTutor 的流式事件
- 不把 LangGraph 变成全局编排器

### 8.2 建议新增模块

```text
deeptutor/capabilities/mock_interview.py
deeptutor/agents/interview/
  __init__.py
  graph.py
  state.py
  candidate_agent.py
  examiner_agent.py
  evaluator_agent.py
  report_agent.py
  prompts/
```

建议依赖隔离：

- 将 `langgraph` 放到可选依赖
- 只在 `mock_interview` 初始化时 import
- 未安装时给出明确提示

### 8.3 MockInterviewState

建议定义：

```python
class MockInterviewState(TypedDict):
    session_id: str
    user_id: str
    mode: str
    interview_type: str
    position_target: str
    question_type: str
    difficulty: str
    learner_profile: dict
    question: dict
    answer_turns: list[dict]
    followup_turns: list[dict]
    followup_count: int
    max_followups: int
    rubric: dict
    scores: dict
    report: dict
    next_action: str
    status: str
    error: str
```

建议支持两种模式：

- `user_answer_mode`
- `candidate_simulation_mode`

## 9. 双 Agent 模拟面试设计

### 9.1 candidate_agent

`candidate_agent` 负责从考生角度进行答题。

职责：

- 理解面试题目
- 按考生视角组织答案
- 根据设定水平模拟答题表现
- 输出结构化答题结果

建议输入：

- 面试题目
- 题型
- 岗位方向
- 限时要求
- learner profile
- 历史薄弱项

建议输出：

- 答题文本
- 答题结构
- 核心论点
- 论据材料
- 预计作答时长
- 可能失分点

它的作用不是代替真实考生训练，而是：

- 做参考作答
- 做高分 / 中分 / 低分答案对比
- 做教学示范
- 做系统调试

### 9.2 examiner_agent

`examiner_agent` 负责从现场面试考官角度对答题评分。

职责：

- 发起题目
- 控制面试节奏
- 判断是否追问
- 生成追问问题
- 基于 rubric 做分维度评分
- 输出结构化点评

建议输入：

- 面试题目
- 用户或 `candidate_agent` 的作答
- 岗位要求
- 评分 rubric
- 追问策略

建议输出：

- 是否追问
- 追问问题
- 总分
- 分维度评分
- 优点总结
- 问题总结
- 改进建议

### 9.3 为什么必须拆成两个 Agent

不建议用一个 agent 同时扮演考生和考官。

原因：

- 角色目标冲突
- 评分容易失真
- 追问逻辑不稳定
- 难以区分“参考作答”和“考官评价”

拆分的收益：

- 角色边界清晰
- 更适合多轮追问
- 更容易做结构化评分
- 更容易替换为真人答题输入
- 更方便调试与评测

## 10. 面试资料组织方式

建议把输入数据拆成三类库。

### 10.1 Interview Bank

存储：

- 往年真题
- 题型标签
- 岗位标签
- 难度标签
- 热点标签

### 10.2 High Score Answer Bank

存储：

- 高分学生作答文本
- 高分作答拆解
- 优秀表达片段
- 不同水平答案对比

### 10.3 Methodology Bank

存储：

- 老师的题型方法论
- 审题方法
- 立意方法
- 结构模板
- 展开方法
- 追问应对方法
- 常见失分点

## 11. 模拟面试流程

建议第一版流程：

1. 选择面试类型、岗位方向、题型和难度
2. 从 `Interview Bank` 抽题
3. 进入正式模拟面试
4. 用户作答，或由 `candidate_agent` 模拟考生作答
5. `examiner_agent` 进行初评
6. 如有必要，发起追问
7. 用户或 `candidate_agent` 再次补答
8. `evaluator_agent` 聚合评分
9. `report_agent` 生成复盘报告
10. 把结果回写 learner profile

## 12. 评分 Rubric

建议第一版评分维度：

- 审题与立意
- 结构化表达
- 逻辑完整性
- 论据与案例质量
- 岗位匹配度
- 语言自然度
- 临场应对
- 追问应答质量

每个维度建议输出：

- 分数
- 扣分原因
- 改进建议
- 更优表达示例

## 13. 与 DeepTutor 的集成方式

### 13.1 Capability 层

新增 capability：

```text
deeptutor/capabilities/mock_interview.py
deeptutor/capabilities/pdf_to_markdown_ingest.py
```

它应继续遵循 DeepTutor 当前机制：

- 由 `ChatOrchestrator` 调度
- 使用 `UnifiedContext` 接收输入
- 使用 `StreamBus` 输出阶段事件

### 13.2 Agent 层

新增：

```text
deeptutor/agents/interview/candidate_agent.py
deeptutor/agents/interview/examiner_agent.py
deeptutor/agents/interview/evaluator_agent.py
deeptutor/agents/interview/report_agent.py
deeptutor/agents/interview/graph.py
```

职责分配：

- `graph.py` 负责 LangGraph 状态机
- `candidate_agent.py` 负责考生视角作答
- `examiner_agent.py` 负责考官追问与评分
- `evaluator_agent.py` 负责评分聚合
- `report_agent.py` 负责复盘报告

### 13.3 数据层

建议新增：

- `interview_bank`
- `high_score_answer_bank`
- `methodology_bank`
- `interview_session_store`
- `learner_profile_store`

## 14. 分阶段实施方案

### 第一阶段：文本模拟面试 MVP

目标：

先做一个可运行的文本版模拟面试平台。

范围：

- 新增 `pdf_to_markdown_ingest`
- 使用 MinerU 做 PDF -> Markdown
- 增加 Markdown 清洗
- 增加 LLM API 结构化整理
- 新增 `mock_interview` capability
- 新增 `candidate_agent`
- 新增 `examiner_agent`
- 局部引入 LangGraph
- 支持真题抽取
- 支持用户文本作答
- 支持 `candidate_agent` 模拟作答
- 支持 `examiner_agent` 评分
- 输出 Markdown 复盘报告

### 第二阶段：高分作答与方法论增强

目标：

让系统能真正利用高分学生作答和老师方法论。

范围：

- 建立 `High Score Answer Bank`
- 建立 `Methodology Bank`
- 支持作答对比
- 支持“高分答案拆解”
- 支持“老师方法论引用”
- 支持题型化改进建议

### 第三阶段：多轮追问与结构化评分

目标：

让模拟面试更接近真实面试。

范围：

- 增加追问策略
- 增加多轮追问
- 增加分维度评分
- 增加面试报告结构化存储
- 回写 learner profile

### 第四阶段：语音 / 视频面试

目标：

从文本面试升级到更真实的语音 / 视频面试。

范围：

- 语音输入
- 作答转写
- 视频录制
- 回放
- 表达流畅度分析
- 面试示范视频素材复用

## 15. 优先级建议

### P0

- 新增 `pdf_to_markdown_ingest`
- 接入 MinerU
- 建立 PDF -> Markdown -> LLM 整理链路
- 新增 `mock_interview` capability
- 新增 `candidate_agent`
- 新增 `examiner_agent`
- 局部引入 LangGraph
- 定义 `MockInterviewState`
- 建立 Interview Bank
- 输出基础复盘报告

### P1

- 建立 High Score Answer Bank
- 建立 Methodology Bank
- 增加结构化评分 rubric
- 增加追问引擎
- 增加 candidate / examiner 结构化交互协议
- 增加面试记录持久化

### P2

- 增加语音输入与转写
- 增加视频录制与回放
- 增加历史成绩趋势
- 增加表达问题长期分析

## 16. 风险与边界

### 16.1 LangGraph 引入风险

风险：

- 新增依赖复杂度
- 状态恢复设计不当会影响体验
- 多轮面试中断后恢复需要额外测试

控制方式：

- 只在 `mock_interview` 内部使用
- 放入 optional dependency
- 不改现有 orchestrator
- 不影响其他 capability
- 第一阶段只做文本状态机

### 16.2 MinerU 解析风险

风险：

- PDF 版式复杂时 Markdown 质量不稳定
- 段落切分可能错乱
- 图片、页眉页脚、分页可能引入噪声

控制方式：

- 在 MinerU 后增加 Markdown 清洗层
- 再通过 LLM API 做结构化整理
- 对关键资料保留人工校对入口

### 16.3 评分可信度风险

风险：

- AI 评分可能偏宽或偏严
- 不同模型评分不稳定
- 追问质量依赖 prompt 和 rubric

控制方式：

- 固定评分 rubric
- 输出分维度评分和扣分原因
- 保留原始答题文本
- 后续支持多考官 agent 平均评分

### 16.4 角色混淆风险

风险：

- 一个 agent 同时扮演考生和考官会导致角色污染。

控制方式：

- 拆分 `candidate_agent` 和 `examiner_agent`
- 各自维护独立 prompt
- 用状态机显式控制阶段转换

## 17. 一句话总结

DeepTutor 可以作为公考 / 事业编面试平台的底座。建议新增 `pdf_to_markdown_ingest` 能力，使用 MinerU 完成 PDF -> Markdown，再通过 LLM API 做资料整理；同时新增 `mock_interview` capability，并在该 capability 内部局部引入 LangGraph，实现“出题 → 答题 → 追问 → 评分 → 复盘”的状态机，再配合 `candidate_agent` 和 `examiner_agent` 的双 Agent 架构，分别处理考生视角作答和现场考官视角评分。

## 参考

- LangGraph Python `StateGraph` 官方参考：`https://reference.langchain.com/python/langgraph/graph/state/StateGraph`
- LangGraph 状态图的核心概念：节点读写共享 state，边表达控制流，编译后图可执行。
