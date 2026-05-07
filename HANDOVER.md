# VisionQuiz Assistant — 项目交接文档

> 生成日期：2026-05-08
> 项目状态：P1-P7 全部完成，核心功能可用

---

## 1. 项目概述

VisionQuiz Assistant 是一款**通用答题助手**，通过截图 + OCR + 题库匹配 + AI 视觉识别，自动识别任意答题系统中的题目并给出答案。

核心价值：**不依赖任何特定平台的 DOM 结构**，换一个答题界面仍然可用。

### 用户操作流程

```
启动 GUI → 选择题库（db/ 目录下的 .db 文件，可选）
         → 选择模式（半自动 / 全自动 × 截图 / 浏览器 / Windows）
         → 按「开始」
         → 系统自动：截图 → OCR → 题库匹配 → AI 识别 → 展示答案 → 自动点击
```

### 两种输入路径

| 路径 | 适用场景 | Token 消耗 | 速度 |
|------|---------|-----------|------|
| **截图模式** (legacy) | 任意桌面程序/网页 | 高（每次 tick 发送 base64 图片） | 3-8s/tick |
| **元素模式** (P7) | 浏览器(CDP) / Windows 桌面程序(UIA) | 极低（仅文本，无图片） | 0.5-2s/tick |

---

## 2. 技术栈

- **语言**: Python 3.11+
- **GUI**: tkinter
- **OCR**: PaddleOCR（本地推理，懒加载）
- **AI**: OpenAI 兼容 API（支持 GPT-4o / Claude / Qwen-VL / MiMo-V2.5 等）
- **数据库**: SQLite3（题库 + 缓存）
- **图像**: mss（截图）、Pillow、imagehash（pHash）
- **浏览器元素**: websocket（Chrome DevTools Protocol）
- **Windows 元素**: comtypes / uiautomation（UI Automation）
- **点击**: pyautogui（坐标点击）/ element.click()（元素直点）

---

## 3. 目录结构

```
VisionQuiz-Assistant/
├── main.py                      # 入口，启动 tkinter GUI
├── core/                        # 核心引擎层
│   ├── config.py                # 配置管理（DPAPI 加密、模型预设、阈值）
│   ├── engine.py                # 主引擎：后台线程，tick 循环
│   ├── recognizer.py            # 识别器：多路策略编排
│   ├── matcher.py               # 题库匹配：Schema 自适应 + n-gram 关键词
│   ├── answer_normalizer.py     # 答案归一化：5 种格式 → 选项字母
│   ├── ai_client.py             # AI 客户端：Prompt A/B/C 统一接口
│   ├── cache.py                 # 双层缓存：内存 LRU + SQLite
│   ├── clicker.py               # 点击器：坐标点击 + 元素点击
│   ├── screenshot.py            # 截图 + pHash 计算
│   ├── ocr.py                   # PaddleOCR 封装（懒加载）
│   ├── db_manager.py            # Excel 导入题库
│   ├── element_provider.py      # ElementProvider 抽象接口
│   ├── browser_provider.py      # Browser 实现（Chrome CDP）
│   └── windows_provider.py      # Windows 实现（UI Automation）
├── ui/                          # GUI 层
│   ├── main_window.py           # 主窗口：控制面板 + 模式选择
│   ├── hud.py                   # HUD 悬浮窗：答案展示
│   ├── settings_dialog.py       # 设置对话框：API / 模型 / 模式
│   ├── db_viewer.py             # 题库查看器
│   └── error_mapper.py          # 错误码 → 用户友好提示
├── web/                         # P6 测试用答题网站
│   ├── app.py                   # Flask 后端
│   ├── templates/               # HTML 前端
│   └── data/                    # 50 题数据集
├── tests/                       # 测试
├── db/                          # 题库（.db 文件，gitignored）
└── models/                      # PaddleOCR 模型（用户下载）
```

**代码规模**: ~6400 行 Python（core 4975 行 + ui 1621 行 + main 34 行）

---

## 4. 核心模块详解

### 4.1 Engine (`core/engine.py`, 689 行)

主引擎，后台线程运行 tick 循环。根据 `input_mode` 选择路径：

```
截图模式: _tick() → _tick_capture() → _tick_hash() → _tick_recognize() → _tick_click()
元素模式: _tick_provider() → provider.get_question_elements() → matcher → clicker
```

关键方法：
- `_normalize_bank_result()`: 题库命中后补调 Prompt A 获取选项坐标，归一化答案
- `_tick_provider()`: 元素模式的完整答题流程
- `start()` / `stop()`: 线程生命周期管理

### 4.2 Recognizer (`core/recognizer.py`, 522 行)

识别器，编排多路策略。优先级：

```
1. pHash 缓存命中 → 直接返回（0ms）
2. question_hash 缓存命中 → 直接返回（~1ms）
3. 题库模糊匹配 → 返回 + 写缓存（~5-90ms）
4. AI 识别（Prompt A + Prompt B）→ 返回 + 写缓存（~2-8s）
```

两个入口：
- `recognize()`: 截图模式，接收 PIL.Image
- `recognize_from_elements()`: 元素模式，接收 QuestionElement

### 4.3 Matcher (`core/matcher.py`, 177 行)

题库匹配器。已修复的核心特性：

- **Schema 自适应**: 自动检测 `questdb(quest, answer)` 或 `questions(question, answer)`
- **n-gram 关键词**: 对长中文片段生成 2-4 字滑动窗口子串，保证无标点 OCR 文本能匹配
- **关键词索引**: 加载时构建倒排索引，查询时先过滤候选集
- **宽松重叠过滤**: 仅排除零交集候选，SequenceMatcher 做精确评分

性能：13K 题库加载 0.71s，查询 0.5-90ms/题，命中率 6/7（含无标点 OCR 文本）

### 4.4 Answer Normalizer (`core/answer_normalizer.py`, 238 行)

将题库原始答案映射为 clicker 可用的选项字母。支持 5 种格式：

| 格式 | 示例 | 输出 |
|------|------|------|
| 字母前缀 | `D: 沿门框墙全高布置` | `D` |
| 纯字母 | `A` | `A` |
| 纯文本 | `下浮7%` | `C`（匹配选项文本） |
| 多选分隔 | `文本1\|答案分隔\|文本2` | `A\|答案分隔\|C` |
| 判断题 | `正确` / `错误` | `正确` / `错误` |

### 4.5 AI Client (`core/ai_client.py`, 537 行)

统一 AI 接口，兼容 OpenAI Chat Completions 格式。三个 Prompt：

- **Prompt A**: 图片 + 文本 → 结构化题目信息（题型、选项坐标、置信度）
- **Prompt B**: 文本 → 答案推理（答案 + 来源 + 置信度）
- **Prompt C**: 点击前后截图对比 → 确认是否选中

返回数据类：`PromptAResult`, `PromptBResult`, `PromptCResult`

### 4.6 ElementProvider (`core/element_provider.py`, 139 行)

抽象接口，定义 5 个方法：`connect()`, `get_question_elements()`, `click_option()`, `fill_input()`, `is_option_selected()`, `close()`

数据类：`QuestionElement`（题干 + 选项列表 + 输入框列表）、`OptionElement`、`InputTarget`

### 4.7 Browser Provider (`core/browser_provider.py`, 399 行)

通过 websocket 连接 Chrome DevTools Protocol (CDP)。用 `Runtime.evaluate` 执行 JS 查询 DOM。

支持外部 JSON 选择器配置文件，自动重连。默认选择器兼容常见答题系统。

### 4.8 Windows Provider (`core/windows_provider.py`, 446 行)

通过 comtypes 调用 Windows UI Automation API。遍历控件树，按标题模糊匹配目标窗口。

支持 Button / CheckBox / RadioButton / Edit 等控件类型的读取和操作。

### 4.9 Clicker (`core/clicker.py`, 544 行)

两种实现：
- `AutoClicker`: 坐标点击（pyautogui），用于截图模式
- `ElementClicker`: 元素操作（element.click / element.select），用于元素模式

`_resolve_option_coord()` 三级匹配：精确文本 → 包含关系 → 字母索引（A=0, B=1...）

### 4.10 Cache (`core/cache.py`, 318 行)

双层缓存：
- 内存 LRU（快速，进程内）
- SQLite（持久化，跨会话）

索引：pHash（截图去重）+ question_hash（题目文本去重）

---

## 5. 配置项 (`config.json`)

```json
{
    "api_key": "",                    // DPAPI 加密存储
    "api_base_url": "https://api.openai.com/v1",
    "model": "",
    "selected_preset": "",            // 模型预设键名
    "timeout": 30,                    // AI 调用超时（秒）
    "similarity_threshold": 0.55,     // 题库匹配阈值
    "cache_expire_days": 7,
    "screenshot_interval": 2,         // 截图间隔（秒）
    "hud_opacity": 0.85,
    "hud_top_offset": 20,
    "phash_threshold": 8,             // pHash Hamming 距离阈值
    "recognition_timeout": 45,        // 单次识别超时（秒）
    "auto_mark_timeout": 10,          // 半自动自动标记超时（秒）
    "input_mode": "screenshot",       // screenshot | browser | windows
    "browser_debug_port": 9222,       // Chrome CDP 调试端口
    "browser_selector_config": "",    // 外部选择器配置 JSON 路径
    "windows_target_title": ""        // Windows 目标窗口标题（模糊匹配）
}
```

---

## 6. 完成的里程碑

| 阶段 | 内容 | 日期 |
|------|------|------|
| P1 | 核心引擎层稳定性（异常容错、资源管理） | 2026-05-06 |
| P2 | 界面层稳定性（主线程阻塞、窗口竞态） | 2026-05-06 |
| P3 | 功能可用性（JSON 提示词、全自动答题、HUD、题库扫描） | 2026-05-06 |
| P4 | MiMo-V2.5 接入（模型预设系统、thinking 块剥离） | 2026-05-06 |
| P5 | 核心加固（pHash Hamming、超时保护、模型预设扩展） | 2026-05-06 |
| P6 | 答题网站 + E2E 测试（Flask 50 题、全自动/半自动测试） | 2026-05-06 |
| P7 | ElementProvider 架构（Browser CDP + Windows UIA） | 2026-05-07 |
| 补丁 | 题库匹配管道修复（Schema 自适应、n-gram、答案归一化） | 2026-05-08 |

---

## 7. 已知技术债

1. **题库编码问题**: zjsj.db 部分题目首字符为 `?`（疑似 GBK→UTF-8 转换截断），不影响匹配但显示不完整
2. **Browser Provider 选择器**: 默认 CSS 选择器覆盖常见答题系统，但特定系统可能需要外部 JSON 配置
3. **Windows Provider 未实战验证**: 仅通过 E2E mock 测试，未在真实桌面程序上验证
4. **pHash 碰撞**: 相似但不同的题目截图可能产生相同 pHash，导致缓存误命中
5. **AI 幻觉坐标**: 截图模式下 Prompt A 返回的选项坐标可能不准确（元素模式无此问题）

---

## 8. 后续方向（Deferred）

| 方向 | 说明 | 优先级 |
|------|------|--------|
| 试卷批量解析 | 整张试卷多题识别，一次性解析 | 中 |
| 多轮对话 | 追问、举一反三、知识点讲解 | 低 |
| LaTeX/AST 支持 | 数学公式还原、代码题解析 | 低 |
| 学习报告导出 | 错题归类、薄弱知识点分析、PDF/Excel | 中 |
| 大题库内存优化 | 10K+ 题索引化，降低内存占用 | 低 |
| 真实系统 E2E 验证 | 在真实答题系统上端到端测试截图模式和元素模式 | 高 |

---

## 9. 运行指南

### 环境准备

```bash
pip install -r requirements.txt
```

### 配置 AI

启动 → 设置 → 选择模型预设（如 MiMo-V2.5）或手动填写 API Key / Base URL / Model

### 题库

将 `.db` 文件放入 `db/` 目录，启动时自动扫描。支持两种 schema：
- `questdb(id, quest, answer)` — 建工题库等
- `questions(id, question, answer)` — 自建题库

### 启动答题

1. 选择题库（可选，不选则纯 AI 模式）
2. 选择模式：半自动（展示答案，手动点）/ 全自动（自动点）
3. 按「开始」

### 浏览器模式额外步骤

1. Chrome 启动时加 `--remote-debugging-port=9222`
2. 设置 `input_mode` 为 `browser`
3. （可选）编写外部选择器 JSON 配置文件

### Windows 模式额外步骤

1. 设置 `input_mode` 为 `windows`
2. 填写 `windows_target_title`（目标窗口标题，模糊匹配）
