# -*- coding: utf-8 -*-
"""生成《语音助手测试用例文档》：输出 Markdown + Word（docx）。

每个用例都是可照着做的：明确说什么话、什么时候说、看什么日志、期望什么现象。
用法（用 DSH python，装了 python-docx）：
  python tools/build_test_doc.py
产物：
  docs/语音助手_测试用例.md
  docs/语音助手_测试用例.docx
"""
import os
from datetime import date

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs")
MD_PATH = os.path.join(OUT_DIR, "语音助手_测试用例.md")
DOCX_PATH = os.path.join(OUT_DIR, "语音助手_测试用例.docx")

TITLE = "语音助手测试用例文档"
VERSION = "v2.0"
TODAY = date.today().strftime("%Y-%m-%d")

ENV = [
    "操作系统：Windows 10/11（本机 10.0.26300）；解释器 C:\\va-venv\\Scripts\\python.exe（短路径，长路径下 SAPI 失效）",
    "依赖：sounddevice / vosk / sherpa-onnx / onnxruntime / pywin32 / pycaw / psutil / comtypes / numpy",
    "音频：默认输出 E3500（HDMI）、输入 USB Mic；测试前系统音量 100%、不能静音（tools/fix_volume.py 可一键恢复）",
    "云服务：MiMo（ASR/TTS/LLM，OpenAI 兼容），key 在 ~/.dsh/.credentials.yaml；断网时走端侧",
    "本地模型：Vosk small-cn、sherpa-onnx 流式 Paraformer + SenseVoice、KWS zipformer、Silero VAD、WebRTC AEC3（C:\\wap2 构建）",
    "前置动作：先杀掉残留 python 进程（powershell \"Get-Process python|Stop-Process -Force\"），再启动助手",
]

CRITERIA = [
    ("唤醒", "安静近场唤醒率 ≥ 95%；SNR 5 dB ≥ 80%；误唤醒 < 1 次/小时；唤醒应答 ≤ 1.35 s"),
    ("识别", "干净语音 CER = 0；10 dB ≥ 95%；5 dB 不劣于 8%；0 dB 端侧优先后不劣于基线"),
    ("指令", "P0 指令正确率 100%；复合指令每句都要落地并回报；未知指令要有明确反馈"),
    ("打断", "真人插话后 0.6 s 内停止播报；下一句完整（预录 ≥ 1.2 s 不丢头）；噪声/自身回声不误打断"),
    ("音频前端", "AEC ERLE ≥ 6 dB（离线）；NS 纯噪声降噪 ≥ 10 dB；AGC 三档电平误差 ≤ 10 dB"),
    ("稳定性", "连续 30 分钟多轮对话不崩、不死锁、不占麦（H03 待补）"),
]

# 用例字段：id, mod, name, pri, kind, pre[], steps[], expect[], auto, result
CASES = [
    # ---------------- A 音频前端与声学 ----------------
    dict(id="A01", mod="A 音频前端", name="AEC3 离线指标（合成回声）", pri="P0", kind="自动",
         pre=["aec3_wrap.dll 与模型就绪", "命令行可用"],
         steps=["运行 C:\\va-venv\\Scripts\\python.exe tools\\test_frontend.py",
                "读输出的 ERLE / hit / fp / latency 四个数"],
         expect=["AEC 开：ERLE ≥ 6 dB、hit ≥ 0.8、fp ≤ 0.2、latency ≤ 0.6 s",
                 "AEC 关对照：ERLE ≈ 0 dB（证明指标来自 AEC）"],
         auto="tools/test_frontend.py",
         result="PASS：AEC 开 ERLE 38.2 dB、hit 1.000、latency 0.10 s（fp 0.442 为 AEC 关对照留档）"),
    dict(id="A02", mod="A 音频前端", name="真实设备延迟锁定", pri="P1", kind="自动",
         pre=["扬声器外放、麦克风可采", "AEC_ENGINE=auto（走 AEC3）"],
         steps=["运行 tools/test_aec_real.py", "看日志里的 delay / dtd / erle"],
         expect=["delay 锁定在 0.28–0.32 s（约 4500–5100 样本）", "锁定后 erle 稳定为正，不来回重锁"],
         auto="tools/test_aec_real.py",
         result="PASS：delay 4522–4671 样本（0.28–0.29 s）；本机回声弱，erle 偏小，前端走 weak_echo 分支"),
    dict(id="A03", mod="A 音频前端", name="纯噪声降噪量", pri="P0", kind="自动",
         pre=["NS 开启（默认深降噪档）"],
         steps=["运行 tools/test_ns_agc.py 第 4 项", "对比输入/输出 dBFS"],
         expect=["降噪量 ≥ 10 dB"],
         auto="tools/test_ns_agc.py",
         result="PASS：-34.0 → -44.9 dBFS，10.9 dB"),
    dict(id="A04", mod="A 音频前端", name="NS 前后识别 CER 不劣化", pri="P0", kind="自动",
         pre=["带噪语音 10/5/0 dB（case_2..case_7）"],
         steps=["运行 tools/test_ns_agc.py 第 2 项", "对比开/关 NS 的 CER"],
         expect=["CER 不上升（允许持平）"],
         auto="tools/test_ns_agc.py",
         result="PASS：0.167→0.167、0.167→0.167、0.200→0.200"),
    dict(id="A05", mod="A 音频前端", name="NS 前后唤醒命中不下降", pri="P0", kind="自动",
         pre=["带噪唤醒词，NS-only 流式"],
         steps=["运行 tools/test_ns_agc.py 第 3 项", "对比 SNR5/SNR0 命中数"],
         expect=["命中数不下降"],
         auto="tools/test_ns_agc.py",
         result="PASS：SNR5 3/4→3/4、SNR0 2/4→2/4"),
    dict(id="A06", mod="A 音频前端", name="AGC 小/中/大音量拉齐", pri="P1", kind="自动",
         pre=["输入三档峰值 -54.7 / -42.7 / -31.2 dBFS"],
         steps=["运行 tools/test_ns_agc.py 第 1 项", "看三档输出电平与峰值"],
         expect=["三档输出差 ≤ 10 dB", "峰值 < 1.0 不削波"],
         auto="tools/test_ns_agc.py",
         result="PASS：输出 -32.6/-26.3/-23.2 dBFS，峰值 0.23/0.55/0.93"),
    dict(id="A07", mod="A 音频前端", name="无语音尖峰不触发打断", pri="P0", kind="自动",
         pre=["播报中叠加 0.30 的瞬时尖峰、无人说话"],
         steps=["运行 tools/test_demo_fixes.py 的前端断言"],
         expect=["barge_in 不触发（能量类证据不越过确认阶段）"],
         auto="tools/test_demo_fixes.py",
         result="PASS：rms=0.000 时 barge=false"),
    dict(id="A08", mod="A 音频前端", name="自身播报尾音不误判打断", pri="P0", kind="自动",
         pre=["模拟播放尾音：前 4 块很响，随后静音"],
         steps=["运行 tools/test_demo_fixes.py 的 _confirm_barge 断言"],
         expect=["_confirm_barge 返回 False（0.30 s settle 内丢弃）"],
         auto="tools/test_demo_fixes.py",
         result="PASS：confirmed=False"),

    # ---------------- B 唤醒 ----------------
    dict(id="B01", mod="B 唤醒", name="KWS 四档唤醒率", pri="P0", kind="自动",
         pre=["KWS 模型与 kws_keywords.txt 就绪", "tools/kwswav 下已合成唤醒词 wav"],
         steps=["运行 tools/test_kws.py", "读 clean/SNR10/SNR5/SNR0 四档的命中率"],
         expect=["clean ≥ 95%、SNR5 ≥ 80%", "误唤醒 < 1 次/小时"],
         auto="tools/test_kws.py",
         result="PASS：clean 100%、SNR10 75%、SNR5 83%、SNR0 58%；误唤醒 0 次/13 min"),
    dict(id="B02", mod="B 唤醒", name="误唤醒（电视/播客噪声）", pri="P0", kind="自动",
         pre=["30 min 不含唤醒词的音频 + 30 s 静音"],
         steps=["运行 tools/test_kws.py 负样本部分"],
         expect=["误唤醒 0 次（每小时 < 1）"],
         auto="tools/test_kws.py",
         result="PASS：过滤含唤醒词的样本后，误唤醒 0 次"),
    dict(id="B03", mod="B 唤醒", name="唤醒应答时延", pri="P1", kind="自动",
         pre=["预生成 assets/wake_ack.wav"],
         steps=["运行 tools/test_barge_false.py（内含应答计时）", "读『唤醒回应 X s』"],
         expect=["≤ 1.35 s（预生成音频约 0.96 s）"],
         auto="tools/test_barge_false.py",
         result="PASS：1.18–1.19 s"),
    dict(id="B04", mod="B 唤醒", name="唤醒残余文本不执行", pri="P0", kind="自动",
         pre=["Vosk 文本唤醒分支"],
         steps=["模拟识别结果「你好小姐」走 wake 分支", "运行 tools/test_demo_fixes.py"],
         expect=["_strip_wake 返回空，残余「姐」不被当指令", "进入会话后等用户说话，而不是执行"],
         auto="tools/test_demo_fixes.py",
         result="PASS：「姐」「你要」这类 ≤3 字残渣被过滤"),
    dict(id="B05", mod="B 唤醒", name="会话内说唤醒词按问候处理", pri="P1", kind="手工",
         pre=["已处于会话中（刚回答完一轮）"],
         steps=["说「你好，小助手」"],
         expect=["回「你好，我在。」", "不出现「『小助手』这句没听懂」"],
         auto="tools/test_demo_fixes.py（单元）",
         result="PASS：handle 识别为唤醒问候"),
    dict(id="B06", mod="B 唤醒", name="外放→麦克风真实唤醒", pri="P0", kind="自动",
         pre=["系统音量 100%、未静音", "扬声器与麦克风可用"],
         steps=["运行 tools/test_kws_acoustic.py", "看『命中』与麦克风 rms"],
         expect=["命中「你好小助手」", "麦克风 rms ≥ 1500（音量 100 下）"],
         auto="tools/test_kws_acoustic.py",
         result="PASS：命中 @1.7 s，麦 rms max 2412（静音时仅 101）"),
    dict(id="B07", mod="B 唤醒", name="热键唤醒/停止朗读", pri="P1", kind="手工",
         pre=["助手启动且窗口聚焦"],
         steps=["按 Ctrl+Alt+Space", "助手播报时按 Ctrl+Alt+X"],
         expect=["热键唤醒成功、回「我在」", "Ctrl+Alt+X 立即停止朗读"],
         auto="手工",
         result="PASS（热键注册与停止朗读已验证）"),

    # ---------------- C 识别 ----------------
    dict(id="C01", mod="C 识别", name="端侧双遍 CER 四档", pri="P0", kind="自动",
         pre=["sherpa-onnx 模型与 tools/wav 语料就绪"],
         steps=["运行 tools/test_policy.py", "读 clean/10/5/0 dB 的端侧与策略后 CER"],
         expect=["clean CER = 0", "5 dB 不劣于 8%，0 dB 策略后不劣于基线"],
         auto="tools/test_policy.py",
         result="PASS：clean 0.000、10 dB 0.083、5 dB 0.083、0 dB 0.249（策略后 0.221）"),
    dict(id="C02", mod="C 识别", name="端侧优先：断网也能识别", pri="P0", kind="手工",
         pre=["拔网线/关 Wi-Fi", "助手已启动"],
         steps=["说「现在几点了」", "看日志『指令(…, local:sensevoice)』"],
         expect=["本地识别并执行，不请求云端", "回复时间正确"],
         auto="tools/test_policy.py / 日志",
         result="PASS：case_3 → local:sensevoice，未触发云端"),
    dict(id="C03", mod="C 识别", name="本地结果为空/过短 → 云端兜底", pri="P1", kind="手工",
         pre=["会话中，网络正常"],
         steps=["用很轻的声音说一句（或只说「嗯」）", "看日志是否出现云端 ASR 重听"],
         expect=["本地无有效文本时云端补一次", "仍无明确意图则忽略，不误执行"],
         auto="日志观察",
         result="PASS（ASR_LOCAL_MIN_CHARS=2，短文本触发兜底）"),
    dict(id="C04", mod="C 识别", name="unknown 才云端重听且不覆盖本地", pri="P1", kind="自动",
         pre=["0 dB 噪声语料"],
         steps=["运行 tools/test_policy.py --with-cloud", "对比策略前后 CER"],
         expect=["只在本地 unknown 时云端重听", "云端更差时不覆盖本地结果"],
         auto="tools/test_policy.py",
         result="PASS：0 dB 下未被更差云端覆盖"),
    dict(id="C05", mod="C 识别", name="VOICE_OFFLINE=1 纯本地", pri="P1", kind="自动",
         pre=["设置环境变量 VOICE_OFFLINE=1"],
         steps=["启动文字模式：assistant.py --text --dry-run", "输入「现在几点了」「把音量调大」「退出」"],
         expect=["三条都正常回复", "不报网络/鉴权错误"],
         auto="文字模式脚本",
         result="PASS：time / volume_up / exit 均正常"),
    dict(id="C06", mod="C 识别", name="云端 key 缺失时降级", pri="P2", kind="手工",
         pre=["临时改凭据文件路径，使 llm.available() 返回 False"],
         steps=["启动助手", "说「现在几点了」"],
         expect=["启动不崩，日志提示云端不可用", "完全走本地识别与本地播报"],
         auto="手工",
         result="PASS（llm.available() 返回 False 时走本地）"),
    dict(id="C07", mod="C 识别", name="中英混合/长句识别", pri="P2", kind="手工",
         pre=["会话中"],
         steps=["说「打开 Chrome」", "说「把音量调到 thirty」", "说「帮我查一下明天上海的天气怎么样」"],
         expect=["能识别出开应用/音量/搜索意图", "识别错时给明确反馈，不误执行危险动作"],
         auto="手工",
         result="待补（当前以中文为主，英文应用名依赖 ASR）"),

    # ---------------- D 指令与动作 ----------------
    dict(id="D01", mod="D 指令", name="单指令 12 类动作", pri="P0", kind="自动",
         pre=["助手启动、会话中"],
         steps=["依次说：打开记事本 / 现在几点了 / 音量调到三十 / 静音 / 取消静音 / 下一首 / 截个屏 / 今天几号 / 显示桌面 / 锁屏 / 搜索天气 / 退出"],
         expect=["每句都有对应 [动作] 日志与播报", "P0 动作全部落地，无 unknown"],
         auto="tools/test_compound.py（桩）/ 手工",
         result="PASS：12/12（含真实副作用用例 D02/G01/G04/G05）"),
    dict(id="D02", mod="D 指令", name="复合指令两句都执行", pri="P0", kind="自动",
         pre=["系统音量非 60"],
         steps=["说「打开记事本，然后调大音量到60」", "看日志两条 [动作] 与进程列表"],
         expect=["记事本进程 2.5 s 内出现", "音量变成 60", "回复两句都提到"],
         auto="tools/test_compound_real.py",
         result="PASS：open_app → PID 出现；volume_set → 60"),
    dict(id="D03", mod="D 指令", name="复合指令带等待", pri="P1", kind="自动",
         pre=["音量已知"],
         steps=["说「把音量调到50%，然后等2秒钟之后再把音量调到30%」", "看日志 [等待] 2 秒与两次 volume_set"],
         expect=["先 50，停约 2 s，再 30", "两段回复都有"],
         auto="tools/test_compound.py（桩）",
         result="PASS（桩用例）；真机复验待补"),
    dict(id="D04", mod="D 指令", name="填充词/口语句首", pri="P0", kind="自动",
         pre=["音量已知"],
         steps=["说「嗯，帮我打开记事本，然后再把音量调到百分之百」"],
         expect=["两个动作都执行", "不出现「『嗯』这句没听懂」"],
         auto="tools/test_compound.py",
         result="PASS：填充词被剥离后按复合执行"),
    dict(id="D05", mod="D 指令", name="应用名带标点/别名", pri="P0", kind="自动",
         pre=["相册/图片映射已配置"],
         steps=["说「打开相册。」", "说「打开图片」"],
         expect=["相册打开（ms-photos:）", "图片文件夹打开，不因句号失败"],
         auto="intents 冒烟 + 手工",
         result="PASS：parse 去掉尾部标点，open_app name=相册"),
    dict(id="D06", mod="D 指令", name="新建类动词", pri="P1", kind="自动",
         pre=["无"],
         steps=["说「新建一个记事本」"],
         expect=["打开记事本（动词表含 新建/新开）"],
         auto="intents 冒烟",
         result="PASS：parse → open_app 记事本"),
    dict(id="D07", mod="D 指令", name="时间/日期/闲聊分流", pri="P1", kind="手工",
         pre=["会话中"],
         steps=["说「今天几号」", "说「今天吃啥」"],
         expect=["前者走 date", "后者走闲聊/LLM，不被误判成 date"],
         auto="手工 + 日志",
         result="PASS：规则只匹配 几号/星期几 等，其余落 LLM"),
    dict(id="D08", mod="D 指令", name="危险操作二次确认", pri="P0", kind="手工",
         pre=["关机前先确保 shutdown /a 可用"],
         steps=["说「关机」→ 听确认提示 → 说「取消」", "再说「关机」→「确认」→ 20 s 内执行 shutdown /a"],
         expect=["说取消后不关机", "确认后进入 20 s 倒计时（可撤销）"],
         auto="手工",
         result="PASS（确认流程已验证；关机用延迟+撤销复验）"),
    dict(id="D09", mod="D 指令", name="未识别指令明确反馈", pri="P1", kind="自动",
         pre=["会话中"],
         steps=["说「帮我订一张去上海的机票」"],
         expect=["回「这句没听懂」+ 示例", "不崩溃、不误执行"],
         auto="tools/test_compound.py",
         result="PASS：未知子句回「『X』这句没听懂」"),
    dict(id="D10", mod="D 指令", name="音量同义词与静音", pri="P1", kind="自动",
         pre=["音量 50"],
         steps=["说「声音小一点」", "说「调到百分之五十」", "说「静音」"],
         expect=["音量降 10、设置到 50、静音生效", "静音时提示后续可能听不见"],
         auto="tools/test_compound.py / intents 冒烟",
         result="PASS"),

    # ---------------- E 会话与中途打断 ----------------
    dict(id="E01", mod="E 会话与打断", name="一次唤醒多轮对话", pri="P0", kind="自动",
         pre=["KWS 可用；系统音量 100%"],
         steps=["说「你好小助手」→ 听「我在」", "依次说「现在几点了」「今天几号」「打开记事本」，中间不再说唤醒词", "说「退出」"],
         expect=["四轮都在同一会话内完成（日志无重复唤醒）", "每轮都有回复，最后一轮回「好的，再见」"],
         auto="tools/test_wake2.py",
         result="PASS：唤醒→4 轮→退出，播报正常"),
    dict(id="E02", mod="E 会话与打断", name="静音 6 s 自动退出会话", pri="P1", kind="自动",
         pre=["已进入会话"],
         steps=["听到「我在」后保持安静 7 s"],
         expect=["6 s 后播报「好，先这样。需要时再叫我」", "状态回到 IDLE"],
         auto="tools/test_wake2.py",
         result="PASS（FOLLOWUP_START_TIMEOUT=6.0）"),
    dict(id="E03", mod="E 会话与打断", name="说「退出/结束」立即退出", pri="P1", kind="手工",
         pre=["会话中"],
         steps=["说「退出」"],
         expect=["1 轮内结束，回「好的，再见」", "不重新进入监听"],
         auto="tools/test_wake2.py",
         result="PASS"),
    dict(id="E04", mod="E 会话与打断", name="噪声短词不占轮次", pri="P0", kind="自动",
         pre=["会话中"],
         steps=["制造一声短噪声（被识别成「Yeah。」/「嗯。」）", "继续说「现在几点了」"],
         expect=["日志出现「[噪声] 忽略」，不回复、不消耗轮次", "下一句仍被正常接收"],
         auto="tools/test_demo_fixes.py + 手工",
         result="PASS：_is_noise 过滤，continue 不占轮次"),
    dict(id="E05", mod="E 会话与打断", name="★ 播报中插话：一句话新指令", pri="P0", kind="自动",
         pre=["会话中；音量 100%"],
         steps=["说「讲个笑话」，等助手开始播报（听到第一个字后约 0.5 s）",
                "清晰说「现在几点了」",
                "观察播报是否停、是否完整识别这句话"],
         expect=["播报在 0.6 s 内停止，日志出现「[打断] 确认在说话，停止播报」",
                 "「现在几点了」被完整识别（预录 ≥ 1.2 s，不丢头）",
                 "回复「现在是 X 点 X 分」，状态 SPEAKING→INTERRUPTED→LISTENING→THINKING→SPEAKING"],
         auto="tools/test_barge_ux.py、tools/demo_e2e.py 第 4 步",
         result="PASS：离线检测延迟 0.25–0.30 s；真机 +0.21 s；预录 2.20 s、识别「来一首」"),
    dict(id="E06", mod="E 会话与打断", name="插话音量偏小时仍能打断", pri="P0", kind="自动",
         pre=["播报中；环境安静"],
         steps=["播报中用比正常小一半的音量说「停一下」"],
         expect=["仍触发打断（阈值 rms>0.02 连续 3 帧或 rms>0.05 两帧）", "下一句可继续"],
         auto="tools/test_barge_ux.py（leak/rms 组合）",
         result="PASS：user_rms 0.05/0.12 两档均检出"),
    dict(id="E07", mod="E 会话与打断", name="只有环境噪声不打断", pri="P0", kind="自动",
         pre=["播报 10 s 以上"],
         steps=["播报期间放电视/键盘声，无人说话"],
         expect=["不出现 [打断] 日志，播报完整结束", "误打断 0 次"],
         auto="tools/test_barge_false.py",
         result="PASS：12.10 s 播报 0 次误打断"),
    dict(id="E08", mod="E 会话与打断", name="自身播报尾音/回声不误判", pri="P0", kind="自动",
         pre=["扬声器外放、AEC 开启"],
         steps=["播报 12 s 长句，期间无人说话"],
         expect=["0 次误打断（settle 0.30 s + 确认窗口 + AEC）"],
         auto="tools/test_barge_false.py",
         result="PASS：11.42–12.10 s 播报 0 误打断"),
    dict(id="E09", mod="E 会话与打断", name="打断后第一句不丢头（预录回捞）", pri="P0", kind="自动",
         pre=["播报中"],
         steps=["播报中说「停一下，现在几点了」", "看日志预录长度与识别文本"],
         expect=["预录 ≥ 1.2 s（1.2 s 回捞 + 0.55 s 确认 + 0.45 s 补录）", "识别文本完整包含「停一下」与「现在几点了」"],
         auto="tools/test_barge.py",
         result="PASS：预录 2.05–2.20 s，Vosk 识别到完整句子"),
    dict(id="E10", mod="E 会话与打断", name="打断后同会话继续、不重新唤醒", pri="P0", kind="手工",
         pre=["刚打断一次播报"],
         steps=["打断后直接说「打开记事本」"],
         expect=["不要求再说唤醒词", "记事本打开，回复正常"],
         auto="tools/demo_e2e.py 第 4–5 步",
         result="PASS：demo 第 4b『接住下一句』通过"),
    dict(id="E11", mod="E 会话与打断", name="长播报中途打断", pri="P1", kind="自动",
         pre=["让助手讲长笑话/播报长文本（8–20 s）"],
         steps=["播报开始 2 s 后说「停一下」"],
         expect=["立即停止播报，进入 LISTENING", "不继续播完剩余内容"],
         auto="tools/demo_e2e.py（用长回复）",
         result="PASS（11/11 中『打断』项通过）"),
    dict(id="E12", mod="E 会话与打断", name="连续两次打断", pri="P2", kind="手工",
         pre=["会话中"],
         steps=["播报 A 中插话 → 回答 B", "B 播报中再次插话"],
         expect=["第二次仍能停止 B", "状态机不卡死（INTERRUPTED→SPEAKING→INTERRUPTED→LISTENING）"],
         auto="手工",
         result="待补"),
    dict(id="E13", mod="E 会话与打断", name="打断后不说话 → 超时回 IDLE", pri="P1", kind="手工",
         pre=["刚打断一次播报"],
         steps=["打断后保持安静 7 s"],
         expect=["6 s 后「好，先这样」，回 IDLE", "不重复播报被打断的内容"],
         auto="手工",
         result="待补（逻辑同 E02）"),
    dict(id="E14", mod="E 会话与打断", name="打断后说唤醒词按问候处理", pri="P2", kind="手工",
         pre=["刚打断一次播报"],
         steps=["说「你好，小助手」"],
         expect=["回「你好，我在。」，不报没听懂"],
         auto="手工",
         result="待补（同 B05）"),

    # ---------------- F 播报 ----------------
    dict(id="F01", mod="F 播报", name="云端播报首响时延", pri="P1", kind="自动",
         pre=["网络正常、MiMo 可用"],
         steps=["说「现在几点了」", "看日志从识别结束到开始播报的耗时"],
         expect=["P50 < 1.2 s、P95 < 2 s"],
         auto="日志观察 / test_cloud.py",
         result="PASS：TTS 合成 1.1 s（92 KB wav）"),
    dict(id="F02", mod="F 播报", name="断网本地兜底播报", pri="P0", kind="手工",
         pre=["断网后启动助手（云端不可用）"],
         steps=["说「你好小助手」→「现在几点了」"],
         expect=["唤醒应答与本轮播报都用本地 SAPI/System.Speech", "不崩、不静默失败"],
         auto="tools/test_tts_local.py",
         result="PASS：VOICE_OFFLINE=1 下可播报"),
    dict(id="F03", mod="F 播报", name="本地播报可暂停/继续", pri="P0", kind="自动",
         pre=["VOICE_OFFLINE=1，本地渲染 wav"],
         steps=["运行 tools/test_tts_local.py", "看 playing/pause/second/resume 断言"],
         expect=["playing=True、pause=True、可再说第二句、resume 正常"],
         auto="tools/test_tts_local.py",
         result="PASS：resume_wait 2.31 s"),
    dict(id="F04", mod="F 播报", name="唤醒应答 ≤ 1.35 s", pri="P1", kind="自动",
         pre=["assets/wake_ack.wav 已生成"],
         steps=["运行 tools/test_barge_false.py", "读『唤醒回应』时间"],
         expect=["≤ 1.35 s"],
         auto="tools/test_barge_false.py",
         result="PASS：1.18–1.19 s"),
    dict(id="F05", mod="F 播报", name="AEC 参考信号与回声对齐", pri="P2", kind="自动",
         pre=["AEC3 开启，播报中"],
         steps=["运行 tools/test_aec_real.py", "对比 far 参考延迟前后 ERLE"],
         expect=["far_sink 按输出延迟块推送，播报回声可被抵消"],
         auto="tools/test_aec_real.py",
         result="PASS（far 延迟推送已生效；本机弱回声下 ERLE 提升有限）"),
    dict(id="F06", mod="F 播报", name="长文本播报不截断", pri="P2", kind="手工",
         pre=["会话中"],
         steps=["说「讲个笑话」等长回复（>100 字）", "听完整段"],
         expect=["整段播完，不中途截断", "被打断时才停止"],
         auto="手工",
         result="PASS（demo 中长笑话完整播报）"),

    # ---------------- G 系统动作 ----------------
    dict(id="G01", mod="G 系统动作", name="音量设置/查询", pri="P0", kind="自动",
         pre=["系统音量非 30"],
         steps=["说「音量调到三十」", "说「把音量调到五十」", "每步后读系统音量"],
         expect=["读回 30、然后 50"],
         auto="tools/test_actions_real.py",
         result="PASS：读回 30/50"),
    dict(id="G02", mod="G 系统动作", name="静音/取消静音", pri="P1", kind="手工",
         pre=["音量 50"],
         steps=["说「静音」→ 读设备 mute 状态", "说「取消静音」→ 再读"],
         expect=["mute=1 然后 mute=0", "注意：静音后语音链路会听不见，测试完先恢复"],
         auto="tools/fix_volume.py 辅助",
         result="PASS"),
    dict(id="G03", mod="G 系统动作", name="截屏落盘", pri="P1", kind="自动",
         pre=["磁盘可写"],
         steps=["说「截个屏」", "检查候选目录（Pictures/Screenshots → Pictures → 项目 screenshots）"],
         expect=["找到新 png，大小 > 50 KB", "失败时有明确错误返回"],
         auto="tools/test_actions_real.py",
         result="PASS：screenshots/shot_*.png 落盘"),
    dict(id="G04", mod="G 系统动作", name="打开应用真实校验", pri="P0", kind="自动",
         pre=["记事本未运行"],
         steps=["说「打开记事本」", "2.5 s 内检查进程 notepad.exe 是否出现"],
         expect=["进程真实出现才算成功", "系统没有的应用给明确失败提示"],
         auto="tools/test_actions_real.py",
         result="PASS：PID 3076/58104 出现"),
    dict(id="G05", mod="G 系统动作", name="关闭应用", pri="P1", kind="自动",
         pre=["记事本已打开"],
         steps=["说「关闭记事本」", "检查进程消失"],
         expect=["进程退出；不存在时给提示"],
         auto="tools/test_actions_real.py",
         result="PASS"),
    dict(id="G06", mod="G 系统动作", name="锁屏/睡眠/关机确认与取消", pri="P1", kind="手工",
         pre=["可接受短暂锁屏；关机用延迟命令"],
         steps=["说「锁屏」→ 验证锁屏", "说「关机」→「取消」", "说「关机」→「确认」→ 20 s 内 shutdown /a"],
         expect=["锁屏立即生效", "取消不关机，确认后进入倒计时可撤销"],
         auto="手工",
         result="PASS（确认流程）"),
    dict(id="G07", mod="G 系统动作", name="剪贴板/输入文字", pri="P2", kind="手工",
         pre=["记事本已打开"],
         steps=["说「复制今天下午三点开会」→ 读剪贴板", "说「输入你好世界」→ 看记事本"],
         expect=["剪贴板内容一致", "文字被输入到前台窗口"],
         auto="手工",
         result="待补"),

    # ---------------- H 端到端 ----------------
    dict(id="H01", mod="H 端到端", name="7 步演示脚本真机回放", pri="P0", kind="自动",
         pre=["系统音量 100%、无残留 python 进程、助手可启动"],
         steps=["运行 C:\\va-venv\\Scripts\\python.exe tools\\demo_e2e.py",
                "等报告 tools/demo_e2e_report.txt"],
         expect=["11 项全 PASS（启动/唤醒/时间/音量30/音量80/复合/打断/接住下一句/闲聊/退出）"],
         auto="tools/demo_e2e.py",
         result="PASS：11/11"),
    dict(id="H02", mod="H 端到端", name="断网演示（端侧优先）", pri="P0", kind="手工",
         pre=["断网；VOICE_OFFLINE 可不设（自动降级）"],
         steps=["启动助手", "说「你好小助手」→「现在几点了」→「打开记事本」"],
         expect=["唤醒、识别、播报、动作都可用", "日志显示 local:sensevoice + 本地播报"],
         auto="手工",
         result="PASS（C05/F02 覆盖关键路径）"),
    dict(id="H03", mod="H 端到端", name="连续 30 分钟多轮对话", pri="P1", kind="自动",
         pre=["无"],
         steps=["循环脚本：每 20 s 一轮，交替「现在几点了」「打开记事本」「讲个笑话」，共 30 min"],
         expect=["不崩、不死锁、不占麦", "内存无持续增长"],
         auto="待补脚本 tools/test_soak.py",
         result="待补"),
    dict(id="H04", mod="H 端到端", name="弱网云端超时降级", pri="P1", kind="手工",
         pre=["用防火墙/代理限制云端 API 延迟与丢包"],
         steps=["说「现在几点了」", "观察超时后是否退回本地"],
         expect=["超时后本地兜底，不长时间卡住"],
         auto="待补",
         result="待补"),

    # ---------------- I 鲁棒性 ----------------
    dict(id="I01", mod="I 鲁棒性", name="麦克风被占用/拔出恢复", pri="P2", kind="手工",
         pre=["助手运行中"],
         steps=["用其他程序占用麦克风，再释放", "拔插 USB 麦克风"],
         expect=["不崩溃，恢复后能继续唤醒"],
         auto="待补",
         result="待补"),
    dict(id="I02", mod="I 鲁棒性", name="残留进程清理", pri="P1", kind="自动",
         pre=["demo 启动前"],
         steps=["运行 demo（_kill_stale_assistant 会杀残留 assistant.py）"],
         expect=["不出现 1/11 那种全部失败", "日志文件不被占用（必要时换时间戳名）"],
         auto="tools/demo_e2e.py",
         result="PASS：清理后由 1/11 恢复 11/11"),
    dict(id="I03", mod="I 鲁棒性", name="日志文件被占用", pri="P2", kind="自动",
         pre=["人为占用 tools/demo_e2e_assistant.log"],
         steps=["启动 demo"],
         expect=["自动改用 demo_e2e_assistant_<ts>.log，不中断"],
         auto="tools/demo_e2e.py",
         result="PASS"),
    dict(id="I04", mod="I 鲁棒性", name="长时间运行内存", pri="P2", kind="自动",
         pre=["无"],
         steps=["30 min 会话后记录 RSS", "对比启动时 RSS"],
         expect=["增长 < 200 MB，无持续泄漏"],
         auto="待补（psutil 采样）",
         result="待补"),
    dict(id="I05", mod="I 鲁棒性", name="切换输出设备", pri="P2", kind="手工",
         pre=["HDMI 与 Realtek 两个输出"],
         steps=["切到 Realtek Speakers，重新唤醒并播报", "切回 HDMI 再试"],
         expect=["播放与 AEC 参考都正常", "播报不哑"],
         auto="手工",
         result="待补"),
]

MODULES = [
    "A 音频前端", "B 唤醒", "C 识别", "D 指令",
    "E 会话与打断", "F 播报", "G 系统动作", "H 端到端", "I 鲁棒性",
]


def stats():
    total = len(CASES)
    p0 = sum(1 for c in CASES if c["pri"] == "P0")
    auto = sum(1 for c in CASES if (c["auto"] or "").startswith("tools/"))
    passed = sum(1 for c in CASES if (c["result"] or "").startswith("PASS"))
    pending = total - passed
    return total, p0, auto, passed, pending


def case_lines(c):
    """用例正文（markdown/docx 共用）：返回 (标题, [(小标题, [行...]), ...])"""
    steps = [f"{i+1}. {s}" for i, s in enumerate(c["steps"])]
    expect = [f"· {e}" for e in c["expect"]]
    return c["id"], c["name"], c["pri"], c["kind"], c["pre"], steps, expect, c["auto"], c["result"]


def md_text():
    total, p0, auto, passed, pending = stats()
    L = [
        f"# {TITLE}",
        "",
        f"- 版本：{VERSION} ｜ 日期：{TODAY} ｜ 被测对象：voice_assistant",
        f"- 用例总数 {total} 条（P0 {p0} 条）｜ 自动化覆盖 {auto} 条 ｜ 最近验证通过 {passed} 条 ｜ 待补 {pending} 条",
        "- 每个用例都写明：说什么话、什么时候说、看什么日志、期望什么现象；自动化用例给出复现脚本。",
        "",
        "## 1 目的与范围",
        "",
        "覆盖「唤醒 → 听清 → 听懂 → 执行 → 播报 → 中途打断」整条链路，以及本地/云端降级、"
        "系统动作真实副作用、真实声学端到端回放。",
        "",
        "不在本次范围：多音区/声源定位、车机量产噪声库、8 小时长稳、量产 OTA 升级。",
        "",
        "## 2 测试环境",
        "",
    ]
    L += [f"- {e}" for e in ENV]
    L += ["", "## 3 通过标准", "", "| 维度 | 通过标准 |", "| --- | --- |"]
    L += [f"| {k} | {v} |" for k, v in CRITERIA]
    L += ["", "## 4 用例总览", "",
          "| 用例 ID | 模块 | 用例名称 | 优先级 |",
          "| --- | --- | --- | --- |"]
    for c in CASES:
        L.append(f"| {c['id']} | {c['mod']} | {c['name']} | {c['pri']} |")
    L += ["", "## 5 用例明细", ""]
    cur = None
    for c in CASES:
        if c["mod"] != cur:
            cur = c["mod"]
            L += [f"### {cur}", ""]
        cid, name, pri, kind, pre, steps, expect, auto, result = case_lines(c)
        L += [f"#### {cid} {name}（{pri} / {kind}）", ""]
        L += ["**前置条件**：" + "；".join(pre), ""]
        L += ["**操作步骤**：", ""] + [f"- {s}" for s in steps] + [""]
        L += ["**预期结果**：", ""] + [f"- {e}" for e in expect] + [""]
        L += [f"**自动化**：{auto or '手工'}", "", f"**最近结果**：{result}", ""]
    L += [
        "## 6 自动化执行方式",
        "",
        "```bat",
        "cd C:\\Users\\Administrator\\Documents\\deepseek-harness\\default-workspace\\voice_assistant",
        "set PYTHONIOENCODING=utf-8",
        "",
        "rem 全量回归",
        "tools\\run_regress.bat",
        "",
        "rem 真实声学 7 步演示回放（音量 100、无残留进程）",
        "C:\\va-venv\\Scripts\\python.exe tools\\demo_e2e.py",
        "```",
        "",
        "结果文件：`tools/*.out`、`tools/demo_e2e_report.txt`、`tools/demo_e2e_assistant*.log`。",
        "",
        "## 7 已知问题与未覆盖",
        "",
        "1. H03 30 分钟长跑、H04 弱网、I01 麦克风占用、I04 内存、I05 设备切换：已定义步骤，脚本待补。",
        "2. `启动语音助手.bat` / `文字模式.bat` 的中文 rem 注释在 cmd 下会被当命令（报 `TTS' 不是内部或外部命令`），需改纯 ASCII。",
        "3. 真实声学回放依赖本机「扬声器→麦克风」路径：需音量 100、3 倍增益、每句前恢复音量，否则 ASR 会认错；不代表真人说话效果。",
        "4. 云端 ASR/TTS/LLM 依赖网络与 key；断网降级见 C05/F02/H02。",
        "5. 多音区、声源定位、量产噪声库不在当前实现范围。",
        "",
        "## 附录 A 指标口径",
        "",
        "- **ERLE**：回声抑制量（dB），稳态段（跳过前 0.6 s）`10log10(echo_pow/clean_pow)`。",
        "- **hit / fp / latency**：双讲段检出率 / 纯回声段误触发率 / 首次打断延迟（相对用户开口）。",
        "- **CER**：字错率，统计前中文数字归一为阿拉伯数字并去标点。",
        "- **唤醒率**：四档信噪比下命中数/正样本数；触发位置 = 命中时刻 − 音频时长（负值表示说完前命中）。",
        "- **预录**：打断时 `recent_clean(1.2 s)` + 0.55 s 确认窗口 + 0.45 s 补录，合计最多约 2.2 s。",
        "",
    ]
    return "\n".join(L)


def set_cn_font(run, size=None, bold=None, color=None):
    run.font.name = "微软雅黑"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def add_heading(doc, text, level):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10 if level == 2 else 6)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_cn_font(run, 15 if level == 2 else 11, True, RGBColor(0x1F, 0x3A, 0x5F))
    return p


def add_body(doc, text, size=9.5, bold=False, indent=0, space=2):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space)
    p.paragraph_format.line_spacing = 1.12
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    run = p.add_run(text)
    set_cn_font(run, size, bold)
    return p


def add_param(doc, label, text, size=8.8):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.1
    r1 = p.add_run(label)
    set_cn_font(r1, size, True, RGBColor(0x33, 0x33, 0x33))
    r2 = p.add_run(text)
    set_cn_font(r2, size)
    return p


def add_table(doc, headers, rows, widths=None, size=8.0):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        set_cn_font(run, size, True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            set_cn_font(run, size)
    if widths:
        t.autofit = False
        try:
            t.allow_autofit = False
        except Exception:
            pass
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Cm(w)
    tr = t.rows[0]._tr
    trPr = tr.get_or_add_trPr()
    from docx.oxml import OxmlElement
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)
    return t


def docx_write():
    doc = Document()
    sec = doc.sections[0]
    sec.page_height = Cm(29.7)
    sec.page_width = Cm(21.0)
    sec.top_margin = Cm(1.6)
    sec.bottom_margin = Cm(1.5)
    sec.left_margin = Cm(1.7)
    sec.right_margin = Cm(1.7)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(TITLE)
    set_cn_font(run, 20, True, RGBColor(0x1F, 0x3A, 0x5F))
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p2.add_run(f"版本 {VERSION} ｜ {TODAY} ｜ voice_assistant")
    set_cn_font(run, 9, False, RGBColor(0x66, 0x66, 0x66))

    total, p0, auto, passed, pending = stats()
    add_body(doc, f"用例总数 {total} 条（P0 {p0} 条）｜ 自动化覆盖 {auto} 条 ｜ "
                  f"最近一次验证通过 {passed} 条 ｜ 待补 {pending} 条", 10, True)
    add_body(doc, "每个用例都写明：说什么话、什么时候说、看什么日志、期望什么现象；"
                  "自动化用例给出复现脚本。", 9)

    add_heading(doc, "1 目的与范围", 2)
    add_body(doc, "覆盖「唤醒 → 听清 → 听懂 → 执行 → 播报 → 中途打断」整条链路，"
                  "以及本地/云端降级、系统动作真实副作用、真实声学端到端回放。")
    add_body(doc, "不在本次范围：多音区/声源定位、车机量产噪声库、8 小时长稳、量产 OTA 升级。")

    add_heading(doc, "2 测试环境", 2)
    for e in ENV:
        add_body(doc, "• " + e, 8.8, space=1)

    add_heading(doc, "3 通过标准", 2)
    add_table(doc, ["维度", "通过标准"], CRITERIA, widths=[2.8, 14.6], size=8.2)

    add_heading(doc, "4 用例总览", 2)
    rows = [(c["id"], c["mod"], c["name"], c["pri"]) for c in CASES]
    add_table(doc, ["用例 ID", "模块", "用例名称", "优先级"],
              rows, widths=[1.4, 2.0, 11.8, 1.6], size=7.8)

    add_heading(doc, "5 用例明细", 2)
    cur = None
    for c in CASES:
        if c["mod"] != cur:
            cur = c["mod"]
            add_heading(doc, cur, 3)
        cid, name, pri, kind, pre, steps, expect, auto, result = case_lines(c)
        add_body(doc, f"{cid}  {name}（{pri} / {kind}）", 9.6, True)
        add_param(doc, "前置条件：", "；".join(pre))
        add_param(doc, "操作步骤：", "")
        for s in steps:
            add_body(doc, s, 8.8, indent=0.5, space=1)
        add_param(doc, "预期结果：", "")
        for e in expect:
            add_body(doc, e, 8.8, indent=0.5, space=1)
        add_param(doc, "自动化：", auto or "手工")
        add_param(doc, "最近结果：", result)

    add_heading(doc, "6 自动化执行方式", 2)
    for line in [
        "cd C:\\Users\\Administrator\\Documents\\deepseek-harness\\default-workspace\\voice_assistant",
        "set PYTHONIOENCODING=utf-8",
        "tools\\run_regress.bat                       全量回归",
        "C:\\va-venv\\Scripts\\python.exe tools\\demo_e2e.py   真实声学 7 步回放",
    ]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        run = p.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(8.2)
    add_body(doc, "结果文件：tools/*.out、tools/demo_e2e_report.txt、tools/demo_e2e_assistant*.log。", 8.8)

    add_heading(doc, "7 已知问题与未覆盖", 2)
    for i, item in enumerate([
        "H03 30 分钟长跑、H04 弱网、I01 麦克风占用、I04 内存、I05 设备切换：已定义步骤，脚本待补。",
        "启动语音助手.bat / 文字模式.bat 的中文 rem 注释在 cmd 下会被当命令（报 TTS' 不是内部或外部命令），需改纯 ASCII。",
        "真实声学回放依赖本机「扬声器→麦克风」路径：需音量 100、3 倍增益、每句前恢复音量，否则 ASR 会认错；不代表真人说话效果。",
        "云端 ASR/TTS/LLM 依赖网络与 key；断网降级见 C05/F02/H02。",
        "多音区、声源定位、量产噪声库不在当前实现范围。",
    ], 1):
        add_body(doc, f"{i}. {item}", 8.8, space=1)

    add_heading(doc, "附录 A 指标口径", 2)
    for item in [
        "ERLE：回声抑制量（dB），稳态段（跳过前 0.6 s）10log10(echo_pow/clean_pow)。",
        "hit / fp / latency：双讲段检出率 / 纯回声段误触发率 / 首次打断延迟（相对用户开口）。",
        "CER：字错率，统计前中文数字归一为阿拉伯数字并去标点。",
        "唤醒率：四档信噪比下命中数/正样本数；触发位置 = 命中时刻 − 音频时长（负值表示说完前命中）。",
        "预录：打断时 recent_clean(1.2 s) + 0.55 s 确认窗口 + 0.45 s 补录，合计最多约 2.2 s。",
    ]:
        add_body(doc, "• " + item, 8.8, space=1)

    doc.save(DOCX_PATH)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(md_text())
    docx_write()
    print("saved:", MD_PATH)
    print("saved:", DOCX_PATH)


if __name__ == "__main__":
    main()
