# Run with Pester 5 on Windows: Invoke-Pester .\deploy\sentinel\tests\install-windows.Tests.ps1
Describe 'Sentinel installer failure handling' {
    BeforeAll {
        $Installer = Join-Path $PSScriptRoot '..\install-windows.ps1'
    }
    BeforeEach {
        $Repo = Join-Path $TestDrive 'repo'
        $Store = Join-Path $TestDrive 'data'
        $Monitor = Join-Path $TestDrive 'monitoring.json'
        New-Item -ItemType Directory -Path "$Repo\.venv\Scripts", $Store -Force | Out-Null
        New-Item -ItemType File -Path "$Repo\.venv\Scripts\python.exe", $Monitor -Force | Out-Null
        Mock Get-Credential { [PSCredential]::new('MicrosoftAccount\test@example.com', (ConvertTo-SecureString 'fake-test-password' -AsPlainText -Force)) }
        Mock New-Object {
            $Account = [PSCustomObject]@{}
            $Account | Add-Member -MemberType ScriptMethod -Name Translate -Value { param($Type) [PSCustomObject]@{Value='S-1-5-21-100'} }
            $Account
        } -ParameterFilter { $TypeName -eq 'System.Security.Principal.NTAccount' }
        Mock New-ScheduledTaskAction { [PSCustomObject]@{} }
        Mock New-ScheduledTaskTrigger { [PSCustomObject]@{} }
        Mock New-ScheduledTaskSettingsSet { [PSCustomObject]@{} }
        Mock Register-ScheduledTask { [PSCustomObject]@{TaskName='DX27-Sentinel-Pilot'} }
        Mock Get-ScheduledTask { [PSCustomObject]@{State='Running';Principal=[PSCustomObject]@{UserId='MicrosoftAccount\test@example.com'}} }
        Mock Start-ScheduledTask {}
        Mock Start-Sleep {}
        Mock Write-Error { Write-Host $Message }
    }
    It 'uses the explicit MicrosoftAccount identity and verifies Running' {
        $Output = & $Installer -Repo $Repo -Store $Store -MonitorConfig $Monitor -TaskUser 'MicrosoftAccount\test@example.com'
        Should -Invoke Write-Error -Times 0
        $Output | Should -Match 'task observed Running'
        Should -Invoke Register-ScheduledTask -Times 1 -ParameterFilter { $User -eq 'MicrosoftAccount\test@example.com' }
        Should -Invoke Start-ScheduledTask -Times 1
    }
    It 'stops after registration failure without claiming success or starting an old task' {
        Mock Register-ScheduledTask { throw '0x80070534 test registration failure' }
        $Output = & $Installer -Repo $Repo -Store $Store -MonitorConfig $Monitor -TaskUser 'MicrosoftAccount\test@example.com'
        $LASTEXITCODE | Should -Be 1
        ($Output -join '\n') | Should -Not -Match 'task observed Running'
        Should -Invoke Register-ScheduledTask -Times 1
        Should -Invoke Start-ScheduledTask -Times 0
    }
    It 'does not claim success when start fails' {
        Mock Start-ScheduledTask { throw 'start failed' }
        $Output = & $Installer -Repo $Repo -Store $Store -MonitorConfig $Monitor -TaskUser 'MicrosoftAccount\test@example.com'
        $LASTEXITCODE | Should -Be 1
        ($Output -join '\n') | Should -Not -Match 'task observed Running'
        Should -Invoke Start-ScheduledTask -Times 1
    }
    It 'does not claim success when the task never reaches Running' {
        Mock Get-ScheduledTask { [PSCustomObject]@{State='Ready';Principal=[PSCustomObject]@{UserId='MicrosoftAccount\test@example.com'}} }
        $Output = & $Installer -Repo $Repo -Store $Store -MonitorConfig $Monitor -TaskUser 'MicrosoftAccount\test@example.com'
        $LASTEXITCODE | Should -Be 1
        ($Output -join '\n') | Should -Not -Match 'task observed Running'
        Should -Invoke Start-ScheduledTask -Times 1
    }
    It 'rejects cancelled credentials before registration' {
        Mock Get-Credential { $null }
        $Output = & $Installer -Repo $Repo -Store $Store -MonitorConfig $Monitor -TaskUser 'MicrosoftAccount\test@example.com'
        $LASTEXITCODE | Should -Be 1
        Should -Invoke Register-ScheduledTask -Times 0
    }
}
