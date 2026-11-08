<#
Image Compactor build script.

Builds a static avifenc from libavif 1.4.2 and SVT-AV1 4.3.0, then builds the
single-file PyInstaller executable (dist\image-compactor.exe). Run from the
repo root:

    powershell -ExecutionPolicy Bypass -File build.ps1

Build prerequisites: Python 3.11+ (64-bit), Visual Studio 2022 Build Tools
with the MSVC C++ workload, CMake, Git, and internet access for the source
downloads. NASM is downloaded and staged automatically.

The executable is reused when dist\image-compactor.exe is newer than the
source, build files, and cached encoder. Pass -Force to rebuild it. The encoder
is reused from build\encoder when present. If it is missing, the script asks
before starting the long source build. Pass -ForceEncoder to rebuild without
asking, -SkipEncoderBuild to refuse a source build, or -SkipVerify to skip the
frozen-app checks.

Logs: %TEMP%\ic-pip.log, ic-encoder-configure.log, ic-encoder-build.log,
ic-encoder-verify.log, ic-tests.log, ic-pyinstaller.log, ic-verify.log.

Exit codes:
  0 success
  1 Python 3.11+ (64-bit) not found
  2 Python environment or dependency install failed
  3 encoder toolchain or encoder build failed
  4 PyInstaller build failed
  5 frozen executable verification failed
  6 unit tests failed
  7 avifenc.exe is missing and the source build was declined
#>
param(
    [switch]$Force,
    [switch]$SkipVerify,
    [switch]$SkipEncoderBuild,
    [switch]$ForceEncoder
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root
$ProgressPreference = "SilentlyContinue"

$exe = Join-Path $root "dist\image-compactor.exe"
$encoderDir = Join-Path $root "build\encoder"
$encoderExe = Join-Path $encoderDir "avifenc.exe"

if (-not ($Force -or $ForceEncoder)) {
    $exeInfo = Get-Item -LiteralPath $exe -ErrorAction SilentlyContinue
    if ($exeInfo) {
        $sources = @()
        $sources += Get-ChildItem -LiteralPath $root -Filter "*.py" -File
        foreach ($name in @("build.ps1", "image-compactor.spec", "requirements.txt", "requirements-build.txt")) {
            $path = Join-Path $root $name
            if (Test-Path -LiteralPath $path) { $sources += Get-Item -LiteralPath $path }
        }
        if (Test-Path -LiteralPath $encoderDir) {
            $sources += Get-ChildItem -LiteralPath $encoderDir -File
        }
        $newest = ($sources | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
        if ($newest -and $exeInfo.LastWriteTime -ge $newest) {
            Write-Host "Build is up to date: $exe" -ForegroundColor Green
            Write-Host "Nothing was rebuilt. Pass -Force to rebuild the executable." -ForegroundColor DarkGray
            exit 0
        }
    }
}

$AvifVersion = "1.4.2"
$AvifSourceUrl = "https://github.com/AOMediaCodec/libavif/archive/refs/tags/v$AvifVersion.zip"
$AvifSourceSha256 = "79b6ed913a5f573e6c5c85721bb3046231df48c9743a7f4c3f5146ed0c1c06d0"
$SvtVersion = "4.3.0"
$NasmVersion = "2.16.03"
$NasmUrl = "https://www.nasm.us/pub/nasm/releasebuilds/$NasmVersion/win64/nasm-$NasmVersion-win64.zip"
$NasmSha256 = "3ee4782247bcb874378d02f7eab4e294a84d3d15f3f6ee2de2f47a46aa7226e6"

function Write-Step { param([string]$Text) Write-Host "==> $Text" -ForegroundColor Cyan }
function Fail { param([int]$Code, [string]$Text) Write-Host "ERROR: $Text" -ForegroundColor Red; exit $Code }

function Show-Log {
    param([string]$Path, [int]$Lines = 25)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $content = @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)
    if ($content.Count -eq 0) { return }
    $errors = @($content |
        Select-String -Pattern '^\s*(ERROR|CRITICAL|FATAL|Traceback)|^\s*error(\[|:)' |
        Select-Object -First 10)
    if ($errors.Count -gt 0) {
        Write-Host "--- error lines from $Path ---" -ForegroundColor DarkGray
        foreach ($match in $errors) { Write-Host $match.Line -ForegroundColor DarkGray }
    }
    $tail = @($content | Select-Object -Last $Lines)
    Write-Host "--- last $($tail.Count) lines of $Path ---" -ForegroundColor DarkGray
    foreach ($line in $tail) { Write-Host $line -ForegroundColor DarkGray }
    Write-Host "---" -ForegroundColor DarkGray
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
}

function Download-File {
    param([string]$Url, [string]$Path, [string]$Sha256)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    if (-not (Test-Path -LiteralPath $Path)) {
        Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
    }
    if ($Sha256) {
        $actual = Get-FileSha256 $Path
        if ($actual -ne $Sha256.ToLower()) {
            Fail 3 "Checksum mismatch for $Path. Expected $Sha256, got $actual."
        }
    }
}

function Build-Encoder {
    Write-Step "Locating encoder build tools"
    $cmake = (Get-Command cmake -ErrorAction SilentlyContinue)
    if (-not $cmake) { Fail 3 "CMake was not found on PATH. Install CMake and re-run." }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail 3 "Git was not found on PATH. Install Git and re-run."
    }
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) {
        Fail 3 "Visual Studio Installer (vswhere) was not found. Install VS 2022 Build Tools."
    }
    $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vsPath) {
        Fail 3 "Visual Studio 2022 Build Tools with the MSVC C++ workload was not found."
    }
    Write-Host "   CMake: $($cmake.Source)"
    Write-Host "   Visual Studio: $vsPath"

    Write-Step "Staging NASM $NasmVersion"
    $nasmRoot = Join-Path $root "build\tools\nasm-$NasmVersion"
    $nasmExe = Join-Path $nasmRoot "nasm.exe"
    if (-not (Test-Path -LiteralPath $nasmExe)) {
        $nasmZip = Join-Path $root "build\downloads\nasm-$NasmVersion-win64.zip"
        Download-File $NasmUrl $nasmZip $NasmSha256
        New-Item -ItemType Directory -Force -Path (Join-Path $root "build\tools") | Out-Null
        Expand-Archive -LiteralPath $nasmZip -DestinationPath (Join-Path $root "build\tools") -Force
    }
    if (-not (Test-Path -LiteralPath $nasmExe)) {
        Fail 3 "NASM did not unpack to $nasmExe."
    }
    $env:PATH = "$nasmRoot;$env:PATH"
    Write-Host "   NASM: $nasmExe"

    Write-Step "Staging libavif $AvifVersion"
    $sourceRoot = Join-Path $root "build\libavif-extract\libavif-$AvifVersion"
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "CMakeLists.txt"))) {
        $sourceZip = Join-Path $root "build\libavif-$AvifVersion.zip"
        Download-File $AvifSourceUrl $sourceZip $AvifSourceSha256
        Expand-Archive -LiteralPath $sourceZip -DestinationPath (Join-Path $root "build\libavif-extract") -Force
    }
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "CMakeLists.txt"))) {
        Fail 3 "libavif source did not unpack to $sourceRoot."
    }

    Write-Step "Staging SVT-AV1 $SvtVersion"
    $svtDir = Join-Path $sourceRoot "ext\SVT-AV1"
    if (-not (Test-Path -LiteralPath (Join-Path $svtDir "CMakeLists.txt"))) {
        if (Test-Path -LiteralPath $svtDir) { Remove-Item -LiteralPath $svtDir -Recurse -Force }
        $gitLog = Join-Path $env:TEMP "ic-encoder-git.log"
        & git clone --depth 1 --branch "v$SvtVersion" https://github.com/AOMediaCodec/SVT-AV1.git $svtDir *> $gitLog
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $svtDir "CMakeLists.txt"))) {
            Show-Log $gitLog
            Fail 3 "SVT-AV1 v$SvtVersion clone failed. Full output: $gitLog"
        }
    }
    Write-Host "   SVT-AV1: $svtDir"

    $buildDir = Join-Path $root "build\encoder-build"
    if ($ForceEncoder -and (Test-Path -LiteralPath $buildDir)) {
        Write-Step "Removing the previous encoder build"
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }

    Write-Step "Configuring libavif with SVT-AV1"
    $configureLog = Join-Path $env:TEMP "ic-encoder-configure.log"
    & $cmake.Source -S $sourceRoot -B $buildDir -G "Visual Studio 17 2022" -A x64 `
        -DBUILD_SHARED_LIBS=OFF `
        -DAVIF_BUILD_APPS=ON `
        -DAVIF_BUILD_TESTS=OFF `
        -DAVIF_BUILD_MAN_PAGES=OFF `
        -DAVIF_CODEC_SVT=LOCAL `
        -DAVIF_JPEG=LOCAL `
        -DAVIF_ZLIBPNG=LOCAL `
        -DAVIF_LIBYUV=LOCAL `
        -DAVIF_LIBSHARPYUV=LOCAL *> $configureLog
    if ($LASTEXITCODE -ne 0) {
        Show-Log $configureLog 30
        Fail 3 "libavif configure failed (exit $LASTEXITCODE). Full output: $configureLog"
    }

    Write-Step "Compiling avifenc"
    $buildLog = Join-Path $env:TEMP "ic-encoder-build.log"
    & $cmake.Source --build $buildDir --config Release --target avifenc --parallel *> $buildLog
    if ($LASTEXITCODE -ne 0) {
        Show-Log $buildLog 30
        Fail 3 "avifenc build failed (exit $LASTEXITCODE). Full output: $buildLog"
    }

    $built = Get-ChildItem -LiteralPath $buildDir -Recurse -Filter "avifenc.exe" |
        Where-Object { $_.FullName -notmatch "CMakeFiles" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $built) {
        Show-Log $buildLog 30
        Fail 3 "The build finished but avifenc.exe was not found under $buildDir."
    }

    $encoderDir = Join-Path $root "build\encoder"
    New-Item -ItemType Directory -Force -Path $encoderDir | Out-Null
    Copy-Item -LiteralPath $built.FullName -Destination (Join-Path $encoderDir "avifenc.exe") -Force
    Write-Host "   Built: $($built.FullName) ($($built.Length) bytes)"

    $crtRoot = Join-Path $vsPath "VC\Redist\MSVC"
    $redist = Get-ChildItem -LiteralPath $crtRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^\d+\." } |
        Sort-Object { [version]$_.Name } -Descending |
        Select-Object -First 1
    if ($redist) {
        $crt = Join-Path $redist.FullName "x64\Microsoft.VC143.CRT"
        if (Test-Path -LiteralPath $crt) {
            Get-ChildItem -LiteralPath $crt -Filter "vcruntime140*.dll" |
                ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $encoderDir -Force }
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $encoderDir "vcruntime140.dll"))) {
        Write-Host "   Warning: vcruntime140.dll was not copied. The encoder may need the VC redistributable." -ForegroundColor Yellow
    }
}

function Test-EncoderVersion {
    param([string]$EncoderExe)
    $versionLog = Join-Path $env:TEMP "ic-encoder-version.log"
    & $EncoderExe --version *> $versionLog
    $versionText = if (Test-Path -LiteralPath $versionLog) { Get-Content -LiteralPath $versionLog -Raw } else { "" }
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch "svt") {
        Show-Log $versionLog
        Fail 3 "The encoder at $EncoderExe does not report an SVT build."
    }
    Write-Host "   $($versionText.Split("`n")[0].Trim())"
}

function Confirm-EncoderBuild {
    param([string]$EncoderDir)
    $message = "A build of SVT-AV1 is required, but `"avifenc.exe`" is not found in $EncoderDir. Do you wish to build avifenc.exe from source? It will take a long time (from 10 to 40 minutes depending on the computer performance)."
    $answer = Read-Host "$message [y/N]"
    return $answer.Trim() -match "^(y|yes)$"
}

function Verify-Encoder {
    param([string]$EncoderExe)
    Test-EncoderVersion $EncoderExe

    Write-Step "Verifying the bundled encoder"
    $verifyDir = Join-Path $root "build\encoder-verify"
    Remove-Item -LiteralPath $verifyDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $verifyDir | Out-Null
    $makeCode = "from PIL import Image; import sys; from pathlib import Path; d=Path(sys.argv[1]); Image.new('RGB',(64,48),(20,180,40)).save(d/'verify.jpg', quality=92); Image.new('RGBA',(64,48),(20,180,40,128)).save(d/'verify.png')"
    & $buildPython -c $makeCode $verifyDir *> $null
    if ($LASTEXITCODE -ne 0) { Fail 3 "Could not create encoder verification images." }

    $verifyLog = Join-Path $env:TEMP "ic-encoder-verify.log"
    & $EncoderExe -c svt -q 45 -s 3 -y 420 -d 10 -r full -j 1 -a tune=4 --sharpyuv `
        (Join-Path $verifyDir "verify.jpg") (Join-Path $verifyDir "verify.avif") *> $verifyLog
    $jpegExit = $LASTEXITCODE
    & $EncoderExe -c svt -q 45 -s 3 -y 420 -d 10 -r full -j 1 -a tune=4 --sharpyuv `
        (Join-Path $verifyDir "verify.png") (Join-Path $verifyDir "verify-png.avif") *>> $verifyLog
    $pngExit = $LASTEXITCODE
    $jpegOut = Join-Path $verifyDir "verify.avif"
    $pngOut = Join-Path $verifyDir "verify-png.avif"
    if ($jpegExit -ne 0 -or $pngExit -ne 0 -or -not (Test-Path -LiteralPath $jpegOut) -or -not (Test-Path -LiteralPath $pngOut)) {
        Show-Log $verifyLog 40
        Fail 3 "The bundled encoder could not encode the verification images."
    }
    $checkCode = "from PIL import Image; import sys; from pathlib import Path; d=Path(sys.argv[1]); a=Image.open(d/'verify.avif'); b=Image.open(d/'verify-png.avif'); assert a.size==(64,48); assert b.size==(64,48); assert b.mode=='RGBA'; print('encoder-check=ok')"
    & $buildPython -c $checkCode $verifyDir
    if ($LASTEXITCODE -ne 0) {
        Show-Log $verifyLog 40
        Fail 3 "The verification AVIF files could not be opened."
    }
    Write-Host "   JPEG and PNG input, 10-bit SVT, and --sharpyuv all work."
}

Write-Step "Locating Python 3.11+ (64-bit)"
$pythonPath = $null
$candidates = @("py -3.13", "py -3.12", "py -3.14", "py -3.11", "python")
$probe = @"
import sys, struct
ok = sys.version_info >= (3, 11) and struct.calcsize('P') == 8
venv = getattr(sys, 'base_prefix', sys.prefix) != sys.prefix
print(sys.executable if ok and not venv else '')
"@
foreach ($cand in $candidates) {
    $parts = $cand.Split(" ")
    if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
    $args = @()
    if ($parts.Length -gt 1) { $args += $parts[1] }
    $args += @("-c", $probe)
    $out = & $parts[0] @args 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) { $pythonPath = $out.Trim(); break }
}
if (-not $pythonPath) {
    Fail 1 "Python 3.11+ (64-bit) was not found on PATH. Install it from https://www.python.org/downloads/windows/ and re-run."
}
Write-Host "   Using: $pythonPath"

Write-Step "Preparing the build environment"
$venv = Join-Path $root "build\venv"
$buildPython = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $buildPython)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $root "build") | Out-Null
    & $pythonPath -m venv $venv *> (Join-Path $env:TEMP "ic-venv.log")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $buildPython)) {
        Show-Log (Join-Path $env:TEMP "ic-venv.log")
        Fail 2 "Could not create the build virtual environment."
    }
}

$pipLog = Join-Path $env:TEMP "ic-pip.log"
& $buildPython -m pip install --upgrade pip *> $pipLog
if ($LASTEXITCODE -ne 0) {
    Show-Log $pipLog
    Fail 2 "pip upgrade failed (exit $LASTEXITCODE). Full output: $pipLog"
}
& $buildPython -m pip install -r requirements-build.txt *> $pipLog
if ($LASTEXITCODE -ne 0) {
    Show-Log $pipLog 40
    Fail 2 "Build dependency install failed (exit $LASTEXITCODE). Full output: $pipLog"
}

$encoderExists = Test-Path -LiteralPath $encoderExe
if ($SkipEncoderBuild) {
    if (-not $encoderExists) {
        Fail 3 "-SkipEncoderBuild was passed but $encoderExe is missing."
    }
    Write-Step "Using the cached encoder"
    Write-Host "   Encoder already exists. Skipping the source build."
    Test-EncoderVersion $encoderExe
} elseif ($ForceEncoder) {
    Write-Step "Rebuilding the encoder (-ForceEncoder)"
    Build-Encoder
    Verify-Encoder $encoderExe
} elseif (-not $encoderExists) {
    if (-not (Confirm-EncoderBuild $encoderDir)) {
        Fail 7 "avifenc.exe is required in $encoderDir. The source build was declined."
    }
    Build-Encoder
    Verify-Encoder $encoderExe
} else {
    Write-Step "Using the cached encoder"
    Write-Host "   Encoder already exists. Skipping the source build."
    Test-EncoderVersion $encoderExe
}

Write-Step "Running unit tests with the bundled encoder"
$testLog = Join-Path $env:TEMP "ic-tests.log"
$parent = Split-Path $root -Parent
$env:AVIFENC = $encoderExe
& $buildPython -m unittest discover -s "$root\tests" -t $parent *> $testLog
$testExit = $LASTEXITCODE
Remove-Item Env:AVIFENC -ErrorAction SilentlyContinue
if ($testExit -ne 0) {
    Show-Log $testLog 40
    Fail 6 "Unit tests failed (exit $testExit). Full output: $testLog"
}
Write-Host "   Unit tests passed."

Write-Step "Stopping any running Image Compactor process"
Get-Process -Name "image-compactor" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Step "Building the portable executable (PyInstaller)"
$pyiLog = Join-Path $env:TEMP "ic-pyinstaller.log"
& $buildPython -m PyInstaller --clean --noconfirm image-compactor.spec *> $pyiLog
if ($LASTEXITCODE -ne 0) {
    Show-Log $pyiLog 40
    Fail 4 "PyInstaller build failed (exit $LASTEXITCODE). Full output: $pyiLog"
}
if (-not (Test-Path -LiteralPath $exe)) {
    Show-Log $pyiLog 40
    Fail 4 "PyInstaller exited 0 but $exe is missing. Full output: $pyiLog"
}

if (-not $SkipVerify) {
    Write-Step "Verifying the frozen executable"
    Remove-Item Env:AVIFENC -ErrorAction SilentlyContinue
    $verifyEncoderLog = Join-Path $env:TEMP "ic-verify-encoder.log"
    $verifyUiLog = Join-Path $env:TEMP "ic-verify-ui.log"
    Remove-Item -LiteralPath $verifyEncoderLog, $verifyUiLog -Force -ErrorAction SilentlyContinue

    $encProcess = Start-Process -FilePath $exe -ArgumentList @("--verify-encoder", "`"$verifyEncoderLog`"") -Wait -PassThru
    $encText = if (Test-Path -LiteralPath $verifyEncoderLog) { Get-Content -LiteralPath $verifyEncoderLog -Raw } else { "" }
    $encOk = $encProcess.ExitCode -eq 0 -and $encText -match "ok=True" -and $encText -match "encoder=.*avifenc\.exe" -and $encText -match "bytes=\d+"
    if (-not $encOk) {
        Show-Log $verifyEncoderLog 30
        Fail 5 "Frozen encoder verification failed (exit $($encProcess.ExitCode)). Log: $verifyEncoderLog"
    }

    $uiProcess = Start-Process -FilePath $exe -ArgumentList @("--verify-ui", "`"$verifyUiLog`"") -Wait -PassThru
    $uiText = if (Test-Path -LiteralPath $verifyUiLog) { Get-Content -LiteralPath $verifyUiLog -Raw } else { "" }
    $uiOk = $uiProcess.ExitCode -eq 0 -and $uiText -match "dnd_ready=True" -and $uiText -match "ready=True"
    if (-not $uiOk) {
        Show-Log $verifyUiLog 30
        Fail 5 "Frozen UI verification failed (exit $($uiProcess.ExitCode)). Log: $verifyUiLog"
    }
    Write-Host "   Bundled encoder encoded an AVIF. The GUI loaded with drag and drop."
} else {
    Write-Host "   Skipping verification (-SkipVerify)"
}

$exeInfo = Get-Item -LiteralPath $exe
Write-Host ""
Write-Host "Build complete: $exe ($($exeInfo.Length) bytes)" -ForegroundColor Green
Write-Host "Bundled encoder: $(Join-Path $encoderDir 'avifenc.exe')" -ForegroundColor Green
exit 0
