# 贡献指南

欢迎提 issue / PR。这个项目是 Windows 上的本地语音助手，改动前请先看下面几条约定。

## 开发环境

```bat
:: 1. 运行依赖（Windows 专用 wheel：pywin32/pycaw/vosk/sherpa-onnx 等）
python -m pip install -r requirements.txt

:: 2. 开发依赖（pytest/ruff）
python -m pip install -r requirements-dev.txt
```

建议使用短路径 venv（例如 `C:\va-venv`）：SAPI / System.Speech 在解释器路径过长时
会出现「系统上未安装语音」之类的异常。

## 本地检查

```bat
python -m ruff check .
python -m pytest -m "not audio"      :: 纯逻辑用例，不需要声卡
python -m pytest                      :: Windows 有音频依赖时跑全量（含 audio 标记）
tools\run_regress.bat                 :: 本机声学/端到端回归
```

CI 只跑 `ruff check` + `pytest -m "not audio"`，所以**改动核心逻辑时请补一个不依赖
声卡的用例**；涉及音频路径的改动请在 PR 里贴 `tools/run_regress.bat` 的输出。

## 代码约定

- 只依赖标准库 + `requirements.txt` 里的包；新增依赖要写进 `requirements.txt` 并说明用途。
- 面向用户的回复用中文、口语化；日志用 `self.log()` / `logging`，不要随手 `print`。
- 捕获异常要写清楚是有意兜底（注释）还是必须 debug 记录；不要静默 `except Exception: pass`。
- 不在代码里写死个人路径 / 密钥；凭据走环境变量或 `~/.dsh/.credentials.yaml`。

## 指令解析（`intents.py`）

`intents.py` 是规则表驱动：`RULES` 按顺序尝试，**第一条命中的规则生效**。
所以：

1. 新增说法时，把规则插到正确的优先级位置（例如系统控制类要排在「打开/关闭」之前）；
2. 在 `tests/test_intents.py` 的 `CASES` 里补一条 `(说法, 期望 intent)`；
3. 跑 `pytest -m "not audio"`，`test_parse_golden` 全绿才算没破坏旧说法。

`tests/test_intents.py` 里的 golden 用例由重构前的实现生成，用来保证「规则表化」
重构零行为变化；新增用例时先确认 `parse()` 输出符合你的预期，再写进期望值。

## 提交 PR

- 一个 PR 只做一件事；重构与行为变更分开提交。
- 提交信息用 `<type>: <中文摘要>`，例如 `refactor: intents 改为规则表驱动`。
- 更新 README / docs 里受影响的部分。
