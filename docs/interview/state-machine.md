# Mock Interview 状态机设计

## 状态图

```
                  ┌──────────────────────────┐
                  │         IDLE             │
                  └──────────┬───────────────┘
                             │ start_interview()
                             ▼
                  ┌──────────────────────────┐
                  │      QUESTIONING         │
                  │   (出题 + 上下文构建)      │
                  └──────────┬───────────────┘
                             │ submit_answer()
                             ▼
                  ┌──────────────────────────┐
                  │       ANSWERING          │
                  │   (评估是否需要追问)       │
                  └──────┬──────────┬────────┘
                         │          │
             需要追问     │          │ 不需要追问
                         ▼          ▼
              ┌──────────────┐  ┌──────────────┐
              │ FOLLOWUP_    │  │   SCORING    │
              │ QUESTIONING  │  │  (评分)      │
              └──────┬───────┘  └──────┬───────┘
                     │                 │
           submit_   │                 │
           followup_ │                 │
           answer()  │                 ▼
                     ▼         ┌──────────────┐
              ┌──────────────┐  │  REVIEWING   │
              │ FOLLOWUP_    │  │  (复盘)      │
              │ ANSWERING    │  └──────┬───────┘
              └──────┬───────┘         │
                     │                 │
                     ▼                 ▼
              ┌──────────────────────────────┐
              │          COMPLETED           │
              │   (评分 + 复盘 + 写入记忆)     │
              └──────────────────────────────┘
```

## 状态定义

| 状态 | 说明 | 可执行动作 |
|------|------|-----------|
| idle | 未开始面试 | start_interview() |
| questioning | 正在出题、构建上下文 | submit_answer() |
| answering | 已收到用户作答，评估中 | —（内部转评分或追问） |
| followup_questioning | 已生成追问 | submit_followup_answer() |
| followup_answering | 已收到追答，进入评分 | —（内部转评分） |
| scoring | LLM 评分中 | —（内部执行） |
| reviewing | LLM 复盘报告中 | —（内部执行） |
| completed | 完成，已写入记忆 | 无 |
| cancelled | 用户取消 | 无 |
| error | 异常状态 | 无 |

## P0 约束

- 追问最多 1 轮
- 文本作答（不支持音视频）
- 题目来源：Interview Bank（RAG 检索），RAG 不可用时使用 LLM 生成
- 评分维度：8 个固定 rubric 维度

## 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| 用户提交了空作答 | 提示用户补充内容，不进入评分 |
| LLM 评分调用失败 | 降级为简化评分（仅总分估计），不阻塞流程 |
| 追问 LLM 调用失败 | 跳过追问，直接进入评分 |
| RAG 检索失败 | 使用 LLM 直接生成题目（fallback） |
| 中断恢复 | session 存储在 InterviewMemoryService 中，支持通过 session_id 恢复 |

## 数据流

```
start_interview():
  1. 读取 learner profile
  2. 读取最近 N 场训练
  3. 构建考官上下文（context_builder）
  4. 从 Interview Bank 选题
  5. 初始化 InterviewSession
  6. 返回题目 → 用户

submit_answer(answer):
  1. 记录作答到 InterviewSession
  2. 调用 should_follow_up() 判断
  3. 如需追问 → 调用 generate_followup() → 返回追问
  4. 否则 → 进入 _score_and_review()

submit_followup_answer(answer):
  1. 记录追答到 InterviewSession
  2. 进入 _score_and_review()

_score_and_review():
  1. 调用 score_answer() → 8 维度评分
  2. 调用 generate_review() → 复盘报告
  3. 调用 write_session_to_memory() → 写入 InterviewMemoryService
  4. 返回评分 + 复盘 → 用户
```
