# ATLAS cloud deployment

This bundle deploys the ATLAS API, a shared-state worker, PostgreSQL, and Redis.
PostgreSQL and Redis remain private to the container network. The Docker-VM
overlay adds Caddy, which is the only service that binds host ports and obtains
the TLS certificate for the configured domain.

## Before deployment

1. Copy `.env.example` to `.env` in this directory. Do not commit the copied
   file.
2. Create unique URL-safe values for every password and API key. A value used
   inside `ATLAS_DATABASE_URL` must be URL-encoded if it contains reserved URL
   characters.
3. Generate the vault key with:

   ```sh
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Put the OpenRouter key in the cloud provider's secret manager. The default
   free-only model is `openrouter/free`; provider credentials are never baked
   into the image.
5. Set `ATLAS_CORS_ORIGINS` to the exact HTTPS origin for any browser client.
   Do not use `*` in production.

## Deploy to a Docker VM

Before running the stack:

1. Point the DNS `A`/`AAAA` record for `ATLAS_DOMAIN` to the VM's public IP.
2. Allow inbound TCP ports 80 and 443 in the VM's cloud firewall. Do not expose
   ports 5432, 6379, or 8000.
3. Install Docker Engine with the Docker Compose plugin on the Linux VM.

### No custom domain yet

For a no-cost preview address, use the VM's public IPv4 address with
[`sslip.io`](https://sslip.io). For example, if the VM IP is `203.0.113.42`,
put these exact values in the VM secret file:

```dotenv
ATLAS_DOMAIN=203-0-113-42.sslip.io
ATLAS_CORS_ORIGINS=https://203-0-113-42.sslip.io
```

`sslip.io` resolves hostnames containing an IPv4 address to that address, so no
DNS record purchase or configuration is required. Caddy can obtain a valid
certificate only after the VM is publicly reachable on ports 80 and 443. Use a
domain you control before treating the service as a long-term production
endpoint.

From the repository root:

```sh
docker compose --env-file deploy/cloud/.env \
  -f deploy/cloud/docker-compose.yml \
  -f deploy/cloud/docker-compose.vm.yml up -d --build
curl --fail https://atlas.example.com/readyz
```

Caddy handles HTTPS and proxies only to the internal API. Validate the full
deployment with `docker compose ... ps` and the public `/readyz` request. If a
deployment fails, leave the previous image running and inspect the failed
service with `docker compose ... logs --tail=200 <service>`.

## Use Supabase for managed PostgreSQL

Use this option when the Docker VM should not store PostgreSQL locally. Create
a Supabase project first, then copy its PostgreSQL connection string from the
project's **Connect** panel into `ATLAS_DATABASE_URL`. A persistent Docker VM
should use the direct connection string where networking permits; use the
Supabase session pooler only when the VM cannot reach the direct endpoint.

```sh
cp deploy/cloud/.env.supabase.example deploy/cloud/.env.supabase
# Edit deploy/cloud/.env.supabase with secrets in an editor on the VM.
chmod 600 deploy/cloud/.env.supabase
bash deploy/cloud/deploy-supabase-vm.sh
```

This stack has no local PostgreSQL container. The API and worker share the
Supabase database through `ATLAS_DATABASE_URL`; Redis remains private on the
VM. Do not expose the Supabase database password or the provider key in chat,
commit history, or a Vercel environment intended for client-side code. The
script validates Compose variables, starts the stack, and checks the public
HTTPS `/readyz` endpoint before it reports success.

## Connect a CLI to the deployed API

Store the operator key outside shell history, then configure the local client:

```sh
export ATLAS_API_URL=https://atlas.example.com
export ATLAS_API_KEY=<operator-key>
atlas server status
```

On PowerShell, use `$env:ATLAS_API_URL` and `$env:ATLAS_API_KEY` instead.

## Operational notes

- The worker selects `PostgresStorage` automatically when `ATLAS_DATABASE_URL`
  is a PostgreSQL URL, so it shares tasks, leases, and approval state with the
  API instead of creating an isolated SQLite database.
- The API refuses to start in production if API keys or explicit browser CORS
  origins are missing. Compose also refuses missing secret values before
  containers start.
- Keep a database backup and roll back by returning the API and worker to the
  previous image tag. Database schema changes must remain backward-compatible.
