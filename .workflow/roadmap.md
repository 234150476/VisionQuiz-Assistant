# Roadmap: VisionQuiz Assistant

## Overview

项目已完成稳定性基础建设（P1 Core Stability + P2 UI Stability），34/34 测试通过。当前进入功能可用性阶段：修复设计规范与实际实现之间的功能差距，补齐核心流程中缺失的关键环节，使工具从"勉强能运行"提升为"完整可用"。重点修复 AI 提示词结构化、全自动答题流程、HUD 展示规范等 7 项功能缺陷。

## Phases

- [x] **Phase 1: Core Stability — 核心引擎层稳定性** — 修复 engine/recognizer/cache/ai_client/ocr/screenshot 的异常处理、资源管理和容错机制
- [x] **Phase 2: UI Stability — 界面层稳定性** — 修复主线程阻塞、窗口竞态、错误展示和优雅关闭
- [x] **Phase 3: Functional Usability — 功能可用性** — 补齐设计规范中的功能差距，使核心答题流程完整可用
- [ ] **Phase 4: MiMo-V2.5 Integration — 新模型接入** — 接入 Xiaomi MiMo-V2.5 多模态模型，实现模型预设配置和切换

## Phase Details

### Phase 1: Core Stability — 核心引擎层稳定性（已完成）

**Goal**: 消除引擎运行中的卡死、崩溃和资源泄漏，确保 core 层在任何外部依赖异常时都能优雅降级

**Status**: Completed 2026-05-06

---

### Phase 2: UI Stability — 界面层稳定性（已完成）

**Goal**: 消除 UI 冻结和竞态条件，确保用户操作始终有响应，错误信息清晰展示

**Status**: Completed 2026-05-06

---

### Phase 3: Functional Usability — 功能可用性

**Goal**: 补齐设计规范（design.md §3.1-§3.8）与实际实现之间的功能差距，使半自动和全自动两种模式都完整可用

**Depends on**: Phase 1 + Phase 2（稳定性基础已就绪）

**Requirements**: 功能完整可用

**Tasks**:

1. **AI 提示词结构化改造** (`core/ai_client.py`) — 将 Prompt A/B/C 从纯文本改为 JSON 格式返回，Prompt A 返回题目类型+选项坐标，Prompt B 返回答案+置信度，Prompt C 返回确认状态。消除双重 API 调用（当前识别+定位分两次调用）

2. **全自动答题流程补全** (`core/clicker.py`) — 补齐填空题/简答题的 pyautogui 键盘输入能力；实现点击确认后自动重试一次；题目类型路由（单选/多选/判断/填空/简答）

3. **HUD 单行紧凑布局** (`ui/hud.py`) — 改为设计规范要求的单行紧凑格式 `[状态] 题目：xxx | 来源：xxx | 答案：xxx`；动态计算题目截断长度（前 20% + `...`）替代固定 30 字符

4. **题库目录自动扫描** (`ui/main_window.py`) — 启动时扫描 `db/` 目录自动列出 `.db` 文件到下拉列表；运行中禁止切换题库（设计规范要求启动前选定）

5. **OCR 文本预处理** (`core/recognizer.py`) — OCR 结果送去模糊匹配和缓存前，过滤乱码/噪声字符；OCR 结果质量差时直接标记跳过，避免缓存污染

6. **启动按钮状态逻辑** (`ui/main_window.py`) — 严格按设计规范：api_key/model 为空 → 显示"请先完善配置"并禁用；未选题库 → 显示"请先选择题库"并禁用

7. **配置管理清理** (`core/config.py`, `ui/settings_dialog.py`) — 移除未使用的 `provider` 字段；为 `api_key` 添加本地加密存储（设计规范要求）；移除 requirements.txt 中多余的 pywin32

**Success Criteria**:
1. 全自动模式下填空题/简答题可自动输入文字内容
2. AI 识别返回结构化 JSON（含题型、选项坐标、置信度），不再需要单独的 locate_option 调用
3. HUD 显示为单行紧凑格式，题目截断长度自适应屏幕宽度
4. 启动时 `db/` 目录下所有 `.db` 文件自动出现在下拉列表中
5. 启动按钮在配置不完整时显示明确的文字提示并禁用

**Wave 依赖**:
- Wave 1（可并行）: Task 1 AI提示词 + Task 3 HUD布局 + Task 5 OCR预处理 + Task 7 配置清理
- Wave 2（依赖 Wave 1）: Task 2 全自动答题（依赖 Task 1 的 JSON 响应格式）+ Task 4 题库扫描 + Task 6 按钮状态

---

### Phase 4: MiMo-V2.5 Integration — 新模型接入

**Goal**: 接入 Xiaomi MiMo-V2.5 多模态模型作为可选 AI 后端，实现模型预设配置和一键切换，对比视觉理解效果

**Depends on**: Phase 3（功能可用性基础已就绪，JSON 提示词管道完整）

**Requirements**: 新模型接入

**Tasks**:

1. **MiMo API 兼容性验证** (`core/ai_client.py`) — 验证 MiMo-V2.5 的 API 是否兼容 OpenAI Chat Completions 格式；处理可能的差异（endpoint path、auth header、request/response schema）

2. **模型预设配置系统** (`core/config.py`, `ui/settings_dialog.py`) — 在 CONFIG_DEFAULTS 中添加 `model_presets` 字段，内置 MiMo-V2.5 等推荐模型的 base_url + model_name 预设；设置对话框增加"快速选择"下拉

3. **图片编码适配** (`core/ai_client.py`) — 不同模型对图片输入格式可能不同（base64 inline、file upload、URL），添加图片编码策略抽象，支持 MiMo 的图片输入方式

4. **响应格式适配** (`core/ai_client.py`) — MiMo 返回的 JSON 结构可能与 GPT-4o/Claude 有差异，添加响应解析适配层，确保 PromptAResult/PromptBResult/PromptCResult 能正确解析 MiMo 输出

5. **模型切换 UI** (`ui/settings_dialog.py`, `ui/main_window.py`) — 设置页增加模型预设选择器，主界面状态栏显示当前使用的模型名称，运行时不允许切换

6. **基准测试框架** (`tests/test_model_benchmark.py`) — 建立可重复的模型对比测试：固定题目集 → 不同模型识别 → 准确率/延迟/成本对比

7. **文档和配置更新** (`README.md`, `requirements.txt`) — 更新 README 中的模型推荐列表，添加 MiMo-V2.5 配置指南

**Success Criteria**:
1. 用户可在设置中一键选择 MiMo-V2.5 预设，无需手动填写 base_url 和 model_name
2. MiMo-V2.5 能正确返回结构化 JSON（题型、选项坐标、置信度），解析成功率 ≥ 90%
3. 模型切换不影响已有功能，切换后所有题型（单选/多选/判断/填空/简答）正常工作
4. 基准测试可重复运行，输出准确率和延迟对比报告

**Wave 依赖**:
- Wave 1（可并行）: Task 1 API 兼容性 + Task 2 模型预设配置 + Task 3 图片编码适配
- Wave 2（依赖 Wave 1）: Task 4 响应格式适配（依赖 T1 验证结果）+ Task 5 模型切换 UI（依赖 T2 预设系统）
- Wave 3（依赖 Wave 2）: Task 6 基准测试（依赖 T4 响应适配）+ Task 7 文档更新

## Scope Decisions

- **In scope**: 设计规范（design.md）中已确认但未实现/部分实现的 7 项功能
- **Deferred**（后续里程碑）:
  - 试卷批量解析（整张试卷多题识别）
  - 多轮对话（上下文关联追问）
  - LaTeX/AST 支持（公式识别和结构化表达）
  - 学习报告导出（错题集、统计、PDF/Excel）
  - QuestionMatcher 大题库内存优化（10k+ 题索引化）
- **Out of scope**: 跨平台支持、UI 重新设计、测试框架搭建

## Progress

| Phase | Status | Completed |
|-------|--------|-----------|
| 1. Core Stability | Completed | 2026-05-06 |
| 2. UI Stability | Completed | 2026-05-06 |
| 3. Functional Usability | Completed | 2026-05-06 |
| 4. MiMo-V2.5 Integration | Not started | - |
