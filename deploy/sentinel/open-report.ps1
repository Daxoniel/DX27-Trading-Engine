param(
    [string]$DataDirectory,
    [string]$Protocol,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$Stage = 'configuration'
function Quote-ReportPath([string]$Value) {
    # Windows argv parsing treats backslashes before a closing quote specially.
    return '"' + [regex]::Replace($Value, '(\\+)$', '$1$1') + '"'
}
try {
    # This launcher neither installs dependencies nor touches the pilot task/store.
    $Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..') -ErrorAction Stop).Path
    $Python = Join-Path $Repo '.venv\Scripts\python.exe'
    if (-not (Test-Path $Python -PathType Leaf)) {
        throw 'Missing Windows .venv\Scripts\python.exe. Create a Windows virtual environment in this project first.'
    }
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535.' }
    if ([string]::IsNullOrWhiteSpace($DataDirectory)) {
        $DataDirectory = Join-Path $Repo 'work\sentinel-research-live'
    }
    if ([string]::IsNullOrWhiteSpace($Protocol)) {
        $Protocol = Join-Path $Repo 'research\sentinel\6b-2g-contracts\protocol.json'
    }
    $DataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
    $Protocol = (Resolve-Path $Protocol -ErrorAction Stop).Path
    # Match the server's physical-path identity, including Windows junctions.
    # JSON stdin also keeps path characters out of the Python source/argv.
    $PathJson = ConvertTo-Json -InputObject @($DataDirectory, $Protocol) -Compress
    $PreviousOutputEncoding = $OutputEncoding
    try {
        $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $CanonicalJson = $PathJson | & $Python -X utf8 -c 'import json, pathlib, sys; print(json.dumps([str(pathlib.Path(p).resolve()) for p in json.load(sys.stdin)]))'
        $PathResolutionExitCode = $LASTEXITCODE
    }
    finally { $OutputEncoding = $PreviousOutputEncoding }
    if ($PathResolutionExitCode -ne 0) { throw 'Could not resolve the research paths with the Windows interpreter.' }
    $CanonicalPaths = $CanonicalJson | ConvertFrom-Json
    $DataDirectory = $CanonicalPaths[0]
    $Protocol = $CanonicalPaths[1]

    $Stage = 'research dependencies'
    $DependenciesReady = $false
    try {
        & $Python -X utf8 -c 'from dx27.adapters.sentinel.research_service import validate_research_dependencies; validate_research_dependencies()'
        $DependenciesReady = ($LASTEXITCODE -eq 0)
    }
    catch { $DependenciesReady = $false }
    if (-not $DependenciesReady) {
        throw 'Research dependencies are missing or unavailable. From the project root run: .venv\Scripts\python.exe -m pip install -e ".[research-report]". Then open this launcher again.'
    }

    $Stage = 'background service startup'
    $LogDirectory = Join-Path $Repo 'work\sentinel-web-launch'
    [void](New-Item -ItemType Directory -Path $LogDirectory -Force)
    $LaunchId = [Guid]::NewGuid().ToString('N')
    $OutLog = Join-Path $LogDirectory ($LaunchId + '.stdout.log')
    $ErrLog = Join-Path $LogDirectory ($LaunchId + '.stderr.log')
    # Start-Process joins arguments on Windows, so explicitly quote path arguments.
    $Arguments = @(
        '-X', 'utf8', '-u', '-m', 'dx27.adapters.sentinel.observation_web',
        '--data-directory', (Quote-ReportPath $DataDirectory),
        '--protocol', (Quote-ReportPath $Protocol),
        '--port', $Port.ToString(), '--open-browser'
    )
    $Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $Repo -WindowStyle Hidden -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru -ErrorAction Stop

    $Stage = 'service readiness verification'
    $Url = 'http://127.0.0.1:{0}/' -f $Port
    $Ready = $false
    $ProcessFailure = $null
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        # Another simultaneous launcher can start the matching server first.
        # A verified matching service takes priority over this child's exit code.
        try {
            $Health = Invoke-RestMethod -Uri ($Url + 'healthz') -Method Get -TimeoutSec 2 -MaximumRedirection 0 -ErrorAction Stop
            if ($Health.service -ne 'dx27-sentinel-research-live-v1' -or $Health.data_directory -ne $DataDirectory -or $Health.protocol_path -ne $Protocol) {
                throw 'Port is occupied by a different service or research directory. Choose another -Port or use matching settings.'
            }
            $Ready = $true
            break
        }
        catch {
            if ($_.Exception.Message -like 'Port is occupied*') { throw }
        }
        $Process.Refresh()
        if ($Process.HasExited -and $Process.ExitCode -ne 0 -and $null -eq $ProcessFailure) {
            # The winning launcher may still be initializing its matching server.
            # Retain this child's failure, but allow the bounded readiness window.
            $ProcessFailure = if (Test-Path $ErrLog) { ([string](Get-Content $ErrLog -Raw -Encoding UTF8)).Trim() } else { 'No diagnostic was written.' }
            if ([string]::IsNullOrWhiteSpace($ProcessFailure)) { $ProcessFailure = 'No diagnostic was written.' }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Ready) {
        if ($null -ne $ProcessFailure) {
            throw ('The report process exited unsuccessfully and no matching service became ready. ' + $ProcessFailure)
        }
        throw ('The report service did not become ready. Check: ' + $ErrLog)
    }
    # The Python launcher opens the browser and reuses a verified existing server.
    Write-Output ('Research report service verified: ' + $Url)
    Write-Output 'Opening this page refreshes its independent research report once.'
    exit 0
}
catch {
    Write-Error ('Research report failed at ' + $Stage + '. ' + $_.Exception.Message) -ErrorAction Continue
    exit 1
}
