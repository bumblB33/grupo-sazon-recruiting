# Troubleshooting and demo runbook

Commands run and checks made to bring the stack up on a laptop with a public tunnel for the Twilio WhatsApp sandbox. Each section records what was run, what it showed, and what to do when it does not. Tech debt is listed at the end. Open product work is in `docs/STATUS.md`.

The demo scripts live outside the repo in `~/sazon-demo/`, so no secret or tunnel URL is ever committed. `.env` is never edited by a script.

## Layout outside the repo

| File | Purpose |
|---|---|
| `~/sazon-demo/compose.demo.yaml` | Compose override: dev mode, generated session secret, recruiter domain, short silence thresholds, 60 s sweep, 3 s candidate page refresh, public URL and webhook URL from `NGROK_URL`, login mail redirected to the presenter's inbox. |
| `~/sazon-demo/demo.env` | Written by the launcher with mode 0600. `NGROK_URL` and `NGROK_AUTHTOKEN`. Read by compose for variable substitution. |
| `~/sazon-demo/demo-up.sh` | Writes `demo.env`, brings the stack up with the `tunnel` profile, waits for the API and the tunnel, invites the demo recruiter, prints the URLs. |
| `~/sazon-demo/demo-login.sh` | Fallback when `.env` has no SendGrid keys: requests a login link for the demo recruiter and prints it from the container's stderr. |
| `~/sazon-demo/demo-down.sh` | Stops the stack including the tunnel. Keeps the `mongo-data` volume. |

## 1. The public URL is the `ngrok` compose service

`compose.yaml` has an `ngrok` service (image `ngrok/ngrok:3`) behind the `tunnel` profile, so `docker compose up` alone starts no tunnel. It runs `ngrok http api:8000 --url $NGROK_URL` inside the compose network, so the host port is irrelevant; the equivalent host command is `ngrok http 8000 --url <domain>`. `NGROK_AUTHTOKEN` and `NGROK_URL` are required; compose refuses to start the profile without them.

ngrok's free plan assigns each account one dev domain, described in ngrok's docs as "a stable, auto-assigned hostname" that "cannot be changed". The launcher's default is this account's domain; override it with `NGROK_URL=https://<name>.ngrok-free.dev`. Twilio's sandbox webhook can be set only in the console, so the fixed domain is what makes the paste a one-time step.

Install the host agent once, to hold the authtoken the launcher copies into `demo.env`. Commands as published on ngrok's Linux download page:

```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok
ngrok config add-authtoken "<token from dashboard.ngrok.com>"
```

Verified 27 Oct: `ngrok version 3.39.13`, config at `~/.config/ngrok/ngrok.yml`. Exporting `NGROK_AUTHTOKEN` before the launcher also works.

The launcher reads the bound URL from the container's local API, published on `127.0.0.1:4040` (`/api/tunnels`, `public_url`), and fails when it differs from `NGROK_URL`. Browser requests through a free ngrok domain see an interstitial page once per browser; `curl` checks pass `ngrok-skip-browser-warning: 1` to skip it. Twilio's webhook POST is not affected.

cloudflared is no longer used. The old quick-tunnel launcher changed URL on every start.

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

1. Checks `docker` and `curl` exist, the Docker daemon answers, and `.env` exists in the repo.
2. Reads the authtoken from `~/.config/ngrok/ngrok.yml` (or `NGROK_AUTHTOKEN`) and writes `NGROK_URL` and `NGROK_AUTHTOKEN` to `demo.env`.
3. Runs `docker compose --project-directory <repo> --env-file ~/sazon-demo/demo.env -f compose.yaml -f ~/sazon-demo/compose.demo.yaml --profile tunnel up -d --remove-orphans`.
4. Polls `http://localhost:8000/docs` up to 60 s, then `http://127.0.0.1:4040/api/tunnels` up to 60 s and checks the bound URL equals `NGROK_URL`.
5. Runs `screening-admin invite demo@gruposazon.com` inside `api`. The invite is an upsert, so repeating it is safe.
6. Prints the public URL, the Twilio webhook URL to paste, and the login page.

Override the recruiter address with `RECRUITER_EMAIL=you@gruposazon.com ~/sazon-demo/demo-up.sh`. The domain must be in `SCREENING_RECRUITER_EMAIL_DOMAINS` in the override.

## 4. Prove the tunnel before touching Twilio

Known-positive control, then the negative:

```bash
URL=$(sed -n 's/^NGROK_URL=//p' ~/sazon-demo/demo.env)
curl -s -o /dev/null -w "%{http_code}\n" -H "ngrok-skip-browser-warning: 1" "$URL/docs"
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "ngrok-skip-browser-warning: 1" "$URL/webhook/whatsapp" -d "From=whatsapp:%2B34600&Body=hi&MessageSid=x"
```

Expected: `200` then `401`. The 200 proves the public URL reaches the API. The 401 proves the Twilio signature check is live outside dev mode: an unsigned request is refused, a request Twilio signs for the exact URL in the console is accepted.

Passed 27 Oct against the fixed domain. If the first is not 200: `docker compose --profile tunnel logs ngrok` for the tunnel, `docker compose logs api` for the app.

## 5. Twilio sandbox

In the Twilio console, Messaging, Try it out, Send a WhatsApp message, Sandbox settings:

1. "When a message comes in": the webhook URL the launcher printed, method POST. It must match `SCREENING_TWILIO_WEBHOOK_URL` character for character, because the signature covers the URL.
2. Join the sandbox from the phone with the join phrase shown on that page.
3. The sandbox number must equal `SCREENING_TWILIO_WHATSAPP_FROM` in `.env`.

The URL is fixed, so step 1 is done once.

A sandbox join expires three days after joining (Twilio sandbox docs). Rejoin from the phone before the recording if the join is older.

## 6. Recruiter login

Two paths. Which one runs depends only on whether `.env` has `SCREENING_SENDGRID_API_KEY` and `SCREENING_LOGIN_EMAIL_FROM`. Dev mode alone does not pick.

Mailbox path, for the recording. The override sets `SCREENING_LOGIN_EMAIL_REDIRECT_TO` to the presenter's mailbox, so the login mail for `demo@gruposazon.com` is delivered there with "Requested for demo@gruposazon.com." as its first line. Needs the two SendGrid settings in `.env` and a sender verified in SendGrid. Type the demo address on `http://localhost:8000/recruiter/login`, open the mail, replace the link's host with `localhost:8000`, open it, press confirm. The session cookie is host-only and set on the origin that confirms the link, so a confirm on the public domain does not log in `localhost`. The redirect is refused outside dev mode: the login form answers 503 and the log names the setting.

Terminal path, when the SendGrid settings are empty. The sender falls back to stderr, and the redirect only changes the printed "email to" address:

```bash
~/sazon-demo/demo-login.sh
```

Prints a link on the public domain, `https://<name>.ngrok-free.dev/recruiter/login/<token>`, because `SCREENING_PUBLIC_URL` in the override is that domain. Replace the host with `localhost:8000` before opening it, for the same cookie reason as above. Click confirm. The link is single use and expires in 15 minutes. Run the script again for a new one.

## 7. Watch a live screening

```bash
docker compose -f compose.yaml -f ~/sazon-demo/compose.demo.yaml logs -f api
```

Open `http://localhost:8000/recruiter/candidates/<E.164 phone>` for the inspector. The page reloads itself every 3 s while the conversation is open (`SCREENING_CANDIDATE_PAGE_REFRESH_SECONDS` in the override).

Silence thresholds in the override, in minutes: nudge at 3 and 6, abandon at 12, opener retry at 3, opener abandon at 12. The sweep runs every 60 s. A paused take is abandoned by the sweep. Keep the take moving, or stop the `sweep` service for the recording with `docker compose stop sweep`.

Thresholds are wall-clock. A laptop that sleeps between the dry run and the recording abandons every in-progress candidate on the first tick after it wakes. Run the dry run inside the window or restart the stack first.

Open the recruiter pages on `http://localhost:8000` for the recording, the origin the login was confirmed on. The free ngrok domain shows a one-time interstitial page in a browser.

The meta refresh on the candidate page discards an unsaved override note while the conversation is in progress. Write the note after the outcome.

## 8. Stop

```bash
~/sazon-demo/demo-down.sh
```

Runs `docker compose down` without `-v`, so the conversations in `mongo-data` survive, and kills the tunnel. Never run `docker compose down -v` before the recording.

## Warnings seen and their meaning

- `zsh: no such file or directory: tunnel` after pasting a command with `<tunnel>` in it. The angle brackets are a placeholder. zsh read `<tunnel>` as a file redirect. Replace it with the real URL, or use the launcher, which never asks for a paste.
- `service "api" is not running` from `docker compose exec`. The stack is down, usually because the previous command failed. Run `demo-up.sh`.
- `InsecureKeyLengthWarning` from PyJWT in the test suite. Tests use a short session secret on purpose. The override generates a 32-byte secret.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Twilio's debugger shows a webhook fetch error, or the phone gets no reply | Webhook URL in the console differs from `SCREENING_TWILIO_WEBHOOK_URL`, or the `ngrok` container is down | `docker compose --profile tunnel ps`, re-run `demo-up.sh`, compare the console URL with the printed one |
| `ngrok` container exits at once | Authtoken missing or wrong, or the domain belongs to another account | `docker compose --profile tunnel logs ngrok`, then `ngrok config add-authtoken` and re-run `demo-up.sh` |
| Webhook answers 401 to Twilio | `SCREENING_TWILIO_AUTH_TOKEN` in `.env` is not the account's auth token, or the URL mismatch above | Check the token in the Twilio console, then the URL |
| Webhook answers 503 | Twilio auth token unset and dev mode off | Set the token in `.env`, or dev mode in the override |
| `POST /candidates` answers 409 | The phone already has a conversation. The phone is the candidate id, so a finished or abandoned candidate blocks it too | Add the phone to `SCREENING_DEMO_PHONES` and press "Reset and archive" on its recruiter page, or use another number |
| `POST /candidates` answers 500, `api` log shows `401 Unauthorized` for `Messages.json` | The Twilio API key SID or secret does not belong to `SCREENING_TWILIO_ACCOUNT_SID`. The opener is sent before the candidate is saved, so nothing was written | Run the key check below, fix `.env`, then `docker compose up -d --force-recreate api sweep` |
| `POST /candidates` answers 500, Twilio error 63015 | The phone has not joined the sandbox, or its join expired | Send the join phrase from that phone |
| Reply never arrives but the inspector shows the turn | Outbound is TwiML on the webhook response, so the turn did reply; Twilio could not deliver | Re-send the join phrase from the phone. A sandbox join expires after three days |
| First reply takes long or 500s | Provider key missing or the org key lacks `PROJECT_ANTHROPIC_WORKSPACE_ID` | `docker compose logs api` for `ProviderKeyMissingError` or a 400 from the provider |
| Login link not printed by `demo-login.sh` | Address not invited or domain not allowed | `docker compose exec api screening-admin invite <email>`; domain in the override |
| Login link not printed by `demo-login.sh`, no "email to" line in the log | SendGrid keys present in `.env`, so the mail went out for real | Read the redirect inbox, or empty the two SendGrid settings for the terminal path |
| Login form answers 503, log says `SCREENING_LOGIN_EMAIL_REDIRECT_TO is allowed in dev mode only` | Redirect set with dev mode off | Remove the redirect or set `SCREENING_DEV_MODE=true` in the override |
| `pymongo.errors.ServerSelectionTimeoutError` in tests | mongod died at Docker's default open-file limit | `docker logs` for `Too many open files`; the test container sets `nofile=65536` |

## Tech debt

- Login links appear in access and proxy logs until used or expired. The token is single use and short lived, so this is accepted for now.
- The bake-off cost column counts the turn model only. Guardrail, summary and judge tokens are not included.
- The guardrail latency gate default (p95 at most 2.5 s) was set before any live run. Adjust from the first valid `bakeoff.json`.
- `llm_timeout_seconds` is a float. `langchain-mistralai` types its timeout as int. Keep it whole-numbered for Mistral runs.
- `mistralai:mistral-medium-latest` and `mistralai:mistral-small-latest` are aliases that Mistral can move to a new model and price. Pin `mistral-medium-3-5` and `mistral-small-2603` for a repeatable bake-off.
- The no-PII test configures Logfire in-process, so pymongo, httpx and the app stay instrumented for the rest of the pytest session. Nothing is sent without a token. A subprocess would isolate it at the cost of speed and debuggability.
- The Logfire pytest plugin is disabled in `addopts`. It exports test spans whenever `CI` and `LOGFIRE_TOKEN` are both set.
- The span-processor order relative to Logfire's pending-span processor comes from installed source, not docs. The no-PII test pins it; a Logfire upgrade can break it.
- Package data covers only `templates/*.html`. Any static file for the console needs a `StaticFiles` mount and a package-data glob in `pyproject.toml`.
