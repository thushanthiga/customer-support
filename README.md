# Apptimate Support Assistant & RAG Knowledge Base

A standalone, 24x7 intelligent ERP support copilot with **hierarchical Markdown chunking**, **vector RAG retrieval**, and **secure read-only multi-tenant database integration**.

---

## 🏗️ Architecture

```
support-assistant/
├── api/                     # Django REST Framework Backend
│   ├── config/              # Django settings & URL routing
│   ├── assistant/           # Support copilot application
│   │   ├── models.py        # UploadedDocument, DocumentChunk, ChatUsageLog
│   │   ├── chunking_service.py # Hierarchical markdown parser & OpenAI embeddings
│   │   ├── rag_service.py   # Vector cosine similarity retrieval
│   │   ├── db_service.py    # Strict read-only tenant DB connector (stancl/tenancy)
│   │   ├── views.py         # Upload, Chunks, Activation, Chat endpoints
│   │   └── urls.py
│   ├── uploads/             # Physical store for uploaded Markdown (.md) documents
│   ├── .env & .env.example  # OpenAI & MySQL configuration
│   └── manage.py
└── ui/                      # Next.js 16 + React 19 Frontend
    ├── src/app/             # Modern glassmorphic support dashboard
    │   ├── page.tsx         # Dual-tab view: Support Chat + MD Knowledge Portal
    │   ├── layout.tsx
    │   └── globals.css
    └── package.json
```

---

## 🚀 Key Features

1. **Markdown Upload & Intelligent Chunking**:
   - Upload any `.md` or `.markdown` file directly from the UI.
   - Hierarchical section parsing: splits by `#`, `##`, `###` headings, preserving context breadcrumbs (e.g. `[Sales > Orders > Quotations]`).
   - Generates embeddings using OpenAI `text-embedding-3-small` in batches.
   - Interactive **Chunk Inspector** to audit all indexed sections, hierarchy paths, and word counts.

2. **RAG Vector Retrieval**:
   - Queries are embedded and compared against the active document's chunks using cosine similarity.
   - Retrieves top-K semantically relevant sections and injects only relevant context into prompt, avoiding token bloat.
   - Transparent references: each assistant message displays an expandable drawer showing the exact referenced markdown sections and similarity scores.

3. **Secure Read-Only Multi-Tenant Database Verification**:
   - Authenticates active ERP accounts, resolves the tenant against the configured registry, and confines each query to that tenant database (`apptimate_<tenant_id>`). Admin analytics grants all signed-in users access across business modules; ERP grants can be applied with the `erp` access policy.
   - Query safety checking blocks any mutation keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc.).
   - Pre-parameterized queries: checks item catalog status, `is_discountable` flag, batch/serial tracking, warehouse-by-warehouse stock levels, total available quantity, and active promotional markdowns.
   - Quantity answers distinguish item-master thresholds, transaction rules and warehouse availability. Non-stock items are not blocked merely because their stock balance is zero.
   - Specific tools handle common lookups, and a structured cross-module query tool handles other live-data questions. It receives a tenant-specific schema hint, compiles validated `SELECT` plans, allows database keys and source-verified application joins, binds filter values, and caps each page at 500 rows. Ordered queries support offsets and next-page metadata. Tenant schema metadata is cached for ten minutes, and the larger query tool is only sent for likely live-data questions. The model never receives a raw SQL execution tool.
   - Generic query plans execute through SQLAlchemy `text()` with named bound parameters and a pooled, tenant-specific engine. Schema hints include relevant business tables and more of their columns for cross-module analytics and tracking-field questions.
4. **General Apptimate Support**:
   - Use the active knowledge document for workflows, troubleshooting, and product guidance.
   - Use live tenant tools only when the answer depends on current records. Specific tools cover frequent questions; the structured query tool supports other validated lookups and cross-module joins.

---

## 🛠️ Quick Start

### 1. Backend (`api/`)
```bash
cd support-assistant/api
pip install -r requirements.txt
# Environment is pre-configured in .env
./venv/bin/python manage.py migrate
./venv/bin/python manage.py runserver 8008
```

### 2. Frontend (`ui/`)
```bash
cd support-assistant/ui
npm run dev -- -p 3008
```

The browser calls the UI's same-origin `/api/` route, which Next.js
proxies to Django at `http://127.0.0.1:8008/api` by default. If Django is on a
different host or port, set `SUPPORT_ASSISTANT_API_URL` in the UI server's
environment (for example, `http://192.168.8.20:8008/api`) and restart Next.js.

Open your browser at `http://localhost:3008`.

The configured chat planner is **GPT-6 Luna** (`CHAT_MODEL=gpt-6-luna`), with
`SUPPORT_BUSINESS_ENGINE=true`. GPT-6 Luna receives
the question, relevant schema and recent user questions to
propose structured queries. Business result rows are queried on the configured database and rendered by the API.
Query validation errors stay in the connected environment.
The UI shows the configured model, and each new answer stores the model and token
source used. There is no on-device model or Ollama dependency. Offline verification
uses `SUPPORT_DISABLE_MODEL_CALLS=true` and mocks provider calls.

With the business engine enabled, the assistant uses
`SUPPORT_ANALYTICS_ACCESS=admin`. Every active, signed-in ERP account can ask
business questions across all modules and organizations in its connected tenant,
including payroll and saved reports. The UI shows **Admin · All modules**.
This grants analytics access inside the assistant without updating ERP user roles.
Queries remain read-only, tenant-scoped, and exclude passwords, tokens and secrets.
Set `SUPPORT_ANALYTICS_ACCESS=erp` to apply ERP module and organization grants
inside the assistant instead. The access policy works with the database host
configured for the deployment server.
The local answer evaluator records this policy in its report. The original
164-case HR permission-denial expectations apply in `erp` mode; `admin` mode
expects those business queries to be allowed. Reports from different policies
cannot be combined with `--resume`.

Numeric comparisons preserve direction, inclusivity, field and threshold before
execution: `greater than 1000` requires `> 1000`; `< 1000`, `>= 1000` and a changed
threshold are rejected. Common comparison typos such as `gratre than` are normalized.
Questions such as “items greater than 1000” ask which metric is intended rather
than guessing Max Qty. A stock-quantity answer sums recorded balances across
warehouses and variants; an empty balance is not invented as zero.

## Local payroll/BOM verification

Create or reuse the synthetic `AN-QA-` fixtures from `apps/api`:

```sh
php artisan support:seed-local-fixtures apptimate_infinity
```

Then, from `support-assistant/api`, verify them and replay recorded catalogue plans without model calls:

```sh
./venv/bin/python manage.py verify_local_scenarios --tenant apptimate_infinity
./venv/bin/python manage.py test assistant.tests --noinput
```

The fixture verifier only connects to local MySQL and blocks model generation.
The offline endpoint evaluator does not replace GPT-6 Luna with another model;
cases requiring query planning report a failure while model calls are disabled.
See [the existing 164-case report](QA/catalogue-164-verification.md) for its recorded
evidence and limitations. That historical report does not certify server deployment.

For server environment, ERP path and production start commands, see
[DEPLOYMENT.md](DEPLOYMENT.md).

## Evaluation files and caching

`QA/` means quality assurance. Its JSON files are saved test reports, not a
chat-response cache. `api/assistant/evaluations/` contains executable test inputs
and independent SQL checks. Customer chat does not load either directory to
answer business questions. Historical report passes describe that recorded run;
they are not a guarantee about new questions or current database values.

New `evaluate_support` reports default to a summary containing questions, test
status, timings and model usage. Answers, business rows, SQL snapshots and model
proposals are saved only with explicit `--report-detail evidence`. Historical
evidence files have been retained and are ignored by Git; exclude them from
production images. See [QA storage details](QA/README.md).

The runtime caches schema metadata for ten minutes and reuses database
connections. It reads business results from the connected database on each
query. `api/db.sqlite3` persists chat/session/document data; `ui/.next/` is the
compiled Next.js cache. Neither is an evaluation-answer cache.

## Grounded support and analytics

The current business engine routes record questions to live, tenant-scoped queries,
workflow questions to retrieved documentation, and mixed questions to both sources.
Business values and result tables are rendered directly from validated query results;
they are not rewritten by a second model call. Missing values remain unknown, empty
results are scoped to the executed query, and response metadata does not claim a
100% correctness score. Unsupported parts are explicitly marked as partial.

Large source datasets are aggregated inside MySQL using validated SELECT plans.
Counts, sums, averages, date groups, arithmetic and HAVING conditions operate over
the matching source rows before the output page limit. Each response page is capped
at 500 rows, exposes all returned rows, and retains continuation state for each
result. Existing database statement timeouts still apply. This is not a new Google
BigQuery connector, distributed warehouse, unlimited export or asynchronous job
system. Unsupported window functions and cross-result comparisons are reported
rather than approximated from a page of rows. Large production workloads still
require representative load tests and appropriate database indexes.

Query retries now receive compiler validation feedback. The planner is instructed
to preserve dates, predicates, currencies and units, avoid multiplied totals from
joins, and request missing context instead of choosing an arbitrary interpretation.
These safeguards reduce specific failure modes; they do not guarantee perfect
natural-language interpretation or hallucination-free documentation prose.

Run the current-engine regression coverage without model/database calls:

```sh
cd api
SUPPORT_DISABLE_MODEL_CALLS=true ./venv/bin/python manage.py test assistant.tests.test_reliable_support --noinput
```

On 2026-11-04, all 16 new regression tests passed. The full historical suite had
8 failures and 23 errors both before and after this change, including references
to removed modules and older database mocks. Production data correctness and
throughput have not been certified by these offline tests.

## Request-driven query planning

The planner no longer uses canned per-question SQL recipes or question-specific
spelling/risk rules. Its general prompt requires an `analysis_contract` describing
the entity, metric, row grain, scope, assumptions, unresolved ambiguities and the
plans supporting each requested component. The current user question remains
unchanged throughout discovery and repair. Previous questions supply context only;
they are not saved factual answers.

Planner JSON is validated locally against its schema and checked for complete plan
coverage. Before execution, a separate model call reviews the proposed plans against
the original question and authorized schema. Rejection goes back to planning with
specific feedback; unavailable review fails closed. Validating JSON structure alone
does not establish semantic correctness; this distinction follows the
[OpenAI structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs).
Database execution still validates fields, relationships, types and bound predicates.

Schema context includes indexes/unique keys and labels declared versus inferred
relationships, so planners can assess join fan-out and avoid treating a naming
convention as proof of business meaning. The schema cache stores metadata only.
Business results are freshly queried; neither retrieval snippets nor prior answers
supply analytical values. Repaired proposals replace previous proposal results.
Displayed analyses include the reviewed metric, scope and any assumptions.

`QUERY_REASONING_EFFORT` (default `medium`) and `REVIEW_REASONING_EFFORT` (default
`low`) configure the existing model's reasoning levels. Existing environment values
take precedence; configure levels supported by your deployment. An executable plan
adds one review call, increasing token use and latency in exchange for a second
semantic check. Structural/semantic repair is bounded by the four-attempt planning
loop; service failures stop rather than repeatedly attempting unreviewed execution.

Verification on 2026-11-04: general contract/execution tests and the current-engine
regressions pass offline. Two real-provider synthetic-schema checks additionally
verified a scoped count plan and a clarification after a metric change, without
reading tenant records. These checks verify specific behavior, not universal model
accuracy or production throughput. Model-based review can still miss errors; live
scenario evaluation remains necessary.

```sh
cd api
SUPPORT_DISABLE_MODEL_CALLS=true ./venv/bin/python manage.py test assistant.tests.test_planning_contract assistant.tests.test_reliable_support --noinput
```

### Everyday requests and clarification

The planner and reviewer share a conversational analytics policy. Ordinary
exploratory questions use a useful, disclosed reporting basis instead of asking
customers to specify every query parameter. Informal rankings default to a relevant
recorded volume/activity measure, the last 30 days when a transaction date exists,
and a top 10. Explicit current instructions and established follow-up preferences
override those defaults. Unqualified ordinary lists/counts do not inherit the
ranking window. Missing dates can use labeled recorded history; a proxy source is
labeled as a proxy and never presented as a different business event.

Reporting defaults appear in the answer's scope/assumptions and do not manufacture
business facts. Missing exact identities, contradictory requirements and unknown
custom formulas can still require clarification. Question-only proposals now pass
through review as well: optional reporting preferences alone should trigger a
revised plan rather than an unnecessary questionnaire. Schema discovery is still
handled before execution. These are shared decision rules, not phrase-to-query
recipes or stored answers.

Validation: 34 focused offline tests pass. A real-provider synthetic-schema check
produced an executable reviewed plan for an informal product-popularity request on
the first attempt, and for a customer-performance ranking after two repair attempts.
An exact proprietary-score request correctly asked for its missing formula. No
production records were used. The repairs show that model interpretation and
latency remain variable; these checks do not establish perfect understanding.
