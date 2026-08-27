# 奶龙情感陪伴AI —— 文字对话 Demo

一个对标「路遥情感AI」的奶龙人设多轮文字对话控制台程序。内置软萌奶龙 System Prompt，支持多轮上下文记忆、聊天记录留存，通过通用 OpenAI 兼容接口调用大模型，方便切换不同厂商 API。语音（ASR/TTS）与硬件对接均已预留扩展接口。

## 一、项目结构

```
nailong/
├── main.py                     # 主程序（控制台对话循环）
├── config.yaml                 # 独立配置：API地址 / 密钥 / 模型 / 人设
├── requirements.txt            # 依赖清单
├── README.md                   # 本文档
├── core/
│   ├── config.py               # 配置加载与校验
│   ├── personality.py          # 奶龙人设（默认 System Prompt）
│   ├── llm_client.py           # OpenAI兼容接口封装 + 异常处理
│   ├── conversation.py         # 多轮上下文 + 聊天记录留存
│   ├── memory.py               # 长期记忆（事实抽取 + 检索注入）
│   └── emotion.py              # 动态情绪状态（含破防机制）
├── interfaces/
│   ├── asr.py                  # ASR 语音转文字预留接口
│   └── tts.py                  # TTS 文字转语音预留接口
├── data/                       # 聊天记录留存目录（运行后自动生成）
└── docs/
    ├── 语音功能扩展方案.md
    └── 后续硬件移植完整实施指南.md
```

## 二、环境要求

- Python 3.8 及以上（建议 3.10+）
- 可访问目标大模型接口的网络环境

## 三、安装与启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 填写配置

编辑项目根目录下的 `config.yaml`，至少修改以下两项：

```yaml
llm:
  base_url: "https://api.openai.com/v1"   # 换成你的接口地址
  api_key: "sk-你的密钥"                    # 换成你的密钥
  model: "gpt-4o-mini"                     # 换成你的模型名
```

常见厂商的 `base_url` 参考（务必以 `/v1` 结尾）：

| 厂商 | base_url |
|------|----------|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Moonshot | `https://api.moonshot.cn/v1` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

### 3. 运行

```bash
python main.py
```

启动后会打印欢迎横幅，直接输入文字即可与奶龙对话。

## 四、内置命令

| 命令 | 作用 |
|------|------|
| `/help` | 查看命令帮助 |
| `/exit`（或 `退出`） | 退出对话（自动留存记录） |
| `/new`（或 `清空`） | 开启全新对话，清空上下文 |
| `/save`（或 `保存`） | 手动保存当前聊天记录 |

## 五、本地测试步骤

1. **依赖自检**：`python -c "import requests, yaml; print('ok')"`，无报错即依赖就绪。
2. **语法自检**：`python -m py_compile main.py core/*.py interfaces/*.py`，无输出即通过。
3. **配置缺失测试**：故意把 `config.yaml` 改名，运行 `python main.py`，应看到「配置错误」提示而非崩溃。
4. **密钥缺失测试**：将 `api_key` 留空，运行后输入任意内容，应看到「尚未填写有效的 API 密钥」提示。
5. **网络断开测试**：断网或填错 `base_url`，输入内容，应看到「网络连接失败」等友好提示而非堆栈崩溃。
6. **多轮记忆测试**：先说「我叫小明」，下一轮问「我叫什么名字」，奶龙应能记住。
7. **记录留存测试**：退出后查看 `data/` 目录，应生成 `chat_YYYYMMDD_HHMMSS.jsonl`；再次启动会自动加载最近一次记录。

## 六、常见报错排查

| 报错 / 现象 | 原因 | 解决办法 |
|-------------|------|----------|
| `ModuleNotFoundError: No module named 'requests'` | 依赖未安装 | `pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'yaml'` | PyYAML 未安装 | `pip install PyYAML` |
| `找不到配置文件` | config.yaml 缺失或被改名 | 在项目根目录新建 config.yaml |
| `配置文件解析失败` | YAML 语法错误 | 检查冒号后是否有空格、缩进是否一致 |
| `尚未填写有效的 API 密钥` | api_key 为空或仍是占位符 | 编辑 config.yaml 填入真实密钥 |
| `请求超时` | 网络慢或接口无响应 | 增大 `timeout`，检查网络 |
| `网络连接失败` | 断网 / base_url 填错 | 检查网络与 `base_url`（需带 `/v1`） |
| `API 密钥无效（401）` | 密钥错误或过期 | 核对密钥、确认账户权限 |
| `额度不足（429）` | 请求超频或余额不足 | 稍后重试或检查账户额度 |
| `接口返回错误（HTTP 404）` | base_url 路径不对 | 确认是否漏了 `/v1` |

## 七、长期记忆与动态情绪（借鉴 ai-friend）

在原有文字对话基础上，反哺了 [ai-friend](https://github.com/OrinVoss/ai-friend) 的两个核心思路，均为精简落地、**零新增第三方依赖**：

### 长期记忆
- **抽取**：每轮对话后，用大模型从对话中抽取「值得记住的事实」（名字、喜好、事件等），写入 `data/memory.json`；
- **存储**：本地 JSON 文件，带重要性评分，超上限自动裁剪；
- **注入**：下一轮对话前，按字符相似度检索与当前输入最相关的记忆，注入人设提示词。
- 效果：不再把所有历史塞进上下文，会话变长也不怕超 token。

### 动态情绪
- 用内置情感词表（规则法，不额外调模型）判断用户输入的正负情感；
- 维护奶龙的「效价（valence）」情绪状态，每轮向基线衰减；
- 连续 5 次负面交互触发「破防」，语气变委屈/哭腔；
- 当前情绪会被翻译成自然语言，动态注入人设，影响回复语气。

### 配置开关
在 `config.yaml` 中：

```yaml
memory:
  enabled: true      # 关闭则只保留本轮上下文
  top_k: 3
  max_items: 200
  path: ""

emotion:
  enabled: true
  baseline: 0.2
  decay: 0.3
```

> 注意：长期记忆的「事实抽取」每轮会额外调用一次大模型（增加延迟与 token 消耗）；若想省成本，可将 `memory.enabled` 设为 `false`，情绪模块仍可独立工作。

## 八、交付说明

**Trae 本次已实现交付**：整体架构、目录结构、全部 Python 代码、配置文件、依赖清单、注释、本文档、语音扩展方案、硬件移植指南、自测逻辑。

**后续需用户自行操作扩展**：API 密钥注册/充值、ASR/TTS 具体接入、GPT-SoVITS 声线训练、ESP32 硬件采购与固件烧录、外壳制作、网页/动画图形界面开发。
