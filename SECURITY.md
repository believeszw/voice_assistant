# 安全策略

## 报告的漏洞

如果你发现了安全问题，请不要公开提 issue，直接发邮件到
**765846560@qq.com**，标题带上 `[voice_assistant security]`。

我会在 7 天内确认，并在修复后于 README 的更新记录里致谢（如果你愿意具名）。

## 需要关注的风险面

这个项目会调用系统能力（启动应用、调音量、截屏、关机等），以下面是主要风险点：

1. **指令注入**：ASR 文本会进入 `intents.parse`，最终可能落到
   `cmd /c start`、`taskkill`、`explorer` 等系统命令。`actions.py`
   只对白名单内的应用/文件夹做启动，未知应用名会先过 `_SAFE_TARGET` 正则；
   发现绕过方式请直接报告。
2. **危险动作**：`shutdown/restart/sleep/close_app/lock` 在 `config.DANGEROUS`
   里，执行前要二次确认；`--dry-run` 可以用来演示而不真正执行。
3. **凭据**：云服务 key 只从环境变量或 `~/.dsh/.credentials.yaml` 读取，
   不写入仓库；提交前请确认没有把 key 带进 diff。
4. **模型文件**：`models/` 与 `tools/llama/` 不进 git，避免供应链污染；
   下载官方 release 后请核对大小/哈希。

## 不在范围内

- 本机被物理控制后的事后取证；
- Windows 自身的权限提升问题（本项目以当前用户权限运行，建议不要用管理员运行）。
