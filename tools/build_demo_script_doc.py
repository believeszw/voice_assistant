# -*- coding: utf-8 -*-
"""生成《语音助手演示脚本（测试用例版）》：输出 Markdown + Word（docx）。

主体是「顺序 / 你说 / 展示点 / 通过标准」的演示脚本表，
再对每一步给出可照着做的验收细则（前置、操作、看什么日志、通过标准）。

用法：python tools/build_demo_script_doc.py
产物：docs/语音助手_演示脚本.md / .docx
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
MD_PATH = os.path.join(OUT_DIR, "语音助手_演示脚本.md")
DOCX_PATH = os.path.join(OUT_DIR, "语音助手_演示脚本.docx")

TITLE = "语音助手演示脚本（测试用例版）"
VERSION = "v1.0"
TODAY = date.today().strftime("%Y-%m-%d")

PREP = [
    "启动：双击 voice_assistant\\启动语音助手.bat（或 C:\\va-venv\\Scripts\\python.exe assistant.py --no-hotkey）",
    "先杀残留进程：powershell \"Get-Process python | Stop-Process -Force\"（否则麦克风被占，表现为唤不醒）",
    "音量 100%、不要静音：C:\\va-venv\\Scripts\\python.exe tools\\fix_volume.py（或手动调系统音量）",
    "确认日志首行出现「[唤醒] KWS 本地模型: 可用」「[识别] 云端 MiMo 主力；本地双遍: 可用」",
    "演示环境安静、离麦克风 30–50 cm；等「我在」播完再说话（唤醒应答约 1 s 内不监听插话）",
]

# 演示脚本主表：(顺序, 你说, 展示点, 通过标准)
DEMO = [
    ("1", "「你好小助手」→「现在几点了」",
     "本地 KWS 唤醒 + 端侧识别 + 秒回",
     "唤醒应答 ≤1.35 s；识别日志 local:sensevoice；回复时间与系统时间一致；不联网也能跑"),
    ("2", "接着说「把音量调到三十」→「静音」",
     "一次唤醒多轮，不用重复说唤醒词",
     "后续指令不再要求唤醒词（最多 6 轮）；日志 [动作] volume_set 30；静音生效（演示完记得恢复音量）"),
    ("3", "「打开记事本，然后调大音量」",
     "一句话多指令、按序执行、合并汇报",
     "记事本 2.5 s 内真实打开（进程校验）；音量上调；回复两件事合并成一句；日志 [动作] 两条"),
    ("4", "问「讲个笑话」，念到一半插话「停一下，现在几点了」",
     "打断 + 防误打断确认 + 接住被打断的话",
     "0.6 s 内停播；日志「[打断] 确认在说话，停止播报」；预录 ≥1.2 s，整句完整识别；回复时间；不重新唤醒"),
    ("5", "断网或 VOICE_OFFLINE=1 跑文字模式",
     "端侧优先：KWS/识别/规则都在本地，云端只兜底",
     "唤醒、识别、指令全部本地完成；文字模式 time/volume_up/exit 正常；不报云端错误"),
    ("6", "「关机」→ 二次确认 → 说「取消」",
     "危险操作白名单 + 二次确认",
     "先询问确认；说「取消」后不关机；说「确认」才进入 20 s 倒计时（可用 shutdown /a 撤销）"),
    ("7", "「讲个笑话」「今天天气怎么样」",
     "云端 LLM 闲聊（车机式问答）",
     "回复自然、1–2 句；云端不可用时降级为本地，不崩溃、不静默"),
]

# 每一步的验收细则：(序号, 标题, 前置[], 操作[], 期望[], 证据/自动化)
DETAIL = [
    ("1", "唤醒 + 时间（本地 KWS + 端侧识别）",
     ["助手已启动，音量 100%，日志显示 KWS/双遍可用"],
     ["说「你好小助手」", "听到「我在」后说「现在几点了」"],
     ["唤醒 1.0–1.4 s 内应答；时间回复正确",
      "日志出现「唤醒词命中」「指令(…, local:sensevoice)」「[动作] time」"],
     "tools/test_wake2.py；tools/demo_e2e.py 第 0–2 步"),
    ("2", "一次唤醒多轮",
     ["已完成第 1 步，仍在会话中（未回 IDLE）"],
     ["直接说「把音量调到三十」", "直接说「静音」"],
     ["不再要求唤醒词；音量读回 30；静音后提示后续可能听不见",
      "日志两条 [动作]，无「[唤醒]」重复行"],
     "tools/test_wake2.py（多轮）；tools/test_actions_real.py（音量读回）"),
    ("3", "一句话多指令",
     ["系统音量非 60；记事本未运行"],
     ["说「打开记事本，然后调大音量到60」", "2.5 s 后看任务管理器 / 进程列表"],
     ["notepad.exe 进程出现；音量变成 60；回复「已打开 记事本；音量已调到 60%」",
      "日志「理解(复合)」两条 + 「[动作]」两条"],
     "tools/test_compound_real.py；tools/demo_e2e.py 第 3 步"),
    ("4", "中途打断（重点）",
     ["会话中；音量 100%；环境安静"],
     ["说「讲个笑话」，听到播报第一个字后约 0.5 s", "清晰说「停一下，现在几点了」", "说完保持安静，听下一句回复"],
     ["播报 0.6 s 内停止；日志「[打断] 确认在说话，停止播报（rms=… ratio=…）」",
      "预录 ≥1.2 s（1.2 s 回捞 + 0.55 s 确认 + 0.45 s 补录），「停一下，现在几点了」完整识别",
      "回复「现在是 X 点 X 分」，不重新唤醒；状态 SPEAKING→INTERRUPTED→LISTENING→THINKING→SPEAKING"],
     "tools/test_barge.py（假麦/预录）；tools/test_barge_ux.py（合成场景）；tools/demo_e2e.py 第 4 步"),
    ("5", "端侧优先 / 断网可用",
     ["断网，或设 VOICE_OFFLINE=1"],
     ["重新启动助手", "说「你好小助手」→「现在几点了」→「打开记事本」"],
     ["启动日志提示云端不可用（或离线模式）；唤醒/识别/动作正常",
      "播报走本地 SAPI/System.Speech；无网络报错弹窗"],
     "tools/test_tts_local.py；文字模式脚本；C05/F02 用例"),
    ("6", "危险操作二次确认",
     ["先在终端确认 shutdown /a 可用"],
     ["说「关机」→ 听确认提示 → 说「取消」", "再说「关机」→「确认」→ 20 s 内执行 shutdown /a"],
     ["说「取消」后不关机；说「确认」后进入倒计时，可用 shutdown /a 撤销",
      "日志出现确认分支与取消/执行结果"],
     "手工；危险动作白名单在 config.DANGEROUS"),
    ("7", "云端 LLM 闲聊",
     ["网络正常、MiMo key 可用"],
     ["说「讲个笑话」", "说「今天天气怎么样」"],
     ["回复自然、口语化、1–2 句；不输出 Markdown/工具调用语法",
      "日志走 LLM 路径（理解→chat）或云端重听"],
     "tools/demo_e2e.py 第 5–6 步；手工"),
]

# 打断专项子用例：(编号, 场景, 操作, 通过标准, 结果)
BARGE = [
    ("B1", "播报中插一句话新指令", "播「讲个笑话」0.5 s 后说「现在几点了」",
     "0.6 s 内停播；下一句完整识别；回时间；不重新唤醒", "PASS（真机 +0.21 s，预录 2.20 s）"),
    ("B2", "插话音量偏小", "播报中用约一半音量说「停一下」",
     "仍触发打断（rms>0.02 连续 3 帧或 rms>0.05 两帧）", "PASS（user_rms 0.05/0.12 两档）"),
    ("B3", "只有环境噪声", "播 10 s 以上，期间放电视/键盘声、无人说话",
     "0 次打断，播报完整结束", "PASS（12.10 s 播报 0 误打断）"),
    ("B4", "自身播报尾音/回声", "播报 12 s 长句，无人说话",
     "0 次误打断（settle 0.30 s + 确认 + AEC）", "PASS（11.42–12.10 s 0 误打断）"),
    ("B5", "打断后第一句不丢头", "播报中说「停一下，现在几点了」",
     "预录 ≥1.2 s；整句完整识别；回复时间", "PASS（预录 2.05–2.20 s）"),
    ("B6", "长播报中途打断", "长笑话播到 2 s 时说「停一下」",
     "立即停；不播完剩余；进入 LISTENING", "PASS（demo 11/11）"),
    ("B7", "连续两次打断", "播报 A 中插话→回答 B→B 播报中再插话",
     "第二次仍能停；状态机不卡死", "待补（手工）"),
    ("B8", "打断后不说话", "打断后静音 7 s",
     "6 s 后「好，先这样」，回 IDLE", "待补（手工）"),
]

BACKUP = [
    ("打断没触发", "离麦克风近一点（30 cm）、提高音量重说；看日志是否有「[打断]」行；确认系统音量 100% 未静音"),
    ("唤醒没反应", "先 kill 残留 python；确认日志「KWS 可用」；说慢一点、等「我在」播完再说"),
    ("识别成别的句子", "本机外放回放会失真（扬声器→麦弱），改用真人对着麦克风说；或看日志是否 local:sensevoice 与云端重听"),
    ("云端挂了", "切 VOICE_OFFLINE=1 跑第 5 步；本地双遍 + SAPI 可完整走完 1/2/3/6 步"),
    ("演示中途静音了听不见", "说「取消静音」或跑 tools/fix_volume.py 恢复音量"),
]

LIMITS = [
    "第 4 步打断是「语音活动 + 能量确认」两段式：真人插话 0.6 s 内停；连续两次打断（B7）尚未自动化。",
    "第 5 步断网：KWS/端侧双遍/Vosk/SAPI 均本地；LLM 闲聊依赖云端，断网时闲聊降级为固定回复。",
    "第 6 步关机测试会真关机：务必用 20 s 延迟 + shutdown /a，或改在虚拟机验证。",
    "演示回放脚本（demo_e2e.py）用扬声器播合成语音，本机扬声器→麦克风路径弱，需音量 100 + 3 倍增益；真人演示不受此限。",
]


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


def add_body(doc, text, size=9.2, bold=False, indent=0, space=2):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space)
    p.paragraph_format.line_spacing = 1.15
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    run = p.add_run(text)
    set_cn_font(run, size, bold)
    return p


def add_label(doc, label, text, size=9.0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.12
    r1 = p.add_run(label)
    set_cn_font(r1, size, True, RGBColor(0x33, 0x33, 0x33))
    r2 = p.add_run(text)
    set_cn_font(r2, size)
    return p


def add_table(doc, headers, rows, widths=None, size=8.2):
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


def md_text():
    L = [
        f"# {TITLE}",
        "",
        f"- 版本：{VERSION} ｜ 日期：{TODAY} ｜ 被测对象：本地语音助手（KWS 唤醒 + 端侧双遍 ASR + 云端 MiMo + TTS + 电脑控制）",
        "- 用法：按「演示脚本」表从上到下说；每一步的判据见「逐步验收细则」；打断专项见第 4 节。",
        "",
        "## 0 演示前准备",
        "",
    ]
    L += [f"- {p}" for p in PREP]
    L += ["", "## 1 演示脚本（按这个顺序说）", "",
          "| 顺序 | 你说 | 展示点 | 通过标准 |", "| --- | --- | --- | --- |"]
    L += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in DEMO]
    L += ["", "## 2 逐步验收细则", ""]
    for no, title, pre, steps, expect, evidence in DETAIL:
        L += [f"### 第 {no} 步 {title}", ""]
        L += ["**前置条件**：" + "；".join(pre), ""]
        L += ["**操作**："]
        L += [f"- {s}" for s in steps]
        L += ["", "**通过标准**："]
        L += [f"- {e}" for e in expect]
        L += ["", f"**证据/自动化**：{evidence}", ""]
    L += ["## 3 打断专项（第 4 步展开）", "",
          "| 编号 | 场景 | 操作 | 通过标准 | 最近结果 |", "| --- | --- | --- | --- | --- |"]
    L += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in BARGE]
    L += ["", "## 4 演示翻车时的备用路径", ""]
    L += [f"- **{k}**：{v}" for k, v in BACKUP]
    L += ["", "## 5 已知限制", ""]
    L += [f"- {x}" for x in LIMITS]
    L += [
        "",
        "## 6 详细用例",
        "",
        "完整 68 条测试用例（含音频前端、唤醒、识别、指令、播报、系统动作、端到端、鲁棒性）见 `docs/语音助手_测试用例.md`。",
        "",
    ]
    return "\n".join(L)


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
    add_body(doc, "用法：按「演示脚本」表从上到下说；每一步判据见「逐步验收细则」；"
                  "第 4 步打断展开见「打断专项」。", 9)

    add_heading(doc, "0 演示前准备", 2)
    for item in PREP:
        add_body(doc, "• " + item, 8.8, space=1)

    add_heading(doc, "1 演示脚本（按这个顺序说）", 2)
    add_table(doc, ["顺序", "你说", "展示点", "通过标准"], DEMO,
              widths=[1.0, 4.4, 4.2, 7.8], size=8.0)

    add_heading(doc, "2 逐步验收细则", 2)
    for no, title, pre, steps, expect, evidence in DETAIL:
        add_body(doc, f"第 {no} 步  {title}", 9.8, True)
        add_label(doc, "前置条件：", "；".join(pre))
        add_label(doc, "操作：", "")
        for s in steps:
            add_body(doc, "· " + s, 8.8, indent=0.4, space=1)
        add_label(doc, "通过标准：", "")
        for e in expect:
            add_body(doc, "· " + e, 8.8, indent=0.4, space=1)
        add_label(doc, "证据/自动化：", evidence)

    add_heading(doc, "3 打断专项（第 4 步展开）", 2)
    add_table(doc, ["编号", "场景", "操作", "通过标准", "最近结果"], BARGE,
              widths=[1.0, 3.0, 4.4, 5.2, 3.8], size=7.6)

    add_heading(doc, "4 演示翻车时的备用路径", 2)
    for k, v in BACKUP:
        add_label(doc, f"{k}：", v)
    add_heading(doc, "5 已知限制", 2)
    for x in LIMITS:
        add_body(doc, "• " + x, 8.8, space=1)
    add_heading(doc, "6 详细用例", 2)
    add_body(doc, "完整 68 条测试用例（音频前端、唤醒、识别、指令、播报、系统动作、端到端、鲁棒性）"
                  "见 docs/语音助手_测试用例.md。", 8.8)

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
