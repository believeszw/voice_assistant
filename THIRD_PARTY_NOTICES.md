# 第三方组件与许可

本仓库自带或依赖以下第三方组件，各自遵循其原始许可证：

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| webrtc-audio-processing (WebRTC AEC3) | 回声消除动态库（tools/aec3/*.dll，源码来自 freedesktop.org v2.1） | BSD-3-Clause |
| sherpa-onnx / k2-fsa | 流式 Paraformer、SenseVoice、KWS zipformer 推理 | Apache-2.0 |
| Vosk + vosk-model-small-cn-0.22 | 离线兜底识别 | Apache-2.0 |
| onnxruntime | Silero VAD 推理 | MIT |
| sounddevice / PortAudio | 音频采集与播放 | MIT |
| pywin32 / comtypes / pycaw | Windows SAPI、COM、音量控制 | PSF / MIT / MIT |
| psutil / pyperclip / Pillow / numpy | 进程、剪贴板、截屏、数值计算 | BSD-3 / BSD-3 / HPND / BSD-3 |
| 小米 MiMo API | 云端 ASR / TTS / LLM | 以服务方条款为准 |

模型文件（models/，约 2 GB）与测试音频不随仓库分发：首次运行前按 README「准备模型」一节下载，
或运行 `python tools/dl_models.py`。
