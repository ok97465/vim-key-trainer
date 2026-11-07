#Requires -Version 5.1

$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw '이 스크립트는 Windows에서 실행하세요.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$iconPath = Join-Path $projectRoot 'src\vim_key_trainer\resources\icons\vim-key-trainer.ico'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw '프로젝트 폴더에서 uv sync --dev를 먼저 실행하세요. .venv\Scripts\pythonw.exe가 없습니다.'
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "바탕화면 아이콘 파일이 없습니다: $iconPath"
}

$desktopPath = [Environment]::GetFolderPath('Desktop')
if (-not $desktopPath -or -not (Test-Path -LiteralPath $desktopPath -PathType Container)) {
    throw '사용자 바탕화면 폴더를 찾을 수 없습니다.'
}

$shortcutPath = Join-Path $desktopPath 'vim-key-trainer.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $null
try {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    if ((Test-Path -LiteralPath $shortcutPath) -and
        ($shortcut.TargetPath -ne $pythonPath -or $shortcut.Arguments -ne '-m vim_key_trainer')) {
        throw "다른 바로가기를 보존했습니다. 이름을 바꾼 뒤 다시 실행하세요: $shortcutPath"
    }

    $shortcut.TargetPath = $pythonPath
    $shortcut.Arguments = '-m vim_key_trainer'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = "$iconPath,0"
    $shortcut.Description = 'Vim 키보드 연습 · ok97465'
    $shortcut.Save()
    Write-Output "바탕화면 바로가기를 만들었습니다: $shortcutPath"
}
finally {
    if ($null -ne $shortcut) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut)
    }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
}
