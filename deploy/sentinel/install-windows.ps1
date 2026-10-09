param(
    [Parameter(Mandatory=$true)][string]$Repo,
    [Parameter(Mandatory=$true)][string]$Store,
    [Parameter(Mandatory=$true)][string]$MonitorConfig,
    [string]$TaskUser
)
$ErrorActionPreference = 'Stop'
$Stage = 'configuration'
try {
    $Repo = (Resolve-Path $Repo -ErrorAction Stop).Path
    $Store = (Resolve-Path $Store -ErrorAction Stop).Path
    $MonitorConfig = (Resolve-Path $MonitorConfig -ErrorAction Stop).Path
    $Python = Join-Path $Repo '.venv\Scripts\python.exe'
    if (-not (Test-Path $Python -PathType Leaf)) { throw 'Missing venv.' }
    # WindowsIdentity.Name can be a local alias for a MicrosoftAccount login.
    # Never infer a scheduler account from DESKTOP\USER. Ask for explicit identity.
    if ([string]::IsNullOrWhiteSpace($TaskUser)) {
        $TaskUser = Read-Host 'Task account: MicrosoftAccount\email@example.com, DOMAIN\user, or COMPUTER\localuser'
    }
    if ([string]::IsNullOrWhiteSpace($TaskUser)) { throw 'Explicit task account required.' }
    $Stage = 'credentials / account resolution'
    $Credential = Get-Credential -UserName $TaskUser -Message 'Use the full Windows account identity and account password, not a Windows Hello PIN'
    if ($null -eq $Credential) { throw 'Credential entry cancelled.' }
    $Account = New-Object System.Security.Principal.NTAccount($Credential.UserName)
    $AccountSid = $Account.Translate([System.Security.Principal.SecurityIdentifier])
    if ($null -eq $AccountSid) { throw 'Task account cannot be resolved.' }
    $Arguments = '-u -m dx27.adapters.sentinel.supervised_runner --store "{0}" --monitor-config "{1}"' -f $Store, $MonitorConfig
    $Action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Repo -ErrorAction Stop
    $Trigger = New-ScheduledTaskTrigger -AtStartup -ErrorAction Stop
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -WakeToRun -ErrorAction Stop
    # Battery operation is not assumed. Use AC power and keep the machine awake.
    $Stage = 'task registration'
    $Registered = Register-ScheduledTask -TaskName 'DX27-Sentinel-Pilot' -Action $Action -Trigger $Trigger -Settings $Settings -User $Credential.UserName -Password $Credential.GetNetworkCredential().Password -Description 'Frozen 2026-10-08 through 2026-11-04 pilot. Deployment acceptance pending.' -Force -ErrorAction Stop
    if ($null -eq $Registered) { throw 'Registration returned no task.' }
    # A task left over from an earlier install is not evidence this registration succeeded.
    $Installed = Get-ScheduledTask -TaskName 'DX27-Sentinel-Pilot' -ErrorAction Stop
    $InstalledAccount = New-Object System.Security.Principal.NTAccount($Installed.Principal.UserId)
    if ($InstalledAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value -ne $AccountSid.Value) {
        throw 'Registered task principal does not match selected account.'
    }
    $Stage = 'task start / Running state verification'
    Start-ScheduledTask -TaskName 'DX27-Sentinel-Pilot' -ErrorAction Stop
    $Running = $false
    for ($Attempt = 0; $Attempt -lt 15; $Attempt++) {
        $Task = Get-ScheduledTask -TaskName 'DX27-Sentinel-Pilot' -ErrorAction Stop
        if ($Task.State -eq 'Running') { $Running = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $Running) { throw 'Task did not reach Running state.' }
    Write-Output 'Task registration verified; task observed Running. Complete all frozen 3A recovery and email acceptance tests; Running alone is not acceptance.'
}
catch {
    # Do not echo credentials or private command arguments in failure output.
    Write-Error "Sentinel installation failed at $Stage. No success is claimed. Check Task Scheduler details; for Microsoft login use MicrosoftAccount\email@example.com and the account password." -ErrorAction Continue
    exit 1
}
