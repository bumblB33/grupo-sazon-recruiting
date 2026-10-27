# Troubleshooting and demo runbook

Commands run and checks made to bring the stack up on a laptop with a public tunnel for the Twilio WhatsApp sandbox. Each section records what was run, what it showed, and what to do when it does not.

The demo scripts live outside the repo in `~/sazon-demo/`, so no secret or tunnel URL is ever committed. `.env` is never edited by a script.

## Layout outside the repo

| File | Purpose |
|---|---|
| `~/sazon-demo/compose.demo.yaml` | Compose override: dev mode, generated session secret, recruiter domain, short silence thresholds, 60 s sweep, 3 s candidate page refresh, webhook URL from `TUNNEL_URL`. |
| `~/sazon-demo/demo.env` | Written by the launcher. One line, `TUNNEL_URL=https://...`. Read by compose for variable substitution. |
| `~/sazon-demo/demo-up.sh` | Starts the tunnel, writes `demo.env`, brings the stack up, waits for the API, invites the demo recruiter, prints the URLs to paste. |
| `~/sazon-demo/demo-login.sh` | Requests a login link for the demo recruiter and prints it from the container's stderr. |
| `~/sazon-demo/demo-down.sh` | Stops the stack and the tunnel. Keeps the `mongo-data` volume. |
| `~/sazon-demo/cloudflared.log`, `cloudflared.pid` | Tunnel output and process id. |

## 1. Install cloudflared

`cloudflared` is Cloudflare's tunnel client. Verified before installing: GitHub `cloudflare/cloudflared`, Apache-2.0, release built by Cloudflare's bot; Cloudflare's docs name `pkg.cloudflare.com` as the install source. There is no `cloudflared` on PyPI, so never `pip install` it.

This machine is Linux Mint 22.3, which is Ubuntu 24.04 `noble`. Vendor apt repository with the key pinned by `signed-by`:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared noble main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
cloudflared --version
```

Result on this machine: `cloudflared version 2026.10.5` at `/usr/local/bin/cloudflared`.

A quick tunnel (`cloudflared tunnel --url ...`) needs no account. Its `https://<words>.trycloudflare.com` URL changes every time the tunnel process restarts. A stable hostname needs a domain on a Cloudflare account and a named tunnel; not used here.

## 2. Build the image

The image must be rebuilt after any dependency change. It was stale after `logfire[...]` was added.

```bash
docker compose build api
```

## 3. Bring the stack up

```bash
~/sazon-demo/demo-up.sh
```

What it does, in order:

1. Checks `docker`, `cloudflared`, `curl` exist, the Docker daemon answers, and `.env` exists in the repo.
2. Starts `cloudflared tunnel --url http://localhost:8000 --no-autoupdate` in the background unless the pid file points at a live process.
3. Polls the tunnel log up to 60 s for the `trycloudflare.com` URL and writes it to `demo.env`.
4. Runs `docker compose --project-directory <repo> --env-file ~/sazon-demo/demo.env -f compose.yaml -f ~/sazon-demo/compose.demo.yaml up -d --remove-orphans`. The API reads `SCREENING_TWILIO_WEBHOOK_URL` at start, so a new tunnel URL recreates the `api` container.
5. Polls `http://localhost:8000/docs` up to 60 s.
6. Runs `screening-admin invite demo@gruposazon.com` inside `api`. The invite is an upsert, so repeating it is safe.
7. Prints the tunnel URL, the Twilio webhook URL to paste, and the login page.

Override the recruiter address with `RECRUITER_EMAIL=you@gruposazon.com ~/sazon-demo/demo-up.sh`. The domain must be in `SCREENING_RECRUITER_EMAIL_DOMAINS` in the override.

## 4. Prove the tunnel before touching Twilio

Known-positive control, then the negative:

```bash
URL=$(cut -d= -f2 ~/sazon-demo/demo.env)
curl -s -o /dev/null -w "%{http_code}\n" "$URL/docs"
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$URL/webhook/whatsapp" -d "From=whatsapp:%2B34600&Body=hi&MessageSid=x"
```

Expected: `200` then `401`. The 200 proves the public URL reaches the API. The 401 proves the Twilio signature check is live outside dev mode: an unsigned request is refused, a request Twilio signs for the exact URL in the console is accepted.

If the first is not 200: `tail ~/sazon-demo/cloudflared.log` for the tunnel, `docker compose logs api` for the app.

## 5. Twilio sandbox

In the Twilio console, Messaging, Try it out, Send a WhatsApp message, Sandbox settings:

1. "When a message comes in": the webhook URL the launcher printed, method POST. It must match `SCREENING_TWILIO_WEBHOOK_URL` character for character, because the signature covers the URL.
2. Join the sandbox from the phone with the join phrase shown on that page.
3. The sandbox number must equal `SCREENING_TWILIO_WHATSAPP_FROM` in `.env`.

After every tunnel restart, repeat step 1 with the new URL. Nothing else changes.

## 6. Recruiter login

Dev mode in the override routes the login email to the container's stderr instead of SendGrid.

```bash
~/sazon-demo/demo-login.sh
```

Prints a link like `http://localhost:8000/recruiter/login/<token>`. Open it, click confirm. The link is single use and expires in 15 minutes. Run the script again for a new one.

## 7. Watch a live screening

```bash
docker compose -f compose.yaml -f ~/sazon-demo/compose.demo.yaml logs -f api
```

Open `http://localhost:8000/recruiter/candidates/<E.164 phone>` for the inspector. The page reloads itself every 3 s while the conversation is open (`SCREENING_CANDIDATE_PAGE_REFRESH_SECONDS` in the override).

Silence thresholds in the override, in minutes: nudge at 3 and 6, abandon at 12, opener retry at 3, opener abandon at 12. The sweep runs every 60 s. A paused take is abandoned by the sweep.

## 8. Stop

```bash
~/sazon-demo/demo-down.sh
```

Runs `docker compose down` without `-v`, so the conversations in `mongo-data` survive, and kills the tunnel. Never run `docker compose down -v` before the recording.

## Warnings seen and their meaning

- `zsh: no such file or directory: tunnel` after pasting a command with `<tunnel>` in it. The angle brackets are a placeholder. zsh read `<tunnel>` as a file redirect. Replace it with the real URL, or use the launcher, which never asks for a paste.
- `service "api" is not running` from `docker compose exec`. The stack is down, usually because the previous command failed. Run `demo-up.sh`.
- `WRN ... GID ... is not within ping_group_range` and `ICMP proxy feature is disabled` from cloudflared. The ICMP proxy serves `ping` through private-network tunnels for WARP clients. An HTTP quick tunnel never uses it. Ignore. To silence it, a system-wide kernel change: `sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"`, persisted in `/etc/sysctl.d/99-cloudflared.conf`.
- `InsecureKeyLengthWarning` from PyJWT in the test suite. Tests use a short session secret on purpose. The override generates a 32-byte secret.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Twilio's debugger shows a webhook fetch error, or the phone gets no reply | Webhook URL in the console differs from `SCREENING_TWILIO_WEBHOOK_URL`, or the tunnel restarted | Re-run `demo-up.sh`, paste the printed URL into the console |
| Webhook answers 401 to Twilio | `SCREENING_TWILIO_AUTH_TOKEN` in `.env` is not the account's auth token, or the URL mismatch above | Check the token in the Twilio console, then the URL |
| Webhook answers 503 | Twilio auth token unset and dev mode off | Set the token in `.env`, or dev mode in the override |
| `POST /candidates` answers 409 | The phone already has a conversation | Use another number, or the demo reset once built |
| Reply never arrives but the inspector shows the turn | Outbound is TwiML on the webhook response, so the turn did reply; Twilio could not deliver | Re-send the join phrase from the phone. How long a sandbox join lasts is unverified (STATUS open question) |
| First reply takes long or 500s | Provider key missing or the org key lacks `PROJECT_ANTHROPIC_WORKSPACE_ID` | `docker compose logs api` for `ProviderKeyMissingError` or a 400 from the provider |
| Login link not printed by `demo-login.sh` | Address not invited or domain not allowed | `docker compose exec api screening-admin invite <email>`; domain in the override |
| `pymongo.errors.ServerSelectionTimeoutError` in tests | mongod died at Docker's default open-file limit | `docker logs` for `Too many open files`; the test container sets `nofile=65536` |
