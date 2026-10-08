param(
    [Parameter(Mandatory=$true)][string]$Repo,
    [Parameter(Mandatory=$true)][string]$Store,
    [Parameter(Mandatory=$true)][string]$MonitorConfig,
    [string]$TaskUser
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path $Repo).Path
$Store = (Resolve-Path $Store).Path
$MonitorConfig = (Resolve-Path $MonitorConfig).Path
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Create the repository venv before installing the task.' }
if (-not $TaskUser) { $TaskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name }
# The local password is entered only into the OS credential dialog, never chat or files.
$Credential = Get-Credential -UserName $TaskUser -Message 'Windows account for DX27 task: run even while logged out'
$Arguments = '-u -m dx27.adapters.sentinel.supervised_runner --store "{0}" --monitor-config "{1}"' -f $Store, $MonitorConfig
$Action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -WakeToRun
# Battery operation is not assumed. Use AC power and keep the machine awake.
Register-ScheduledTask -TaskName 'DX27-Sentinel-Pilot' -Action $Action -Trigger $Trigger -Settings $Settings -User $Credential.UserName -Password $Credential.GetNetworkCredential().Password -Description 'Frozen 2026-10-08 through 2026-11-04 pilot. Deployment acceptance pending.' -Force | Out-Null
Start-ScheduledTask -TaskName 'DX27-Sentinel-Pilot'
Write-Output 'Task registered and started. This is not 3A acceptance: verify reboot recovery and external email alerts.'
