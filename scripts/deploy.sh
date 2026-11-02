#!/usr/bin/env bash
# Deploy (or update) one environment to Azure.
#
#   ./scripts/deploy.sh dev            # infra + build image + migrate + roll out
#   ./scripts/deploy.sh dev --app-only # skip the Bicep step
#
# Needs: Azure CLI logged in (`az login`), and these env vars on first run:
#   SQL_ADMIN_PASSWORD, ADMIN_PASSCODE
# Optional: RESOURCE_GROUP (default jse-regs-<env>), LOCATION (default eastus2)
set -euo pipefail

ENV_NAME="${1:?usage: deploy.sh <dev|prod> [--app-only]}"
APP_ONLY="${2:-}"
RG="${RESOURCE_GROUP:-jse-regs-${ENV_NAME}}"
LOCATION="${LOCATION:-eastus2}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"

deploy_infra() {
  local image="$1"
  az deployment group create -g "$RG" -f "$ROOT/infra/main.bicep" \
    -p env="$ENV_NAME" image="$image" \
       sqlAdminPassword="${SQL_ADMIN_PASSWORD:?set SQL_ADMIN_PASSWORD}" \
       adminPasscode="${ADMIN_PASSCODE:?set ADMIN_PASSCODE}" \
    --query properties.outputs -o json
}

out() { az deployment group show -g "$RG" -n main --query "properties.outputs.$1.value" -o tsv; }

if [[ "$APP_ONLY" != "--app-only" ]]; then
  az group create -n "$RG" -l "$LOCATION" -o none
  # First pass creates the registry (with a placeholder image if nothing is pushed yet).
  if ! az deployment group show -g "$RG" -n main >/dev/null 2>&1; then
    deploy_infra "mcr.microsoft.com/k8se/quickstart:latest" >/dev/null
  fi
fi

ACR="$(out acrName)"
SERVER="$(out acrLoginServer)"
IMAGE="$SERVER/jse-regs:$TAG"

echo "==> Building $IMAGE in ACR"
az acr build -r "$ACR" -t "jse-regs:$TAG" "$ROOT" -o none

MIGRATE_JOB="$(out migrateJobName)"
echo "==> Running migrations with the new image"
az containerapp job update -g "$RG" -n "$MIGRATE_JOB" --image "$IMAGE" -o none
EXEC="$(az containerapp job start -g "$RG" -n "$MIGRATE_JOB" --query name -o tsv)"
for _ in $(seq 1 60); do
  STATUS="$(az containerapp job execution show -g "$RG" -n "$MIGRATE_JOB" \
    --job-execution-name "$EXEC" --query properties.status -o tsv)"
  case "$STATUS" in
    Succeeded) break ;;
    Failed|Stopped|Degraded) echo "Migration $EXEC $STATUS; see its logs in the portal" >&2; exit 1 ;;
  esac
  sleep 10
done
[[ "$STATUS" == "Succeeded" ]] || { echo "Migration $EXEC timed out ($STATUS)" >&2; exit 1; }

echo "==> Rolling out $IMAGE"
if [[ "$APP_ONLY" != "--app-only" ]]; then
  deploy_infra "$IMAGE" >/dev/null
else
  az containerapp job update -g "$RG" -n "$(out workerJobName)" --image "$IMAGE" -o none
  az containerapp update -g "$RG" -n "$(out apiName)" --image "$IMAGE" -o none
fi

echo "==> Deployed: $(out appUrl)"
