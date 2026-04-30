# VisionQuiz Assistant · 多模态题目智能解析 Agent
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![PaddleOCR](https://img.shields.io/badge/OCR-PaddleOCR-red)
![Multimodal](https://img.shields.io/badge/AI-Multimodal-purple)
![Agent](https://img.shields.io/badge/Architecture-Agent-orange)
> 基于视觉大模型 + OCR 的通用题目理解工具，面向**个人学习、培训复习、题库内容生成、教育辅助**场景。
> 通过截图输入，自动识别题型、定位题干与选项、生成答案解析与知识点讲解。
> 支持任意兼容 OpenAI 格式的多模态模型自由切换。

---

## 🎯 项目定位

传统题目处理工具往往深度绑定某一特定平台的 DOM 结构或固定坐标，换个界面就完全失效。
本项目采用 **"视觉大模型 + OCR"** 的 Agent 架构，不依赖任何特定平台结构，
实现**跨界面、跨样式的通用题目理解**，核心价值在于：

- **学习辅助**：学生/职场人自学时快速获得题目解析与知识点讲解
- **题库生成**：将历史资料、扫描件批量转换为结构化题库 + 标准解析
- **培训复习**：个人复习阶段对照讲解，定位薄弱知识点
- **教育内容处理**：教师/内容创作者快速生成题目讲解稿

---

## ✨ 核心特性

| 模块 | 说明 |
| --- | --- |
| **本地题库检索** | Excel 导入已有资料，difflib 模糊匹配，命中本地解析时零 API 消耗 |
| **多模态 AI 理解** | OCR 文本 + 原图双路输入，兼容 OpenAI / Claude / Qwen-VL / MiMo 等 |
| **智能缓存层** | 图像 pHash + 文本 MD5 双索引，已解析内容秒级复用 |
| **可视化讲解面板** | 轻量化展示区呈现题目摘要 + 答案 + 知识点来源 |
| **交互模式** | 学习模式（仅展示解析）/ 辅助模式（辅助定位答题区域） |
| **多题型兼容** | 单选 / 多选 / 判断 / 填空，多答案使用竖线分隔存储 |
| **本地 OCR** | PaddleOCR 本地推理，数据不出域，适合隐私敏感场景 |
| **题库热切换** | 运行中可动态切换知识库，无需重启 |

---

## 🏗️ Agent 架构

```mermaid
flowchart TB
    subgraph P["🔍 感知层 · Perception"]
        P1[屏幕截图采集<br/>mss]
        P2[PaddleOCR<br/>文本与坐标提取]
        P3[pHash<br/>图像指纹]
    end

    subgraph M["🧠 记忆层 · Memory"]
        M1[(本地题库<br/>SQLite)]
        M2[(解析缓存<br/>pHash + MD5)]
        M3[Excel 资料<br/>批量导入]
    end

    subgraph R["⚙️ 决策层 · Reasoning"]
        R1{命中<br/>缓存?}
        R2{命中<br/>题库?}
        R3[题型识别<br/>单选/多选/判断/填空]
        R4[策略路由<br/>Strategy Router]
        R5[多模态大模型<br/>Vision + Text]
    end

    subgraph O["📤 输出层 · Output"]
        O1[结构化答案]
        O2[知识点解析]
        O3[置信度标注]
        O4[缓存回写]
    end

    P1 --> P3
    P1 --> P2
    P3 --> R1
    P2 --> R1
    R1 -- 命中 --> O1
    R1 -- 未命中 --> R2
    M1 -.查询.-> R2
    M2 -.查询.-> R1
    M3 -.导入.-> M1
    R2 -- 命中 --> O1
    R2 -- 未命中 --> R3
    R3 --> R4
    R4 --> R5
    R5 --> O1
    O1 --> O2
    O2 --> O3
    O3 --> O4
    O4 -.写入.-> M2

    style P fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style M fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style R fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style O fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. （可选）配置本地 OCR 模型

将 PaddleOCR 模型放到运行目录的 `models/` 子目录：

```
models/
├── det/        # 检测模型
├── rec/        # 识别模型
└── cls/        # 方向分类模型
```

模型下载：[PaddleOCR 官方模型库](https://paddlepaddle.github.io/PaddleOCR/latest/model/index.html)

### 3. 运行

```bash
python main.py
```

### 4. 配置多模态模型

【设置】→ API 设置：

- **API Base URL**：默认 `https://api.openai.com/v1`，可替换为任意 OpenAI 兼容端点
- **模型名称**：推荐使用视觉模型，如 `gpt-4o`、`claude-3-5-sonnet`、`Qwen2.5-VL`、`MiMo-V2.5` 等

### 5. 导入学习资料

Excel 格式：A 列题目 / B 列参考答案（多答案用 `|` 分隔）

---

## 📁 项目结构

```
├── main.py                 # 程序入口
├── core/
│   ├── config.py           # 配置管理
│   ├── db_manager.py       # 题库 SQLite + Excel 导入
│   ├── matcher.py          # 文本模糊匹配
│   ├── cache.py            # 双层缓存（内存 + SQLite，线程安全）
│   ├── screenshot.py       # 图像采集 + pHash
│   ├── ocr.py              # PaddleOCR 封装（懒加载）
│   ├── ai_client.py        # 多模态模型统一接口
│   ├── recognizer.py       # 多路识别策略编排
│   ├── clicker.py          # 区域定位辅助
│   └── engine.py           # Agent 调度引擎
├── ui/                     # 可视化界面
├── db/                     # 题库与缓存
└── models/                 # OCR 模型
```

---

## 🔧 决策流程

```mermaid
flowchart LR
    A([输入图像]) --> B[计算 pHash]
    B --> C{图像缓存<br/>命中?}
    C -- ✅ --> Z([输出解析])
    C -- ❌ --> D[PaddleOCR<br/>文本提取]
    D --> E[文本 MD5]
    E --> F{文本缓存<br/>命中?}
    F -- ✅ --> Z
    F -- ❌ --> G[本地题库<br/>模糊检索]
    G --> H{相似度<br/>≥ 阈值?}
    H -- ✅ --> Z
    H -- ❌ --> I[多模态大模型<br/>图+文双路输入]
    I --> J[结构化解析]
    J --> K[(写入缓存)]
    K --> Z

    style A fill:#bbdefb,stroke:#1976d2
    style Z fill:#c8e6c9,stroke:#388e3c
    style I fill:#f8bbd0,stroke:#c2185b
    style K fill:#ffe0b2,stroke:#f57c00
```
## 🔄 端到端时序

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant E as Agent Engine
    participant C as Cache
    participant O as PaddleOCR
    participant D as 本地题库
    participant M as 多模态模型
    participant V as 展示面板

    U->>E: 触发截图
    E->>E: 计算 pHash
    E->>C: 查询图像缓存

    alt 缓存命中
        C-->>E: 返回历史解析
        E->>V: 渲染解析
    else 缓存未命中
        E->>O: 请求 OCR
        O-->>E: 文本 + 坐标
        E->>C: 查询文本缓存

        alt 文本缓存命中
            C-->>E: 返回历史解析
        else 继续
            E->>D: 模糊检索本地题库
            alt 题库命中
                D-->>E: 返回参考答案
            else 题库未命中
                E->>M: 调用多模态模型<br/>(图 + OCR 文本)
                M-->>E: 结构化解析 + 知识点
            end
        end

        E->>C: 回写缓存
        E->>V: 渲染解析
    end

    V-->>U: 展示答案 + 讲解
```

## 🛣️ Roadmap

- [ ] 接入 Xiaomi MiMo-V2.5 原生多模态模型，对比视觉理解效果
- [ ] 基于长上下文能力，支持整套试卷一次性解析与知识点归纳
- [ ] 增加多轮对话式讲解（追问、举一反三）
- [ ] 数学公式 LaTeX 还原 + 代码题 AST 解析专项优化
- [ ] 导出学习报告（错题归类 / 薄弱知识点分析）

---

## 🛠️ 技术栈

`Python 3.11` · `PaddleOCR` · `OpenAI SDK` · `SQLite3` · `imagehash` · `mss` · `Pillow` · `tkinter`

---

## 📄 License

MIT License

---

## ⚠️ 使用声明

本项目为**个人学习与教育辅助**用途开源工具。请使用者自行遵守所在地区法律法规
及所使用平台的服务条款，**切勿用于任何形式的违规考试、作弊或侵犯他人权益的场景**。
开发者不对使用者的任何使用行为承担责任。
