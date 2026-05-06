# Project: VisionQuiz Assistant

## What This Is

基于视觉大模型 + OCR 的多模态题目智能解析工具，面向个人学习、培训复习、题库内容生成、教育辅助场景。通过截图输入自动识别题型、定位题干与选项、生成答案解析。支持半自动（仅显示答案）和全自动（自动点击选项）两种模式。

## Core Value

**跨界面、跨样式的通用题目理解** — 不依赖任何特定平台 DOM 结构或固定坐标，通过"视觉大模型 + OCR"的 Agent 架构实现通用识别。这是与传统工具的核心差异化。

## Requirements

### Validated

<!-- 已实现并确认有价值的功能 -->

- [x] 本地题库检索（Excel 导入 + SQLite + difflib 模糊匹配）
- [x] 多模态 AI 理解（OCR 文本 + 原图双路输入，OpenAI 兼容接口）
- [x] 智能缓存层（pHash + MD5 双索引，线程安全）
- [x] 可视化 HUD 面板（鼠标穿透、半透明、置顶）
- [x] 半自动/全自动双模式
- [x] 多题型兼容（单选/多选/判断/填空）
- [x] 本地 OCR（PaddleOCR 懒加载）
- [x] 题库热切换（运行时动态切换）

### Active

<!-- 当前推进的需求 — 聚焦稳定性提升 -->

- [x] **稳定性：系统健壮性提升** — 修复各类运行时错误、异常处理、资源管理、线程安全问题
- [x] **稳定性：外部依赖容错** — AI API 超时/失败、OCR 模型缺失、数据库异常的优雅降级
- [x] **稳定性：UI 响应性** — 消除主线程阻塞、引擎停止卡顿、关窗竞态等问题
- [x] **功能可用性：核心流程完整化** — AI JSON 提示词、全自动答题、HUD 规范、题库扫描、按钮状态逻辑
- [ ] **新模型接入：MiMo-V2.5** — 接入 Xiaomi MiMo-V2.5 多模态模型，模型预设配置和一键切换

### Out of Scope

<!-- 明确排除的范围 -->

- 浏览器注入/DOM 操作 — 坚持非侵入式截图方案
- 多平台支持（macOS/Linux）— 当前仅 Windows
- 远程题库/云同步 — 纯本地优先

## Context

项目已有完整实现代码（core/ 10 模块 + ui/ 4 模块），设计文档完整（design.md），README 含路线图。当前工具"勉强能运行"，存在各类稳定性问题需系统性修复。

**已知不稳定表现：**
- AI 调用异常时引擎可能卡死
- OCR 初始化失败后可能影响后续识别流程
- 引擎停止时 UI 冻结或资源未正确释放
- 线程间通信可能丢失或竞态
- 缓存数据库连接在异常路径下可能泄漏

## Constraints

- **平台**: 仅 Windows（依赖 pywin32、WS_EX_TRANSPARENT）
- **Python**: 3.11+
- **打包**: PyInstaller 单文件 .exe（目标 ≤ 30MB）
- **数据**: 纯本地存储，不出域

## Tech Stack

- **Language**: Python 3.11
- **UI**: tkinter（内置）
- **OCR**: PaddleOCR（本地推理）
- **AI**: OpenAI SDK（兼容 OpenAI / Claude / Qwen-VL 等）
- **Database**: SQLite3（题库 + 缓存）
- **Screen**: mss + Pillow + imagehash
- **Automation**: pyautogui + pywin32

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 截图+OCR 而非 DOM 注入 | 通用性最强，不依赖特定平台 | 已验证 |
| 题库优先 + AI 兜底 | 减少 API 消耗，提升响应速度 | 已实现 |
| pHash + MD5 双缓存 | 图像级+文本级去重，最大化缓存命中 | 已实现 |
| PaddleOCR 懒加载 | 避免启动过慢，无模型时优雅降级 | 已实现 |
| tkinter UI | 内置、无需额外安装、打包体积最小 | 已实现 |
| 聚焦稳定性优先 | 当前工具不稳定，功能迭代前先夯实基础 | 待执行 |

## Stakeholders

- 个人学习/培训场景使用者

---
*Last updated: 2026-05-06 after brownfield init*
