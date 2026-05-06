# Roadmap: VisionQuiz Assistant

## Overview

项目已完成全部 6 个里程碑：稳定性基础建设（P1-P2）、功能可用性（P3）、模型接入（P4）、核心加固（P5）、答题网站与端到端测试（P6）。所有自动化测试通过，Web 答题系统运行正常。

## Phases

- [x] **Phase 1: Core Stability — 核心引擎层稳定性** — 修复 engine/recognizer/cache/ai_client/ocr/screenshot 的异常处理、资源管理和容错机制
- [x] **Phase 2: UI Stability — 界面层稳定性** — 修复主线程阻塞、窗口竞态、错误展示和优雅关闭
- [x] **Phase 3: Functional Usability — 功能可用性** — 补齐设计规范中的功能差距，使核心答题流程完整可用
- [x] **Phase 4: MiMo-V2.5 Integration — 新模型接入** — 接入 Xiaomi MiMo-V2.5 多模态模型，实现模型预设配置和切换
- [x] **Phase 5: Core Functionality Hardening — 核心功能加固** — 修复重复画面检测、引擎超时保护、识别结果过滤、HUD 截断、模型预设扩展、半自动模式修正
- [x] **Phase 6: Quiz Website & E2E Testing — 答题网站与端到端测试** — 构建 Web 答题网站、题库抽题与题干改写、网络编撰补充题目、全自动/半自动模式端到端测试验证

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

### Phase 6: Quiz Website & E2E Testing — 答题网站与端到端测试（已完成）

**Goal**: 构建 Web 答题网站（参考截图入口.png/题目1.png/题目2.png），从题库抽取 37 道题并改写题干（相似度 ≤ 10%），网络编撰 13 道补充题，最终通过 VisionQuiz Assistant 的全自动/半自动模式端到端测试，题库题成功率 ≥ 95%

**Depends on**: Phase 1-5（全部核心功能已就绪）

**Requirements**: 答题网站 + 端到端测试

**测试指标**:
- 总题数：50 道（单选题 + 多选题）
- 题库抽取题：~37 道（75%），要求正确率 ≥ 95%
- 网络编撰题：~13 道（25%），仅要求正确识别题干，不要求正确率
- 改写后题干与原始题干相似度 ≤ 10%

**Tasks**:

1. **题库数据准备：抽题 + AI 改写** (`web/question_bank.py`) — 从 SQLite 题库数据库抽取题目，使用 AI 改写题干使相似度 ≤ 10%（余弦相似度/TF-IDF 验证），保持答案正确性不变。输出 37 道改写后的单选题+多选题 JSON 文件

2. **网络题目编撰** (`web/question_bank.py`) — 通过网络搜索补充 13 道单选题和多选题，覆盖 IT/安全/编程/数据库等方向，确保与现有题库无重复，格式统一（题干+选项+正确答案+题型）

3. **题库格式转换与合并** (`web/data/`) — 将 Task 1 + Task 2 的题目统一格式化为 Web 答题系统可用的 JSON 数据文件（question_id, type, stem, options[], correct_answer），生成完整 50 题数据集 + 题号元数据（来源标记：db/web）

4. **Web 答题网站后端** (`web/app.py`) — Flask 应用：GET / 加载首页、GET /api/questions 返回题目列表、POST /api/submit 提交答案并评分、GET /api/result 返回得分和错题详情

5. **Web 答题网站前端** (`web/templates/`) — 参考截图设计：左侧题号导航条（彩色圆角方块标记已答/未答/当前）、右侧题目区域（题型标签 + 题干 + 选项列表）、底部上/下一题+提交按钮。支持单选点击和多选复选框

6. **VisionQuiz Prompt 调优** (`core/ai_client.py`) — 针对 Web 页面截图特点优化 Prompt：网页题目通常无灰色填充和红色勾选，选项为纯文本单选/复选框。确保 Prompt A 识别题型准确、Prompt B 答案匹配正确

7. **全自动模式集成测试** (`tests/test_e2e_full.py`) — 启动 Web 答题站 → VisionQuiz 全自动模式运行 → 验证：
   - 题库题（37 道）正确率 ≥ 95%（至少 35/37 答对）
   - 网络题（13 道）识别率（题干识别正确即可）
   - 总体无崩溃、无超时卡死

8. **全自动模式调试迭代** (`tests/test_e2e_full.py`) — 若 Task 7 未达 95%，分析失败原因（识别错误/点击偏差/题型误判），调整截图区域或 Prompt 后重测，最多 3 轮迭代

9. **半自动模式集成测试** (`tests/test_e2e_semi.py`) — 启动 Web 答题站 → VisionQuiz 半自动模式运行 → 验证：
   - 题库题正确率 ≥ 95%
   - 网络题识别率正常
   - HUD 正确显示题目+答案、用户确认流程无异常

10. **半自动模式调试迭代** (`tests/test_e2e_semi.py`) — 若 Task 9 未达 95%，分析失败原因，调整后重测，最多 3 轮迭代

11. **E2E 测试报告生成** (`tests/e2e_report.md`) — 汇总全自动/半自动测试结果：正确率、识别率、失败题目分析、截图区域配置建议。注册 TST-006 artifact

**Success Criteria**:
1. 答题网站正常运行，包含 50 道题（单选 + 多选）
2. 改写后题干与原始题干 TF-IDF 余弦相似度 ≤ 10%
3. VisionQuiz 全自动模式：题库题正确率 ≥ 95%，网络题识别率正常
4. VisionQuiz 半自动模式：题库题正确率 ≥ 95%，HUD 显示+确认流程正常
5. E2E 测试报告完整，含正确率/识别率/失败分析

**Wave 依赖**:
- Wave 1（可并行）: Task 1 题库抽题改写 + Task 2 网络编撰 + Task 6 Prompt 调优
- Wave 2（依赖 Wave 1）: Task 3 格式合并（依赖 T1+T2）+ Task 4 后端（依赖 T3）+ Task 5 前端（依赖 T4）
- Wave 3（依赖 Wave 2）: Task 7 全自动测试（依赖 T4+T5+T6）→ Task 8 调试迭代（依赖 T7）
- Wave 4（依赖 Wave 3）: Task 9 半自动测试（依赖 T8 通过）→ Task 10 调试迭代（依赖 T9）
- Wave 5（依赖 Wave 4）: Task 11 测试报告（依赖 T8+T10）

---

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
| 4. MiMo-V2.5 Integration | Completed | 2026-05-06 |
| 5. Core Functionality Hardening | Completed | 2026-05-06 |
| 6. Quiz Website & E2E Testing | Completed | 2026-05-06 |
