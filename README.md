# MerchantOS

## Day 2: Merchant, catalog, inventory, and policy foundation

The FastAPI backend now provides PostgreSQL-backed merchant catalog management. All primary keys are UUIDs, timestamps are UTC database timestamps, and database constraints protect stock and policy values.

### Data model

- `merchants` owns products, policies, and users. `slug` is unique.
- `merchant_policies` is a one-to-one merchant policy record, with structured JSON rules for future policy engines.
- `products` belongs to a merchant and owns variants.
- `product_variants` belongs to a product. `sku` is globally unique.
- `inventory` is a one-to-one variant record. Database checks prohibit negative available or reserved quantities.
- `users` may belong to a merchant. `email` is unique.

Deleting a merchant cascades to its policies, products, variants, and inventory. Deleting a merchant sets its users' merchant reference to null.

### API

All Day 2 routes are prefixed with `/api/v1`:

- `POST`, `GET /merchants`; `GET /merchants/{merchant_id}`
- `PUT`, `GET /merchants/{merchant_id}/policy`
- `POST`, `GET /products`; `GET`, `PATCH /products/{product_id}`
- `POST /variants`; `GET /products/{product_id}/variants`; `PATCH /variants/{variant_id}`
- `POST /inventory`; `GET`, `PATCH /inventory/{variant_id}`
- `POST /inventory/{variant_id}/reserve` and `/release`
- `POST`, `GET /users`; `GET /users/{user_id}`

The existing `GET /health` remains available.

### Run locally

From `backend`:

```powershell
venv\Scripts\python.exe -m alembic upgrade head
venv\Scripts\python.exe -m app.seed
venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

The Docker database is mapped to port `5433`; the existing `backend/.env` uses that port.

### Tests

```powershell
venv\Scripts\python.exe -m pytest -q
```

The suite exercises merchant and policy creation, product/variant/inventory lifecycle, reserve/release operations, duplicate SKU and slug handling, negative stock validation, and foreign-key validation.

## Day 3: Buyer intent and catalog search

Day 3 adds the customer-facing search layer without creating a second catalog. It reuses `merchants`, `products`, `product_variants`, `inventory`, and `merchant_policies`.

Available endpoints:

- `GET /api/v1/search`
- `POST /api/v1/buyer/intent`
- `POST /api/v1/buyer/search`

The intent extractor uses a provider abstraction and a deterministic fallback parser by default. The fallback supports common shopping language such as `under Rs. 2500`, `in stock`, category words like `headphones`, and attributes such as color, size, connectivity, quantity, and battery-life hints. No LLM API key is required for local development.

## Day 4: Merchant agent, tools, and ranking

Day 4 adds a Merchant Agent that orchestrates the Day 3 intent extractor, a controlled tool registry, database-backed tool execution, deterministic ranking, and tool-call logging.

Available endpoint:

- `POST /api/v1/agent/chat`

Example request:

```json
{
  "merchant_id": "00000000-0000-0000-0000-000000000000",
  "message": "I need black wireless headphones under Rs. 2500 that are in stock."
}
```

Example response shape:

```json
{
  "session_id": "...",
  "intent": {
    "intent": "product_search",
    "query": "black wireless headphones",
    "category": "headphones",
    "max_price": "2500",
    "requires_in_stock": true
  },
  "response": "I found 1 black wireless headphones under Rs. 2500 that are in stock. The top match is Black Wireless Headphones.",
  "products": [],
  "tool_calls": [],
  "provider": "deterministic-fallback"
}
```

Agent tools are registered centrally and cannot be dynamically imported or selected directly by a buyer:

- `search_products`
- `get_product_details`
- `check_inventory`
- `get_merchant_policy`
- `rank_products`

Each tool validates input, scopes every database query by merchant, returns structured output, and records an `agent_tool_calls` row with input, output, success/failure, error text, and execution duration. Agent interactions are grouped under `agent_sessions`.

Ranking is deterministic and explainable. It combines Day 3 textual relevance with Day 4 signals such as category match, requested attributes, budget fit, and inventory availability. Ranking responses include reasons such as `matches requested category`, `within budget`, and `currently in stock`.

LLM configuration is optional:

```env
LLM_PROVIDER=fallback
LLM_API_KEY=
```

The default is `fallback`, so the backend runs without paid API access. If an LLM provider is configured but unavailable, the agent falls back to deterministic tool planning and continues serving requests. The LLM layer is not allowed to generate SQL, Python, filesystem access, or arbitrary tool names.

Merchant isolation is mandatory. For the current local API, `merchant_id` is treated as trusted development context until authentication is introduced. Every agent tool uses that server-side context and applies merchant-scoped queries so one merchant cannot access another merchant's products, variants, inventory, policies, sessions, or tool calls.

## Day 5: Negotiation, recommendations, and growth experiments

Day 5 adds policy-aware negotiation, deterministic upsell and cross-sell recommendations, and a small deterministic experiment assignment service. These features reuse the existing merchant catalog, inventory, policy, and agent tool-call logging patterns.

Available endpoints:

- `POST /api/v1/negotiation`
- `GET /api/v1/products/{product_id}/upsells`
- `GET /api/v1/products/{product_id}/cross-sells`
- `GET /api/v1/experiments/{experiment_name}/assignment`
- `POST /api/v1/agent/chat` also supports Day 5 requests

Negotiation uses `merchant_policies.negotiation_enabled` and `merchant_policies.maximum_discount_percent`.

Example:

```json
{
  "merchant_id": "00000000-0000-0000-0000-000000000000",
  "variant_id": "11111111-1111-1111-1111-111111111111",
  "offered_price": "2000.00"
}
```

For a product priced at `2500.00` with a `10%` maximum discount, the minimum approved price is `2250.00`. Offers at or above that price are accepted; lower offers receive a deterministic counter-offer.

New agent tools:

- `negotiate_price`
- `get_upsell_recommendations`
- `get_cross_sell_recommendations`
- `get_growth_experiment_variant`

Upsells recommend higher-value, in-stock products from the same merchant and category. Cross-sells recommend complementary in-stock products from the same merchant, using a small category relationship map. Recommendations never return the source product or another merchant's catalog.

Growth experiments are intentionally lightweight. `GrowthExperimentService` assigns a stable variant from `session_id + experiment_name`, so the same session always receives the same result. The default `upsell_strategy` experiment has `control` and `treatment` variants.

Day 5 records:

- Negotiation outcomes in `policy_decisions`
- Recommendation rows in `recommendations`
- Upsell display events in `upsell_events`
- Agent-triggered Day 5 tools in `agent_tool_calls`

## Day 6: Cart, checkout, and Razorpay foundation

Day 6 adds a one-merchant cart and checkout flow. Carts never trust client-side prices: unit prices are copied from the active product variant when an item is added, and checkout recalculates totals from server-side cart state before creating an order.

Cart endpoints:

- `POST /api/v1/carts`
- `GET /api/v1/carts/{cart_id}`
- `POST /api/v1/carts/{cart_id}/items`
- `PATCH /api/v1/carts/{cart_id}/items/{item_id}`
- `DELETE /api/v1/carts/{cart_id}/items/{item_id}`
- `DELETE /api/v1/carts/{cart_id}`

Checkout and order endpoints:

- `POST /api/v1/checkout`
- `GET /api/v1/orders/{order_id}`

Example cart creation:

```json
{
  "merchant_id": "00000000-0000-0000-0000-000000000000",
  "buyer_session_id": "buyer-session-123"
}
```

Example add item:

```json
{
  "product_variant_id": "11111111-1111-1111-1111-111111111111",
  "quantity": 2
}
```

Checkout validates that:

- The cart exists and belongs to the merchant.
- The cart is active and not empty.
- Products and variants are active.
- Inventory records exist.
- Available inventory is at least the requested quantity.

Checkout creates:

- An `orders` row with status `PENDING_PAYMENT`
- Immutable `order_items` snapshots with product name, SKU, attributes, quantity, unit price, and line total
- A `payments` row with status `CREATED`
- A `payment_attempts` row for the initial Razorpay order creation

Example checkout request:

```json
{
  "cart_id": "22222222-2222-2222-2222-222222222222",
  "merchant_id": "00000000-0000-0000-0000-000000000000",
  "buyer_session_id": "buyer-session-123"
}
```

Example checkout response:

```json
{
  "order_id": "...",
  "payment_id": "...",
  "amount": "2500.00",
  "currency": "INR",
  "status": "PENDING_PAYMENT",
  "razorpay": {
    "key_id": "",
    "order_id": "mock_order_...",
    "amount": 250000,
    "currency": "INR",
    "mode": "mock"
  }
}
```

Razorpay configuration:

```env
PAYMENT_PROVIDER=razorpay
PAYMENT_MODE=mock
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
```

`PAYMENT_MODE=mock` is the default and is safe for local development without credentials. Mock mode clearly returns provider order IDs prefixed with `mock_order_`. In real mode, Razorpay credentials are required and the secret is never returned to the frontend.

Day 6 also adds controlled agent tools:

- `add_to_cart`
- `view_cart`
- `checkout_cart`

Day 7 will build on this foundation with payment state transitions, idempotency, webhook verification, retries, and advanced failure handling.

## Day 7: Payment reliability, idempotency, and webhooks

Day 7 adds the payment processing foundation on top of Day 6 checkout. Payment success is never accepted from a plain frontend status flag. Real Razorpay verification uses signed payment data, webhook processing uses the raw request body signature, and local development uses an explicit mock endpoint.

Payment state:

```text
CREATED -> PENDING -> PROCESSING -> SUCCESS
               \-> FAILED -> retry -> PROCESSING
```

Order payment states:

```text
PENDING_PAYMENT -> PAID
PENDING_PAYMENT -> PAYMENT_FAILED -> PAID
```

`Payment` represents the overall payment intent for an order. `PaymentAttempt` preserves the history of each try, so a failed attempt can be followed by a successful retry without overwriting history.

Day 7 endpoints:

- `GET /api/v1/payments/{payment_id}`
- `POST /api/v1/payments/verify`
- `POST /api/v1/payments/mock-success`
- `POST /api/v1/payments/fail`
- `POST /api/v1/webhooks/razorpay`

Razorpay verification request:

```json
{
  "merchant_id": "00000000-0000-0000-0000-000000000000",
  "payment_id": "11111111-1111-1111-1111-111111111111",
  "razorpay_payment_id": "pay_xxx",
  "razorpay_order_id": "order_xxx",
  "razorpay_signature": "signature_from_checkout"
}
```

Use `Idempotency-Key` for retryable payment operations:

```http
Idempotency-Key: client-generated-unique-key
```

Idempotency records are stored in PostgreSQL with a unique `(key, operation)` constraint, so duplicate verification, mock success, failure recording, and webhook processing are safe across process restarts.

Webhook handling:

- Reads the raw request body.
- Verifies `X-Razorpay-Signature` outside mock mode.
- Stores provider webhook events with a unique provider event ID.
- Processes `payment.authorized`, `payment.captured`, and `payment.failed`.
- Safely acknowledges duplicate webhook deliveries without duplicate inventory deduction.

Inventory is deducted only in the centralized payment-success workflow, after payment verification or a valid success webhook. Deduction happens once using the `payments.inventory_deducted` guard. If inventory is insufficient at finalization time, payment success is rejected and the order is left for a later retry/manual resolution path.

Mock development mode:

- `PAYMENT_MODE=mock` enables `POST /api/v1/payments/mock-success`.
- Mock success is rejected when `ENVIRONMENT=production`.
- Mock success follows the same state machine and inventory deduction workflow as verified real payments.

Day 7 intentionally leaves richer production concerns for later polish: full concurrent race hardening, refund/compensation automation, webhook event replay tooling, and external Razorpay API payment amount fetches.

## Day 8: Audit events and merchant analytics

Day 8 adds a centralized audit trail and merchant-scoped dashboard APIs. Business workflows now emit durable `AuditEvent` rows for catalog setup, inventory changes, carts, checkout, payments, payment webhooks, agent tools, negotiations, and recommendations.

Audit endpoint:

- `GET /api/v1/audit-events?merchant_id=...`

Supported filters:

- `event_type`
- `entity_type`
- `entity_id`
- `start_date`
- `end_date`
- `limit`
- `offset`

Dashboard endpoints:

- `GET /api/v1/dashboard/overview`
- `GET /api/v1/dashboard/revenue`
- `GET /api/v1/dashboard/orders`
- `GET /api/v1/dashboard/products`
- `GET /api/v1/dashboard/inventory`
- `GET /api/v1/dashboard/agent-activity`
- `GET /api/v1/dashboard/negotiations`
- `GET /api/v1/dashboard/recommendations`

All dashboard endpoints are scoped by `merchant_id`. Date-aware endpoints validate that `start_date <= end_date` and return `422` for invalid ranges. Inventory analytics represent the current stock snapshot; revenue, orders, agent activity, negotiations, and recommendations can be filtered by date range.

## Day 9: Portfolio-quality SaaS frontend and integration hardening

Day 9 turns MerchantOS into a polished full-stack SaaS demo. The frontend now uses the existing Next.js App Router stack with Tailwind and a centralized typed API client.

Run backend:

```powershell
cd backend
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Run frontend:

```powershell
cd frontend
npm.cmd run dev
```

Frontend environment:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Safe public configuration endpoint:

- `GET /api/v1/config/public`

Operational list endpoints added for the UI:

- `GET /api/v1/orders?merchant_id=...`
- `GET /api/v1/payments?merchant_id=...`

These endpoints are merchant-scoped and do not expose secrets.

### MerchantOS Product Tour

- Dashboard: revenue, orders, successful payments, AI sessions, recent orders, inventory alerts, and audit pulse.
- Catalog: create products, add variants, search products, view status, and deactivate/reactivate products.
- Inventory: update available stock, see reserved quantity, and identify low/out-of-stock variants.
- Orders: monitor buyer sessions, order items, amount, order state, and linked payment state.
- Payments: inspect provider state, attempts, failure reasons, and run mock success in development.
- AI Agent: demo-ready chat interface with product search, policy, negotiation, recommendations, and tool activity visualization.
- Buyer Experience: guided search → negotiation → cart → checkout → mock payment journey.
- Analytics: revenue chart, order state, AI tool usage, negotiation acceptance, and recommendation mix.
- Policies: edit return window, cancellation window, minimum order value, negotiation status, max discount, and free-shipping threshold.
- Audit Logs: filter and inspect business events with metadata.
- Settings: show merchant information, API base URL, health, environment, payment mode, and safe configuration status.

Verification commands:

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall app tests
.\venv\Scripts\python.exe -m alembic upgrade head

cd ..\frontend
npm.cmd run lint
npm.cmd run build
```

## Day 10: Final production polish and demo readiness

MerchantOS is positioned for Razorpay Track 01 - AI Growth & Agentic Commerce: an AI-native merchant operating system that helps merchants sell more while keeping money-changing actions bounded by deterministic tools, merchant policy, payment verification, idempotency, inventory safety, and audit logs.

### Problem

Merchants lose revenue when buyers cannot find the right product, do not understand alternatives, abandon carts, fail payments, or ask for discounts that staff cannot consistently evaluate. Traditional dashboards show what happened after the fact; MerchantOS turns commerce operations into an AI-assisted workflow.

### Solution

MerchantOS combines:

- Buyer intent extraction
- Catalog search
- Controlled merchant agent tools
- Policy-gated negotiation
- Upsell/cross-sell recommendations
- Cart and checkout
- Razorpay-ready payment flow
- Payment state machine and idempotency
- Audit trail
- Merchant analytics
- A polished SaaS console and buyer demo flow

### Architecture diagram

```text
AI Buyer
  |
  v
MerchantOS Frontend
  |
  +--> Buyer Experience / Agent Chat
           |
           v
      LLM / Intent Layer
           |
           v
      Merchant Agent
           |
           v
      Controlled Tool Registry
        |-- Search
        |-- Inventory
        |-- Recommendations
        |-- Negotiation
        |-- Policy
        `-- Checkout
              |
              v
         Payment Layer
              |
              v
           Razorpay
              |
              v
          PostgreSQL

Audit + Analytics are cross-cutting layers across catalog, agent, cart, checkout, payment, and policy workflows.
```

### Demo mode

The app includes a deterministic demo seed for development and judging. It creates a clearly labeled demo merchant, realistic catalog, inventory, orders, payments, payment attempts, agent sessions, tool calls, negotiations, recommendations, upsell events, and audit events.

Run from CLI:

```powershell
cd backend
.\venv\Scripts\python.exe -m app.seed
```

Or from the frontend:

- Click `Load Demo Data` in the top bar.

Development-only API:

- `POST /api/v1/dev/seed-demo-data`

The endpoint is disabled when `ENVIRONMENT=production`.

### Final demo flow: 3-5 minutes

1. Open the MerchantOS frontend.
2. Click `Load Demo Data` if the dashboard is empty.
3. Start on Overview and point out revenue, orders, conversion, AI revenue, revenue at risk, funnel, top products, inventory alerts, and audit pulse.
4. Open AI Agent and ask: `I need black wireless headphones under ₹2500.`
5. Show deterministic tool calls: search, inventory, ranking, policy/recommendations.
6. Select a product/variant context and ask: `Can you do ₹2000?`
7. Show the negotiation result bounded by the merchant's maximum discount policy.
8. Open Buyer Experience and run the guided journey: search -> negotiate -> add to cart -> checkout -> mock payment.
9. Open Payments and show state/attempt history plus duplicate-safe success.
10. Open Audit Logs and show cart, order, payment, negotiation, recommendation, and agent events.
11. Return to Overview/Analytics and show updated metrics.

### Razorpay readiness

- Mock mode works without credentials and is clearly labeled as TEST MODE.
- Real mode requires `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`.
- The frontend never receives the secret.
- Payment success must pass verification/webhook processing or development mock success.
- Inventory is deducted only once after verified success.

### LLM readiness

- If an LLM provider/key is configured, the existing abstraction can be extended through `app/services/llm.py`.
- If no key is configured, deterministic fallback keeps the demo reliable.
- The LLM/agent does not directly mutate payments, inventory, or pricing; controlled tools and backend services enforce policy and state transitions.

### Security assumptions

Development merchant context is currently trusted. Production deployment should add authentication, authorization, role-based access, CSRF strategy where applicable, stricter CORS origins, rate limiting, and tenant-aware authorization checks at every boundary.

Implemented safeguards include:

- Merchant-scoped dashboard, orders, payments, audit, search, negotiation, and checkout workflows
- Pydantic payload validation
- ORM query construction rather than string SQL
- Public config endpoint that does not expose secrets
- Request-size limit middleware
- Razorpay secret never returned to frontend
- Idempotency for payment operations and webhooks

### Known limitations

- Authentication/authorization is not implemented yet.
- Demo metrics are derived from seeded development data when the seed is used; the UI labels test/demo mode clearly.
- Charts are lightweight custom components rather than a heavy charting library.
- Real Razorpay checkout opening in the browser requires valid test credentials and the Razorpay JS integration step.
- Production observability, rate limiting, queue-based webhook replay, refunds, and full concurrency stress hardening remain future work.
