# Deployment guide

This guide covers putting the app on Azure, updating it later, and keeping it healthy. One script does most of the work.

## What gets created

Everything goes into one Azure resource group (`jse-regs-dev` by default):

| Piece | What it does |
|---|---|
| Container App (`…-api`) | Runs the website and the API |
| Container Apps Job (`…-worker`) | The daily check, every morning at 6 AM Eastern |
| Container Apps Job (`…-migrate`) | Updates the database before each release |
| Azure SQL (serverless) | The database. It pauses when idle to save money |
| Storage account | Saved copies of web pages and uploaded PDFs |
| Container Registry | Stores the app image |
| Log Analytics | Logs |

All of this is described in `infra/main.bicep`.

## Before you start

You'll need:

1. Access to JSE's Azure subscription, with permission to create resources
2. The Azure CLI: `brew install azure-cli`
3. The Azure OpenAI details: endpoint, key and deployment name (currently the `jse-openai` resource with `gpt-4.1-mini`)
4. Optionally, a Teams webhook URL for the daily summary. You can also add one later from the admin screen.

You don't need Docker on your computer. The image is built in Azure.

## First deployment

```bash
az login
az account set --subscription "<JSE subscription name or id>"

export SQL_ADMIN_PASSWORD='<a strong password>'
export ADMIN_PASSCODE='<the passcode for the admin view>'
export AZURE_OPENAI_ENDPOINT='https://jse-openai.openai.azure.com/'
export AZURE_OPENAI_API_KEY='<key>'
export AZURE_OPENAI_DEPLOYMENT='gpt-4.1-mini'
export TEAMS_WEBHOOK_URL='<webhook url>'      # optional

./scripts/deploy.sh dev
```

The script:
1. creates the resource group and all the pieces above
2. builds the app image in Azure
3. updates the database and waits until that finishes
4. starts the new version
5. prints the app's address

Save the passwords somewhere safe, like JSE's password manager. You need the same values every time you run the full deploy.

### One more step after the first deploy

Teams messages include links back to the app, so the app needs to know its own address. Copy the address the script printed and run the deploy once more:

```bash
export PUBLIC_BASE_URL='https://<the address it printed>'
./scripts/deploy.sh dev
```

### Check that it worked

1. Open the address. You should see the map.
2. Go to `/api/health`. It should say `"status":"ok"`.
3. Go to `/admin` and log in with your passcode.
4. In **Teams**, add your channel and click **Send test**.
5. In **Jobs & health**, start the daily job by hand (see below) and check that it shows "succeeded".

## Releasing an update

For code changes only, which is the usual case:

```bash
./scripts/deploy.sh dev --app-only
```

If you also changed `infra/main.bicep` or any settings, run the full deploy with all the exported values from above:

```bash
./scripts/deploy.sh dev
```

Database changes are applied automatically before the new version starts. If that step fails, the old version keeps running.

## Production

Production uses the same steps with `prod` instead of `dev`:

```bash
./scripts/deploy.sh prod
```

Before production, the plan calls for:
- real sign-in with Microsoft accounts instead of the shared passcode
- moving secrets to Key Vault
- a JSE engineer signing off on the final list of categories

## Day-to-day operations

```bash
# Run the daily check right now
az containerapp job start -g jse-regs-dev -n jseregs-dev-worker

# Watch the app's logs
az containerapp logs show -g jse-regs-dev -n jseregs-dev-api --follow

# See past runs of the daily job
az containerapp job execution list -g jse-regs-dev -n jseregs-dev-worker -o table
```

- **Changing the time of the daily check:** the `dailyCron` setting in `infra/main.bicep`, in UTC.
- **Switching AI models:** change `AZURE_OPENAI_DEPLOYMENT` and run the full deploy. Nothing in the code is tied to one model.
- **Changing the admin passcode:** change `ADMIN_PASSCODE` and run the full deploy.
- **Rotating the AI key:** change `AZURE_OPENAI_API_KEY` and run the full deploy.
- **AI discovery** runs inside the app, not as a separate job. Start it from **Admin → AI discovery**.

## When something goes wrong

| Problem | What to check |
|---|---|
| The site won't load | `az containerapp logs show …` for the API. The database may be waking up from a pause, so give it a minute and refresh |
| The deploy stopped at the migrate step | `az containerapp job execution list` for the migrate job, then read that run's logs. The old version is still running |
| No Teams summary this morning | **Admin → Jobs & health**. If the daily check is red, open its logs in Azure. Also check the channel is still listed in **Teams** |
| AI steps fail | The key or deployment name is wrong, or the Azure OpenAI quota is used up. The cost panel in **Jobs & health** shows recent use |
| The database won't connect | Try adding `?tds_version=7.4` to the database address in `infra/main.bicep` |

## Not tested on Azure yet

These files were written without access to JSE's subscription. On the first real deploy, keep an eye on:
- `az bicep build -f infra/main.bicep` finishing without errors
- the database connection (see the table above)
- AI discovery's web search working on the production AI resource. It works on `jse-openai`.

More technical detail is in `infra/README.md`.
