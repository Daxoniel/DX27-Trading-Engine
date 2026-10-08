# Windows 10/11：Sentinel 试点迁移与后台运行指南

当前状态：实现及本地恢复测试通过；你的 Windows 部署、重启恢复和真实邮件送达**尚未验收**。
原定 2026-10-08 至 2026-11-04 的 20 个 session 不变，不能因迁移重新开始计数。

先完成第 1–4 步，暂不启动采集。准备就绪后与 Codex 完成第 5 步的单写入者交接。

## 1. 确认这台电脑适合持续运行

- 保持接电、开机和联网；接电时睡眠/休眠设为“从不”。屏幕可以关闭，电脑可以锁屏。
- 笔记本合盖不能导致睡眠。公司策略若强制睡眠/关机或禁止开机任务，该电脑不能通过 3A，需换常驻机器。
- Windows 时间设为自动同步，立即同步一次；运行 `w32tm /query /status` 检查时间源。
- 数据放在本地 NTFS 目录，不放临时目录、网络盘或同步中的 OneDrive 目录。
- 需要 Python 3.12，以及允许注册开机后台任务的 Windows 权限。遇到组织限制请由 IT 处理，不绕过策略。

## 2. 下载代码并创建独立环境

在 PowerShell 中运行。以下目录是用户本地目录，不覆盖已有项目：

```powershell
$Root = Join-Path $env:USERPROFILE 'DX27-Sentinel'
New-Item -ItemType Directory -Path $Root -Force | Out-Null
git clone --branch codex/sentinel-6b-2i-3a-durable-runner https://github.com/Daxoniel/DX27-Trading-Engine.git "$Root\repo"
Set-Location "$Root\repo"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest tests/test_recorded_capture.py tests/test_coverage_pilot.py tests/test_durable_runner.py -q
```

没有 Git 时可下载该分支的 GitHub ZIP，解压成 `$Root\repo`，确保这个目录下直接是 `pyproject.toml`。
不要把 monitor URL/password 放进仓库，不要在聊天中发送凭据。

## 3. 配置外部邮件告警

在 [Healthchecks.io](https://healthchecks.io/docs/) 创建自己的监控账户和一个 check：

- 名称：`DX27 Sentinel Windows Pilot`。
- Simple schedule：Period **2 minutes**，Grace **3 minutes**。
- Email integration：设置为你指定的收件邮箱，完成验证并确认该 check 的邮件集成开启。
- 复制专属 HTTPS ping URL；这是私密令牌，不能提交 GitHub。

在 `$Root\monitoring.json` 创建以下文件，将占位符替换为真实 URL：

```json
{
  "heartbeat_urls": ["https://hc-ping.com/YOUR_PRIVATE_UUID"]
}
```

不需要把 Gmail 密码交给 runner。邮箱通知由外部监控平台发送；电脑断网/关机后，它仍能因心跳缺失发送告警。
此时只是配置，**尚未验证真实邮件送达**。不能仅看本地日志就标为通过。

## 4. 恢复保留原时间戳的数据包，完成只读预检查

从此次交接取得私有 `sentinel-store-6b-2i-3a.tar.gz` 和对应 SHA-256。
数据包包含原始序列，保存在私人目录，不能上传公开 GitHub。
核对哈希，然后恢复到尚不存在的 `$Root\data`：

```powershell
Get-FileHash "$Root\sentinel-store-6b-2i-3a.tar.gz" -Algorithm SHA256
.\.venv\Scripts\python.exe -m dx27.adapters.sentinel.store_migration restore --archive "$Root\sentinel-store-6b-2i-3a.tar.gz" --store "$Root\data"
.\.venv\Scripts\python.exe -m dx27.adapters.sentinel.store_migration verify --store "$Root\data"
.\.venv\Scripts\python.exe -m dx27.adapters.sentinel.supervised_runner --store "$Root\data" --monitor-config "$Root\monitoring.json" --preflight
```

已有 `data` 目录时程序会拒绝覆盖。不要删除原数据来绕过检查；先核对来源，必要时选新的目标目录。
预检查必须显示 Windows、原定首末 session，以及与原始协议一致的 calendar version。
迁移检查只能证明文件/时间戳没有改写，不能证明电脑可以持续运行。

## 5. 与临时环境完成单写入者交接，再安装后台任务

将第 4 步输出告诉 Codex（不包含私密 ping URL）。确认准备就绪后：

1. 停止临时 collector，导出并核对**最终 checkpoint**。
2. 如果准备期间临时机器新增了 capture/job/report，重新交接最新包到新目标目录；不能只用早期副本。
3. 确认旧 collector 已停，Windows 成为唯一权威写入者，再启动任务。

在允许注册开机任务的 PowerShell 中运行：

```powershell
Set-Location "$Root\repo"
.\deploy\sentinel\install-windows.ps1 -Repo "$Root\repo" -Store "$Root\data" -MonitorConfig "$Root\monitoring.json"
Get-ScheduledTask -TaskName 'DX27-Sentinel-Pilot'
Get-ScheduledTaskInfo -TaskName 'DX27-Sentinel-Pilot'
```

脚本在 Windows 凭据窗口中询问你的 **Windows 账户密码**，不是 Windows Hello PIN。
任务配置为开机启动、未登录也运行、失败后 1 分钟重启、单实例、无默认三日运行上限。
账户密码只交给 Windows 任务计划程序，不写入 JSON，也不要发给 Codex。

监控 check 应开始收到每分钟心跳。读取最新状态：

```powershell
$Health = Get-ChildItem "$Root\data\profiles\*\supervisor-health.json" | Select-Object -First 1
Get-Content $Health.FullName
Get-Content "$Root\data\logs\collector.log" -Tail 30
```

`monitor_delivery` 应为 `[true]`，`worker_healthy` 应为 `true`。状态仍写为部署验收待完成，这是预期行为。
HTTPS/代理/证书问题应修正代理或 CA 配置，不关闭 TLS 校验。

## 6. 做真实恢复及邮件验收

尽量在计划轮询窗口之外进行，测试导致的真实缺失也不能抹掉。

1. **重启恢复**：重启 Windows，不手动启动 Python。确认任务自动运行，新的 supervisor/worker PID 和心跳出现，数据和冻结协议不变。确认未登录时任务也能启动。
2. **子进程失败恢复**：从 `supervisor-health.json` 取得 `worker_pid`，终止该 worker；确认任务自动重启，只有一个新 worker，出现告警/恢复信号。不能终止其它 Python 工作。
3. **外部邮件测试**：停止任务并确认 worker 也已停止，等待约 6 分钟；实际收到 down 邮件后重启任务，确认恢复邮件/平台恢复状态。
4. **持续条件**：锁屏后保持任务运行；观察网络断开时外部邮件告警，恢复后不补写过去 slot。若电脑必须自动休眠或夜间回收，则 3A 不通过。

```powershell
Stop-ScheduledTask -TaskName 'DX27-Sentinel-Pilot'
# 确认原 worker PID 已不存在。若仍存在，先处理遗留进程，不能启动第二份 collector。
# 等待外部告警并实际查收邮件。
Start-ScheduledTask -TaskName 'DX27-Sentinel-Pilot'
```

将真实测试的时间、任务状态、PID、邮件到达/恢复结果和迁移 hash 留在私有验收记录中。
在这些证据齐全之前，**3A = NOT_READY**，不能把任务注册成功当作持久化验收通过。

## 日常检查与结束

第一天计划轮询是柏林时间 2026-10-08 22:20、23:00、23:40、23:55；截止为 10 月 9 日 00:00。
以后由冻结 XNYS 日历计算，避免欧洲/美国夏令时切换造成偏差。
每日查看 `profiles\<id>\coverage\` 的最新报告，缺失保留并单独核对基础设施事故。
20 日窗口结束后程序正常退出，暂停外部 check，避免把正常结束误报为停机；保留所有数据。
后续 126/252 日收集需单独记录延续计划，不能由这份任务自动宣称 S/D 或 6B-2J 通过。

操作依据：[Microsoft Task Scheduler settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)、[Healthchecks notifications](https://healthchecks.io/docs/configuring_notifications/)。
