# ==========================================================
#   Luna AI Writing Studio - Azure B1s VM Provisioner
# ==========================================================
$PSScriptRoot = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition

Write-Host "=========================================" -ForegroundColor Magenta
Write-Host "   LUNA AI WRITING STUDIO - B1s VM DEPLOY" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Magenta

# 1. Lock Active Subscription
Write-Host "[Step 1] Setting active Azure subscription..." -ForegroundColor Green
az account set --subscription "242395c4-5140-4580-8e17-55336aab8a10"
if ($LASTEXITCODE -ne 0) { throw "Could not lock subscription." }

# 2. Configurations
$ResourceGroup = "luna-writing-studio-rg4"
$Region = "francecentral"
$VMName = "luna-writing-vm-" + (Get-Random -Minimum 10000 -Maximum 99999)
$AdminUser = "lunaadmin"
$AdminPassword = "LunaAdmin123!Adeola"

# 3. Create Free B1s VM
Write-Host "`n[Step 2] Provisioning Free Standard_B1s Linux VM ($VMName)..." -ForegroundColor Green
Write-Host "Finding an available region for B1s..." -ForegroundColor Gray

$RegionsToTry = @("spaincentral", "polandcentral", "italynorth", "austriaeast", "francecentral")
$ipAddress = $null
$SuccessfulRegion = $null

foreach ($Reg in $RegionsToTry) {
    Write-Host "Attempting VM creation in region '$Reg'..." -ForegroundColor Gray
    $ipVal = az vm create `
      --resource-group $ResourceGroup `
      --name $VMName `
      --image Ubuntu2204 `
      --size Standard_B1s `
      --admin-username $AdminUser `
      --admin-password $AdminPassword `
      --public-ip-sku Standard `
      --location $Reg `
      --query publicIpAddress -o tsv 2>$null
      
    if ($LASTEXITCODE -eq 0 -and $ipVal) {
        $ipAddress = $ipVal.Trim()
        $SuccessfulRegion = $Reg
        break
    } else {
        Write-Host "VM size Standard_B1s is unavailable or failed in region '$Reg'. Trying next..." -ForegroundColor Yellow
    }
}

if (-not $SuccessfulRegion) { throw "VM creation failed in all allowed student regions!" }
Write-Host "VM successfully created in region '$SuccessfulRegion'! Public IP Address: $ipAddress" -ForegroundColor Green

# 4. Open Port 80 (HTTP) and authorize VM IP on Database Firewall
Write-Host "`n[Step 3] Configuring Network and Database Firewall Rules..." -ForegroundColor Green
az vm open-port --port 80 --resource-group $ResourceGroup --name $VMName --priority 1010
if ($LASTEXITCODE -ne 0) { throw "Failed to open port 80!" }

Write-Host "Authorizing VM IP address ($ipAddress) on PostgreSQL Database firewall..." -ForegroundColor Gray
az postgres flexible-server firewall-rule create `
  --resource-group $ResourceGroup `
  --name "luna-writing-db-53434" `
  --rule-name "AllowVM" `
  --start-ip-address $ipAddress `
  --end-ip-address $ipAddress `
  --query name -o tsv
if ($LASTEXITCODE -ne 0) { throw "Failed to configure database firewall rule!" }

# 5. Generate and Write init_vm.sh Script
Write-Host "`n[Step 4] Generating VM initialization script..." -ForegroundColor Green

$envFile = "$PSScriptRoot\backend\.env"
if (-not (Test-Path $envFile)) {
    throw "Error: backend/.env not found! Please run .\deploy_azure.ps1 first."
}
$envContent = Get-Content $envFile -Raw

$shScript = @"
#!/bin/bash
set -e

echo "=== Starting Linux system updates ==="
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git

echo "=== Creating directories ==="
sudo mkdir -p /home/$AdminUser/writing_agent/backend
sudo chown -R ${AdminUser}:${AdminUser} /home/$AdminUser/writing_agent

echo "=== Writing cloud environment secrets ==="
cat << 'EOF' > /home/$AdminUser/writing_agent/backend/.env
$envContent
EOF
sudo chown ${AdminUser}:${AdminUser} /home/$AdminUser/writing_agent/backend/.env
sudo chmod 600 /home/$AdminUser/writing_agent/backend/.env

echo "=== Seeding API placeholders to prevent initial start failure ==="
cat << 'EOF' > /home/$AdminUser/writing_agent/backend/main.py
from fastapi import FastAPI
app = FastAPI(title="Writing Agent API - VM Placeholder")

@app.get("/api/books")
def list_books():
    return []
EOF
sudo chown ${AdminUser}:${AdminUser} /home/$AdminUser/writing_agent/backend/main.py

echo "=== Initializing Python Virtual Environment ==="
python3 -m venv /home/$AdminUser/writing_agent/venv
/home/$AdminUser/writing_agent/venv/bin/pip install --upgrade pip
/home/$AdminUser/writing_agent/venv/bin/pip install fastapi uvicorn requests pydantic reportlab psycopg2-binary azure-storage-blob gunicorn

echo "=== Creating systemd background service ==="
cat << 'EOF' > /etc/systemd/system/writing-api.service
[Unit]
Description=Luna AI Writing Studio FastAPI Service
After=network.target

[Service]
User=root
WorkingDirectory=/home/$AdminUser/writing_agent/backend
ExecStart=/home/$AdminUser/writing_agent/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:80 main:app
Restart=always
EnvironmentFile=/home/$AdminUser/writing_agent/backend/.env

[Install]
WantedBy=multi-user.target
EOF

echo "=== Activating and starting systemd service ==="
sudo systemctl daemon-reload
sudo systemctl enable writing-api.service
sudo systemctl start writing-api.service

echo "=== VM Initialization Complete! ==="
"@

$shPath = "$PSScriptRoot\init_vm.sh"
Set-Content -Path $shPath -Value $shScript -Encoding utf8NoBOM

# 6. Execute Setup Script on VM
Write-Host "`n[Step 5] Triggering real-time VM setup execution..." -ForegroundColor Green
Write-Host "Installing Python packages and registering systemd service on VM. Please wait..." -ForegroundColor Gray

az vm run-command invoke `
  --resource-group $ResourceGroup `
  --name $VMName `
  --command-id RunShellScript `
  --scripts '@init_vm.sh' `
  --query "value[0].message" -o tsv

if ($LASTEXITCODE -ne 0) { throw "VM setup configuration script failed!" }

# 7. Cleanup and Output Connection Details
Remove-Item $shPath -Force

$connectionInfo = @"
==========================================================
   LUNA AI WRITING STUDIO - B1s VM CONNECTION CARD
==========================================================
VM NAME        : $VMName
RESOURCE GROUP : $ResourceGroup
PUBLIC IP      : $ipAddress
ADMIN USER     : $AdminUser
ADMIN PASSWORD : $AdminPassword
API BASE URL   : http://$ipAddress/api
==========================================================
"@
$connectionInfo | Set-Content -Path "$PSScriptRoot\vm_connection_info.txt"

Write-Host "=========================================" -ForegroundColor Magenta
Write-Host "🎉 VM PROVISIONED & CONFIGURED SUCCESSFULLY 🎉" -ForegroundColor Green
Write-Host "Your Public API URL : http://$ipAddress" -ForegroundColor Cyan
Write-Host "Saved Connection details to: $PSScriptRoot\vm_connection_info.txt" -ForegroundColor Yellow
Write-Host "-----------------------------------------" -ForegroundColor Magenta
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Create two GitHub secrets in your repo:" -ForegroundColor Gray
Write-Host "   - 'AZURE_VM_HOST'     : $ipAddress" -ForegroundColor Gray
Write-Host "   - 'AZURE_VM_PASSWORD' : $AdminPassword" -ForegroundColor Gray
Write-Host "2. Push the GitHub workflow to trigger continuous SSH deployment." -ForegroundColor Gray
Write-Host "=========================================" -ForegroundColor Magenta
