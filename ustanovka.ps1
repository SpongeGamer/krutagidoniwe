# Установка Python для Крутагидона.
#
# Почему отдельный файл, а не всё в .bat:
# cmd.exe перечитывает .bat кусками прямо во время выполнения, и русский
# текст в нём рассыпается на обрывки, которые cmd пытается выполнить как
# команды. PowerShell читает скрипт целиком и с юникодом работает нормально,
# поэтому весь понятный человеку текст живёт здесь.

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

function Test-Python {
    foreach ($cmd in @('py', 'python', 'python3')) {
        try {
            # Пробный запуск отсекает заглушку Microsoft Store:
            # она есть в PATH, но выполнять код не умеет.
            & $cmd -c "" 2>$null
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch { }
    }
    # Установка могла не прописаться в PATH текущего окна.
    $paths = @(
        "$env:LocalAppData\Programs\Python\Python313\python.exe"
        "$env:LocalAppData\Programs\Python\Python312\python.exe"
        "$env:LocalAppData\Programs\Python\Python311\python.exe"
        "$env:ProgramFiles\Python313\python.exe"
        "$env:ProgramFiles\Python312\python.exe"
    )
    foreach ($p in $paths) { if (Test-Path $p) { return $true } }
    return $false
}

Write-Host ""
Write-Host "  Python не найден — установлю его сам." -ForegroundColor Yellow
Write-Host "  Это разовое дело на пару минут, нажимать ничего не надо."
Write-Host ""

# Способ 1: встроенный в Windows 10/11 менеджер пакетов.
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "  [1/2] Устанавливаю через магазин приложений Windows…"
    winget install --id Python.Python.3.12 -e --source winget `
        --accept-package-agreements --accept-source-agreements --silent
    # Обновляем PATH, иначе свежий Python не виден этому окну.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    if (Test-Python) {
        Write-Host "  Готово. Запускаю игру…" -ForegroundColor Green
        exit 0
    }
}

# Способ 2: официальный установщик с python.org.
Write-Host "  [2/2] Скачиваю установщик с python.org…"
$arch = if ([Environment]::Is64BitOperatingSystem) { '-amd64' } else { '' }
$url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7$arch.exe"
$file  = Join-Path $env:TEMP 'python-krutagidon.exe'

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing

    Write-Host "  Устанавливаю (окна может не быть — это нормально)…"
    $args_list = '/passive', 'InstallAllUsers=0', 'PrependPath=1',
                 'Include_launcher=1', 'Include_test=0'
    Start-Process -FilePath $file -ArgumentList $args_list -Wait
    Remove-Item $file -ErrorAction SilentlyContinue

    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    if (Test-Python) {
        Write-Host "  Готово. Запускаю игру…" -ForegroundColor Green
        exit 0
    }
} catch {
    Write-Host "  Не вышло: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "  Автоматически установить не получилось." -ForegroundColor Red
Write-Host "  Скорее всего мешает антивирус или нет интернета."
Write-Host ""
Write-Host "  Поставь вручную:"
Write-Host "  1. Открой https://www.python.org/downloads/"
Write-Host "  2. Скачай и запусти установщик"
Write-Host "  3. ОБЯЗАТЕЛЬНО поставь галочку «Add Python to PATH»"
Write-Host "  4. Запусти ИГРАТЬ.bat снова"
Write-Host ""
Start-Process "https://www.python.org/downloads/"
exit 1
