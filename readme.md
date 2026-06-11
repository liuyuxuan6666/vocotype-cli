# VocoType - 精准的离线语音输入法

<h2 align="center">您的声音，绝不离开电脑</h2>

**VocoType** 是一款专为注重隐私和效率的专业人士打造的、**完全免费**的桌面端语音输入法。所有识别均在本地完成，无惧断网，不上传任何数据。

这个 GitHub 项目是 VocoType 核心引擎的 **CLI (命令行) 开源版本**，主要面向开发者。

---

### **➡️ 想获得最佳体验？请立即下载免费桌面版！**

开箱即用，功能更完整，无需任何技术背景。

**[立即访问官网，下载免费、完整的 VocoType 桌面版](https://vocotype.com)**

## 功能简介

VocoType 是一款智能语音输入工具，通过快捷键即可将语音实时转换为文字并自动输入到当前应用。支持MCP语音转文字、 AI 优化文本、自定义替换词典等功能，让语音输入更高效、更准确。

### 📹 演示视频

<video controls width="100%">
  <source src="https://s1.bib0.com/leilei/i/2025/11/04/5yba.mp4" type="video/mp4">
  您的浏览器不支持视频播放。
</video>


## 🐧 Linux / Wayland 适配（二次开发）

> 本次二次开发将 VocoType CLI 从纯 Windows 项目适配到 **Linux (Wayland / Hyprland)** 平台。Windows 代码完整保留，不影响原有功能。

### 改动概要

| 模块 | 变更 |
|------|------|
| `app/output.py` | 新增 Linux 文本注入：Wayland 使用 `wtype`，X11 回退 `xdotool`。Windows 代码不变。 |
| `main.py` | 移除 `keyboard` 库依赖，改用 **SIGUSR1 信号** 驱动录音 toggle。PID 文件写入 `/tmp/vocotype.pid`。 |
| `scripts/toggle.sh` | 新建。读取 PID 文件，发送 `kill -USR1`。绑定到 WM 快捷键。 |

### 环境要求（Linux）

- **Python 3.12+**，推荐使用 `uv` 管理虚拟环境
- **Wayland 环境**：`wtype`、`wl-copy`、`wl-paste`（`sudo pacman -S wtype wl-clipboard`）
- **X11 回退**（可选）：`xdotool`、`xclip`
- **PulseAudio / PipeWire**：录音设备需要支持 16kHz 采样率（ALSA 直连设备通常不支持，需使用 `pulse` 或 `pipewire` 虚拟设备）

### 快速开始

```bash
# 1. 安装系统依赖 (Arch)
sudo pacman -S wtype wl-clipboard

# 2. 克隆并安装 Python 依赖
cd vocotype-cli
uv venv
uv pip install -r requirements.txt

# 3. 创建配置文件 ~/.vocotype_config.json
cat > ~/.vocotype_config.json << 'EOF'
{
    "audio": {"device": "pulse"},
    "output": {"method": "wtype"},
    "asr": {
        "use_vad": true,
        "use_punc": true,
        "language": "zh"
    }
}
EOF

# 4. 启动（必须设置 FUNASR_USE_VAD 环境变量以启用 VAD）
FUNASR_USE_VAD=true python main.py --config ~/.vocotype_config.json
```

### Hyprland 集成

将以下内容加入 `~/.config/hypr/hyprland.conf`：

```ini
# 开机自启动（确保麦克风取消静音 & 增益合理）
exec-once = pactl set-source-mute <your-mic> 0
exec-once = pactl set-source-volume <your-mic> 60%
# 启动 VocoType 后台进程
exec-once = bash -c 'FUNASR_USE_VAD=true /path/to/vocotype-cli/.venv/bin/python /path/to/vocotype-cli/main.py --config ~/.vocotype_config.json'

# 快捷键绑定（F2 开始/停止录音）
bind = , F2, exec, /path/to/vocotype-cli/scripts/toggle.sh
```

> 查找你的麦克风名：`pactl list sources short | grep input`

### 架构说明：SIGUSR1 vs 键盘钩子

原 Windows 版本使用 Python `keyboard` 库注册全局热键，在 Linux 上需要 root 权限且与 Wayland 不兼容。本次适配改为：

```
Hyprland F2  →  toggle.sh  →  kill -USR1 $(cat /tmp/vocotype.pid)
                                    ↓
                            main.py signal handler → _toggle(worker)
```

### 常见问题

**"VAD ONNX模型加载完成" 未出现？** 说明 VAD 未启用。必须设置环境变量 `FUNASR_USE_VAD=true` 才能加载 VAD 模型，否则识别效果很差。

**录音没声音？** 检查：
1. `pactl get-source-mute <mic>` — 是否为 `no`
2. `pactl get-source-volume <mic>` — 是否 >= 50%
3. 配置文件正确使用了 `"device": "pulse"`（而非空的默认值，避免 ALSA hw 设备）

**识别效果差？** 可能原因：
1. **使用 int8 量化 ONNX 模型（默认）精度有限** → 升级到 PyTorch 全精度模型（见下方）
2. VAD 未开启 → 启动日志确认包含 "VAD ONNX模型加载完成"（ONNX模式）或 "ASR PyTorch 模型加载完成"
3. 麦克风增益过高导致削波 → 降至 60% 左右
4. **丢字？** 已修复：VAD 检测语音段 → 切割 → 仅喂语音段给 ASR。确认日志包含 "VAD处理完成，检测到 X 个语音段"

### 升级到 PyTorch 全精度模型（推荐）

默认使用 **int8 量化 ONNX 模型**（227MB，`model_quant.onnx`）以节省内存和加载时间，但精度有损失。如需更高识别准确率，可切换到 PyTorch 全精度模型（944MB）：

```bash
# 1. 安装 PyTorch CPU + torchaudio
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install torchaudio --index-url https://download.pytorch.org/whl/cpu

# 2. 安装 funasr（PyTorch 版）
uv pip install funasr einops more_itertools

# 3. 设置环境变量启动
FUNASR_ASR_MODEL="iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch" \
    python main.py --config ~/.vocotype_config.json
```

首次启动会自动下载模型 ~944MB（缓存到 `~/.cache/modelscope/hub/`）。

Hyprland 自启动：

```ini
exec-once = bash -c 'FUNASR_ASR_MODEL="iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch" /path/to/venv/bin/python /path/to/main.py --config ~/.vocotype_config.json'
```

### PyTorch 模型 vs ONNX 量化对比

## 下载

| OS | Download |
|---|---|
| **Windows** | [![Setup](https://img.shields.io/badge/Setup-x64-blue)](https://github.com/233stone/vocotype-cli/releases/download/v1.5.5/VocoType_1.5.5_x64-setup.exe)  | 
| **macOS** | [![DMG](https://img.shields.io/badge/DMG-Apple%20Silicon-black)](https://github.com/233stone/vocotype-cli/releases/download/v1.5.5/VocoType_1.5.5_Universal.dmg) [![DMG](https://img.shields.io/badge/DMG-Intel-black)](https://github.com/233stone/vocotype-cli/releases/download/v1.5.5/VocoType_1.5.5_Universal.dmg)  |
---



## 🤔 VocoType 为何与众不同？

| 特性           |    ✅ **VocoType**     |  传统云端输入法   |  操作系统自带   |
| :------------- | :--------------------: | :---------------: | :-------------: |
| **隐私安全**   | **本地离线，绝不上传** | ❌ 数据需上传云端 | ⚠️ 隐私政策复杂 |
| **网络依赖**   |    **完全无需联网**    |  ❌ 必须联网使用  |  ❌ 强依赖网络  |
| **响应速度**   |      **0.1 秒级**      |  慢，受网速影响   | 慢，受网速影响  |
| **定制化能力** |  **强大的自定义词表**  |      弱或无       |    基本没有     |

## ✅ 核心功能

- **完整的图形用户界面**：开箱即用，所有操作清晰直观。
- **系统级全局输入**：在任何软件、任何文本框内都能直接语音输入。
- **自定义词典**：支持添加 20 个常用术语、人名，提升识别准确率。
- **100% 离线运行**：绝对的隐私和数据安全。
- **旗舰级识别引擎**：精准识别中英混合内容。
- **AI 智能优化**：支持选择多种 AI 模型，通过可定制的 Prompt 模板自动修正语音转录中的错别字、同音字和自我修正，智能识别口语中的修正指令（如"不对"、"改成"等），让输出文本更准确流畅。

_(对于有更高需求的专业用户，应用内提供了升级到 Pro 版的选项，以解锁无限词典等高级功能。)_

## 🎯 适用各类专业场景

无论是文字工作者、律师、学者、游戏玩家，还是日常办公，VocoType 都能成为您值得信赖的效率伙伴。

| 用户                | 场景                                                                                           |
| :------------------ | :--------------------------------------------------------------------------------------------- |
| **作家与创作者**    | 撰写文章、小说，整理会议纪要，让思绪通过语音即时转化为文字，心无旁骛，专注于创作本身。         |
| **法律 & 医疗人士** | 处理高度敏感的客户信息或病历时，100%离线确保数据安全。自定义词表更能轻松驾驭行业术语。         |
| **学生与学者**      | 快速记录课堂笔记、整理访谈录音、撰写学术论文。告别繁琐的打字，将更多精力投入到思考与研究之中。 |
| **开发者 & 程序员** | 无论是与 AI 结对编程，还是撰写技术文档，都能精准识别 `function`、`Kubernetes pod` 等专业术语。 |
| **游戏玩家**        | 在激烈的游戏对战中，通过语音快速打字与队友交流，无需停下操作，保持游戏节奏，提升团队协作效率。 |

## ✨ VocoType 核心引擎特性

_所有 VocoType 版本共享同一个强大的核心引擎。_

- **🛡️ 100% 离线，隐私无忧**：所有语音识别在您的电脑本地完成。
- **⚡️ 旗舰级识别引擎**：中英混合输入同样精准，告别反复修改。
- **⚙️ 高度可定制**：独创的替换词表功能，让人名、地名、行业术语一次就对。
- **💻 轻量化设计**：仅需 700MB 内存，纯 CPU 推理，无需昂贵显卡。
- **🚀 0.1 秒级响应**：感受所言即所得的畅快，让您的灵感不再因等待而中断。

---

## 🛠️ 【开发者专属】CLI 版安装指南

**请注意：** 此版本面向有一定技术背景的开发者。如果您不熟悉命令行，我们强烈建议您访问官网，下载简单易用的 **VocoType 免费桌面版**。

### 1. 环境依赖

- Python 3.12
- 我们强烈建议使用 `uv` 或 `venv` 创建虚拟环境。

### 2. 克隆与安装

```bash
# 1. 克隆仓库
git clone https://github.com/233stone/vocotype-cli.git
cd vocotype-cli

# 2. (推荐) 创建并激活虚拟环境
pip install uv
uv venv --python 3.12
source .venv/bin/activate  # macOS/Linux
# 或者 .\.venv\Scripts\activate  (Windows)

# 3. 安装依赖
uv pip install -r requirements.txt

# 4. 运行
python main.py

# 保存数据集运行
python main.py --save-dataset
```

> **模型下载**：首次运行时，程序会自动下载约 500MB 的模型文件，请确保网络连接稳定。

## 🌐 Volcengine 火山引擎 BigASR 流式识别后端（可选）

除了默认的本地 FunASR 离线引擎，VocoType CLI 还支持接入[火山引擎豆包大模型流式语音识别](https://www.volcengine.com/docs/6561/1354869)作为云端识别后端。

### 优势

| 特性 | 本地 FunASR | Volcengine BigASR |
|:--|:--:|:--:|
| 网络要求 | 无 | 需要联网 |
| 模型下载 | ~500 MB | 无需下载 |
| 响应延迟 | 本地推理 | 云端极低延迟 |
| 识别质量 | 高 | 旗舰级大模型 |
| 数据隐私 | 完全离线 | 音频发送至火山引擎 |

### 配置步骤

1. 登录[火山引擎控制台](https://console.volcengine.com/speech/app)，创建一个语音应用，获取 **App Key** 和 **Access Key**。

2. 在项目目录创建 `config.json`：

```json
{
  "backend": "volcengine",
  "volcengine": {
    "app_key": "YOUR_APP_KEY",
    "access_key": "YOUR_ACCESS_KEY",
    "resource_id": "volc.bigasr.sauc.duration",
    "enable_punc": true,
    "enable_itn": true
  }
}
```

3. 以 `--config` 参数启动：

```bash
python main.py --config config.json
```

> **注意**：使用 Volcengine 后端时，录音数据会发送到火山引擎服务器进行识别，不再完全离线。如对隐私有严格要求，请继续使用默认的本地 FunASR 后端。

## 常见问题 (FAQ)

**Q: 我的数据安全吗？**

> A: **100%安全**。所有语音识别均在本地离线完成，您的音频数据不会上传到任何服务器。

## 📞 联系我们

- **Bug 与建议**：请优先使用 GitHub Issues。
- **关注我们获取最新动态**：[https://vocotype.com](https://vocotype.com)

## 🙏 致谢

VocoType 的诞生离不开以下优秀的开源项目：

- **[FunASR](https://github.com/modelscope/FunASR)** - 阿里巴巴达摩院开源的语音识别框架，为 VocoType 提供了强大的离线语音识别能力。
- **[QuQu](https://github.com/yan5xu/ququ)** - 优秀的开源项目，为 VocoType 提供了重要的技术参考和灵感。

感谢这些开源社区的无私贡献！
