# Azure infrastructure

`main.bicep` defines everything for one environment. `../scripts/deploy.sh` wraps it.

| Resource | Purpose | Cost notes |
|---|---|---|
| Container App `jseregs-<env>-api` | FastAPI and the built frontend | Scales to zero when idle |
| Container Apps Job `…-worker` | Daily monitor (`0 11 * * *` UTC = 6 AM ET in winter, 7 AM in summer) | Pay per run |
| Container Apps Job `…-migrate` | `python -m app.bootstrap`, run by every deploy | Pay per run |
| Azure SQL serverless `jse_regs` | Database | Auto-pauses after 60 min idle; first request after a pause takes about 1 min |
| Storage account, container `regs` | Page snapshots and exports | Pennies |
| Container Registry (Basic) | Images | About $5/month |
| Log Analytics | Container logs | 30-day retention |

Secrets (DB URL, storage key, admin passcode, session secret, Azure OpenAI key, optional Teams webhook) are stored as Container Apps secrets. Key Vault is deferred until after the MVP (see `docs/decisions/0001-foundation.md`).

## First deploy

```bash
brew install azure-cli
az login
az account set --subscription "<JSE subscription name or id>"

export SQL_ADMIN_PASSWORD='<strong password>'
export ADMIN_PASSCODE='<passcode for the admin view>'
export AZURE_OPENAI_ENDPOINT='https://jse-openai.openai.azure.com/'
export AZURE_OPENAI_API_KEY='<key>'
export AZURE_OPENAI_DEPLOYMENT='gpt-4.1-mini'     # optional, this is the default
export TEAMS_WEBHOOK_URL='<Workflows webhook>'     # optional; channels can also be added in the admin view
./scripts/deploy.sh dev
```

After the first deploy, set `PUBLIC_BASE_URL` to the printed app URL and run the full deploy once more so links in Teams cards point at the app.

The script:
1. Creates the resource group `jse-regs-dev` (override with `RESOURCE_GROUP=...`, region with `LOCATION=...`).
2. On the first run, deploys the infrastructure with a placeholder image so the registry exists.
3. Builds the image in ACR (no local Docker needed).
4. Runs the migrate job with the new image and waits for it to succeed.
5. Rolls out the image to the API and worker.
6. Prints the app URL.

## Later deploys

```bash
./scripts/deploy.sh dev --app-only   # code changes only, skips Bicep
./scripts/deploy.sh dev              # also applies infra changes
```

Re-running the full deploy needs the same values for every exported variable above.

## Useful commands

```bash
# Run the daily monitor now
az containerapp job start -g jse-regs-dev -n jseregs-dev-worker

# Bulk AI discovery is started from Admin → AI discovery (it runs inside the API app).

# Tail API logs
az containerapp logs show -g jse-regs-dev -n jseregs-dev-api --follow
```

## Not yet verified on Azure

These templates and scripts were written without access to the subscription. On the first real deploy, check:
- `az bicep build -f infra/main.bicep` is clean.
- The Azure OpenAI deployment supports the Responses API `web_search` tool (used by AI discovery). It worked on `jse-openai`/`gpt-4.1-mini` in local testing.
- pymssql connects to Azure SQL over TLS. If it doesn't, try appending `?tds_version=7.4` to `DATABASE_URL`.
