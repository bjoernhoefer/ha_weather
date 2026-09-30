# Azure AI Foundry setup (copyable steps)

`ha_weather` ranks the weather providers automatically from measured accuracy.
An **Azure AI Foundry** deployment is used on top of that to *verify* the result:
the model receives the accuracy statistics, weights them and returns a short
assessment that is shown in the web UI (`POST /api/verify/{location_id}`).

The service runs fine without Azure AI Foundry – the verification endpoint then
reports `"available": false`.

## 1. Prerequisites

```bash
az --version                 # Azure CLI 2.60 or newer
az login
az account set --subscription "<YOUR-SUBSCRIPTION-ID>"
```

## 2. Variables (edit once, copy the rest as is)

```bash
export RG="rg-ha-weather"
export LOCATION="swedencentral"
export FOUNDRY="ha-weather-foundry"      # must be globally unique
export DEPLOYMENT="gpt-4o-mini"
export MODEL="gpt-4o-mini"
export MODEL_VERSION="2024-07-18"
```

## 3. Create the resource group and the Azure AI Foundry resource

```bash
az group create --name "$RG" --location "$LOCATION"

az cognitiveservices account create \
  --name "$FOUNDRY" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --kind AIServices \
  --sku S0 \
  --custom-domain "$FOUNDRY" \
  --yes
```

## 4. Deploy the model

```bash
az cognitiveservices account deployment create \
  --name "$FOUNDRY" \
  --resource-group "$RG" \
  --deployment-name "$DEPLOYMENT" \
  --model-name "$MODEL" \
  --model-version "$MODEL_VERSION" \
  --model-format OpenAI \
  --sku-name GlobalStandard \
  --sku-capacity 10
```

## 5. Read endpoint and key

```bash
export HAW_AZURE_FOUNDRY_ENDPOINT=$(az cognitiveservices account show \
  --name "$FOUNDRY" --resource-group "$RG" --query "properties.endpoint" -o tsv)

export HAW_AZURE_FOUNDRY_API_KEY=$(az cognitiveservices account keys list \
  --name "$FOUNDRY" --resource-group "$RG" --query "key1" -o tsv)

export HAW_AZURE_FOUNDRY_DEPLOYMENT="$DEPLOYMENT"

echo "$HAW_AZURE_FOUNDRY_ENDPOINT"
```

Put the three values into your `.env` file (see `.env.example`) or pass them to
`docker run` / `docker compose`.

## 6. Verify

```bash
curl -s -X POST http://localhost:8080/api/verify/vienna | jq
```

## 7. Optional: run the whole service in Azure Container Instances

Public deployments **must** authenticate every request, therefore
`HAW_DEPLOYMENT_MODE=public` together with `HAW_API_KEYS` is used here.

```bash
export ACR="haweather$RANDOM"
az acr create --resource-group "$RG" --name "$ACR" --sku Basic --admin-enabled true
az acr build --registry "$ACR" --image ha_weather:latest .

export ACR_SERVER=$(az acr show --name "$ACR" --query loginServer -o tsv)
export ACR_USER=$(az acr credential show --name "$ACR" --query username -o tsv)
export ACR_PASSWORD=$(az acr credential show --name "$ACR" --query "passwords[0].value" -o tsv)
export HAW_API_KEY=$(openssl rand -hex 24)

az container create \
  --resource-group "$RG" \
  --name ha-weather \
  --image "$ACR_SERVER/ha_weather:latest" \
  --registry-login-server "$ACR_SERVER" \
  --registry-username "$ACR_USER" \
  --registry-password "$ACR_PASSWORD" \
  --dns-name-label "ha-weather-$RANDOM" \
  --ports 8080 \
  --os-type Linux --cpu 1 --memory 1 \
  --secure-environment-variables \
      HAW_API_KEYS="$HAW_API_KEY" \
      HAW_AZURE_FOUNDRY_API_KEY="$HAW_AZURE_FOUNDRY_API_KEY" \
  --environment-variables \
      HAW_DEPLOYMENT_MODE=public \
      HAW_AZURE_FOUNDRY_ENDPOINT="$HAW_AZURE_FOUNDRY_ENDPOINT" \
      HAW_AZURE_FOUNDRY_DEPLOYMENT="$DEPLOYMENT"

echo "API key: $HAW_API_KEY"
```

Call it with the key:

```bash
curl -s -H "X-API-Key: $HAW_API_KEY" \
  "http://<dns-name-label>.$LOCATION.azurecontainer.io:8080/api/homeassistant/vienna" | jq
```

## 8. Clean up

```bash
az group delete --name "$RG" --yes --no-wait
```
