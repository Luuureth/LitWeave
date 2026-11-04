$ErrorActionPreference = 'Stop'

Write-Host 'Starting LitWeave backend on port 4000...'
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'Set-Location "' + (Get-Location).Path + '\litweave"; npm run server'
Start-Sleep -Seconds 2
Write-Host 'Starting LitWeave frontend on port 5173...'
npm run dev
