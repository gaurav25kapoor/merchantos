# MerchantOS

## AI-native merchant operating system for agentic commerce

MerchantOS is a full-stack commerce control plane for merchants serving AI-assisted buyers. It connects natural-language product discovery, intent understanding, catalog search, recommendations, policy-bounded negotiation, cart and checkout workflows, payment processing, analytics, and auditability in one merchant-scoped system.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Payments](https://img.shields.io/badge/Payments-Razorpay--compatible-0C2451)
![AI](https://img.shields.io/badge/AI-LLM%20fallback%20architecture-5B21B6)

> MerchantOS turns conversational buyer intent into measurable merchant growth while enforcing merchant policies and reliable payment controls.

## Why MerchantOS?

Commerce is moving from a human navigating pages to an AI buyer acting on intent.

```text
Traditional ecommerce:  Human → Website → Product → Cart → Checkout
AI commerce:             AI Buyer → Intent → Search → Recommendation → Negotiation → Purchase
```

This shift requires merchant infrastructure that is AI-readable, AI-interactable, revenue-aware, policy-controlled, payment-safe, and auditable. MerchantOS is that control layer: an agent can interpret a buyer request while server-side services retain authority over critical commerce state.

## The Problem

Traditional merchant systems are designed around human-operated storefronts. AI buyers need natural-language discovery, structured catalog understanding, contextual recommendations, automated negotiation, intelligent upselling, programmatic checkout, reliable payments, and explainable decisions.

Merchants cannot safely give an autonomous system unrestricted authority to change prices, modify inventory, create discounts, or mark payments complete. MerchantOS addresses this gap with a fixed tool registry, merchant-scoped data access, deterministic policy checks, and durable operational records.

## The Solution

MerchantOS is a unified merchant control plane. For merchants, it provides catalog, variant, inventory, and policy management; order/payment monitoring; dashboards; and audit events. For AI buyers, it provides intent extraction, catalog discovery, deterministic ranking, recommendations, negotiation, cart management, and checkout.

For safe commerce, it adds policy gating, server-side pricing, a payment state machine, idempotency records, signed webhook handling where configured, inventory-deduction guards, and mock-mode operation.

## Key Capabilities

| Feature | Description |
| --- | --- |
| AI buyer experience | Natural-language discovery through buyer search and Merchant Agent chat. |
| Intent understanding | Extracts query, category, brand, price bounds, attributes, and stock requirements; deterministic fallback is available by default. |
| Catalog search | Merchant-scoped, inventory-aware search with price, category, brand, and attribute filters. |
| Controlled agent | Merchant Agent orchestrates centrally registered, validated tools and logs execution. |
| Recommendations | Deterministic same-category upsells and complementary-category cross-sells using active, in-stock items. |
| Negotiation | Server-side accept, reject, or counter-offer within merchant policy. |
| Growth experiments | Stable, deterministic session assignment for configured experiment variants. |
| Cart and checkout | One-merchant carts with server-side price snapshots and checkout total recalculation. |
| Payment reliability | Razorpay-compatible mock/test workflow, payment states, attempts, verification paths, and failure recording. |
| Idempotency and webhooks | Persistent idempotency records and duplicate webhook-event protection. |
| Auditability | Durable events across catalog, inventory, commerce, policy, payments, and agent actions. |
| Analytics | Merchant-scoped revenue, orders, products, inventory, agent activity, negotiation, and recommendation metrics. |

## End-to-End AI Commerce Flow

```mermaid
flowchart LR
    A[AI Buyer] --> B[Intent Understanding]
    B --> C[Catalog Search]
    C --> D[Product Ranking]
    D --> E[Recommendation]
    E --> F[Negotiation]
    F --> G[Upsell / Cross-sell]
    G --> H[Cart]
    H --> I[Checkout]
    I --> J[Payment]
    J --> K[Order]
    K --> L[Inventory]
    K --> M[Analytics]
    K --> N[Audit Trail]
```

MerchantOS derives structured intent, searches only the selected merchant's active catalog, and ranks results with reasons such as budget fit or availability. Cart and checkout use server-side prices and stock validation. Successful payment finalization produces the paid outcome and performs the protected inventory deduction. Orders and business events feed dashboards and audit history.

## Architecture

```mermaid
flowchart TB
    Buyer[AI Buyer or Merchant User] --> Web[Next.js / React Frontend]
    Web --> API[FastAPI API]
    API --> Intent[Intent / LLM Provider Abstraction]
    API --> Agent[Merchant Agent]
    Agent --> Registry[Controlled Tool Registry]
    Registry --> Commerce[Catalog, Policy, Cart and Checkout Services]
    Commerce --> Payments[Payment Service]
    Payments --> Provider[Razorpay-compatible Provider]
    API --> Data[(PostgreSQL)]
    Commerce --> Data
    Payments --> Data
    Registry --> Data
    Audit[Audit Service] --> Data
    Analytics[Analytics Service] --> Data
    API --> Audit
    API --> Analytics
```

The Next.js frontend supports merchant operations and buyer journeys. FastAPI validates requests and coordinates domain services. PostgreSQL stores merchant-scoped catalog, policy, agent, cart, order, payment, idempotency, webhook, and audit data. The payment provider is isolated behind a service that supports mock mode and Razorpay-compatible verification/webhook flows.

## AI Agent Architecture

The AI/LLM layer handles natural-language understanding, intent interpretation, conversational response generation, and—when configured—tool planning. The default local provider is deterministic fallback parsing, so the application runs without an LLM key. If a configured provider is unavailable, the agent continues with the deterministic path.

```mermaid
flowchart LR
    LLM[LLM / Intent Layer] --> Agent[Merchant Agent]
    Agent --> Registry[Controlled Tool Registry]
    Registry --> Logic[Deterministic Application Logic]
    Logic --> State[(Merchant-scoped Commerce State)]
    Logic --> Audit[Tool and Audit Events]
```

The LLM does not generate SQL, run Python, access the filesystem, select arbitrary tools, or directly manipulate business state. The registry resolves only known tools, validates inputs, supplies server-side merchant context, and logs results. Deterministic application logic owns pricing rules, inventory mutations, order creation, payment state changes, and policy enforcement. MerchantOS records tool activity and decision outcomes; it does not expose hidden chain-of-thought.

## Agent Tools

Every registered tool receives merchant-scoped context, validates inputs, and records output, success/failure, error text, and duration.

| Tool | Purpose | Inputs | Outputs | Safety considerations |
| --- | --- | --- | --- | --- |
| `search_products` | Search the merchant catalog. | Query, category, brand, price range, stock flag, attributes, limit. | Structured results and total. | Limit is 1–50; search is merchant-scoped. |
| `get_product_details` | Retrieve an active product and variants. | Product ID. | Product metadata and variant availability. | Product must belong to the merchant. |
| `check_inventory` | Read variant stock state. | Variant ID. | SKU, quantity, availability, status. | Read-only; active merchant variant only. |
| `get_merchant_policy` | Retrieve policy data. | Optional policy type. | Policy windows, discount limit, shipping threshold, rules. | Current merchant policy only. |
| `rank_products` | Deterministically rank results against intent. | Products, buyer intent, optional policy. | Scores, reasons, and ranks. | Pure ranking; no database mutation. |
| `negotiate_price` | Evaluate a buyer offer. | Variant ID, offered price, optional session ID. | Decision, price/counter-offer, reason. | Negotiation service enforces policy. |
| `get_upsell_recommendations` | Find higher-value alternatives. | Product ID, session ID, limit. | Results and total. | Active, in-stock same-merchant products. |
| `get_cross_sell_recommendations` | Find complementary products. | Product ID, session ID, limit. | Results and total. | Deterministic category map; merchant-scoped. |
| `get_growth_experiment_variant` | Assign a stable experiment variant. | Session ID, experiment name. | Variant, enabled status, config. | Deterministic assignment. |
| `add_to_cart` | Add a variant to a cart. | Cart ID, variant ID, quantity. | Serialized cart. | Ownership/quantity validated; server price. |
| `view_cart` | Retrieve a cart. | Cart ID. | Serialized cart. | Cart must belong to the merchant. |
| `checkout_cart` | Initiate checkout. | Cart ID, optional buyer session ID. | Order/payment checkout response. | Recalculates totals and validates stock server-side. |

## Merchant Policy & Guardrails

Merchant policies include return and cancellation windows, minimum order value, maximum discount percentage, negotiation enabled status, free-shipping threshold, and structured rules. The negotiation service calculates the minimum allowed price from the configured discount boundary and returns an accept, reject, or counter-offer result.

AI recommendations and negotiation operate within merchant-defined boundaries. Critical money-changing actions remain controlled by deterministic application logic. Agent tools cannot arbitrarily write a price, decrement inventory, or mark payment successful.

## Revenue Growth Engine

Intent-aware search improves relevant discovery through catalog category, price, attribute, and stock filters. Deterministic ranking explains fit through category match, budget fit, requested attributes, and availability.

Upsell and cross-sell recommendations can increase potential basket value by presenting eligible alternatives or complementary products. Policy-bounded negotiation can support conversion recovery while protecting merchant pricing boundaries. Stable experiment assignment supports comparing configured strategies through recorded data. MerchantOS records recommendations, upsell display events, and policy decisions; it does not currently calculate or claim AI-attributed revenue.

## Payment & Reliability Architecture

MerchantOS implements a Razorpay-compatible payment workflow with mock mode as the default. It does not claim live payment processing unless real provider credentials and configuration are supplied.

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> PENDING
    PENDING --> PROCESSING
    PROCESSING --> SUCCESS
    PENDING --> FAILED
    FAILED --> PROCESSING: retry
    SUCCESS --> [*]
```

`SUCCESS` is terminal. `FAILED` records a failed attempt and can be followed by a retry; payment attempts preserve provider payment IDs, provider order IDs, states, and failure reasons. Orders move from `PENDING_PAYMENT` to `PAID`, with `PAYMENT_FAILED` available between a failure and later success.

Verification and webhook processing use persistent idempotency records keyed by operation and client-supplied `Idempotency-Key`. Razorpay webhooks store provider event IDs uniquely, read the raw body, and verify `X-Razorpay-Signature` outside mock mode. Duplicate deliveries do not repeat finalization. Inventory is deducted only by centralized success handling and only once, protected by `inventory_deducted`; insufficient final stock rejects finalization for retry or manual resolution.

`PAYMENT_MODE=mock` supports local test transactions without private Razorpay credentials. Mock success is blocked in production configuration and follows the same state and inventory workflow as verified success. Provider secrets are never returned to the frontend.

## Analytics & Merchant Intelligence

Dashboard data is derived from merchant, order, payment, catalog, inventory, agent-session, tool-call, policy-decision, recommendation, and upsell-event data where applicable.

| Area | Implemented metrics |
| --- | --- |
| Overview | Successful-payment revenue, successful/failed payments, order counts, average order value, product counts, low stock, inventory units, agent sessions, negotiations. |
| Revenue | Successful-payment revenue by day, week, or month. |
| Orders | Orders by state, payment counts and success rate, average order value. |
| Products | Product/variant counts and top paid-order products by units and revenue. |
| Inventory | Units, in/out/low-stock variants, and low-stock item list. |
| Agent activity | Sessions, tool-call counts, success rates, and recent activity. |
| Negotiations | Accepted/rejected/counter offers, acceptance rate, average offered discount. |
| Recommendations | Upsell/cross-sell counts, recommendation events, experiment variants used. |

## Auditability

Agentic commerce needs records that explain what occurred across merchant and automated workflows. MerchantOS emits durable audit events for merchant/policy changes, products, variants, inventory, carts, checkout, payments, payment webhooks, agent tools, negotiations, and recommendations.

Events include merchant, event and entity types, entity ID, actor context, metadata, and timestamp. The audit API filters by event type, entity type, entity ID, and date range, providing an operational history for investigating policy and payment decisions without treating conversational reasoning as a source of truth.

## Technology Stack

| Area | Technologies actually used |
| --- | --- |
| Frontend | Next.js, React, TypeScript, Tailwind CSS, ESLint. |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy, Alembic, Uvicorn. |
| Database | PostgreSQL 16 with Psycopg. |
| AI | Intent/LLM provider abstraction with deterministic fallback. |
| Payments | Razorpay-compatible provider service with mock/test mode, verification, and webhook handling. |
| Infrastructure | Docker Compose for PostgreSQL. |
| Testing | Pytest and HTTPX test client. |

## Project Structure

```text
merchantos/
├── backend/
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── services/
│   │   │   ├── agent_tools.py
│   │   │   ├── analytics.py
│   │   │   ├── payments.py
│   │   │   └── merchant_agent.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   └── seed.py
│   ├── tests/
│   ├── alembic.ini
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── api-test/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── lib/api.ts
│   ├── public/
│   └── package.json
├── docs/
├── scripts/
├── docker-compose.yml
└── README.md
```

## Getting Started

### Prerequisites

- Git
- Python 3.13 or a compatible Python 3 release
- Node.js compatible with Next.js 16
- Docker Desktop with Docker Compose

### Backend setup

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Database setup

From the repository root:

```powershell
docker compose up -d
```

The supplied Compose configuration exposes PostgreSQL on `localhost:5433`. Then run migrations from `backend`:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

## Environment Configuration

Create `backend/.env`:

```env
APP_NAME=MerchantOS API
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg://merchantos:merchantos@localhost:5433/merchantos
FRONTEND_URL=http://localhost:3000

PAYMENT_PROVIDER=razorpay
PAYMENT_MODE=mock
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=

LLM_PROVIDER=fallback
LLM_API_KEY=
```

Optionally create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Never commit secrets or API keys to source control. `PAYMENT_MODE=mock` and `LLM_PROVIDER=fallback` allow local operation without private payment or LLM credentials.

## Running the Application

Start the backend from `backend`:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Start the frontend from `frontend` in another terminal:

```powershell
npm install
npm run dev
```

- API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Demo Mode

MerchantOS runs without live payment credentials. Load deterministic demo data in development:

```powershell
cd backend
.\venv\Scripts\python.exe -m app.seed
```

The development-only `POST /api/v1/dev/seed-demo-data` provides the same seeded setup and is disabled when `ENVIRONMENT=production`. It supports product discovery, intent extraction, recommendations, negotiation, upsell/cross-sell, cart, checkout, mock payment success/failure, inventory updates, audit events, and dashboards.

Test mode is the payment-provider mock workflow, demo data is seeded local data, and LLM fallback is deterministic intent/tool planning. These are separate development capabilities. Demo and mock transactions are not real payments.

## Example AI Buyer Flow

The following values are illustrative demo values.

> Buyer: “I need black wireless headphones under ₹2500.”

1. MerchantOS extracts category, color, connectivity, budget, and stock intent.
2. It searches the merchant catalog, checks inventory, ranks matches, and recommends the best fit.

> Buyer: “Can you do ₹2000?”

For a ₹2500 product with a 10% maximum discount, the policy minimum is ₹2250. The deterministic decision is a counter-offer of ₹2250. An eligible complementary offer may follow: **Protective Case — ₹299**. The buyer can then proceed through cart → checkout → payment → order → inventory update → audit event → analytics update.

## API Overview

All endpoints below are prefixed with `/api/v1`. API schemas and interactive details are available at `/docs`.

| Group | Implemented endpoints |
| --- | --- |
| Search | `GET /search`, `POST /buyer/intent`, `POST /buyer/search` |
| Agent | `POST /agent/chat` |
| Negotiation | `POST /negotiation` |
| Recommendations | `GET /products/{product_id}/upsells`, `GET /products/{product_id}/cross-sells` |
| Experiments | `GET /experiments/{experiment_name}/assignment` |
| Cart | `POST /carts`, `GET /carts/{cart_id}`, item create/update/delete routes, `DELETE /carts/{cart_id}` |
| Checkout | `POST /checkout`, `GET /orders/{order_id}`, `GET /orders` |
| Payments | `GET /payments/{payment_id}`, `GET /payments`, `POST /payments/verify`, `POST /payments/mock-success`, `POST /payments/fail` |
| Webhooks | `POST /webhooks/razorpay` |
| Audit | `GET /audit-events` |
| Dashboard | `GET /dashboard/overview`, `/revenue`, `/orders`, `/products`, `/inventory`, `/agent-activity`, `/negotiations`, `/recommendations` |

Merchant, policy, catalog, variant, inventory, user, public-configuration, and development seed routes are also available. Merchant ID is trusted development context in the current API; production authentication and authorization are not yet implemented.

## Security & Reliability

- Merchant-scoped search, agent tools, recommendations, negotiation, carts, checkout, orders, payments, audit, and dashboard workflows.
- Pydantic validation, database constraints, ORM queries, and 1 MB request-size middleware.
- Server-side cart prices and checkout total recalculation.
- Deterministic merchant-policy enforcement for negotiation.
- Payment state transitions, attempts, idempotency records, provider IDs, duplicate-event protection, and signature validation outside mock mode.
- Centralized success finalization and one-time inventory deduction.
- Audit records and a public configuration endpoint that excludes payment secrets.

The current merchant context is trusted for development. Production deployment needs authentication, tenant-aware authorization, RBAC, rate limiting, production CORS policy, monitoring, and incident controls.

## Testing

Run backend tests from `backend`:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

The suite covers catalog/inventory operations, buyer intent/search, agent tools and merchant isolation, negotiation, recommendations and experiments, carts/checkout, payment state/idempotency/webhooks, audit events, analytics, and integration security checks.

Frontend checks:

```powershell
cd frontend
npm run lint
npm run build
```

## Limitations

- Authentication and authorization are not implemented; merchant context is trusted in local development.
- Real Razorpay processing needs configured credentials and production integration setup; mock mode is the default local workflow.
- The LLM provider is optional; deterministic fallback is included for reliable local operation.
- Refunds, compensation workflows, webhook replay tooling, queue-based processing, production observability, rate limiting, and full concurrency stress hardening remain production-hardening work.

## Future Roadmap

- Production authentication, RBAC, and multi-merchant deployment controls.
- Richer AI buyer interoperability and agent-to-agent commerce protocols.
- Merchant-specific learning and advanced experimentation.
- Automated payment recovery and compensation workflows.
- Real-time revenue intelligence, deeper payment integrations, and advanced risk controls.

## Buildathon Track Alignment

| Track Goal | MerchantOS Implementation |
| --- | --- |
| Revenue growth | Intent-aware search, recommendations, upsell, cross-sell, negotiation, and recorded experiment variants. |
| AI buyers | Natural-language buyer experience and intent-driven merchant catalog discovery. |
| Agentic commerce | Merchant Agent with a controlled, validated tool registry. |
| Payment execution | Checkout, payment states, and Razorpay-compatible mock/test workflow. |
| Safety | Merchant policies, server-side pricing, bounded actions, inventory guards. |
| Explainability | Tool activity, ranking reasons, policy decisions, recommendation reasons. |
| Auditability | Merchant-scoped audit-event system. |
| Reliability | Idempotency, configured webhook verification, duplicate-event protection, payment states. |

## Conclusion

MerchantOS is designed around a simple idea: AI should not just help merchants operate their store — it should help them sell more, while every important commerce action remains bounded, explainable, reliable and auditable.
