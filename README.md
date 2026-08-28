# 奶龙情感陪伴 AI —— 语音交互机器人（FastAPI 后端 + ESP32-S3-Box-3 终端）

一个软萌奶龙人设的情感陪伴 AI 机器人：**ESP32-S3-Box-3 开发板**作为「哑终端」（录音 / 播放 / 屏幕显示双方对话），**电脑端 Python FastAPI 服务**承担全部智能（本地 ASR 语音识别 → DeepSeek 大模型情感对话 → 本地 GPT-SoVITS 语音合成），两端通过局域网 HTTP 通信，实现完整的语音对话闭环。

```
┌─────────────────────────┐        局域网 HTTP          ┌─────────────────────────────┐
│  ESP32-S3-Box-3（哑终端）│  ─── POST /voice ────▶  │   电脑 FastAPI 后端 (:8000)   │
│  ES7210 双麦克风录音      │                         │  faster-whisper 本地 ASR     │
│  ES8311 扬声器播放        │  ◀── 文字+音频 ─────   │  DeepSeek API 情感对话        │
│  LVGL 屏幕显示双方对话    │                         │  GPT-SoVITS 本地 TTS (:9880)  │
└─────────────────────────┘                         └─────────────────────────────┘
```

## 一、功能特性

- **完整语音闭环**：按键录音 → 本地 ASR 转文字 → 大模型情感对话 → 本地 TTS 合成语音 → 板子播放 + 屏幕显示双方对话
- **软萌奶龙人设**：内置 System Prompt，语气奶声奶气、先共情再回应
- **多轮上下文记忆**：同一会话上下文累积，记忆随对话延续
- **长期记忆**：每轮对话抽取「值得记住的事实」存本地 JSON，下一轮按相关性检索注入（零第三方依赖，会话再长也不怕超 token）
- **动态情绪**：规则法判断用户正负情感，维护奶龙情绪状态（含「破防」机制），影响回复语气
- **模块化设计**：LLM / ASR / TTS / 记忆 / 情绪均独立，可在 `config.yaml` 开关；LLM 走 OpenAI 兼容接口，可切换任意厂商
- **端侧哑终端设计**：板子只负责录音 / 播放 / 显示，智能全在后端，方便替换模型与升级

## 二、项目结构

```
nailong/
├── main.py                      # FastAPI 后端服务（/health /chat /voice）
├── config.yaml                  # 配置文件（API密钥 / 模型 / 人设 / 记忆 / 情绪 / 语音）
├── requirements.txt             # Python 依赖清单
├── core/
│   ├── config.py                # 配置加载与校验（api_key 支持环境变量 DEEPSEEK_API_KEY）
│   ├── personality.py           # 奶龙人设（默认 System Prompt）
│   ├── llm_client.py            # OpenAI 兼容接口封装 + 异常处理
│   ├── conversation.py          # 多轮上下文
│   ├── memory.py                # 长期记忆（事实抽取 + bigram 相似度检索 + JSON 存储）
│   └── emotion.py               # 动态情绪状态（含破防机制）
├── interfaces/
│   ├── asr.py                   # faster-whisper 本地语音识别
│   └── tts.py                   # GPT-SoVITS 语音合成
├── firmware/                    # ESP32-S3-Box-3 固件（ESP-IDF v5.5.5）
│   ├── main/
│   │   ├── main.c               # 入口：按键录音 → 上传 → 显示 → 播放
│   │   ├── app_audio.c/h        # ES7210 录音 / ES8311 播放（32kHz/16bit）
│   │   ├── app_backend.c/h      # HTTP 上传录音、接收回复音频
│   │   ├── app_display.c/h      # LVGL 屏幕：状态栏 + 双方对话滚动区
│   │   ├── app_wifi.c/h         # WiFi Station
│   │   ├── idf_component.yml    # 组件依赖（esp-box-3 / button / esp_codec_dev）
│   │   └── Kconfig.projbuild    # WiFi SSID / 后端地址 配置项
│   ├── partitions.csv           # 自定义分区表（6MB factory）
│   └── sdkconfig.defaults       # 默认编译配置
├── data/                        # 运行数据（聊天记录、记忆、调试音频，自动生成）
└── docs/
    ├── 开发问题排查记录.md       # 开发过程问题排查活文档（现象/原因/解决）
    ├── 语音功能扩展方案.md
    └── 后续硬件移植完整实施指南.md
```

## 三、后端（Python FastAPI）

### 1. 环境要求

- Python 3.10+
- 可访问 DeepSeek API 的网络环境（或换成其它 OpenAI 兼容接口）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

编辑 `config.yaml`，至少配置 `llm` 段：

```yaml
llm:
  base_url: "https://api.deepseek.com/v1"   # 务必以 /v1 结尾
  api_key: ""                               # 可留空，改用环境变量
  model: "deepseek-chat"
```

**API 密钥两种方式（任选其一，推荐环境变量，避免密钥进仓库）**：

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-你的密钥"
python main.py

# Linux / macOS
export DEEPSEEK_API_KEY="sk-你的密钥"
python main.py
```

或直接填在 `config.yaml` 的 `llm.api_key`（注意：该文件已被 `.gitignore` 忽略，不会提交到仓库）。

### 4. 启动

```bash
python main.py            # 默认 0.0.0.0:8000
# 或
uvicorn main:app --host 0.0.0.0 --port 8000
```

启动时会自动加载配置并预热 ASR 模型。看到 `Uvicorn running on http://0.0.0.0:8000` 即启动成功。

### 5. HTTP 接口

| 接口 | 说明 |
|------|------|
| `GET /health` | 健康检查，返回 `{"status": "ok"}` |
| `POST /chat` | 输入文字 `{"text": "..."}`，返回奶龙回复文字 + TTS 音频（base64） |
| `POST /voice` | 输入音频 `{"audio_base64": "...", "audio_format": "wav"}`，先 ASR 识别再对话，返回识别文字 + 回复文字 + TTS 音频 |

### 6. 语音模型（可选，仅语音功能需要）

- **ASR**：faster-whisper 本地模型（`config.yaml` 的 `asr` 段，默认 base / cpu / int8 / 中文），首次请求自动下载
- **TTS**：GPT-SoVITS（本地启动 api，监听 `127.0.0.1:9880`），需在 `config.yaml` 的 `tts` 段填好 `ref_audio_path` 与 `prompt_text`

## 四、固件（ESP32-S3-Box-3）

### 1. 环境

- ESP-IDF **v5.5.5**（含 ESP32-S3 工具链）
- 组件依赖（`firmware/main/idf_component.yml`）：`esp-box-3 ^3.2.0`、`button ^4.0.0`、`esp_codec_dev ~1.5`

> 注意：必须用 **esp-box-3**（Box-3 专用 BSP），不要用老款 `esp-box`——老 BSP 的 I2S 字同步引脚（LCLK）与 Box-3 硬件不符，会导致 ES7210 录音全为 0、扬声器音调失真（详见 `docs/开发问题排查记录.md`）。

### 2. 配置 WiFi 与后端地址

编译前执行 `idf.py menuconfig`，在「奶龙语音终端配置」菜单里填写：

| 配置项 | 说明 |
|--------|------|
| `WIFI_SSID` | WiFi 名称 |
| `WIFI_PASSWORD` | WiFi 密码（开放网络留空） |
| `BACKEND_BASE_URL` | 电脑后端地址，如 `http://192.168.1.100:8000`（电脑 IP 需与板子同一局域网） |

### 3. 编译烧录

```powershell
# 激活 ESP-IDF 环境
. D:\ESP-IDF\v5.5.5\esp-idf\export.ps1
cd firmware

# 首次需设置目标芯片
idf.py set-target esp32s3

# 编译
idf.py build

# 烧录 + 串口监视（把 COMx 换成实际串口号）
idf.py -p COM3 flash monitor
```

### 4. 使用方式

1. 电脑端先启动 GPT-SoVITS（9880）与后端（8000）；
2. 板子上电连上 WiFi（串口日志出现 `got ip` 与 `backend: http://...`）；
3. 按一下 **boot 键**（GPIO0，配置键）开始录音，说完**再按一下结束**（超 30 秒自动结束）；
4. 板子自动上传录音 → 显示「你」说的话与奶龙的回复 → 播放奶龙语音。

> 静音键（GPIO1）按下会点亮静音灯、在硬件层面静音麦克风，**不能**用来录音。

## 五、配置说明（config.yaml）

| 段落 | 关键项 | 说明 |
|------|--------|------|
| `llm` | base_url / api_key / model | 大模型接口与密钥（api_key 可走环境变量） |
| `personality` | system_prompt | 奶龙人设提示词，可自由修改 |
| `memory` | enabled / top_k / max_items | 长期记忆开关、每轮注入条数、上限 |
| `emotion` | enabled / baseline / decay | 动态情绪开关与参数 |
| `asr` | enabled / model_size / device / compute_type / language | 本地语音识别（faster-whisper） |
| `tts` | enabled / api_url / ref_audio_path / prompt_text | 语音合成（GPT-SoVITS） |

## 六、开发问题排查记录

开发过程中遇到的坑（组件版本冲突、I2S 引脚错误、I2C 驱动冲突、大音频传输超时、麦克风静音键误用等）及解决方案，持续维护在 [docs/开发问题排查记录.md](docs/开发问题排查记录.md)，遇到问题优先查阅。

## 七、安全提示

- `config.yaml` 包含 API 密钥，已被 `.gitignore` 排除，**请勿手动提交**；
- 推荐使用环境变量 `DEEPSEEK_API_KEY` 传递密钥；
- 完整配置项说明见上文「五、配置说明」。
