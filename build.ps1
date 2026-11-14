$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'code/.venv/Scripts/python.exe'
$tempPath = Join-Path $projectRoot 'work/temp'
New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$env:TEMP = $tempPath
$env:TMP = $tempPath
Push-Location (Join-Path $projectRoot 'code')
try {
    & $pythonPath -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    $sourceFiles = @(Get-ChildItem -File -Filter '*.py' | ForEach-Object FullName)
    & $pythonPath -m black --check @sourceFiles tests
    if ($LASTEXITCODE -ne 0) { throw 'Formatting check failed' }
    & $pythonPath -m pylint --persistent=n @sourceFiles
    if ($LASTEXITCODE -ne 0) { throw 'Pylint failed' }
    & $pythonPath -m build --no-isolation
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
} finally {
    Pop-Location
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
