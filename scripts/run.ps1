# OpenFund-AI single entrypoint (Windows PowerShell).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --port 8010 --no-backends
#   powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --funds fresh-all
#   powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --install-deps
#   powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --no-chat   # API only, no interactive chat

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..") ).Path
Set-Location $ROOT

# Suppress urllib3 OpenSSL (NotOpenSSLWarning) and resource_tracker warnings in all Python child processes.
$env:PYTHONWARNINGS = "ignore:.*OpenSSL.*::,ignore:.*leaked semaphore.*::"

$port = 8000
$startBackends = 1
$seedDemo = 1
$loadFunds = "existing"   # existing | fresh-symbols | fresh-all | skip
$installDeps = 0
$waitSecs = 8
$startChat = 1

for ($i = 0; $i -lt $args.Count; $i++) {
  $arg = $args[$i]
  switch ($arg) {
    "--port" { $port = [int]$args[$i + 1]; $i++; break }
    "--no-backends" { $startBackends = 0; break }
    "--no-seed" { $seedDemo = 0; break }
    "--funds" { $loadFunds = $args[$i + 1]; $i++; break }
    "--install-deps" { $installDeps = 1; break }
    "--wait" { $waitSecs = [int]$args[$i + 1]; $i++; break }
    "--no-chat" { $startChat = 0; break }
    "-h" { $arg = "--help"; }
    "--help" {
      @"
OpenFund-AI single runner (PowerShell)

Options:
  --port <n>           API port (default 8000)
  --no-backends        Skip starting Postgres/Neo4j/Milvus
  --no-seed            Skip `python -m data_manager populate`
  --funds <mode>       existing | fresh-symbols | fresh-all | skip
  --install-deps       Install Python extras [backends,llm]
  --wait <secs>        Wait after backend start before seed (default 8)
  --no-chat            Start API only; do not launch interactive chat client
"@ | Write-Host
      exit 0
    }
    default {
      Write-Error "Unknown option: $arg"
      exit 1
    }
  }
}

function Resolve-Python {
  $venvPython = Join-Path $ROOT ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) { return $venvPython }
  $py = Get-Command python3 -ErrorAction SilentlyContinue
  if ($py) { return $py.Source }
  $py = Get-Command python -ErrorAction SilentlyContinue
  if ($py) { return $py.Source }
  return "python"
}

$activate = Join-Path $ROOT ".venv\Scripts\Activate.ps1"
if (Test-Path $activate) {
  try { . $activate } catch { Write-Host "Warning: failed to activate venv: $($_.Exception.Message)" }
}

$PYTHON = Resolve-Python

if (-not (Test-Path (Join-Path $ROOT ".env"))) {
  $envExample = Join-Path $ROOT ".env.example"
  if (Test-Path $envExample) {
    Copy-Item $envExample (Join-Path $ROOT ".env")
    Write-Host "Created .env from .env.example at $ROOT\.env"
    Write-Host "Edit .env (LLM_API_KEY is required) then re-run scripts\\run.ps1"
    exit 0
  } else {
    Write-Error "Missing .env and .env.example"
    exit 1
  }
}

# Load .env into environment variables (simple KEY=VALUE parsing)
Get-Content (Join-Path $ROOT ".env") | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#")) { return }
  if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$") {
    $key = $matches[1]
    $value = $matches[2]
    if ($value.StartsWith("\"") -and $value.EndsWith("\"")) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    Set-Item -Path "Env:$key" -Value $value
  }
}

if ($installDeps -eq 1) {
  if (-not (Test-Path (Join-Path $ROOT ".venv"))) {
    & $PYTHON -m venv (Join-Path $ROOT ".venv")
  }
  $activate = Join-Path $ROOT ".venv\Scripts\Activate.ps1"
  if (Test-Path $activate) { . $activate }
  & $PYTHON -m pip install -e ".[backends,llm]"
}

if ($startBackends -eq 1) {
  function Test-Docker {
    return (Get-Command docker -ErrorAction SilentlyContinue) -ne $null
  }

  function Wait-Port([string]$host, [int]$port, [int]$maxSecs) {
    $elapsed = 0
    while ($elapsed -lt $maxSecs) {
      try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($host, $port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(2000)
        if ($ok -and $client.Connected) { $client.Close(); return $true }
        $client.Close()
      } catch { }
      Start-Sleep -Seconds 2
      $elapsed += 2
    }
    return $false
  }

  function Parse-PostgresUrl([string]$url) {
    # postgres://user:pass@host:port/db
    $pattern = '^postgres(?:ql)?://([^:/?#]+)(?::([^@/?#]*))?@([^:/?#]+)(?::(\d+))?/([^/?#]+)'
    if ($url -match $pattern) {
      $port = 5432
      if ($matches[4]) { $port = [int]$matches[4] }
      return @{
        user = $matches[1]
        pass = $matches[2]
        host = $matches[3]
        port = $port
        db   = $matches[5]
      }
    }
    return $null
  }

  function Start-Postgres {
    if (-not $env:DATABASE_URL) { Write-Host "PostgreSQL: skipped"; return }
    $info = Parse-PostgresUrl $env:DATABASE_URL
    if (-not $info) { Write-Host "PostgreSQL: DATABASE_URL not parseable; skipped"; return }
    if ($info.host -notin @("localhost", "127.0.0.1")) { Write-Host "PostgreSQL: non-local host; skipped"; return }
    if (-not (Test-Docker)) { Write-Host "PostgreSQL: docker not found"; return }
    $name = "openfund-postgres"
    if (docker ps --format "{{.Names}}" | Select-String -Quiet "^$name$") { Write-Host "PostgreSQL: already running"; return }
    if (docker ps -a --format "{{.Names}}" | Select-String -Quiet "^$name$") {
      docker start $name | Out-Null
      Write-Host "PostgreSQL: started existing container"
      return
    }
    $pgUser = $info.user
    $pgPass = $info.pass
    $pgDb = $info.db
    $pgPort = $info.port
    $vol = Join-Path $ROOT "volumes\postgres"
    New-Item -ItemType Directory -Force -Path $vol | Out-Null
    $args = @(
      "run","-d","--name",$name,
      "-e","POSTGRES_USER=$pgUser",
      "-e","POSTGRES_DB=$pgDb",
      "-p","$pgPort`:5432",
      "-v","$vol:/var/lib/postgresql/data"
    )
    if ($pgPass) {
      $args += @("-e","POSTGRES_PASSWORD=$pgPass")
    } else {
      $args += @("-e","POSTGRES_HOST_AUTH_METHOD=trust")
      Write-Host "PostgreSQL: no password in DATABASE_URL; using trust auth"
    }
    $args += "postgres:16"
    docker @args | Out-Null
    Write-Host "PostgreSQL: started new container"
  }

  function Start-Neo4j {
    if (-not $env:NEO4J_URI) { Write-Host "Neo4j: skipped"; return }
    if ($env:NEO4J_URI -notmatch "localhost|127\.0\.0\.1") { Write-Host "Neo4j: non-local host; skipped"; return }
    if (-not (Test-Docker)) { Write-Host "Neo4j: docker not found"; return }
    $name = "openfund-neo4j"
    if (docker ps --format "{{.Names}}" | Select-String -Quiet "^$name$") { Write-Host "Neo4j: already running"; return }
    if (docker ps -a --format "{{.Names}}" | Select-String -Quiet "^$name$") {
      docker start $name | Out-Null
      Write-Host "Neo4j: started existing container"
      return
    }
    $neo4jUser = $env:NEO4J_USER
    $neo4jPass = $env:NEO4J_PASSWORD
    $vol = Join-Path $ROOT "volumes\neo4j"
    New-Item -ItemType Directory -Force -Path $vol | Out-Null
    $args = @(
      "run","-d","--name",$name,
      "-p","7474:7474","-p","7687:7687",
      "-v","$vol:/data"
    )
    if ($neo4jUser -and $neo4jPass) {
      $args += @("-e","NEO4J_AUTH=$neo4jUser/$neo4jPass")
    } else {
      $args += @("-e","NEO4J_AUTH=none")
      Write-Host "Neo4j: no NEO4J_USER/NEO4J_PASSWORD; auth disabled"
    }
    $args += "neo4j:5"
    docker @args | Out-Null
    Write-Host "Neo4j: started new container"
  }

  function Start-Milvus {
    if (-not $env:MILVUS_URI) { Write-Host "Milvus: skipped"; return }
    if ($env:MILVUS_URI -notmatch "localhost|127\.0\.0\.1") { Write-Host "Milvus: non-local host; skipped"; return }
    if (-not (Test-Docker)) { Write-Host "Milvus: docker not found"; return }
    $name = "milvus-standalone"
    if (docker ps --format "{{.Names}}" | Select-String -Quiet "^$name$") { Write-Host "Milvus: already running"; return }
    if (docker ps -a --format "{{.Names}}" | Select-String -Quiet "^$name$") {
      docker start $name | Out-Null
      Write-Host "Milvus: started existing container"
      return
    }
    $cfgDir = Join-Path $ROOT "scripts\milvus"
    $vol = Join-Path $ROOT "volumes\milvus"
    New-Item -ItemType Directory -Force -Path $vol | Out-Null
    docker run -d `
      --name $name `
      --security-opt seccomp=unconfined `
      -e ETCD_USE_EMBED=true `
      -e ETCD_DATA_DIR=/var/lib/milvus/etcd `
      -e ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml `
      -e COMMON_STORAGETYPE=local `
      -e DEPLOY_MODE=STANDALONE `
      -v "$vol:/var/lib/milvus" `
      -v "$cfgDir/embedEtcd.yaml:/milvus/configs/embedEtcd.yaml:ro" `
      -v "$cfgDir/user.yaml:/milvus/configs/user.yaml:ro" `
      -p 19530:19530 `
      -p 9091:9091 `
      milvusdb/milvus:v2.6.11 `
      milvus run standalone | Out-Null
    Write-Host "Milvus: started new container"
  }

  Write-Host "==> Starting configured local backends"
  Start-Postgres
  Start-Neo4j
  Start-Milvus
  Write-Host "==> Waiting ${waitSecs}s for backends..."
  Start-Sleep -Seconds $waitSecs
  if ($env:NEO4J_URI -and ($env:NEO4J_URI -match "localhost|127\.0\.0\.1")) {
    if (Wait-Port "127.0.0.1" 7687 45) { Write-Host "Neo4j: port 7687 ready" }
    else { Write-Host "Neo4j: port 7687 not ready after 45s" }
  }
}

if (Get-Command createdb -ErrorAction SilentlyContinue) {
  & createdb openfund | Out-Null
}

if ($seedDemo -eq 1) {
  Write-Host "==> Seeding backend demo baseline"
  try { & $PYTHON -m data_manager populate } catch { }
}

$fundsFile = Join-Path $ROOT "datasets\combined_funds.json"
if ($loadFunds -ne "skip" -and (Test-Path $fundsFile)) {
  $skipFundLoad = 0
  if ($loadFunds -eq "existing" -and $env:DATABASE_URL) {
    $check = @"
import os, sys
try:
    import psycopg2
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM fund_info LIMIT 1')
    if cur.fetchone():
        sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(2)
"@
    & $PYTHON -c $check
    if ($LASTEXITCODE -eq 0) { $skipFundLoad = 1 }
  }
  if ($skipFundLoad -eq 1) {
    Write-Host "==> Skipping fund load (backend already has fund data)"
  } else {
    Write-Host "==> Loading fund dataset ($loadFunds)"
    switch ($loadFunds) {
      "existing" { & $PYTHON -m data_manager distribute-funds --file $fundsFile --load-mode existing }
      "fresh-symbols" { & $PYTHON -m data_manager distribute-funds --file $fundsFile --load-mode fresh --fresh-scope symbols }
      "fresh-all" { & $PYTHON -m data_manager distribute-funds --file $fundsFile --load-mode fresh --fresh-scope all }
      default { Write-Error "Unknown --funds mode: $loadFunds"; exit 1 }
    }
  }
}

Write-Host "==> Starting live API on port ${port}"
if ($startChat -eq 0) {
  & $PYTHON main.py --serve --port $port
  exit $LASTEXITCODE
}

$proc = Start-Process -FilePath $PYTHON -ArgumentList @("main.py", "--serve", "--port", "$port") -PassThru

# Wait for server to be ready (/openapi.json)
$ready = $false
for ($i = 1; $i -le 15; $i++) {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${port}/openapi.json" -UseBasicParsing -TimeoutSec 2
    if ($resp.StatusCode -eq 200) { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 1
}
if (-not $ready) {
  Write-Error "API did not become ready in time"
  try { Stop-Process -Id $proc.Id -Force } catch { }
  exit 1
}

Write-Host "==> Checking API and LLM..."
& $PYTHON (Join-Path $ROOT "scripts\check_health.py") --port $port

& $PYTHON (Join-Path $ROOT "scripts\chat_cli.py") --port $port

try { Stop-Process -Id $proc.Id -Force } catch { }
