export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type Merchant = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  email?: string | null;
  contact_phone?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type Product = {
  id: string;
  merchant_id: string;
  name: string;
  description?: string | null;
  category?: string | null;
  brand?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type Variant = {
  id: string;
  product_id: string;
  sku: string;
  attributes: Record<string, unknown>;
  price: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type Inventory = {
  id: string;
  variant_id: string;
  available_quantity: number;
  reserved_quantity: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type SearchResult = {
  product_id: string;
  merchant_id: string;
  merchant_name: string;
  name: string;
  description?: string | null;
  category?: string | null;
  brand?: string | null;
  variant_id: string;
  sku: string;
  attributes: Record<string, unknown>;
  price: string;
  available_quantity: number;
  available: boolean;
  score: number;
  rank?: number;
  reasons?: string[];
};

export type Cart = {
  id: string;
  merchant_id: string;
  buyer_session_id: string;
  status: string;
  items: Array<{
    id: string;
    product_variant_id: string;
    product_id: string;
    product_name: string;
    sku: string;
    attributes: Record<string, unknown>;
    quantity: number;
    unit_price: string;
    line_total: string;
    available_quantity: number;
  }>;
  subtotal: string;
  total_amount: string;
  total_item_count: number;
  currency: string;
  created_at: string;
  updated_at: string;
};

export type Order = {
  id: string;
  merchant_id: string;
  cart_id?: string | null;
  buyer_session_id: string;
  subtotal: string;
  total_amount: string;
  currency: string;
  status: string;
  items: Array<{
    id: string;
    product_variant_id?: string | null;
    product_name: string;
    variant_sku: string;
    quantity: number;
    unit_price: string;
    line_total: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type Payment = {
  id: string;
  order_id: string;
  merchant_id: string;
  provider: string;
  provider_order_id: string;
  provider_mode: string;
  amount: string;
  amount_minor: number;
  currency: string;
  status: string;
  inventory_deducted: boolean;
  attempts: Array<{
    id: string;
    provider: string;
    provider_payment_id?: string | null;
    provider_order_id: string;
    amount?: string | null;
    amount_minor?: number | null;
    currency?: string | null;
    status: string;
    failure_reason?: string | null;
    failure_code?: string | null;
    created_at: string;
    updated_at: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  id: string;
  merchant_id: string;
  event_type: string;
  entity_type: string;
  entity_id?: string | null;
  actor_type: string;
  actor_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type Policy = {
  id: string;
  merchant_id: string;
  return_window_days: number;
  cancellation_window_minutes: number;
  minimum_order_value: string;
  maximum_discount_percent: string;
  negotiation_enabled: boolean;
  free_shipping_threshold?: string | null;
  rules: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Overview = {
  total_revenue: string;
  successful_payments: number;
  failed_payments: number;
  total_orders: number;
  completed_orders: number;
  pending_orders: number;
  average_order_value: string;
  total_products: number;
  active_products: number;
  low_stock_products: number;
  total_inventory_units: number;
  total_agent_sessions: number;
  total_negotiations: number;
};

export type RevenueResponse = { total_revenue: string; grouping: string; data: Array<{ period: string; revenue: string; successful_payments: number }> };
export type OrdersDashboard = { total_orders: number; orders_by_status: Record<string, number>; successful_payments: number; failed_payments: number; pending_payments: number; payment_success_rate: string; average_order_value: string };
export type ProductsDashboard = { total_products: number; active_products: number; product_variants: number; top_products: Array<{ product_id: string; product_name: string; units_sold: number; revenue_generated: string }> };
export type InventoryDashboard = { total_inventory_units: number; in_stock_variants: number; out_of_stock_variants: number; low_stock_variants: number; low_stock_items: Array<{ product_id: string; product_name: string; variant_id: string; sku: string; available_quantity: number; threshold: number; status: string }> };
export type AgentDashboard = { total_agent_sessions: number; total_tool_calls: number; successful_tool_calls: number; failed_tool_calls: number; tools: Array<{ tool_name: string; calls: number; success_rate: string }>; recent_activity: Array<{ session_id: string; tool_name: string; success: boolean; created_at: string }> };
export type NegotiationsDashboard = { total_negotiations: number; accepted_negotiations: number; rejected_negotiations: number; counter_offers: number; acceptance_rate: string; average_discount_offered: string };
export type RecommendationsDashboard = { total_recommendations: number; upsell_recommendations: number; cross_sell_recommendations: number; recommendation_events: number; experiment_variants_used: Record<string, number> };

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 12_000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers || {}),
      },
    });
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : "Request failed";
      throw new ApiError(detail, response.status, body?.code);
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw new ApiError("The API request timed out. Check that the backend is running.", 408, "TIMEOUT");
    throw new ApiError(error instanceof Error ? error.message : "Network request failed", 0, "NETWORK_ERROR");
  } finally {
    window.clearTimeout(timer);
  }
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
};

export const api = {
  health: () => request<{ status: string; service: string; database: string; environment: string }>("/health"),
  config: () => request<{ app_name: string; environment: string; payment_provider: string; payment_mode: string; razorpay_configured: boolean; llm_provider: string }>("/api/v1/config/public"),
  seedDemo: () => request<{ merchant_id: string; merchant_slug: string; products: number; orders: number; payments: number; audit_events: number; message: string }>("/api/v1/dev/seed-demo-data", { method: "POST" }),
  merchants: () => request<Merchant[]>("/api/v1/merchants"),
  createMerchant: (payload: { name: string; slug: string; email?: string }) => request<Merchant>("/api/v1/merchants", { method: "POST", body: JSON.stringify(payload) }),
  products: (merchantId: string) => request<Product[]>(`/api/v1/products${qs({ merchant_id: merchantId })}`),
  createProduct: (payload: { merchant_id: string; name: string; description?: string; category?: string; brand?: string }) => request<Product>("/api/v1/products", { method: "POST", body: JSON.stringify(payload) }),
  updateProduct: (id: string, payload: Partial<Product>) => request<Product>(`/api/v1/products/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  variants: (productId: string) => request<Variant[]>(`/api/v1/products/${productId}/variants`),
  createVariant: (payload: { product_id: string; sku: string; price: string; attributes?: Record<string, unknown> }) => request<Variant>("/api/v1/variants", { method: "POST", body: JSON.stringify(payload) }),
  inventory: (variantId: string) => request<Inventory>(`/api/v1/inventory/${variantId}`),
  createInventory: (payload: { variant_id: string; available_quantity: number; reserved_quantity?: number; status?: string }) => request<Inventory>("/api/v1/inventory", { method: "POST", body: JSON.stringify(payload) }),
  updateInventory: (variantId: string, payload: { available_quantity?: number; reserved_quantity?: number; status?: string }) => request<Inventory>(`/api/v1/inventory/${variantId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  search: (merchantId: string, query: string) => request<{ results: SearchResult[]; total: number }>(`/api/v1/search${qs({ merchant_id: merchantId, q: query, limit: 20 })}`),
  buyerSearch: (merchantId: string, message: string) => request<{ message: string; results: SearchResult[]; total: number }>("/api/v1/buyer/search", { method: "POST", body: JSON.stringify({ merchant_id: merchantId, message, limit: 8 }) }),
  agentChat: (payload: { merchant_id: string; message: string; session_id?: string; cart_id?: string; product_id?: string; variant_id?: string; quantity?: number }) => request<{ session_id: string; response: string; products: SearchResult[]; recommendations: SearchResult[]; cart?: Cart; checkout?: { order_id: string; payment_id: string; amount: string; currency: string; status: string }; tool_calls: Array<{ id: string; tool_name: string; success: boolean; duration_ms: number; error?: string | null }> }>("/api/v1/agent/chat", { method: "POST", body: JSON.stringify(payload) }),
  negotiate: (payload: { merchant_id: string; variant_id: string; offered_price: string; session_id?: string }) => request<{ decision: string; original_price: string; offered_price: string; approved_price?: string | null; counter_offer?: string | null; reason: string }>("/api/v1/negotiation", { method: "POST", body: JSON.stringify(payload) }),
  upsells: (merchantId: string, productId: string) => request<{ results: SearchResult[]; total: number }>(`/api/v1/products/${productId}/upsells${qs({ merchant_id: merchantId })}`),
  crossSells: (merchantId: string, productId: string) => request<{ results: SearchResult[]; total: number }>(`/api/v1/products/${productId}/cross-sells${qs({ merchant_id: merchantId })}`),
  createCart: (merchantId: string, buyerSessionId: string) => request<Cart>("/api/v1/carts", { method: "POST", body: JSON.stringify({ merchant_id: merchantId, buyer_session_id: buyerSessionId }) }),
  addCartItem: (cartId: string, variantId: string, quantity: number) => request<Cart>(`/api/v1/carts/${cartId}/items`, { method: "POST", body: JSON.stringify({ product_variant_id: variantId, quantity }) }),
  checkout: (cartId: string, merchantId: string, buyerSessionId?: string) => request<{ order_id: string; payment_id: string; amount: string; currency: string; status: string }>(`/api/v1/checkout`, { method: "POST", body: JSON.stringify({ cart_id: cartId, merchant_id: merchantId, buyer_session_id: buyerSessionId }) }),
  mockSuccess: (merchantId: string, paymentId: string) => request<{ payment: Payment; message: string; idempotent_replay: boolean }>("/api/v1/payments/mock-success", { method: "POST", body: JSON.stringify({ merchant_id: merchantId, payment_id: paymentId }) }),
  orders: (merchantId: string) => request<{ orders: Order[]; total: number }>(`/api/v1/orders${qs({ merchant_id: merchantId, limit: 50 })}`),
  payments: (merchantId: string) => request<{ payments: Payment[]; total: number }>(`/api/v1/payments${qs({ merchant_id: merchantId, limit: 50 })}`),
  policy: (merchantId: string) => request<Policy>(`/api/v1/merchants/${merchantId}/policy`),
  updatePolicy: (merchantId: string, payload: Partial<Policy>) => request<Policy>(`/api/v1/merchants/${merchantId}/policy`, { method: "PUT", body: JSON.stringify(payload) }),
  auditEvents: (merchantId: string, filters: { event_type?: string; limit?: number; offset?: number } = {}) => request<{ events: AuditEvent[]; total: number; limit: number; offset: number }>(`/api/v1/audit-events${qs({ merchant_id: merchantId, limit: filters.limit || 50, offset: filters.offset || 0, event_type: filters.event_type })}`),
  overview: (merchantId: string) => request<Overview>(`/api/v1/dashboard/overview${qs({ merchant_id: merchantId })}`),
  revenue: (merchantId: string) => request<RevenueResponse>(`/api/v1/dashboard/revenue${qs({ merchant_id: merchantId })}`),
  ordersDashboard: (merchantId: string) => request<OrdersDashboard>(`/api/v1/dashboard/orders${qs({ merchant_id: merchantId })}`),
  productsDashboard: (merchantId: string) => request<ProductsDashboard>(`/api/v1/dashboard/products${qs({ merchant_id: merchantId })}`),
  inventoryDashboard: (merchantId: string) => request<InventoryDashboard>(`/api/v1/dashboard/inventory${qs({ merchant_id: merchantId })}`),
  agentDashboard: (merchantId: string) => request<AgentDashboard>(`/api/v1/dashboard/agent-activity${qs({ merchant_id: merchantId })}`),
  negotiationsDashboard: (merchantId: string) => request<NegotiationsDashboard>(`/api/v1/dashboard/negotiations${qs({ merchant_id: merchantId })}`),
  recommendationsDashboard: (merchantId: string) => request<RecommendationsDashboard>(`/api/v1/dashboard/recommendations${qs({ merchant_id: merchantId })}`),
};
