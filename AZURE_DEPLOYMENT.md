# Azure App Service Deployment Guide

## Overview
This guide will help you deploy your Fire Door Survey API to Azure App Service.

## Prerequisites
- Azure subscription
- Azure CLI installed (optional but recommended)
- Your code pushed to GitHub (secrets removed)

## Files Created for Azure Deployment

### 1. `web.config`
- IIS configuration for Azure App Service
- Points to Python 3.11 runtime
- Configures logging and startup settings

### 2. `startup.py`
- Azure startup script
- Uses PORT environment variable from Azure
- Handles debug mode based on environment

### 3. `.deployment`
- Tells Azure which file to use as entry point
- Points to `startup.py`

### 4. Updated `app.py`
- Modified to use Azure PORT environment variable
- Debug mode controlled by FLASK_ENV environment variable

### 5. Updated `requirements.txt`
- Added `gunicorn` and `waitress` for production WSGI servers
- All dependencies pinned to specific versions

## Deployment Methods

### Method 1: Azure Portal (Easiest)

1. **Create App Service**
   - Go to Azure Portal
   - Create Resource → Web App
   - Choose Python 3.11 runtime
   - Select UK South region
   - Choose appropriate pricing tier

2. **Deploy Code**
   - Go to Deployment Center
   - Choose GitHub as source
   - Select your repository: `akashsinghal14/action_api_endpoint_git`
   - Choose branch: `test` (or your preferred branch)
   - Deploy

3. **Configure Environment Variables**
   - Go to Configuration → Application settings
   - Add these settings:
     ```
     YOUR_KEY = your_openai_api_key
     DEV_KEY = your_dev_api_key
     PROD_KEY = your_prod_api_key
     TEST_KEY = your_test_api_key
     DEFAULT_AI_MODEL = gpt-3.5-turbo
     FLASK_ENV = production
     ```

### Method 2: Azure CLI (Recommended)

```bash
# Login to Azure
az login

# Create resource group
az group create --name fire-door-api-rg --location "UK South"

# Create App Service plan
az appservice plan create --name fire-door-api-plan --resource-group fire-door-api-rg --sku B1 --is-linux

# Create web app
az webapp create --resource-group fire-door-api-rg --plan fire-door-api-plan --name your-app-name --runtime "PYTHON|3.11"

# Configure app settings
az webapp config appsettings set --resource-group fire-door-api-rg --name your-app-name --settings \
  YOUR_KEY="your_openai_api_key" \
  DEV_KEY="your_dev_api_key" \
  PROD_KEY="your_prod_api_key" \
  TEST_KEY="your_test_api_key" \
  DEFAULT_AI_MODEL="gpt-3.5-turbo" \
  FLASK_ENV="production"

# Deploy from GitHub
az webapp deployment source config --resource-group fire-door-api-rg --name your-app-name --repo-url https://github.com/akashsinghal14/action_api_endpoint_git.git --branch test --manual-integration
```

### Method 3: GitHub Actions (Most Professional)

1. **Create `.github/workflows/azure-deploy.yml`**
2. **Set up GitHub Secrets**:
   - `AZURE_WEBAPP_NAME`
   - `AZURE_WEBAPP_PUBLISH_PROFILE`
   - `YOUR_KEY`
   - `DEV_KEY`
   - `PROD_KEY`
   - `TEST_KEY`

## Environment Variables Required

| Variable | Description | Example |
|----------|-------------|---------|
| `YOUR_KEY` | Primary OpenAI API key | `sk-...` |
| `DEV_KEY` | Development API key | `sk-...` |
| `PROD_KEY` | Production API key | `sk-...` |
| `TEST_KEY` | Test API key | `sk-...` |
| `DEFAULT_AI_MODEL` | Default AI model | `gpt-3.5-turbo` |
| `FLASK_ENV` | Environment mode | `production` |

## Testing Your Deployment

1. **Check Health Endpoint**
   ```
   GET https://your-app-name.azurewebsites.net/
   ```

2. **Test API Endpoints**
   ```
   POST https://your-app-name.azurewebsites.net/api/action_item/head
   Content-Type: application/json
   
   {
     "value": 5,
     "unit": "mm",
     "api_key": "YOUR_KEY"
   }
   ```

3. **Check Logs**
   - Go to Azure Portal → Your App → Log stream
   - Monitor for any errors

## Troubleshooting

### Common Issues

1. **Module Import Errors**
   - Check `requirements.txt` has all dependencies
   - Ensure Python version is 3.11

2. **Port Binding Issues**
   - Verify `startup.py` uses `os.environ.get('PORT')`
   - Check `web.config` points to correct startup file

3. **API Key Issues**
   - Verify environment variables are set correctly
   - Check Application Settings in Azure Portal

4. **CORS Issues**
   - Ensure `Flask-CORS` is installed
   - Check CORS configuration in `app.py`

### Logs Location
- Application logs: Azure Portal → Your App → Log stream
- Detailed logs: `D:\home\LogFiles\python.log`

## Cost Optimization

- **Free Tier**: 1GB RAM, 1GB storage (limited)
- **Basic B1**: ~£10-15/month (recommended for development)
- **Standard S1**: ~£30-50/month (recommended for production)

## Security Considerations

1. **API Keys**: Never commit real API keys to Git
2. **Environment Variables**: Use Azure Application Settings
3. **HTTPS**: Enabled by default on Azure App Service
4. **CORS**: Configure appropriately for your frontend domain

## Next Steps

1. Deploy using one of the methods above
2. Test all API endpoints
3. Configure custom domain (optional)
4. Set up monitoring and alerts
5. Configure backup and disaster recovery

## Support

- Azure App Service Documentation: https://docs.microsoft.com/en-us/azure/app-service/
- Flask on Azure: https://docs.microsoft.com/en-us/azure/app-service/quickstart-python
- GitHub Actions for Azure: https://github.com/Azure/actions
