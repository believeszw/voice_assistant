"""全局配置：音频参数、唤醒词、应用别名表。"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models" / "vosk-model-small-cn-0.22"

# ---- 音频 ----
SAMPLE_RATE = 16000          # 语音识别标准采样率
BLOCK_MS = 50
BLOCK_SIZE = SAMPLE_RATE * BLOCK_MS // 1000
MIC_NAME = ""                # 留空用系统默认麦克风；也可填 "USB Mic"
# 麦克风偏小可调到 2.0~4.0（会同时放大噪声）；也可用环境变量 MIC_GAIN 临时覆盖
MIC_GAIN = float(os.environ.get("MIC_GAIN", "1.0"))
TTS_VOICE = "Microsoft Huihui Desktop"   # Windows 自带中文女声

# ---- 音频前端：AEC → 降噪 → AGC（顺序与选型文档一致）----
NS_ENABLED = True            # 谱减降噪（稳态噪声）
AGC_ENABLED = True           # 自动增益
AGC_TARGET_RMS = 0.05        # 目标语音 RMS（约 -26 dBFS）
# auto: 优先用 tools/aec3 下的 WebRTC AEC3（延迟/双讲更稳）；不可用时退回自研 FLMS
AEC_ENGINE = "auto"          # auto / aec3 / flms

# ---- 唤醒 ----
WAKE_WORDS = ("小助手", "你好小助手", "小助手小助手", "小爱小助手")
# Vosk 小模型对"小助手"的识别可能漂移，这里列出常见近似结果
WAKE_WORDS_FUZZY = ("小助手", "小柱手", "小就是", "小助", "助手", "你好小")

# ---- 会话 ----
WAKE_ACK = "我在"
COMMAND_MAX_SECONDS = 8.0    # 单条指令最长录音
COMMAND_SILENCE_SECONDS = 0.8  # 多久没声音算说完了
FOLLOWUP_HINT = "还有什么需要我做吗？说“退出”结束。"

# ---- 云端能力（小米 MiMo）----
# 端侧优先：唤醒、VAD、AEC、识别（sherpa-onnx 双遍）、规则意图都在本地完成；
# 云端只做兜底（本地识别为空/太短，或本地文本解析不出意图）和闲聊/知识问答。
CLOUD_ENABLED = True
CLOUD_ASR = True
CLOUD_TTS = True
CLOUD_LLM = True
TTS_VOICE_NAME = "冰糖"       # MiMo 预置音色：冰糖 / 茉莉 / 苏打 / 白桦 / mimo_default
TTS_STYLE = "语速稍快，语气自然"

# ---- TTS 双路（选型 §4 / §5：云端主路 + 端侧兜底，首包即播）----
# 端侧后端用 sherpa-onnx 的 VITS 模型（MeloTTS 中英混合，离线、可暂停、可推 AEC 参考）。
# 选型文档写的是 Piper；两者同属 VITS 家族，本项目已装 sherpa-onnx 运行时（ASR/KWS 同源），
# 换 Piper 只需改 tts_local._load_model() 里的模型文件。
TTS_LOCAL_ENABLED = True
TTS_LOCAL_DIR = BASE_DIR / "models" / "tts" / "vits-melo-tts-zh_en"
TTS_LOCAL_THREADS = 4
TTS_LOCAL_SPEED = 1.0
# 云端 TTS 超过这个时间还没返回整段 wav，就改端侧合成（避免弱网时干等）
TTS_CLOUD_TIMEOUT = 4.0
# True：跳过云端直接用端侧（断网/演示/对比测速用；也可用环境变量 VOICE_OFFLINE=1 全离线）
TTS_LOCAL_FIRST = os.environ.get("TTS_LOCAL_FIRST", "0") == "1"
# 端侧 TTS 后端：""=自动（Piper 优先，缺失退 sherpa VITS）；"piper" / "vits" 强制指定（对比测试用）
TTS_LOCAL_BACKEND = os.environ.get("TTS_LOCAL_BACKEND", "").lower()

# ---- 端侧 NLU（选型 §5：云端 function calling + 端侧 Qwen2.5-1.5B int4 兜底）----
NLU_LOCAL_ENABLED = True
NLU_LOCAL_DIR = BASE_DIR / "models" / "llm"
NLU_LOCAL_MODEL = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
NLU_LOCAL_SERVER = BASE_DIR / "tools" / "llama" / "llama-server.exe"
NLU_LOCAL_PORT = int(os.environ.get("NLU_LOCAL_PORT", "18080"))
NLU_LOCAL_THREADS = 8
NLU_LOCAL_NGL = int(os.environ.get("NLU_LOCAL_NGL", "0"))   # 0=纯 CPU；有 CUDA 版可调 99
NLU_LOCAL_TIMEOUT = 6.0        # 端侧单次解析的总超时（选型：端侧首响 P50<0.9 s，留足冷启动余量）
NLU_LOCAL_MAX_TOKENS = 96
NLU_LOCAL_START_TIMEOUT = 60.0  # llama-server 冷启动（含加载 gguf）最长等待
# True：用 tools + tool_calls 的经典 function calling；False：用 json_schema 约束解码
NLU_LOCAL_TOOL_CALLS = os.environ.get("NLU_LOCAL_TOOL_CALLS", "0") == "1"

# ---- 识别策略：端侧优先，云端为辅（参照小米车机助手）----
ASR_LOCAL_FIRST = True          # True：端侧双遍先出结果；False：云端先（旧行为）
ASR_CLOUD_FALLBACK = True       # 本地结果为空或太短时，云端再听一遍
ASR_CLOUD_RETRY_ON_UNKNOWN = True  # 本地识别有字但规则解析不出意图时，云端重听一次
ASR_LOCAL_MIN_CHARS = 2         # 少于这个字数视为「没听清」，触发云端兜底

# ---- 连续对话 ----
SESSION_MAX_TURNS = 6         # 一次唤醒最多连续聊几轮
FOLLOWUP_START_TIMEOUT = 6.0  # 一轮结束后等用户开口的时间（秒）

# ---- 应用别名 -> 启动方式 ----
# 值可以是 exe 名（走 start）、完整路径、URL 协议（ms-settings:）
APPS = {
    "记事本": "notepad",
    "计算器": "calc",
    "画图": "mspaint",
    "写字板": "write",
    "资源管理器": "explorer",
    "文件管理器": "explorer",
    "我的电脑": "explorer",
    "任务管理器": "taskmgr",
    "控制面板": "control",
    "设置": "ms-settings:",
    "浏览器": "msedge",
    "edge": "msedge",
    "chrome": "chrome",
    "谷歌浏览器": "chrome",
    "cmd": "cmd",
    "命令提示符": "cmd",
    "终端": "wt",
    "powershell": "powershell",
    "vs code": "code",
    "vscode": "code",
    "代码编辑器": "code",
    "微信": "wechat",
    "qq": "qq",
    "网易云音乐": "cloudmusic",
    "网易云": "cloudmusic",
    "音乐": "cloudmusic",
    "播放器": "wmplayer",
    "steam": "steam",
    "钉钉": "dingtalk",
    "飞书": "feishu",
    "telegram": "telegram",
    "哔哩哔哩": "https://www.bilibili.com",
    "b站": "https://www.bilibili.com",
    "百度": "https://www.baidu.com",
    "淘宝": "https://www.taobao.com",
    "京东": "https://www.jd.com",
    "知乎": "https://www.zhihu.com",
    "微博": "https://weibo.com",
    "github": "https://github.com",
    # 系统自带（用协议打开，比 exe 名可靠）
    "相册": "ms-photos:",
    "图片": "ms-photos:",
    "照片": "ms-photos:",
    "相机": "microsoft.windows.camera:",
    "文件": "explorer",
    "此电脑": "explorer",
    "回收站": "shell:RecycleBinFolder",
}

# ---- 可控文件夹 ----
FOLDERS = {
    "下载": "Downloads",
    "下载文件夹": "Downloads",
    "文档": "Documents",
    "桌面": "Desktop",
    "图片": "Pictures",
    "音乐": "Music",
    "视频": "Videos",
}

# 需要二次确认的指令（危险操作）
DANGEROUS = {"shutdown", "restart", "sleep", "close_app", "lock"}
