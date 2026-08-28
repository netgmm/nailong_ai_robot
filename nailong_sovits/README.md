# nailong_sovits —— 奶龙声线 GPT-SoVITS 模型

本目录存放奶龙情感陪伴 AI 使用的 **GPT-SoVITS 语音合成模型**（本地 TTS 声线）。

## 模型文件（GitHub Release 下载）

| 文件 | 大小 | 作用 |
|------|------|------|
| `xxx-e15.ckpt` | ~148 MB | SoVITS 模型权重（音色模型） |
| `xxx_e8_s200.pth` | ~129 MB | GPT 模型权重（语速/韵律模型） |

> 两个文件合计约 277 MB，超出 GitHub 单文件 100MB 限制，因此不直接放进代码仓库，改为发布在仓库的 **Release** 页面：
> **https://github.com/netgmm/nailong_ai_robot/releases**

## 使用方法

1. 从 Release 页面下载两个模型文件，放入 GPT-SoVITS 项目对应目录：
   - `xxx-e15.ckpt` → `GPT-SoVITS/SoVITS_weights/`
   - `xxx_e8_s200.pth` → `GPT-SoVITS/GPT_weights/`
2. 启动 GPT-SoVITS 的 api 服务：
   ```bash
   python api_v2.py -a 0.0.0.0 -p 9880
   ```
3. 在项目根目录 `config.yaml` 的 `tts` 段配置：
   ```yaml
   tts:
     api_url: "http://127.0.0.1:9880/tts"
     ref_audio_path: "nailong_sovits/参考音频.wav"   # 参考音频路径
     prompt_text: "参考音频对应的文字"                # 参考音频的文本内容
     prompt_language: "zh"
     text_language: "zh"
   ```

## 说明

- 模型文件体积大，未纳入 Git 版本控制（已被 `.gitignore` 排除），如需更新请同时发布到 Release。
- 需要重新训练声线时，用 GPT-SoVITS 的「语音训练」流程，产出的 `.pth` 与 `.ckpt` 覆盖本目录。
