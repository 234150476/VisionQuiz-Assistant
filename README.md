# AI 自动答题助手

> 一款非入侵式的企业培训答题辅助工具。通过屏幕截图 + OCR + AI 视觉识别题目，优先从本地题库模糊匹配答案，匹配失败时调用 AI 作答，结果实时显示在屏幕顶部的半透明悬浮条（HUD）上。支持半自动（仅展示答案）和全自动（自动点击选项）两种模式。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **本地题库优先** | Excel 导入题库，difflib 模糊匹配，阈值可配，命中率高时完全不消耗 API |
| **AI 兜底识别** | OCR 文本 + 截图双路输入 AI，支持 OpenAI / Claude / 本地模型（任意兼容 OpenAI API 的服务） |
| **pHash 去重缓存** | 截图 pHash + 题目文本 MD5 双索引缓存，已识别过的题目秒回，不重复调用 AI |
| **HUD 悬浮提示** | 屏幕顶部半透明常驻浮条，鼠标可穿透，显示题目摘要 + 答案 + 来源标签 |
| **半自动模式** | 仅展示答案，用户手动点击，点击"✓ 已答"标记当前题目完成 |
| **全自动模式** | AI 定位选项坐标 → 自动鼠标点击 → 点击后截图验证是否选中 |
| **多选题支持** | 答案以 `\|答案分隔\|` 存储，全自动模式顺序点击每个选项，每次重新截图定位 |
| **本地 OCR** | 使用 PaddleOCR，自动检测 `models/` 目录，优先标准模型，次选轻量模型 |
| **热切换题库** | 引擎运行中可直接选择新题库，无需重启 |

---

## 🖥️ 界面预览

```
┌─────────────────────────────────────────────────┐
│  就绪                                    📚 题库 │  ← HUD（屏幕顶部，鼠标可穿透）
│  下列说法正确的是…                              │
│  答案：A  /  C                                  │
└─────────────────────────────────────────────────┘

┌──────────────────────────────────┐
│  题库: [exam.db]  选择 导入 查看  │
│  模式: ● 半自动  ○ 全自动         │
│  HUD: 透明度████  偏移 20px       │
│  [启动]  [停止]  [✓已答]  [设置] │
│  状态: [题库] 答案: A / C         │
└──────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. （可选）准备 PaddleOCR 模型

如不使用 OCR，程序将仅凭截图调用 AI 识别，功能正常但速度略慢。

如需本地 OCR，将模型文件放到运行目录的 `models/` 子目录：

```
models/
├── det/        # 检测模型（标准）或 det_slim/（轻量）
├── rec/        # 识别模型（标准）或 rec_slim/（轻量）
└── cls/        # 方向分类模型（可选）
```

两套都有时自动使用标准模型。模型下载地址：[PaddleOCR 官方模型库](https://paddlepaddle.github.io/PaddleOCR/latest/model/index.html)

### 3. 运行

```bash
python main.py
```

### 4. 初次配置

点击【设置】→ API 设置 标签页，填写：
- **API Key**：你的 API 密钥
- **API Base URL**：默认 `https://api.openai.com/v1`，使用第三方或本地服务时修改
- **模型名称**：如 `gpt-4o`、`claude-3-5-sonnet-20241022` 等

### 5. 导入题库

点击【导入 Excel】，选择题库文件。Excel 格式要求：
- 第一行为表头（跳过）
- A 列：题目
- B 列：答案（多选题用 `|答案分隔|` 连接，如 `A|答案分隔|C`）

---

## 📁 目录结构

```
├── main.py                 # 程序入口
├── requirements.txt        # 依赖列表
├── core/
│   ├── config.py           # 配置读写
│   ├── db_manager.py       # 题库 SQLite 管理 + Excel 导入
│   ├── matcher.py          # difflib 模糊匹配
│   ├── cache.py            # 双层缓存（内存 + SQLite，线程安全）
│   ├── screenshot.py       # 截图 + pHash + 鼠标遮盖
│   ├── ocr.py              # PaddleOCR 封装（懒加载）
│   ├── ai_client.py        # OpenAI SDK 封装（文本/图文/验证/定位）
│   ├── recognizer.py       # 多路识别策略编排
│   ├── clicker.py          # 鼠标点击 + 验证
│   └── engine.py           # 后台轮询引擎
├── ui/
│   ├── hud.py              # 悬浮 HUD（无边框/置顶/鼠标穿透）
│   ├── main_window.py      # 主控窗口
│   ├── settings_dialog.py  # 设置对话框
│   └── db_viewer.py        # 题库查看器
├── db/                     # 自动创建，存放题库 .db 和缓存 cache.db
└── models/                 # 用户手动放置 PaddleOCR 模型文件
```

---

## ⚙️ 配置项说明

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `provider` | `openai` | 服务商标识（仅描述用，不影响调用） |
| `api_key` | 空 | API 密钥 |
| `api_base_url` | `https://api.openai.com/v1` | API 端点 |
| `model` | 空 | 模型名称 |
| `timeout` | `30` | 请求超时（秒） |
| `similarity_threshold` | `0.8` | 题库模糊匹配阈值（0.0~1.0，不含0.0） |
| `cache_expire_days` | `7` | 缓存过期天数 |
| `screenshot_interval` | `2` | 截图间隔（秒） |
| `hud_opacity` | `0.85` | HUD 透明度 |
| `hud_top_offset` | `20` | HUD 距屏幕顶部像素数 |

---

## 🔧 识别优先级

```
截图 → pHash 查缓存（已答则跳过）
        ↓ 未命中
      OCR 提取文本 → MD5 查缓存
        ↓ 未命中
      题库模糊匹配（阈值过滤）
        ↓ 未命中
      AI 识别（OCR文本 + 截图双路）
        ↓
      写入缓存 → HUD 展示 → [全自动] 点击
```

---

## 📦 打包为 exe

```bash
pyinstaller --onefile --windowed --name AIAutoAnswer main.py
```

打包后 `models/`、`db/`、`config.json` 放在与 exe 相同目录下即可。

---

## ⚠️ 注意事项

- 本工具仅供学习交流，请勿用于违规考试场景
- 全自动模式需要 AI 模型支持图像输入（Vision 能力），纯文本模型无法定位坐标
- PaddleOCR 首次运行会联网下载字典文件（若已离线部署请提前准备）
- 运行目录需要有写权限（用于创建 `db/`、`config.json`）

---

## 🛠️ 技术栈

`Python 3.11` · `tkinter` · `PaddleOCR` · `mss` · `Pillow` · `imagehash` · `pyautogui` · `openai` · `openpyxl` · `pywin32` · `SQLite3`
