# install_way2agi.ps1 – Cross-Platform Installer (Windows + Linux)
# Neueste Repo-Version (15. Maerz 2026) + Streamlit-GUI
# Usage: pwsh install_way2agi.ps1

function Install-Way2AGI {
    param([string]$RepoUrl = "https://github.com/Wittmann1988/Way2AGI-public.git")
    Write-Host "Way2AGI Installation – neueste Version (dashboard/ + gateway/ integriert)"

    # OS-Erkennung
    $IsWin = $IsWindows
    $Git = if ($IsWin) { "git.exe" } else { "git" }
    $InstallDir = Join-Path $PSScriptRoot "Way2AGI"

    # 1. Clone / Pull (frische Version)
    if (-not (Test-Path $InstallDir)) {
        & $Git clone $RepoUrl $InstallDir
    }
    Set-Location $InstallDir
    & $Git pull

    # 2. Auto-Detect Hardware + Nodes
    Write-Host "Auto-Erkennung: Nodes, GPU, Ollama..."
    if ($IsWin) {
        try { Get-WmiObject Win32_VideoController | Select-Object Name, AdapterRAM } catch { Write-Host "GPU-Erkennung: WMI nicht verfuegbar" }
    } else {
        try { nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null } catch { Write-Host "nvidia-smi nicht gefunden — kein NVIDIA GPU oder Treiber fehlt" }
    }

    # Node-Scan (network_manager/)
    if (Test-Path "network_manager") {
        try { python -m network_manager.scan_nodes } catch { Write-Host "Node-Scan uebersprungen (scan_nodes nicht verfuegbar)" }
    }

    # 3. Wizard + .env
    if (Test-Path "wizard.sh") {
        if (-not $IsWin) { chmod +x wizard.sh; ./wizard.sh }
        else { Write-Host "wizard.sh uebersprungen (Windows — nutze GUI stattdessen)" }
    }
    if (-not (Test-Path ".env")) {
        if (Test-Path ".env.example") { Copy-Item ".env.example" ".env" }
        else {
            @"
# Way2AGI Environment Configuration
PRIMARY_MODEL=qwen2:7b
ROUND1=llama3.2:3b
ROUND2=phi4:3.8b
MEMORY_DB=/data/elias-memory/memory.db
OLLAMA_HOST=http://localhost:11434
"@ | Out-File -FilePath ".env" -Encoding utf8
        }
    }

    # 4. Python Dependencies
    Write-Host "Installiere Python-Abhaengigkeiten..."
    pip install -r requirements.txt --quiet 2>$null
    pip install streamlit --quiet 2>$null

    # 5. Node.js Dependencies (falls pnpm verfuegbar)
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        Write-Host "Installiere Node.js-Abhaengigkeiten..."
        pnpm install
    } else {
        Write-Host "pnpm nicht gefunden — TypeScript-Module uebersprungen"
    }

    # 6. INTERAKTIVE ABFRAGE: API-Keys
    $HasAPI = Read-Host "Hast du API-Keys fuer Groq/OpenAI/xAI/Gemini? (j/n)"
    if ($HasAPI -eq "j") {
        $keys = Read-Host "Gib deine Keys ein (Format: GROQ_KEY=xxx OPENAI_KEY=yyy)"
        foreach ($kv in $keys -split " ") {
            Add-Content .env $kv
        }
    } else {
        Write-Host "-> Nutze kostenlose Fallbacks (Groq free tier, OpenRouter)"
    }

    # 7. Ollama + Lokale Modelle registrieren
    Write-Host "Ollama-Modelle erkennen..."
    try {
        $models = python -c "import ollama; print([m['name'] for m in ollama.list()['models']])" 2>$null
        Write-Host "Verfuegbare Modelle: $models"
    } catch {
        Write-Host "Ollama nicht erreichbar — Modelle koennen spaeter konfiguriert werden"
    }

    $primary = Read-Host "Fuehrendes Modell als primaerer Ansprechpartner? (z.B. qwen2:7b)"
    $round1 = Read-Host "Roundtable-Instanz 1 (z.B. llama3.2:3b)?"
    $round2 = Read-Host "Roundtable-Instanz 2 (z.B. phi4:3.8b)?"

    # Aktualisiere .env mit Modell-Konfiguration
    $envContent = Get-Content .env -Raw
    if ($envContent -match "PRIMARY_MODEL=") {
        $envContent = $envContent -replace "PRIMARY_MODEL=.*", "PRIMARY_MODEL=$primary"
    } else {
        Add-Content .env "PRIMARY_MODEL=$primary"
    }
    if ($envContent -match "ROUND1=") {
        $envContent = $envContent -replace "ROUND1=.*", "ROUND1=$round1"
    } else {
        Add-Content .env "ROUND1=$round1"
    }
    if ($envContent -match "ROUND2=") {
        $envContent = $envContent -replace "ROUND2=.*", "ROUND2=$round2"
    } else {
        Add-Content .env "ROUND2=$round2"
    }
    $envContent | Out-File -FilePath ".env" -Encoding utf8

    # 8. GUI erzeugen (cross-platform via Streamlit)
    if (-not (Test-Path "way2agi_gui.py")) {
        Write-Host "Streamlit-GUI bereits vorhanden."
    }

    # 9. Start
    Write-Host ""
    Write-Host "Installation fertig!"
    Write-Host "  CLI starten:  ./way2agi.sh  (Linux) oder way2agi.bat (Windows)"
    Write-Host "  GUI starten:  streamlit run way2agi_gui.py"
    Write-Host ""

    if ($IsWin) {
        Start-Process "streamlit" "run way2agi_gui.py"
    } else {
        Start-Process "streamlit" "run way2agi_gui.py --server.headless true"
    }
    Write-Host "GUI laeuft unter http://localhost:8501"
}

Install-Way2AGI
