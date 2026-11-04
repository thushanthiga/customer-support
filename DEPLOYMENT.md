# Support assistant server deployment

The runtime uses GPT-6 Luna for query planning and the server-configured MySQL
host for business data. It has no local LLM dependency. Only `support-assistant/`
needs the changes in this implementation.

## API configuration

Install Python dependencies from `api/requirements.txt` and create `api/.env`
from `api/.env.example`. Supply the real values for:

| Setting | Server value |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API key available to the API process |
| `CHAT_MODEL` | `gpt-6-luna` |
| `MYSQL_HOST`, `MYSQL_PORT` | Business database host and port accessible from the server |
| `MYSQL_USER`, `MYSQL_PASSWORD` | Database credentials for the tenant registry and tenant reads |
| `MYSQL_ROOT_DB` | Root database containing the registered tenants and domains |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | Persistent generated application secret |
| `DJANGO_ALLOWED_HOSTS` | API/proxy hostnames accepted by Django |
| `SUPPORT_ERP_ROOT` | Absolute path to the existing Laravel ERP app containing `artisan`, `bootstrap/` and `vendor/` |
| `PHP_BINARY` | PHP executable available to the API process |
| `SUPPORT_BUSINESS_ENGINE` | `true` |
| `SUPPORT_ANALYTICS_ACCESS` | `admin`, as requested, for all signed-in users' business analytics |
| `SUPPORT_DISABLE_MODEL_CALLS` | `false` for runtime; `true` only for offline verification |

The ERP bridge loads that Laravel application's existing configuration. Configure
its database connections to the same tenant registry and tenant databases as the
assistant. ERP sign-in and saved reports use those ERP connections; structured
queries use the assistant's `MYSQL_*` settings. Production ERP environments and
remote database hosts are supported.

Run from `support-assistant/api`:

```sh
python -m pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py check --deploy
python -m gunicorn config.wsgi:application --bind 0.0.0.0:8008 --timeout 120
```

Keep `api/db.sqlite3` on persistent writable storage: it contains the assistant's
chat history and sessions, separate from the business MySQL databases. The API
service account needs read/execute access to the configured ERP application.

## UI configuration

Set `SUPPORT_ASSISTANT_API_URL` in the Next.js server/build environment to the
API's reachable URL including `/api`, for example `http://assistant-api:8008/api`.
If both services share a host, `http://127.0.0.1:8008/api` is valid.

Run from `support-assistant/ui` with that variable set:

```sh
npm ci
npm run build
npm run start -- -p 3008
```

Configure the reverse proxy for the UI's public hostname. The browser uses
same-origin `/api/` requests; it never needs direct database access. Rebuild and
restart the UI after changing its API target. At sign-in, enter the registered
tenant ID or domain rather than a development `localhost` value.

The API validates tenant, schema, joins and comparisons before executing reads.
Administrator analytics access applies inside the assistant; ERP role records
are not edited. Passwords, tokens and secrets remain excluded.

GPT-6 Luna receives the user's questions and authorized table/column schema for
planning. Business result rows and query validation errors are kept in the
configured environment. Answers and derived amounts are rendered from local
query results; monetary subtraction uses decimal arithmetic. Planner requests
use `store=False`. Source-defined business reads may answer without a model
call, which is reported as `not_used` rather than invented token usage.

## Repeatable verification

Use an existing synthetic ERP QA account and set its password in
`SUPPORT_QA_PASSWORD`. These commands read the connected tenant; evaluation
reports remain on the server. Temporary evaluation chat rows/sessions are
removed by their unique run identifier.

```sh
# Offline regression suite: mocked provider and database boundaries.
SUPPORT_BUSINESS_ENGINE=false python manage.py test assistant.tests --noinput

# Authenticated answer checks, with independent SQL oracles for focused queries.
python manage.py evaluate_support --tenant REGISTERED_TENANT \
  --cases assistant/evaluations/user_live_queries.json \
  --report /tmp/support-focused-summary.json --allow-provider

# Full catalogue: response assertions; see per-case verification limits.
python manage.py evaluate_support --tenant REGISTERED_TENANT \
  --cases assistant/evaluations/catalogue_164_questions.json \
  --report /tmp/support-catalogue-summary.json --allow-provider
```

The focused oracle file refers to the documented local QA fixtures. Create
equivalent fixtures and adapt their IDs before running it against another
environment. A response-assertion pass does not certify every original
workflow, historical-date or permission acceptance requirement. Missing
attribution/cost/document links are reported explicitly in partial answers.

Reports default to minimal summaries. Add `--report-detail evidence` only when
you need full local answers, query results and independent SQL snapshots for
diagnosis. Reports are not read by chat and do not cache business answers.
See [QA storage details](QA/README.md). Exclude `QA/`, `evaluation-results/`, the evaluation input
directory and old report JSON from production images; retain
`api/assistant/verified_application_relationships.json`, which is runtime source
metadata. Schema metadata has a ten-minute in-memory TTL; business query rows
are read from the configured database on every request.
