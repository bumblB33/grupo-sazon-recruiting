SendGrid keys
You do not need them for the demo. With no SendGrid settings, ~/sazon-demo/demo-login.sh prints the login link.

To get the key:
1. Sign up for the SendGrid trial. Twilio's pricing page says the trial runs 60 days, needs no credit card, and allows 100 emails a day. A third-party review says the free plan was discontinued, so check the live pricing page.
2. Verify a sender, as in my earlier answer.
3. Create the API key. Name the key, choose Restricted Access, and set Mail Send to Full Access. SendGrid shows the key once, so copy it into SCREENING_SENDGRID_API_KEY at once.

python -m evals.run_evals --models anthropic:claude-sonnet-5-5,openai:gpt-6.1-sol,mistralai:mistral-medium-3-5 --guardrail-models anthropic:claude-haiku-5-5,openai:gpt-6-luna,mistralai:mistral-small-2603 --judge --out docs

---

WhatsApp sandbox demo: next steps

Status: steps 1 to 7 are done and an opener arrived. Steps 8 to 10 remain. Next session: plan the demo reset (PLAN.md section 9).

No business registration is needed. The sandbox needs the Twilio account, a working API key and one join text per phone.

1. Fix the Twilio API key (the opener failed with 401 Unauthorized).
   - Twilio Console, Account, API keys & tokens, create a Standard key. The secret is shown once.
   - Put it in `.env`: SCREENING_TWILIO_API_KEY_SID (SK...), SCREENING_TWILIO_API_KEY_SECRET.
   - SCREENING_TWILIO_ACCOUNT_SID (AC...) must be the account that owns the key.
   - SCREENING_TWILIO_AUTH_TOKEN is the account auth token. It only verifies webhook signatures.
2. Prove the key before anything else (expect 200; 401 means the key is still wrong):
   ```bash
   cd ~/Desktop/Orbio/grupo-sazon-recruiting
   val() { sed -n "s/^$1=//p" .env | tail -1 | tr -d "'\""; }
   curl -s -o /dev/null -w "%{http_code}\n" -u "$(val SCREENING_TWILIO_API_KEY_SID):$(val SCREENING_TWILIO_API_KEY_SECRET)" \
     "https://api.twilio.com/2010-04-01/Accounts/$(val SCREENING_TWILIO_ACCOUNT_SID)/Messages.json?PageSize=1"
   ```
3. Reload the stack so `api` and `sweep` read the new `.env`:
   `docker compose up -d --force-recreate api sweep` (or `~/sazon-demo/demo-up.sh`).
4. Check the tunnel (TROUBLESHOOTING.md section 4): the first curl must print 200, the unsigned webhook POST must print 401.
5. Twilio Console, Messaging, Try it out, Send a WhatsApp message, Sandbox settings:
   - "When a message comes in": `<NGROK_URL>/webhook/whatsapp`, method POST. It must match SCREENING_TWILIO_WEBHOOK_URL exactly.
   - The sandbox number must equal SCREENING_TWILIO_WHATSAPP_FROM (.env.example has +14155238886).
6. Join the sandbox from your phone: send `join <your code>` (shown on that page) to the sandbox number. The join lasts 3 days, so do it the day before or the day of the recording. Without it, Twilio refuses the opener (error 63015).
7. Tell Claude "seed". Claude creates an API key and posts your number. Do not seed before steps 2 to 6 pass.
8. Confirm your phone received the opener, reply from a phone, and watch the turn at `http://localhost:8000/recruiter/candidates/<E.164 phone>` (log in with `~/sazon-demo/demo-login.sh`).
9. Before recording (TROUBLESHOOTING.md section 7):
   - Do a dry run inside the silence window. Abandon is at 12 minutes.
   - Run `docker compose stop sweep` for the take.
   - A sleeping laptop abandons every open candidate. Restart the stack if it slept.
   - A second run for the same phone answers 409. Use another joined number.
10. Known limits for tomorrow:
    - The applicant names are not stored. The agent asks for the name in conversation.
    - The same phone cannot hold two conversations.
    - SMS, the intake page and the GUID ids are built after the recording. See PLAN.md.
11. Interview prep: PLAN.md section 5 holds the scaling answers and the queue comparison.

Documentation links

- Twilio WhatsApp sandbox: https://www.twilio.com/docs/whatsapp/sandbox
- Twilio trial account limits: https://www.twilio.com/docs/messaging/guides/how-to-use-your-free-trial-account
- Twilio webhook timeouts and retries: https://www.twilio.com/docs/usage/webhooks/webhooks-connection-overrides
- Twilio Content Templates: https://www.twilio.com/docs/content
- Twilio API keys (not opened this session): https://www.twilio.com/docs/iam/api-keys
- Celery tasks: https://docs.celeryq.dev/en/stable/userguide/tasks.html
- Celery optimizing: https://docs.celeryq.dev/en/stable/userguide/optimizing.html
- ngrok dev domains: https://ngrok.com/docs
- Repo: TROUBLESHOOTING.md sections 3 to 7, README.md configuration block, PLAN.md