# Sentinel 最终报告：Windows 打开即更新

任务 **6B-2K-B**。报告集成 FactSet 和 Yardeni，比较上次实际保存的研究
快照，简短显示变化。完成本项后哨兵进入维护状态，日内量化留到下一项。

## 第一次设置

在含 `pyproject.toml` 的新代码项目根目录打开 PowerShell。保留原有采集
任务及其数据目录；此报告会另外使用 `work\sentinel-research-live`。

若项目已有 Windows `.venv`，只执行安装命令；没有则先创建环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[research-report]"
```

Python 3.12 同样支持，可将创建命令的版本改为 `-3.12`。首次安装需要
联网下载 PDF 和 OCR 依赖；OCR 模型随安装包提供，无须外部 Tesseract 或
PDF 工具，无须付费 API 密钥或邮件配置。

双击 `deploy\sentinel\open-report.cmd`，或运行：

```powershell
.\deploy\sentinel\open-report.ps1
```

它启动并核验本地服务，再打开 `http://127.0.0.1:8765/`。可以给这个
`.cmd` 建立桌面快捷方式。每次打开或刷新网页都检查来源一次；多个
启动器会复用同一个经过核验的报告服务。首次请求要等待网络抓取与 OCR，
页面会显示更新进度。FactSet 通常按周发布，所以每天检查可能没有新一期。

已经保存的 `市场观察.html` 是静态存档，打开它不会更新。日常使用上述
快捷方式或本地 HTTP 地址。

## 页面应显示什么

- 首次打开：首期无比较，建立第一份快照。
- 同口径指标相同：未发现变化，并注明资料未更新不代表市场没变化。
- 同口径数值变动：列出最多三条重点变化；盈利修订方向与幅度分开说明。
- 季度/年度或覆盖切换：暂不能比较，不报成趋势反转。
- 部分来源失败/未提取：仅显示本次有效资料，注明缺口。
- 刷新未完成或系统异常：上次报告明确标为旧版；没有存档时明确提示。

展开来源可核对报告日期、检查开始时间、页码/图号、参考 ID 和内容哈希。
日期缺失保持未知；Yardeni NERI 的月标签不会改成当日日期。

## 关机、重启与数据

浏览器关闭不会清空快照。关机后本地服务退出，回到桌面再双击同一
启动器即可恢复使用；旧的 `work\sentinel-research-live` 必须保留。
这不是新的 24/7 采集任务，不要求全天后台运行。原 pilot collector 及
其计划任务由原部署管理，本报告不会启停或写入它们。

```text
work/sentinel-research-live/
  live-report-profile.json
  latest.json / latest.md       最后成功发布的访问报告
  snapshots/                   已完成访问的独立快照
  research-captures/            FactSet PDF、Yardeni 页面及原图
  observations/                独立行情采集记录
```

不同机器有各自的“上次访问”。迁移时复制完整报告目录，不只复制 HTML。
不要把报告目录指向 pilot 的 `data`、`profiles`、配置目录或其链接。
源码更新与快照分开；不要删除 `work` 来重装代码。

端口占用时指定新端口，启动器会拒绝复用不同目录或其他程序：

```powershell
.\deploy\sentinel\open-report.ps1 -Port 8766
```

服务启动错误保存在 `work\sentinel-web-launch`。依赖缺失或核验失败会
明确报错，不打印成功。直接启动也可以：

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.sentinel.observation_web --data-directory work\sentinel-research-live --port 8765 --open-browser
```

## 验收和维护边界

打开两次：第二次应显示上次实际保存的时间；没有新资料就显示未发现变化。
重启后再打开：上次快照应保留。来源故障时不应把旧值充当新值。
此功能已经在 Linux 的真实来源与浏览器中核验；Windows 启动脚本需在目标
机器执行确认，Linux 检查不代替 Windows 实机验收。

后续仅修复影响这份报告的错误、来源格式和兼容问题。它提供研究解读，
不直接控制账户、下单或认证预测有效性。
