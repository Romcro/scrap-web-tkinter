# Construit l'exécutable autonome dist\EmailScraper\EmailScraper.exe
# Usage (PowerShell, à la racine du projet) :  .\build.ps1
# Prérequis : .venv créé et `pip install -r requirements-dev.txt`.

# Les erreurs sont détectées par le code de sortie : PyInstaller écrit ses messages
# d'information sur la sortie d'erreur, ce que Windows PowerShell prendrait pour un échec.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$python = ".\.venv\Scripts\python.exe"
$workDir = Join-Path $env:TEMP "EmailScraper-build"

Write-Host "1/4 Tests…"
& $python -m pytest -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "Les tests échouent : construction annulée." }

Write-Host "2/4 Construction de l'exécutable…"
$pyiArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
    "--noconsole", "--onefile", "--name", "EmailScraper",
    "--collect-data", "tldextract",
    # Fichiers intermédiaires hors de OneDrive : la synchronisation les verrouille.
    "--distpath", "dist\EmailScraper", "--workpath", "`"$workDir`"", "--specpath", "`"$workDir`"",
    "main.py"
)
& cmd /c "`"$python`" $($pyiArgs -join ' ') 2>&1"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué." }

Write-Host "3/4 Fichiers à côté de l'exécutable…"
$target = "dist\EmailScraper"
New-Item -ItemType Directory -Force "$target\config", "$target\exports", "$target\logs" | Out-Null
if (-not (Test-Path "$target\config\settings.json")) {
    Copy-Item config\settings.json "$target\config\settings.json"
}
Copy-Item README.md "$target\LISEZMOI.md" -Force

# Signature facultative (évite l'avertissement SmartScreen sur les autres postes).
# Nécessite un certificat de signature de code installé dans le magasin de l'utilisateur :
#   $env:SIGN_CERT_THUMBPRINT = "<empreinte du certificat>" ; .\build.ps1
if ($env:SIGN_CERT_THUMBPRINT) {
    Write-Host "    Signature de l'exécutable…"
    $cert = Get-Item "Cert:\CurrentUser\My\$($env:SIGN_CERT_THUMBPRINT)" -ErrorAction SilentlyContinue
    if (-not $cert) { throw "Certificat $($env:SIGN_CERT_THUMBPRINT) introuvable dans Cert:\CurrentUser\My." }
    $timestamp = if ($env:SIGN_TIMESTAMP_URL) { $env:SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
    $signature = Set-AuthenticodeSignature -FilePath "$target\EmailScraper.exe" -Certificate $cert `
        -HashAlgorithm SHA256 -TimestampServer $timestamp
    if ($signature.Status -ne "Valid") { throw "Signature invalide : $($signature.StatusMessage)" }
} else {
    Write-Host "    (exécutable non signé : définir SIGN_CERT_THUMBPRINT pour le signer)"
}

Write-Host "4/4 Autotest de l'exécutable…"
$process = Start-Process "$target\EmailScraper.exe" -ArgumentList "--selftest" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "L'autotest de l'exécutable a échoué (voir $target\logs\app.log)." }

Write-Host "OK : $target\EmailScraper.exe"
