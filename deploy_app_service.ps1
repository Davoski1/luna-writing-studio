# ==========================================================
#   Luna AI Writing Studio - Azure App Service Provisioner
# ==========================================================
$PSScriptRoot = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition

Write-Host "=========================================" -ForegroundColor Magenta
Write-Host "   LUNA AI WRITING STUDIO - WEB APP DEPLOY" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Magenta

# 1. Lock Active Subscription
Write-Host "[Step 1] Setting active Azure subscription..." -ForegroundColor Green
az account set --subscription "242395c4-5140-4580-8e17-55336aab8a10"
if ($LASTEXITCODE -ne 0) { throw "Could not lock subscription." }

# 2. Configurations
$ResourceGroup = "luna-writing-studio-rg4"
$Region = "francecentral"
$WebAppName = "luna-writing-api-" + (Get-Random -Minimum 10000 -Maximum 99999)
$AppServicePlanName = "luna-writing-service-plan"

# 3. Create Free App Service Plan
Write-Host "`n[Step 2] Provisioning Free Linux F1 App Service Plan ($AppServicePlanName)..." -ForegroundColor Green
az appservice plan create `
  --name $AppServicePlanName `
  --resource-group $ResourceGroup `
  --location $Region `
  --sku F1 `
  --is-linux `
  --query provisioningState -o tsv

if ($LASTEXITCODE -ne 0) { throw "App Service Plan creation failed!" }

# 4. Create Web App
Write-Host "`n[Step 3] Provisioning Linux Python 3.10 Web App ($WebAppName)..." -ForegroundColor Green
$proc = Start-Process az -ArgumentList "webapp create --name $WebAppName --resource-group $ResourceGroup --plan $AppServicePlanName --runtime `"PYTHON|3.10`" --query state -o tsv" -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -ne 0) { throw "Web App creation failed!" }

# 5. Load and Inject Environment Settings from backend/.env
Write-Host "`n[Step 4] Reading environment configuration from backend/.env..." -ForegroundColor Green
$envFile = "$PSScriptRoot\backend\.env"
if (-not (Test-Path $envFile)) {
    throw "Error: backend/.env not found! Please run .\deploy_azure.ps1 first."
}

$settings = @()
Get-Content $envFile | Where-Object { $_ -match '=' -and $_ -notmatch '^#' } | ForEach-Object {
    $trimmedLine = $_.Trim()
    if ($trimmedLine) {
        $settings += $trimmedLine
    }
}

Write-Host "Uploading application settings directly to Azure Portal configuration..." -ForegroundColor Gray
az webapp config appsettings set `
  --name $WebAppName `
  --resource-group $ResourceGroup `
  --settings $settings `
  --query "[].name" -o table

if ($LASTEXITCODE -ne 0) { throw "Azure application settings configuration failed!" }

# 6. Export GitHub Actions Publish Profile XML
Write-Host "`n[Step 5] Exporting secure GitHub Actions Publish Profile..." -ForegroundColor Green
$xmlPath = "$PSScriptRoot\publish_profile.xml"

az webapp deployment list-publishing-profiles `
  --name $WebAppName `
  --resource-group $ResourceGroup `
  --xml > $xmlPath

if ($LASTEXITCODE -ne 0) { throw "Publish Profile export failed!" }

Write-Host "=========================================" -ForegroundColor Magenta
Write-Host "🎉 APP SERVICE PROVISIONED SUCCESSFULLY 🎉" -ForegroundColor Green
Write-Host "Your Public API URL : https://$WebAppName.azurewebsites.net" -ForegroundColor Cyan
Write-Host "Publish Profile saved to: $xmlPath" -ForegroundColor Yellow
Write-Host "-----------------------------------------" -ForegroundColor Magenta
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Create a GitHub secret named 'AZURE_WEBAPP_PUBLISH_PROFILE' in your repo." -ForegroundColor Gray
Write-Host "2. Paste the contents of '$xmlPath' into that secret." -ForegroundColor Gray
Write-Host "3. Push the GitHub workflow (.github/workflows/deploy.yml) to trigger the deploy." -ForegroundColor Gray
Write-Host "=========================================" -ForegroundColor Magenta
