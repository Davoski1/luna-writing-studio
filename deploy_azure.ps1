# Luna AI Writing Studio - Azure Automated Student Provisioner
# This script uses Azure CLI (az) to spin up your B1/Burstable resources automatically.

$ErrorActionPreference = "Stop"

# 1. Check for Azure CLI
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Luna AI Writing Studio - Azure Student Deployer" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "[Error] Azure CLI ('az') is not installed on this PC." -ForegroundColor Red
    Write-Host "Please install it from: https://aka.ms/installazurecliwindows" -ForegroundColor Yellow
    Write-Host "After installing, restart your terminal and run this script again." -ForegroundColor Yellow
    Exit
}

# 2. Login Check
Write-Host "[Step 1] Verifying Azure login status..." -ForegroundColor Green
try {
    $account = az account show --query name -o tsv 2>$null
    Write-Host "Successfully authenticated as account: $account" -ForegroundColor Gray
} catch {
    Write-Host "No active login found. Initiating 'az login' browser window..." -ForegroundColor Yellow
    az login
}

# Ensure the correct Azure for Students subscription is selected
Write-Host "Setting active subscription to 'Azure for Students'..." -ForegroundColor Gray
az account set --subscription "242395c4-5140-4580-8e17-55336aab8a10"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Warning] Could not set subscription ID explicitly. Attempting to proceed..." -ForegroundColor Yellow
}

# 3. Prompt Configurations (Universal France Central default to satisfy active policy restrictions)
Write-Host "`n[Step 2] Configuring deployment parameters..." -ForegroundColor Green
$ResourceGroup = "luna-writing-studio-rg4"
$Region = Read-Host "Enter Azure Region (Default: francecentral - highly recommended for school subscriptions)"
if ([string]::IsNullOrWhiteSpace($Region)) { $Region = "francecentral" }

$StorageName = "lunawriterstor" + (Get-Random -Minimum 10000 -Maximum 99999)
$DBServerName = "luna-writing-db-" + (Get-Random -Minimum 10000 -Maximum 99999)
$DBAdmin = "lunaadmin"

Write-Host "Admin Username: $DBAdmin" -ForegroundColor Gray
$DBPassword = Read-Host "Enter Database Admin Password (Must be at least 8 characters, letters & numbers)"
if ($DBPassword.Length -lt 8) {
    Write-Host "[Error] Password must be at least 8 characters long." -ForegroundColor Red
    Exit
}

# 4. Provision Resource Group
Write-Host "`n[Step 3] Provisioning Resource Group: $ResourceGroup..." -ForegroundColor Green
az group create --name $ResourceGroup --location $Region --query properties.provisioningState -o tsv
if ($LASTEXITCODE -ne 0) { throw "Resource Group creation failed!" }

# 5. Provision Storage Account
Write-Host "`n[Step 4] Provisioning Free Storage Account ($StorageName)..." -ForegroundColor Green
az storage account create --name $StorageName --resource-group $ResourceGroup --location $Region --sku Standard_LRS --query provisioningState -o tsv
if ($LASTEXITCODE -ne 0) { throw "Storage Account creation failed!" }

# Introduce a small delay to allow storage keys to propagate in Azure AD
Write-Host "Waiting 15 seconds for storage account keys to propagate..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

# Create Container
Write-Host "Creating blob container 'novels'..." -ForegroundColor Gray
$connString = az storage account show-connection-string --name $StorageName --resource-group $ResourceGroup --query connectionString -o tsv
az storage container create --name novels --connection-string $connString --query created -o tsv
if ($LASTEXITCODE -ne 0) { throw "Storage Container creation failed!" }

# 6. Provision PostgreSQL Flexible Server
Write-Host "`n[Step 5] Deploying Burstable B1MS PostgreSQL Server ($DBServerName)..." -ForegroundColor Green
Write-Host "This will take 1-3 minutes. Please wait..." -ForegroundColor Yellow

try {
    # Deploy flexible server directly matching burstable free tiers
    az postgres flexible-server create `
      --resource-group $ResourceGroup `
      --name $DBServerName `
      --location $Region `
      --admin-user $DBAdmin `
      --admin-password $DBPassword `
      --sku-name Standard_B1ms `
      --tier Burstable `
      --storage-size 32 `
      --yes `
      --query provisioningState -o tsv
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL Server creation failed! The region ($Region) might be restricted or capacity limits reached." }
      
    Write-Host "PostgreSQL Server successfully deployed!" -ForegroundColor Green
    
    # Configure Firewalls
    Write-Host "`n[Step 6] Configuring firewall security..." -ForegroundColor Green
    
    # Allow Azure internal connections (FastAPI VM host)
    Write-Host "Enabling Azure internal services rule..." -ForegroundColor Gray
    az postgres flexible-server firewall-rule create `
      --resource-group $ResourceGroup `
      --name $DBServerName `
      --rule-name AllowAllAzureIPs `
      --start-ip-address 0.0.0.0 `
      --end-ip-address 0.0.0.0 `
      --query provisioningState -o tsv
    if ($LASTEXITCODE -ne 0) { throw "AllowAllAzureIPs firewall rule configuration failed!" }

    # Allow local PC IP address
    Write-Host "Allowing your current client IP address..." -ForegroundColor Gray
    # Fetch local public IP
    $clientIP = (Invoke-RestMethod -Uri "https://api.ipify.org")
    az postgres flexible-server firewall-rule create `
      --resource-group $ResourceGroup `
      --name $DBServerName `
      --rule-name AllowLocalPC `
      --start-ip-address $clientIP `
      --end-ip-address $clientIP `
      --query provisioningState -o tsv
    if ($LASTEXITCODE -ne 0) { throw "AllowLocalPC firewall rule configuration failed!" }
      
    Write-Host "Firewall configured successfully." -ForegroundColor Green
    
    # Print clean connection parameters for the user's config
    Write-Host "`n==========================================================" -ForegroundColor Green
    Write-Host "🎉 PROVISIONING COMPLETED SUCCESSFULLY 🎉" -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "Copy these values to your backend environment configurations:" -ForegroundColor Yellow
    Write-Host "DATABASE_URL : postgresql://${DBAdmin}:${DBPassword}@${DBServerName}.postgres.database.azure.com:5432/postgres?sslmode=require" -ForegroundColor Cyan
    Write-Host "AZURE_STORAGE_CONNECTION_STRING : $connString" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Green

} catch {
    Write-Host "`n[Error] The deployment failed during the database phase." -ForegroundColor Red
    Write-Host "This is highly likely an IT Policy Block from your school." -ForegroundColor Yellow
    Write-Host "Here is the raw error detail returned by Azure:" -ForegroundColor Yellow
    Write-Error $_
}
