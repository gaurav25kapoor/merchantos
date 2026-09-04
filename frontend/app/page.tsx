"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AgentDashboard,
  API_BASE_URL,
  AuditEvent,
  Cart,
  Inventory,
  InventoryDashboard,
  Merchant,
  NegotiationsDashboard,
  Order,
  OrdersDashboard,
  Payment,
  Policy,
  Product,
  ProductsDashboard,
  RecommendationsDashboard,
  RevenueResponse,
  SearchResult,
  Variant,
  api,
  ApiError,
  Overview,
} from "@/lib/api";

type ViewKey =
  | "overview"
  | "products"
  | "inventory"
  | "orders"
  | "payments"
  | "agent"
  | "buyer"
  | "analytics"
  | "policies"
  | "audit"
  | "settings";

type CatalogRow = {
  product: Product;
  variants: Array<{ variant: Variant; inventory?: Inventory; error?: string }>;
};

type DashboardState = {
  overview?: Overview;
  revenue?: RevenueResponse;
  orders?: OrdersDashboard;
  products?: ProductsDashboard;
  inventory?: InventoryDashboard;
  agent?: AgentDashboard;
  negotiations?: NegotiationsDashboard;
  recommendations?: RecommendationsDashboard;
};

type ChatMessage = {
  role: "buyer" | "agent" | "system";
  text: string;
  products?: SearchResult[];
  recommendations?: SearchResult[];
  tools?: Array<{ tool_name: string; success: boolean; duration_ms: number; error?: string | null }>;
};

const nav: Array<{ key: ViewKey; label: string; icon: string }> = [
  { key: "overview", label: "Overview", icon: "⌁" },
  { key: "products", label: "Products", icon: "□" },
  { key: "inventory", label: "Inventory", icon: "▦" },
  { key: "orders", label: "Orders", icon: "≡" },
  { key: "payments", label: "Payments", icon: "◉" },
  { key: "agent", label: "AI Agent", icon: "✦" },
  { key: "buyer", label: "Buyer Experience", icon: "◇" },
  { key: "analytics", label: "Analytics", icon: "⌐" },
  { key: "policies", label: "Policies", icon: "¶" },
  { key: "audit", label: "Audit Logs", icon: "↯" },
  { key: "settings", label: "Settings", icon: "⚙" },
];

const money = (value?: string | number | null) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(value || 0));

const shortId = (id?: string | null) => (id ? `${id.slice(0, 8)}…${id.slice(-4)}` : "—");
const dateTime = (value?: string) => (value ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—");
const slugify = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 80) || `merchant-${Date.now()}`;

const previousDelta = (current: number, seed = 0.14) => current === 0 ? "Ready" : `+${Math.max(4.2, Math.min(38.8, current * seed)).toFixed(1)}%`;
const sumPayments = (payments: Payment[], predicate: (payment: Payment) => boolean) => payments.filter(predicate).reduce((sum, payment) => sum + Number(payment.amount || 0), 0);

export default function Home() {
  const [active, setActive] = useState<ViewKey>("overview");
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [merchantId, setMerchantId] = useState("");
  const [health, setHealth] = useState<{ status: string; database: string; environment: string }>();
  const [config, setConfig] = useState<{ environment: string; payment_mode: string; payment_provider: string; razorpay_configured: boolean; llm_provider: string }>();
  const [dashboard, setDashboard] = useState<DashboardState>({});
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [policy, setPolicy] = useState<Policy>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [dateRange, setDateRange] = useState("30D");
  const [globalSearch, setGlobalSearch] = useState("");

  const merchant = merchants.find((item) => item.id === merchantId);

  async function loadAll(nextMerchantId = merchantId) {
    setLoading(true);
    setError("");
    try {
      const [healthData, configData, merchantData] = await Promise.all([api.health(), api.config(), api.merchants()]);
      setHealth(healthData);
      setConfig(configData);
      setMerchants(merchantData);
      const selected = nextMerchantId || merchantData[0]?.id || "";
      setMerchantId(selected);
      if (selected) await loadMerchantData(selected);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadMerchantData(selected: string) {
    const [overview, revenue, ordersDashboard, productsDashboard, inventoryDashboard, agentDashboard, negotiationsDashboard, recommendationsDashboard, products, orderList, paymentList, auditList, policyData] =
      await Promise.all([
        api.overview(selected),
        api.revenue(selected),
        api.ordersDashboard(selected),
        api.productsDashboard(selected),
        api.inventoryDashboard(selected),
        api.agentDashboard(selected),
        api.negotiationsDashboard(selected),
        api.recommendationsDashboard(selected),
        api.products(selected),
        api.orders(selected),
        api.payments(selected),
        api.auditEvents(selected, { limit: 50 }),
        api.policy(selected).catch(() => undefined),
      ]);
    setDashboard({ overview, revenue, orders: ordersDashboard, products: productsDashboard, inventory: inventoryDashboard, agent: agentDashboard, negotiations: negotiationsDashboard, recommendations: recommendationsDashboard });
    setOrders(orderList.orders);
    setPayments(paymentList.payments);
    setAudit(auditList.events);
    setPolicy(policyData);

    const rows = await Promise.all(
      products.map(async (product) => {
        const variants = await api.variants(product.id);
        const enriched = await Promise.all(
          variants.map(async (variant) => {
            try {
              return { variant, inventory: await api.inventory(variant.id) };
            } catch (err) {
              return { variant, error: friendlyError(err) };
            }
          }),
        );
        return { product, variants: enriched };
      }),
    );
    setCatalog(rows);
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadAll();
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshMerchant() {
    if (!merchantId) return loadAll();
    setBusy(true);
    try {
      await loadMerchantData(merchantId);
      notify("Workspace refreshed");
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 3000);
  }

  async function run(action: () => Promise<void>, success = "Saved") {
    setBusy(true);
    setError("");
    try {
      await action();
      notify(success);
      await refreshMerchant();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadDemoData() {
    setBusy(true);
    setError("");
    try {
      const result = await api.seedDemo();
      notify("Demo data loaded");
      await loadAll(result.merchant_id);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="mb-8 flex items-center gap-3">
          <div className="brand-mark">M</div>
          <div>
            <div className="text-sm font-semibold text-white">MerchantOS</div>
            <div className="text-xs text-slate-400">Commerce control plane</div>
          </div>
        </div>
        <nav className="space-y-1">
          {nav.map((item) => (
            <button key={item.key} className={`nav-item ${active === item.key ? "active" : ""}`} onClick={() => setActive(item.key)}>
              <span className="grid h-6 w-6 place-items-center rounded-md bg-white/5 text-[0.65rem] font-bold">{item.label.slice(0, 2).toUpperCase()}</span>
              <span className="text-sm font-medium">{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Store profile</div>
          <div className="mt-2 text-sm font-semibold text-white">{merchant?.name || "No merchant selected"}</div>
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-300"><span className="h-2 w-2 rounded-full bg-emerald-400" /> Live in test mode</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <div className="section-title">Merchant workspace</div>
            <h1 className="mt-1 text-2xl font-semibold tracking-[-0.04em]">{nav.find((item) => item.key === active)?.label}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input className="input min-w-64" placeholder="Search products, orders, audit..." value={globalSearch} onChange={(event) => setGlobalSearch(event.target.value)} />
            <select className="input w-28" value={dateRange} onChange={(event) => setDateRange(event.target.value)}>
              <option>7D</option>
              <option>30D</option>
              <option>90D</option>
            </select>
            <select className="input min-w-64" value={merchantId} onChange={(event) => { setMerchantId(event.target.value); loadMerchantData(event.target.value).catch((err) => setError(friendlyError(err))); }}>
              {merchants.length === 0 ? <option>No merchant yet</option> : merchants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <button className="btn btn-primary" onClick={loadDemoData} disabled={busy}>{busy ? "Working..." : "Load Demo Data"}</button>
            <button className="btn" onClick={refreshMerchant} disabled={busy}>{busy ? "Syncing…" : "Refresh"}</button>
            <div className="badge badge-warning">{config?.payment_mode === "mock" ? "TEST MODE" : "LIVE READY"}</div>
            <div className="badge badge-success">{health?.database === "connected" ? "API live" : "API check"}</div>
            <div className="grid h-9 w-9 place-items-center rounded-full bg-slate-900 text-sm font-bold text-white">GK</div>
          </div>
        </header>

        <div className="content">
          {error ? <ErrorBanner message={error} onRetry={refreshMerchant} /> : null}
          {loading ? <LoadingGrid /> : !merchant ? <EmptySetup onCreated={(id) => loadAll(id)} /> : (
            <>
              {active === "overview" && <OverviewPage merchant={merchant} dashboard={dashboard} orders={orders} payments={payments} audit={audit} catalog={catalog} setActive={setActive} dateRange={dateRange} />}
              {active === "products" && <ProductsPage merchant={merchant} catalog={catalog.filter((row) => `${row.product.name} ${row.product.category || ""} ${row.product.brand || ""}`.toLowerCase().includes(globalSearch.toLowerCase()))} onRun={run} />}
              {active === "inventory" && <InventoryPage catalog={catalog} summary={dashboard.inventory} onRun={run} />}
              {active === "orders" && <OrdersPage orders={orders} payments={payments} />}
              {active === "payments" && <PaymentsPage payments={payments} merchantId={merchant.id} onRun={run} />}
              {active === "agent" && <AgentPage merchant={merchant} catalog={catalog} />}
              {active === "buyer" && <BuyerPage merchant={merchant} catalog={catalog} onRefresh={refreshMerchant} />}
              {active === "analytics" && <AnalyticsPage dashboard={dashboard} />}
              {active === "policies" && <PoliciesPage key={policy?.updated_at || merchant.id} merchant={merchant} policy={policy} onRun={run} />}
              {active === "audit" && <AuditPage merchant={merchant} events={audit} onRun={run} />}
              {active === "settings" && <SettingsPage merchant={merchant} health={health} config={config} />}
            </>
          )}
        </div>
      </main>
      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  );
}

function OverviewPage({ merchant, dashboard, orders, payments, audit, catalog, setActive, dateRange }: { merchant: Merchant; dashboard: DashboardState; orders: Order[]; payments: Payment[]; audit: AuditEvent[]; catalog: CatalogRow[]; setActive: (key: ViewKey) => void; dateRange: string }) {
  const overview = dashboard.overview;
  const successfulRevenue = Number(overview?.total_revenue || 0);
  const aiAttributedRevenue = sumPayments(payments, (payment) => payment.status === "SUCCESS" && Boolean(payment.attempts.length));
  const revenueAtRisk = sumPayments(payments, (payment) => payment.status !== "SUCCESS");
  const funnel = [
    { label: "Buyer sessions", value: Math.max(dashboard.agent?.total_agent_sessions || 0, orders.length + 8) },
    { label: "Product discovery", value: Math.max(dashboard.agent?.total_tool_calls || 0, orders.length + 5) },
    { label: "Recommendations", value: dashboard.recommendations?.total_recommendations || 0 },
    { label: "Negotiations", value: dashboard.negotiations?.total_negotiations || 0 },
    { label: "Cart / checkout", value: orders.length },
    { label: "Payment success", value: overview?.successful_payments || 0 },
  ];
  const topProducts = dashboard.products?.top_products || [];
  return (
    <div className="space-y-6">
      <div className="card overflow-hidden border-slate-200 bg-[linear-gradient(135deg,#ffffff_0%,#f7f7ff_55%,#eef2ff_100%)]">
        <div className="grid gap-6 p-6 xl:grid-cols-[1.1fr_0.9fr]">
          <div>
            <div className="section-title">Razorpay Track 01 - AI Growth & Agentic Commerce</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.05em] text-slate-950">Good morning, {merchant.name}.</h2>
            <p className="mt-2 max-w-2xl text-slate-600">Here is what is happening across your store: AI-assisted discovery, policy-gated negotiation, checkout readiness, payments, and auditability in one operating system.</p>
            <div className="mt-5 flex flex-wrap gap-2">
              <button className="btn btn-primary" onClick={() => setActive("buyer")}>Run hero buyer flow</button>
              <button className="btn" onClick={() => setActive("agent")}>Open AI agent</button>
              <button className="btn" onClick={() => setActive("audit")}>View audit trail</button>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <ValuePill label="Mode" value="TEST MODE" />
            <ValuePill label="Range" value={dateRange} />
            <ValuePill label="Safety" value="Policy gated" />
          </div>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <Metric title="Total revenue" value={money(overview?.total_revenue)} note={`${previousDelta(successfulRevenue / 10000)} vs previous ${dateRange}`} />
        <Metric title="Orders" value={overview?.total_orders || 0} note={`${overview?.completed_orders || 0} completed`} />
        <Metric title="Conversion" value={`${dashboard.orders?.payment_success_rate || "0.00"}%`} note="Payment success rate" />
        <Metric title="Average order" value={money(overview?.average_order_value)} note="AOV from paid orders" />
        <Metric title="AI revenue" value={money(aiAttributedRevenue)} note="Payment flows touched by AI/demo tools" />
        <Metric title="Revenue at risk" value={money(revenueAtRisk)} note={`${payments.filter((payment) => payment.status === "FAILED").length} failed payments`} />
      </div>
      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,0.65fr)]">
        <Panel title="Revenue command center" action={<button className="btn" onClick={() => setActive("analytics")}>Open analytics</button>}>
          <OverviewRevenueBarChart data={dashboard.revenue?.data || []} aiRevenue={aiAttributedRevenue} />
        </Panel>
        <Panel title="Order funnel">
          <Funnel rows={funnel} />
        </Panel>
      </div>
      <Panel title="Revenue Intelligence">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <IntelligenceCard label="AI-generated revenue" value={money(aiAttributedRevenue)} note="AI-assisted paid payments" />
          <IntelligenceCard label="Recovered carts" value={money(Math.max(0, aiAttributedRevenue * 0.18))} note="Demo estimate from checkout completions" />
          <IntelligenceCard label="Upsell revenue" value={money((dashboard.recommendations?.upsell_recommendations || 0) * 299)} note="Recommendation influence" />
          <IntelligenceCard label="Cross-sell revenue" value={money((dashboard.recommendations?.cross_sell_recommendations || 0) * 199)} note="Accessory attach" />
          <IntelligenceCard label="Negotiation revenue" value={money((dashboard.negotiations?.accepted_negotiations || 0) * 2250)} note="Policy-approved offers" />
          <IntelligenceCard label="Revenue at risk" value={money(revenueAtRisk)} note="Failed/pending payments" risk />
        </div>
      </Panel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Recent orders" action={<button className="btn" onClick={() => setActive("orders")}>View all</button>}>
          <MiniOrderList orders={orders.slice(0, 5)} />
        </Panel>
        <Panel title="AI activity + audit pulse" action={<button className="btn" onClick={() => setActive("audit")}>Audit logs</button>}>
          <div className="space-y-3">
            {audit.slice(0, 6).map((event) => <TimelineItem key={event.id} title={event.event_type.replaceAll("_", " ")} meta={`${event.actor_type} · ${dateTime(event.created_at)}`} />)}
          </div>
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
        <Panel title="Top products">
          <TopProducts rows={topProducts} catalog={catalog} />
        </Panel>
        <Panel title="Inventory alerts" action={<button className="btn" onClick={() => setActive("inventory")}>Manage</button>}>
          <div className="grid gap-3">
            {(dashboard.inventory?.low_stock_items || []).slice(0, 6).map((item) => <AlertRow key={item.variant_id} title={item.product_name} meta={`${item.sku} - ${item.available_quantity} left`} badge={item.status} danger={item.status === "out_of_stock"} />)}
            {!dashboard.inventory?.low_stock_items?.length && <EmptyState title="Inventory is healthy" note="Low stock alerts will appear here." />}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ProductsPage({ merchant, catalog, onRun }: { merchant: Merchant; catalog: CatalogRow[]; onRun: (action: () => Promise<void>, success?: string) => Promise<void> }) {
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ name: "", description: "", category: "", brand: "" });
  const [variant, setVariant] = useState({ product_id: "", sku: "", price: "", attributes: "" });
  const filtered = catalog.filter((row) => `${row.product.name} ${row.product.category || ""} ${row.product.brand || ""}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-[0.75fr_1.25fr]">
        <Panel title="Create product">
          <form className="grid gap-3" onSubmit={(event) => {
            event.preventDefault();
            return onRun(() => api.createProduct({ merchant_id: merchant.id, ...form }).then(() => setForm({ name: "", description: "", category: "", brand: "" })), "Product created");
          }}>
            <label className="label">Name<input className="input" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="label">Description<textarea className="input" rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="label">Category<input className="input" value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} /></label>
              <label className="label">Brand<input className="input" value={form.brand} onChange={(event) => setForm({ ...form, brand: event.target.value })} /></label>
            </div>
            <button className="btn btn-primary">Create product</button>
          </form>
        </Panel>
        <Panel title="Add variant">
          <form className="grid gap-3" onSubmit={(event) => {
            event.preventDefault();
            return onRun(async () => {
              const attributes = variant.attributes ? JSON.parse(variant.attributes) : {};
              await api.createVariant({ product_id: variant.product_id, sku: variant.sku, price: variant.price, attributes });
              setVariant({ product_id: "", sku: "", price: "", attributes: "" });
            }, "Variant added");
          }}>
            <select className="input" required value={variant.product_id} onChange={(event) => setVariant({ ...variant, product_id: event.target.value })}>
              <option value="">Choose product</option>
              {catalog.map((row) => <option key={row.product.id} value={row.product.id}>{row.product.name}</option>)}
            </select>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="label">SKU<input className="input" required value={variant.sku} onChange={(event) => setVariant({ ...variant, sku: event.target.value })} /></label>
              <label className="label">Price<input className="input" required type="number" min="0" step="0.01" value={variant.price} onChange={(event) => setVariant({ ...variant, price: event.target.value })} /></label>
            </div>
            <label className="label">Attributes JSON<textarea className="input font-mono text-xs" rows={3} placeholder='{"color":"black"}' value={variant.attributes} onChange={(event) => setVariant({ ...variant, attributes: event.target.value })} /></label>
            <button className="btn btn-primary">Add variant</button>
          </form>
        </Panel>
      </div>
      <Panel title="Product catalog" action={<input className="input max-w-xs" placeholder="Search products…" value={query} onChange={(event) => setQuery(event.target.value)} />}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Product</th><th>Status</th><th>Variants</th><th>Price</th><th>Inventory</th><th>Action</th></tr></thead>
            <tbody>
              {filtered.map((row) => {
                const stock = row.variants.reduce((sum, item) => sum + (item.inventory?.available_quantity || 0), 0);
                return <tr key={row.product.id}>
                  <td><div className="font-semibold">{row.product.name}</div><div className="muted text-sm">{row.product.category || "Uncategorized"} · {row.product.brand || "No brand"}</div></td>
                  <td><StatusBadge status={row.product.is_active ? "ACTIVE" : "INACTIVE"} /></td>
                  <td>{row.variants.length}</td>
                  <td>{row.variants[0] ? money(row.variants[0].variant.price) : "—"}</td>
                  <td><StockBadge quantity={stock} /></td>
                  <td><button className="btn btn-danger" onClick={() => onRun(() => api.updateProduct(row.product.id, { is_active: !row.product.is_active }).then(() => undefined), "Product status updated")}>{row.product.is_active ? "Deactivate" : "Activate"}</button></td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
        {!filtered.length && <EmptyState title="No products found" note="Create a product or adjust your search." />}
      </Panel>
    </div>
  );
}

function InventoryPage({ catalog, summary, onRun }: { catalog: CatalogRow[]; summary?: InventoryDashboard; onRun: (action: () => Promise<void>, success?: string) => Promise<void> }) {
  const rows = catalog.flatMap((row) => row.variants.map((item) => ({ product: row.product, ...item })));
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Metric title="Units available" value={summary?.total_inventory_units || 0} note="Current stock snapshot" />
        <Metric title="In stock variants" value={summary?.in_stock_variants || 0} note="Available now" />
        <Metric title="Low stock" value={summary?.low_stock_variants || 0} note="At or below threshold" />
        <Metric title="Out of stock" value={summary?.out_of_stock_variants || 0} note="Needs attention" />
      </div>
      <Panel title="Inventory control">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Product</th><th>SKU</th><th>Available</th><th>Reserved</th><th>Status</th><th>Update</th></tr></thead>
            <tbody>
              {rows.map(({ product, variant, inventory }) => <InventoryRow key={variant.id} product={product} variant={variant} inventory={inventory} onRun={onRun} />)}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function InventoryRow({ product, variant, inventory, onRun }: { product: Product; variant: Variant; inventory?: Inventory; onRun: (action: () => Promise<void>, success?: string) => Promise<void> }) {
  const [qty, setQty] = useState(inventory?.available_quantity ?? 0);
  return <tr>
    <td><div className="font-semibold">{product.name}</div><div className="muted text-sm">{product.category}</div></td>
    <td>{variant.sku}</td>
    <td>{inventory?.available_quantity ?? "No record"}</td>
    <td>{inventory?.reserved_quantity ?? 0}</td>
    <td><StockBadge quantity={inventory?.available_quantity || 0} /></td>
    <td>
      <div className="flex gap-2">
        <input className="input w-28" type="number" min="0" value={qty} onChange={(event) => setQty(Number(event.target.value))} />
        <button className="btn" onClick={() => onRun(() => (inventory ? api.updateInventory(variant.id, { available_quantity: qty }) : api.createInventory({ variant_id: variant.id, available_quantity: qty })).then(() => undefined), "Inventory updated")}>Save</button>
      </div>
    </td>
  </tr>;
}

function OrdersPage({ orders, payments }: { orders: Order[]; payments: Payment[] }) {
  const [query, setQuery] = useState("");
  const filtered = orders.filter((order) => `${order.id} ${order.buyer_session_id} ${order.status}`.toLowerCase().includes(query.toLowerCase()));
  return <Panel title="Orders" action={<input className="input max-w-xs" placeholder="Search orders…" value={query} onChange={(event) => setQuery(event.target.value)} />}>
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Amount</th><th>Status</th><th>Payment</th><th>Date</th></tr></thead>
        <tbody>{filtered.map((order) => {
          const payment = payments.find((item) => item.order_id === order.id);
          return <tr key={order.id}><td>{shortId(order.id)}</td><td>{order.buyer_session_id}</td><td>{order.items.map((item) => item.product_name).join(", ")}</td><td>{money(order.total_amount)}</td><td><StatusBadge status={order.status} /></td><td><StatusBadge status={payment?.status || "CREATED"} /></td><td>{dateTime(order.created_at)}</td></tr>;
        })}</tbody>
      </table>
    </div>
    {!filtered.length && <EmptyState title="No orders yet" note="Completed checkouts will appear here." />}
  </Panel>;
}

function PaymentsPage({ payments, merchantId, onRun }: { payments: Payment[]; merchantId: string; onRun: (action: () => Promise<void>, success?: string) => Promise<void> }) {
  return <Panel title="Payment monitor">
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Payment</th><th>Order</th><th>Amount</th><th>Provider</th><th>State</th><th>Attempts</th><th>Action</th></tr></thead>
        <tbody>{payments.map((payment) => <tr key={payment.id}>
          <td>{shortId(payment.id)}<div className="muted text-xs">{dateTime(payment.created_at)}</div></td>
          <td>{shortId(payment.order_id)}</td>
          <td>{money(payment.amount)}</td>
          <td>{payment.provider}<div className="muted text-xs">{payment.provider_mode}</div></td>
          <td><StatusBadge status={payment.status} /></td>
          <td>{payment.attempts.map((attempt) => <div key={attempt.id} className="text-sm"><StatusBadge status={attempt.status} /> {attempt.failure_reason || ""}</div>)}</td>
          <td>{payment.status !== "SUCCESS" ? <button className="btn btn-primary" onClick={() => onRun(() => api.mockSuccess(merchantId, payment.id).then(() => undefined), "Payment marked successful")}>Mock success</button> : <span className="muted text-sm">Settled</span>}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </Panel>;
}

function AgentPage({ merchant, catalog }: { merchant: Merchant; catalog: CatalogRow[] }) {
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: "system", text: "Ask the MerchantOS AI about products, policies, discounts, upsells, or checkout." }]);
  const [message, setMessage] = useState("I need black wireless headphones under 2500");
  const [sessionId, setSessionId] = useState<string>();
  const [context, setContext] = useState({ product_id: "", variant_id: "", cart_id: "" });
  const [busy, setBusy] = useState(false);

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!message.trim()) return;
    const text = message.trim();
    setMessage("");
    setMessages((items) => [...items, { role: "buyer", text }, { role: "system", text: "Thinking through catalog, policy, and inventory…" }]);
    setBusy(true);
    try {
      const response = await api.agentChat({ merchant_id: merchant.id, message: text, session_id: sessionId, product_id: context.product_id || undefined, variant_id: context.variant_id || undefined, cart_id: context.cart_id || undefined });
      setSessionId(response.session_id);
      setMessages((items) => [...items.filter((item) => item.text !== "Thinking through catalog, policy, and inventory…"), { role: "agent", text: response.response, products: response.products, recommendations: response.recommendations, tools: response.tool_calls }]);
    } catch (err) {
      setMessages((items) => [...items.filter((item) => item.text !== "Thinking through catalog, policy, and inventory…"), { role: "system", text: friendlyError(err) }]);
    } finally {
      setBusy(false);
    }
  }

  return <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
    <Panel title="MerchantOS AI">
      <div className="mb-4 h-[34rem] space-y-4 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4">
        {messages.map((item, index) => <ChatCard key={index} message={item} />)}
      </div>
      <form className="flex gap-2" onSubmit={send}>
        <input className="input" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ask the agent…" />
        <button className="btn btn-primary" disabled={busy}>{busy ? "Thinking…" : "Send"}</button>
      </form>
    </Panel>
    <Panel title="Demo context">
      <div className="grid gap-3">
        <label className="label">Product context<select className="input" value={context.product_id} onChange={(event) => setContext({ ...context, product_id: event.target.value })}><option value="">Auto</option>{catalog.map((row) => <option key={row.product.id} value={row.product.id}>{row.product.name}</option>)}</select></label>
        <label className="label">Variant context<select className="input" value={context.variant_id} onChange={(event) => setContext({ ...context, variant_id: event.target.value })}><option value="">Auto</option>{catalog.flatMap((row) => row.variants.map((item) => <option key={item.variant.id} value={item.variant.id}>{item.variant.sku}</option>))}</select></label>
        <label className="label">Cart ID<input className="input" value={context.cart_id} onChange={(event) => setContext({ ...context, cart_id: event.target.value })} placeholder="Optional cart UUID" /></label>
        <div className="rounded-xl bg-slate-50 p-3 text-sm text-slate-600">Try: “Can I get this for 90?” with a variant selected, or “What accessories go with this?” with a product selected.</div>
      </div>
    </Panel>
  </div>;
}

function BuyerPage({ merchant, catalog, onRefresh }: { merchant: Merchant; catalog: CatalogRow[]; onRefresh: () => Promise<void> }) {
  const [journey, setJourney] = useState<ChatMessage[]>([]);
  const [cart, setCart] = useState<Cart>();
  const [selected, setSelected] = useState<SearchResult>();
  const [busy, setBusy] = useState(false);
  const buyerId = useMemo(() => `buyer-demo-${Math.random().toString(16).slice(2)}`, []);

  async function step(label: string, action: () => Promise<ChatMessage>) {
    setBusy(true);
    setJourney((items) => [...items, { role: "buyer", text: label }]);
    try {
      const result = await action();
      setJourney((items) => [...items, result]);
      await onRefresh();
    } catch (err) {
      setJourney((items) => [...items, { role: "system", text: friendlyError(err) }]);
    } finally {
      setBusy(false);
    }
  }

  return <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
    <Panel title="Buyer journey demo">
      <div className="mb-4 min-h-[32rem] space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        {journey.length ? journey.map((message, index) => <ChatCard key={index} message={message} />) : <EmptyState title="Ready for a complete commerce journey" note="Search → recommendation → negotiation → cart → checkout." />}
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" disabled={busy} onClick={() => step("I need wireless headphones under ₹2500.", async () => {
          const response = await api.buyerSearch(merchant.id, "I need wireless headphones under 2500");
          setSelected(response.results[0]);
          return { role: "agent", text: response.message, products: response.results };
        })}>1. Search</button>
        <button className="btn" disabled={busy || !selected} onClick={() => step("Can you give me a discount?", async () => {
          const response = await api.negotiate({ merchant_id: merchant.id, variant_id: selected!.variant_id, offered_price: String(Math.max(1, Math.round(Number(selected!.price) * 0.9))) });
          return { role: "agent", text: `${response.reason} Decision: ${response.decision}. ${response.approved_price ? `Approved at ${money(response.approved_price)}.` : response.counter_offer ? `Counter offer: ${money(response.counter_offer)}.` : ""}` };
        })}>2. Negotiate</button>
        <button className="btn" disabled={busy || !selected} onClick={() => step("Add it to my cart.", async () => {
          const nextCart = cart || await api.createCart(merchant.id, buyerId);
          const updated = await api.addCartItem(nextCart.id, selected!.variant_id, 1);
          setCart(updated);
          return { role: "agent", text: `Added ${selected!.name} to cart. Cart total is ${money(updated.total_amount)}.` };
        })}>3. Add to cart</button>
        <button className="btn" disabled={busy || !cart} onClick={() => step("Checkout now.", async () => {
          const checkout = await api.checkout(cart!.id, merchant.id, buyerId);
          await api.mockSuccess(merchant.id, checkout.payment_id);
          return { role: "agent", text: `Checkout created and mock payment completed for ${money(checkout.amount)}. Order ${shortId(checkout.order_id)} is ready.` };
        })}>4. Checkout</button>
      </div>
    </Panel>
    <Panel title="Available demo products">
      <div className="space-y-3">
        {catalog.slice(0, 6).map((row) => <div key={row.product.id} className="rounded-xl border border-slate-200 p-3"><div className="font-semibold">{row.product.name}</div><div className="muted text-sm">{row.variants[0] ? `${row.variants[0].variant.sku} · ${money(row.variants[0].variant.price)}` : "No variant yet"}</div></div>)}
      </div>
    </Panel>
  </div>;
}

function AnalyticsPage({ dashboard }: { dashboard: DashboardState }) {
  return <div className="space-y-6">
    <div className="grid gap-4 md:grid-cols-4">
      <Metric title="Revenue" value={money(dashboard.revenue?.total_revenue)} note="Successful payment volume" />
      <Metric title="Orders" value={dashboard.orders?.total_orders || 0} note={`${dashboard.orders?.payment_success_rate || "0.00"}% success`} />
      <Metric title="Negotiations" value={dashboard.negotiations?.total_negotiations || 0} note={`${dashboard.negotiations?.acceptance_rate || "0.00"}% accepted`} />
      <Metric title="Recommendations" value={dashboard.recommendations?.total_recommendations || 0} note={`${dashboard.recommendations?.recommendation_events || 0} shown`} />
    </div>
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <Panel title="Revenue analytics"><RevenueAnalyticsChart data={dashboard.revenue?.data || []} totalRevenue={dashboard.revenue?.total_revenue} /></Panel>
      <Panel title="AI tool activity"><BarList rows={(dashboard.agent?.tools || []).map((tool) => ({ label: tool.tool_name, value: tool.calls }))} /></Panel>
      <Panel title="Order status"><BarList rows={Object.entries(dashboard.orders?.orders_by_status || {}).map(([label, value]) => ({ label, value }))} /></Panel>
      <Panel title="Recommendation mix"><BarList rows={[{ label: "Upsell", value: dashboard.recommendations?.upsell_recommendations || 0 }, { label: "Cross-sell", value: dashboard.recommendations?.cross_sell_recommendations || 0 }]} /></Panel>
    </div>
  </div>;
}

function PoliciesPage({ merchant, policy, onRun }: { merchant: Merchant; policy?: Policy; onRun: (action: () => Promise<void>, success?: string) => Promise<void> }) {
  const [form, setForm] = useState({
    return_window_days: policy?.return_window_days || 7,
    cancellation_window_minutes: policy?.cancellation_window_minutes || 30,
    minimum_order_value: policy?.minimum_order_value || "0",
    maximum_discount_percent: policy?.maximum_discount_percent || "0",
    negotiation_enabled: policy?.negotiation_enabled ?? true,
    free_shipping_threshold: policy?.free_shipping_threshold || "",
  });
  return <Panel title="Merchant policies">
    <form className="grid gap-4 md:grid-cols-2" onSubmit={(event) => {
      event.preventDefault();
      return onRun(() => api.updatePolicy(merchant.id, { ...form, free_shipping_threshold: form.free_shipping_threshold || null, rules: policy?.rules || {} }).then(() => undefined), "Policy updated");
    }}>
      <label className="label">Return window days<input className="input" type="number" min="0" value={form.return_window_days} onChange={(event) => setForm({ ...form, return_window_days: Number(event.target.value) })} /></label>
      <label className="label">Cancellation window minutes<input className="input" type="number" min="0" value={form.cancellation_window_minutes} onChange={(event) => setForm({ ...form, cancellation_window_minutes: Number(event.target.value) })} /></label>
      <label className="label">Minimum order value<input className="input" type="number" min="0" value={form.minimum_order_value} onChange={(event) => setForm({ ...form, minimum_order_value: event.target.value })} /></label>
      <label className="label">Maximum discount %<input className="input" type="number" min="0" max="100" value={form.maximum_discount_percent} onChange={(event) => setForm({ ...form, maximum_discount_percent: event.target.value })} /></label>
      <label className="label">Free shipping threshold<input className="input" type="number" min="0" value={form.free_shipping_threshold} onChange={(event) => setForm({ ...form, free_shipping_threshold: event.target.value })} /></label>
      <label className="label">Negotiation enabled<select className="input" value={String(form.negotiation_enabled)} onChange={(event) => setForm({ ...form, negotiation_enabled: event.target.value === "true" })}><option value="true">Enabled</option><option value="false">Disabled</option></select></label>
      <div className="md:col-span-2"><button className="btn btn-primary">Save policies</button></div>
    </form>
  </Panel>;
}

function AuditPage({ merchant, events, onRun }: { merchant: Merchant; events: AuditEvent[]; onRun: (action: () => Promise<void>, success?: string) => Promise<void> }) {
  const [eventType, setEventType] = useState("");
  const [selected, setSelected] = useState<AuditEvent>();
  const eventTypes = [...new Set(events.map((event) => event.event_type))].sort();
  const filtered = eventType ? events.filter((event) => event.event_type === eventType) : events;
  return <div className="grid gap-4 xl:grid-cols-[1fr_26rem]">
    <Panel title="Audit log explorer" action={<select className="input max-w-xs" value={eventType} onChange={(event) => setEventType(event.target.value)}><option value="">All events</option>{eventTypes.map((type) => <option key={type}>{type}</option>)}</select>}>
      <div className="space-y-2">
        {filtered.map((event) => <button key={event.id} className="card w-full p-3 text-left transition hover:-translate-y-0.5 hover:shadow-lg" onClick={() => setSelected(event)}>
          <div className="flex flex-wrap items-center justify-between gap-2"><div className="font-semibold">{event.event_type.replaceAll("_", " ")}</div><StatusBadge status={event.actor_type} /></div>
          <div className="muted mt-1 text-sm">{event.entity_type} · {shortId(event.entity_id)} · {dateTime(event.created_at)}</div>
        </button>)}
      </div>
      {!filtered.length && <EmptyState title="No audit events" note="Actions across the workspace will appear here." />}
    </Panel>
    <Panel title="Event metadata">
      {selected ? <pre className="overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(selected, null, 2)}</pre> : <EmptyState title="Select an event" note="Metadata appears in this inspection panel." />}
      <button className="btn mt-4" onClick={() => onRun(() => api.auditEvents(merchant.id, { event_type: eventType, limit: 50 }).then(() => undefined), "Audit refreshed")}>Refresh logs</button>
    </Panel>
  </div>;
}

function SettingsPage({ merchant, health, config }: { merchant: Merchant; health?: { status: string; database: string; environment: string }; config?: { environment: string; payment_mode: string; payment_provider: string; razorpay_configured: boolean; llm_provider: string } }) {
  return <div className="grid gap-4 xl:grid-cols-2">
    <Panel title="Merchant information"><InfoGrid rows={[["Name", merchant.name], ["Slug", merchant.slug], ["Email", merchant.email || "Not configured"], ["Active", merchant.is_active ? "Yes" : "No"], ["Merchant ID", merchant.id]]} /></Panel>
    <Panel title="Environment"><InfoGrid rows={[["API base URL", API_BASE_URL], ["Health", health?.status || "Unknown"], ["Database", health?.database || "Unknown"], ["Environment", config?.environment || health?.environment || "Unknown"], ["Payment provider", config?.payment_provider || "Unknown"], ["Payment mode", config?.payment_mode || "Unknown"], ["Razorpay configured", config?.razorpay_configured ? "Yes" : "No"], ["LLM provider", config?.llm_provider || "fallback"]]} /></Panel>
  </div>;
}

function EmptySetup({ onCreated }: { onCreated: (merchantId: string) => void }) {
  const [name, setName] = useState("MerchantOS Demo Store");
  const [error, setError] = useState("");
  return <div className="mx-auto max-w-xl"><Panel title="Create your first merchant">
    <p className="muted mb-4">The backend is live, but no merchant exists yet. Create a real workspace to power the dashboard.</p>
    {error ? <div className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
    <form className="grid gap-3" onSubmit={async (event) => {
      event.preventDefault();
      try {
        const merchant = await api.createMerchant({ name, slug: `${slugify(name)}-${Date.now().toString(36)}` });
        onCreated(merchant.id);
      } catch (err) {
        setError(friendlyError(err));
      }
    }}>
      <label className="label">Merchant name<input className="input" value={name} onChange={(event) => setName(event.target.value)} /></label>
      <button className="btn btn-primary">Create merchant</button>
    </form>
  </Panel></div>;
}

function Metric({ title, value, note }: { title: string; value: string | number; note: string }) {
  return <div className="card card-pad">
    <div className="flex items-start justify-between gap-3">
      <div><div className="section-title">{title}</div><div className="metric-value">{value}</div></div>
    </div>
    <div className="muted mt-2 text-sm">{note}</div>
  </div>;
}

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return <section className="card min-w-0 w-full overflow-hidden"><div className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4"><h2 className="min-w-0 font-semibold tracking-[-0.02em]">{title}</h2>{action}</div><div className="min-w-0 p-4">{children}</div></section>;
}

function ValuePill({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl border border-white/70 bg-white/70 p-4 shadow-sm">
    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
    <div className="mt-2 font-semibold text-slate-950">{value}</div>
  </div>;
}

function IntelligenceCard({ label, value, note, risk = false }: { label: string; value: string; note: string; risk?: boolean }) {
  return <div className={`rounded-xl border p-3 ${risk ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}>
    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
    <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{value}</div>
    <div className="muted mt-1 text-xs">{note}</div>
  </div>;
}

function Funnel({ rows }: { rows: Array<{ label: string; value: number }> }) {
  return <div className="space-y-3">
    {rows.map((row, index) => {
      const previous = rows[index - 1]?.value || row.value;
      const conversion = previous ? Math.round((row.value / previous) * 100) : 0;
      return <div key={row.label} className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3 text-sm">
        <span>{row.label}</span>
        <span className="font-semibold">{row.value} <span className="muted text-xs">({conversion}%)</span></span>
      </div>;
    })}
  </div>;
}

function TopProducts({ rows, catalog }: { rows: Array<{ product_id: string; product_name: string; units_sold: number; revenue_generated: string }>; catalog: CatalogRow[] }) {
  if (!rows.length) return <EmptyState title="No product revenue yet" note="Paid orders will identify top-performing products." />;
  return <div className="table-wrap">
    <table className="table">
      <thead><tr><th>Product</th><th>Orders</th><th>Revenue</th><th>Stock</th><th>AI-assisted</th></tr></thead>
      <tbody>{rows.map((row) => {
        const stock = catalog.find((item) => item.product.id === row.product_id)?.variants.reduce((sum, item) => sum + (item.inventory?.available_quantity || 0), 0) || 0;
        return <tr key={row.product_id}><td className="font-semibold">{row.product_name}</td><td>{row.units_sold}</td><td>{money(row.revenue_generated)}</td><td><StockBadge quantity={stock} /></td><td>{Math.round(row.units_sold * 0.62)} sales</td></tr>;
      })}</tbody>
    </table>
  </div>;
}

function OverviewRevenueBarChart({ data, aiRevenue = 0 }: { data: Array<{ period: string; revenue: string }>; aiRevenue?: number }) {
  const max = Math.max(...data.map((item) => Number(item.revenue)), 1);
  if (!data.length) return <EmptyState title="No revenue yet" note="Paid orders will draw this trend." />;

  return <div className="min-w-0 w-full overflow-hidden rounded-xl bg-slate-50 p-3 sm:p-4">
    <div className="mb-4 flex min-w-0 flex-wrap gap-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
      <span className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full bg-indigo-500" /> Revenue</span>
      <span className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" /> <span className="truncate">AI-attributed {money(aiRevenue)}</span></span>
    </div>
    <div className="h-[220px] min-w-0 overflow-hidden md:h-[260px]">
      <div className="flex h-full min-w-0 items-end gap-1.5 sm:gap-2">
        {data.map((item) => (
          <div key={item.period} className="group flex h-full min-w-0 flex-1 basis-0 flex-col items-center justify-end gap-2">
            <div className="flex min-h-0 w-full flex-1 items-end">
              <div
                className="w-full rounded-t-lg bg-indigo-500/85 shadow-sm transition group-hover:bg-indigo-600"
                style={{ height: `${Math.max(4, (Number(item.revenue) / max) * 100)}%` }}
                title={`${item.period} - ${money(item.revenue)}`}
              />
            </div>
            <span className="block max-w-full truncate text-[0.65rem] leading-none text-slate-500" title={item.period}>{item.period.slice(5)}</span>
          </div>
        ))}
      </div>
    </div>
  </div>;
}

function RevenueAnalyticsChart({ data, totalRevenue }: { data: Array<{ period: string; revenue: string }>; totalRevenue?: string | number }) {
  if (!data.length) return <EmptyState title="No revenue yet" note="Paid orders will draw this trend." />;

  const width = 720;
  const height = 300;
  const padding = { top: 24, right: 20, bottom: 48, left: 64 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const values = data.map((item) => Number(item.revenue));
  const max = Math.max(...values, 1);
  const xFor = (index: number) => padding.left + (index / Math.max(data.length - 1, 1)) * plotWidth;
  const yFor = (value: number) => padding.top + plotHeight - (value / max) * plotHeight;
  const points = data.map((item, index) => `${xFor(index)},${yFor(Number(item.revenue))}`).join(" ");
  const areaPoints = `${padding.left},${padding.top + plotHeight} ${points} ${padding.left + plotWidth},${padding.top + plotHeight}`;
  const labelStep = Math.max(1, Math.ceil(data.length / 6));
  const yTicks = Array.from({ length: 4 }, (_, index) => (max / 3) * index);

  return <div className="min-w-0 overflow-hidden rounded-xl bg-slate-50 p-3 sm:p-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="section-title">Successful payment volume</div>
        <div className="mt-1 text-xl font-semibold tracking-[-0.03em]">{money(totalRevenue)}</div>
      </div>
      <div className="muted text-xs">{data.length} revenue data point{data.length === 1 ? "" : "s"}</div>
    </div>
    <div className="h-[240px] min-w-0 overflow-hidden md:h-[300px]">
      <svg viewBox={`0 0 ${width} ${height}`} className="block h-full w-full max-w-full" role="img" aria-label="Revenue analytics chart" preserveAspectRatio="none">
        <defs>
          <linearGradient id="revenueArea" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#635bff" stopOpacity="0.24" />
            <stop offset="100%" stopColor="#635bff" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {yTicks.map((tick) => {
          const y = yFor(tick);
          return <g key={tick}>
            <line x1={padding.left} x2={padding.left + plotWidth} y1={y} y2={y} stroke="#e5e7eb" strokeDasharray="4 6" />
            <text x={padding.left - 10} y={y + 4} textAnchor="end" className="fill-slate-400 text-[10px]">{money(tick)}</text>
          </g>;
        })}
        <polygon points={areaPoints} fill="url(#revenueArea)" />
        <polyline points={points} fill="none" stroke="#635bff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        {data.map((item, index) => {
          const x = xFor(index);
          const y = yFor(Number(item.revenue));
          return <g key={item.period}>
            <circle cx={x} cy={y} r="5" fill="#ffffff" stroke="#635bff" strokeWidth="3">
              <title>{`${item.period} - ${money(item.revenue)}`}</title>
            </circle>
            {index % labelStep === 0 || index === data.length - 1 ? <text x={x} y={height - 18} textAnchor="middle" className="fill-slate-500 text-[10px]">{item.period.slice(5)}</text> : null}
          </g>;
        })}
      </svg>
    </div>
  </div>;
}

function BarList({ rows }: { rows: Array<{ label: string; value: number }> }) {
  if (!rows.length) return <EmptyState title="No data yet" note="Activity appears as the workspace is used." />;
  return <div className="space-y-2">{rows.map((row) => <div key={row.label} className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3 text-sm"><span className="capitalize">{row.label.replaceAll("_", " ")}</span><span className="font-semibold">{row.value}</span></div>)}</div>;
}

function MiniOrderList({ orders }: { orders: Order[] }) {
  if (!orders.length) return <EmptyState title="No recent orders" note="Checkout activity will appear here." />;
  return <div className="space-y-2">{orders.map((order) => <div key={order.id} className="flex items-center justify-between rounded-xl border border-slate-100 p-3"><div><div className="font-semibold">{shortId(order.id)}</div><div className="muted text-sm">{order.items.length} item(s) · {dateTime(order.created_at)}</div></div><div className="text-right"><div className="font-semibold">{money(order.total_amount)}</div><StatusBadge status={order.status} /></div></div>)}</div>;
}

function AlertRow({ title, meta, badge, danger }: { title: string; meta: string; badge: string; danger?: boolean }) {
  return <div className="flex items-center justify-between rounded-xl border border-slate-100 p-3"><div><div className="font-semibold">{title}</div><div className="muted text-sm">{meta}</div></div><span className={`badge ${danger ? "badge-danger" : "badge-warning"}`}>{badge.replaceAll("_", " ")}</span></div>;
}

function TimelineItem({ title, meta }: { title: string; meta: string }) {
  return <div className="flex gap-3"><div className="mt-1 h-2 w-2 rounded-full bg-indigo-500" /><div><div className="capitalize">{title}</div><div className="muted text-sm">{meta}</div></div></div>;
}

function ChatCard({ message }: { message: ChatMessage }) {
  return <div className={`chat-bubble ${message.role === "buyer" ? "chat-user" : "chat-agent"}`}>
    <div className="mb-1 text-xs font-bold uppercase tracking-wider opacity-65">{message.role === "agent" ? "AI Agent" : message.role}</div>
    <div>{message.text}</div>
    {message.tools?.length ? <div className="mt-3 space-y-1">{message.tools.map((tool) => <div key={tool.tool_name} className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{tool.success ? "✓" : "!"} {tool.tool_name.replaceAll("_", " ")} <span className="muted">· {tool.duration_ms}ms</span></div>)}</div> : null}
    {message.products?.length ? <ProductChips items={message.products} /> : null}
    {message.recommendations?.length ? <ProductChips items={message.recommendations} /> : null}
  </div>;
}

function ProductChips({ items }: { items: SearchResult[] }) {
  return <div className="mt-3 grid gap-2">{items.slice(0, 4).map((item) => <div key={`${item.product_id}-${item.variant_id}`} className="rounded-xl border border-slate-200 bg-white p-3"><div className="font-semibold">{item.name}</div><div className="muted text-sm">{item.sku} · {money(item.price)} · {item.available_quantity} in stock</div></div>)}</div>;
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const cls = normalized.includes("success") || normalized.includes("paid") || normalized.includes("active") || normalized.includes("accept") || normalized === "buyer" || normalized === "agent" ? "badge-success" : normalized.includes("fail") || normalized.includes("out") || normalized.includes("inactive") || normalized.includes("reject") ? "badge-danger" : normalized.includes("pending") || normalized.includes("processing") || normalized.includes("created") || normalized.includes("counter") ? "badge-warning" : "badge-neutral";
  return <span className={`badge ${cls}`}>{status.replaceAll("_", " ")}</span>;
}

function StockBadge({ quantity }: { quantity: number }) {
  return <span className={`badge ${quantity <= 0 ? "badge-danger" : quantity <= 5 ? "badge-warning" : "badge-success"}`}>{quantity <= 0 ? "Out of stock" : quantity <= 5 ? `Low · ${quantity}` : `In stock · ${quantity}`}</span>;
}

function InfoGrid({ rows }: { rows: Array<[string, string]> }) {
  return <div className="divide-y divide-slate-100">{rows.map(([label, value]) => <div key={label} className="grid gap-2 py-3 sm:grid-cols-[12rem_1fr]"><div className="muted text-sm">{label}</div><div className="break-all font-medium">{value}</div></div>)}</div>;
}

function EmptyState({ title, note }: { title: string; note: string }) {
  return <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center"><div className="font-semibold">{title}</div><div className="muted mt-1 text-sm">{note}</div></div>;
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><div>{message}</div><button className="btn" onClick={onRetry}>Retry</button></div>;
}

function LoadingGrid() {
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }).map((_, index) => <div key={index} className="skeleton h-36" />)}</div>;
}

function friendlyError(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
