# ElementProvider 架构文档

## 1. 概览

P7 引入 `ElementProvider` 抽象层，将"截图→AI 视觉识别→坐标点击"替换为"直接读取 DOM/控件元素→AI 文本推理→元素操作"。

### 架构图

```
┌─────────────────────────────────────────────┐
│                  Engine                      │
│  input_mode 决定路由:                         │
│  ┌───────────┐  ┌────────────┐  ┌──────────┐ │
│  │ screenshot│  │  browser   │  │ windows  │ │
│  │ (legacy)  │  │  (CDP)     │  │ (UIA)    │ │
│  └─────┬─────┘  └─────┬──────┘  └────┬─────┘ │
│        │              │              │       │
│   _tick_screenshot  _tick_provider (共享)     │
│        │              │              │       │
│  capture_screen  ElementProvider.get_question │
│  pHash + OCR     → QuestionElement            │
│  AI Vision (A)   → AI Text (B only)          │
│  AutoClicker     → provider.click_option     │
└─────────────────────────────────────────────┘
```

### 三种模式对比

| 特性 | 截图模式 (legacy) | 浏览器模式 | 桌面程序模式 |
|------|-------------------|------------|-------------|
| 数据来源 | 全屏截图 | Chrome CDP DOM | UIA 控件树 |
| 识别方式 | OCR + AI Vision | AI 文本推理 | AI 文本推理 |
| 点击方式 | pyautogui 坐标 | CDP DOM 操作 | UIA Invoke |
| Token 消耗 | 高 (500-1500/tick) | 低 (100-300/tick) | 低 (100-300/tick) |
| 响应速度 | 3-8s | 0.5-1.5s | 0.5-1.5s |
| 点击准确性 | 受 DPI 影响 | 确定性 | 确定性 |

## 2. 接口设计

### ElementProvider ABC

```python
class ElementProvider(ABC):
    def connect(**kwargs) -> bool
    def get_question_elements() -> Optional[QuestionElement]
    def click_option(option: OptionElement) -> bool
    def fill_input(target: InputTarget, text: str) -> bool
    def is_option_selected(option: OptionElement) -> bool
    def close()
```

### 数据模型

- `QuestionElement`: 题干文本 + 题型 + 选项列表 + 输入框列表
- `OptionElement`: 选项文本 + element_ref（平台引用）+ 选中状态
- `InputTarget`: placeholder + element_ref

## 3. 配置指南

### config.json 新增字段

```json
{
  "input_mode": "screenshot",
  "browser_debug_port": 9222,
  "browser_selector_config": "",
  "windows_target_title": ""
}
```

### 浏览器模式配置

1. 启动 Chrome: `chrome.exe --remote-debugging-port=9222`
2. 在设置中选择"浏览器模式"
3. 配置调试端口（默认 9222）
4. 可选：配置选择器 JSON 文件路径

### 选择器配置文件格式

```json
{
  "question_text": ".question-text, #stem",
  "option": ".option-item, .answer-choice",
  "option_selected": ".option-item.selected",
  "input_field": "input.answer-input, textarea"
}
```

### 桌面程序模式配置

1. 在设置中选择"桌面程序模式"
2. 填写目标窗口标题（支持模糊匹配）
3. 程序自动通过 UIA 遍历控件树

## 4. 迁移步骤

1. 打开设置 → 输入模式 → 选择"浏览器模式"或"桌面程序模式"
2. 根据选择配置调试端口或窗口标题
3. 确保目标程序/页面已打开
4. 启动引擎

## 5. 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| CDP 连接失败 | Chrome 未启动调试端口 | 添加 `--remote-debugging-port=9222` 启动参数 |
| UIA 树不完整 | 目标程序不支持 UIA | 降级到截图模式 |
| 元素读取为空 | 页面未加载完成 | 增加等待时间或刷新页面 |
| 点击无效果 | 元素被遮挡 | 检查页面布局，尝试滚动 |

当元素模式出现连续失败时，系统会自动降级到截图模式并发出警告。
