# PR 34 review correction

All 6B-2J-A files are byte-identical to pre-review HEAD. 3A remains NOT_READY;
logged-out startup, forced worker termination recovery and distinct recovery
email are required, not optional.

Installer now asks for an explicit scheduler identity, resolves its SID before
registration, uses terminating cmdlet errors, verifies the registered principal
and Running state before success, and exits 1 on failure. Pester cases cover
MicrosoftAccount identity, registration failure, start failure, non-Running
state and cancelled credentials. Native PowerShell/Pester execution NOT_RUN:
this Linux environment has no pwsh. Actual MicrosoftAccount retest remains
pending, as do all outstanding frozen acceptance items.
