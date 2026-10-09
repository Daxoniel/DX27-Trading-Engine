# PR 34 review correction

All 6B-2J-A files are byte-identical to pre-review HEAD. 3A remains NOT_READY;
logged-out startup, forced worker termination recovery and distinct recovery
email are required, not optional.

Installer now asks for an explicit scheduler identity, resolves its SID before
registration, uses terminating cmdlet errors, verifies the registered principal
and Running state before success, and exits 1 on failure. Pester cases cover
MicrosoftAccount identity, registration failure, start failure, non-Running
state and cancelled credentials. Isolated Windows Actions execution PASS: Pester 5.7.1, five tests passed,
zero failed/skipped/not-run. Tested commit 583002d76dceb26ade5ad35fe6570e707f1f738f.
Run: https://github.com/Daxoniel/DX27-Trading-Engine/actions/runs/37901495795
Workflow: .github/workflows/sentinel-windows-installer.yml
JUnit-compatible test-result XML is archived as sentinel-pester-results.

Initial runs exposed fake-credential scope and mock CIM-type problems; tests now
construct typed in-memory task definitions and assert the expected registration/
start call counts, preventing early unrelated exits from passing failure tests.
The live home pilot was not touched. MicrosoftAccount SID/credential behavior
is mocked: this is installer branch validation, not full native deployment proof.
Required native logged-out, forced worker recovery and recovery-email acceptance
remain pending; 3A stays NOT_READY. Focused Python regression: 26 passed in 10.75s.
Final diff against e3db8c4 contains no changes to any 6B-2J-A protocol artifact.
