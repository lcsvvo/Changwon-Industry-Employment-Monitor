# 관세청 수집 이어받기 — Windows 작업 스케줄러 등록 (선택)
#
# 무엇을 만드는가
#   1시간마다 `resume_customs_collection.py --once` 를 실행하는 작업 하나.
#   한 번 실행 = 미수집 조합 1건 probe. 열려 있으면 남은 조합을 이어받고,
#   429 면 아무것도 하지 않고 종료한다.
#
# 왜 이게 필요한가
#   python 프로세스를 그냥 띄워 두는 방식은 VS Code 종료 / PC 종료 / 절전에서 끊긴다.
#   작업 스케줄러는 로그온 후 자동으로 다시 실행되므로 그 문제가 없다.
#
# 실행 전 확인
#   - 이 스크립트는 **기본적으로 아무것도 만들지 않는다.** `-Apply` 를 줘야 등록된다.
#   - 관리자 권한 없이 현재 사용자 작업으로 등록된다(로그온 시 동작).
#   - 제거: schtasks /Delete /TN "ChangwonCustomsResume" /F
#
# 사용
#   powershell -ExecutionPolicy Bypass -File src\evidence\collection\register_customs_resume_task.ps1
#   powershell -ExecutionPolicy Bypass -File src\evidence\collection\register_customs_resume_task.ps1 -Apply

param(
    [switch]$Apply,
    [int]$IntervalMinutes = 60,
    [string]$TaskName = "ChangwonCustomsResume"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
$script = Join-Path $repo "src\evidence\collection\resume_customs_collection.py"
$logDir = Join-Path $repo "logs\customs_resume"
$log = Join-Path $logDir "resume.log"

# 스케줄러는 작업 디렉터리를 상속하지 않으므로 cmd 로 감싸 cd 를 먼저 한다.
$action = "cmd /c cd /d `"$repo`" && `"$python`" `"$script`" --once >> `"$log`" 2>&1"

Write-Host "=== 등록될 작업 내용 ==="
Write-Host "  작업 이름   : $TaskName"
Write-Host "  실행 주기   : $IntervalMinutes 분마다 (로그온 시 시작, 무기한)"
Write-Host "  실행 계정   : $env:USERNAME (현재 사용자, 관리자 권한 불필요)"
Write-Host "  파이썬      : $python"
Write-Host "  스크립트    : $script"
Write-Host "  로그        : $log"
Write-Host ""
Write-Host "  실제 명령:"
Write-Host "    $action"
Write-Host ""
Write-Host "  등록 명령(참고):"
Write-Host "    schtasks /Create /TN `"$TaskName`" /TR `"...`" /SC MINUTE /MO $IntervalMinutes /F"
Write-Host ""
Write-Host "  이 작업이 하는 일: 1시간마다 API 1건 probe. 한도가 열려 있으면 남은 조합만"
Write-Host "  이어받고, 429 면 아무 호출도 하지 않고 즉시 종료한다."
Write-Host "  결손이 0 이 되면 이후 실행은 즉시 종료한다(호출 없음)."
Write-Host ""

if (-not $Apply) {
    Write-Host "[미적용] 실제로 등록하려면 -Apply 를 붙여 다시 실행하세요." -ForegroundColor Yellow
    Write-Host "         제거: schtasks /Delete /TN `"$TaskName`" /F"
    exit 0
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
schtasks /Create /TN $TaskName /TR $action /SC MINUTE /MO $IntervalMinutes /F | Out-Null
Write-Host "[등록 완료] $TaskName" -ForegroundColor Green
Write-Host "  상태 확인: schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "  즉시 실행: schtasks /Run /TN `"$TaskName`""
Write-Host "  제거      : schtasks /Delete /TN `"$TaskName`" /F"
