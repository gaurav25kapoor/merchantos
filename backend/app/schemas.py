from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

class APIModel(BaseModel): model_config = ConfigDict(from_attributes=True)
class MerchantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160); slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    description: str | None = None; email: str | None = Field(default=None, max_length=255); contact_phone: str | None = None
class MerchantOut(APIModel): id: UUID; name: str; slug: str; description: str | None; email: str | None; contact_phone: str | None; is_active: bool; created_at: datetime; updated_at: datetime
class PolicyUpsert(BaseModel):
    return_window_days: int = Field(default=7, ge=0); cancellation_window_minutes: int = Field(default=30, ge=0)
    minimum_order_value: Decimal = Field(default=Decimal("0"), ge=0); maximum_discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    negotiation_enabled: bool = True; free_shipping_threshold: Decimal | None = Field(default=None, ge=0); rules: dict = Field(default_factory=dict)
class PolicyOut(APIModel): id: UUID; merchant_id: UUID; return_window_days: int; cancellation_window_minutes: int; minimum_order_value: Decimal; maximum_discount_percent: Decimal; negotiation_enabled: bool; free_shipping_threshold: Decimal | None; rules: dict; created_at: datetime; updated_at: datetime
class ProductCreate(BaseModel): merchant_id: UUID; name: str = Field(min_length=1, max_length=200); description: str | None = None; category: str | None = None; brand: str | None = None
class ProductUpdate(BaseModel): name: str | None = Field(default=None, min_length=1, max_length=200); description: str | None = None; category: str | None = None; brand: str | None = None; is_active: bool | None = None
class ProductOut(APIModel): id: UUID; merchant_id: UUID; name: str; description: str | None; category: str | None; brand: str | None; is_active: bool; created_at: datetime; updated_at: datetime
class VariantCreate(BaseModel): product_id: UUID; sku: str = Field(min_length=1, max_length=100); attributes: dict = Field(default_factory=dict); price: Decimal = Field(ge=0)
class VariantUpdate(BaseModel): attributes: dict | None = None; price: Decimal | None = Field(default=None, ge=0); is_active: bool | None = None
class VariantOut(APIModel): id: UUID; product_id: UUID; sku: str; attributes: dict; price: Decimal; is_active: bool; created_at: datetime; updated_at: datetime
class InventoryCreate(BaseModel): variant_id: UUID; available_quantity: int = Field(default=0, ge=0); reserved_quantity: int = Field(default=0, ge=0); status: str = Field(default="in_stock", max_length=30)
class InventoryUpdate(BaseModel): available_quantity: int | None = Field(default=None, ge=0); reserved_quantity: int | None = Field(default=None, ge=0); status: str | None = Field(default=None, max_length=30)
class QuantityChange(BaseModel): quantity: int = Field(gt=0)
class InventoryOut(APIModel): id: UUID; variant_id: UUID; available_quantity: int; reserved_quantity: int; status: str; created_at: datetime; updated_at: datetime
class UserCreate(BaseModel): merchant_id: UUID | None = None; name: str = Field(min_length=1, max_length=160); email: str = Field(min_length=3, max_length=255); role: str = Field(default="staff", max_length=40)
class UserOut(APIModel): id: UUID; merchant_id: UUID | None; name: str; email: str; role: str; is_active: bool; created_at: datetime; updated_at: datetime

class SearchResultOut(BaseModel):
    product_id: UUID
    merchant_id: UUID
    merchant_name: str
    name: str
    description: str | None
    category: str | None
    brand: str | None
    variant_id: UUID
    sku: str
    attributes: dict = Field(default_factory=dict)
    price: Decimal
    available_quantity: int
    available: bool
    score: int

class SearchResponse(BaseModel):
    query: str | None = None
    results: list[SearchResultOut]
    total: int

class BuyerIntent(BaseModel):
    intent: str = Field(default="product_search", pattern=r"^[a-z_]+$")
    query: str = Field(default="", max_length=300)
    category: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    attributes: dict = Field(default_factory=dict)
    quantity: int = Field(default=1, gt=0)
    requires_in_stock: bool = True

    @field_validator("max_price")
    @classmethod
    def max_price_must_be_reasonable(cls, value: Decimal | None, info):
        min_price = info.data.get("min_price")
        if value is not None and min_price is not None and value < min_price:
            raise ValueError("max_price must be greater than or equal to min_price")
        return value

class IntentExtractionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)

class IntentExtractionResponse(BaseModel):
    intent: BuyerIntent
    provider: str

class BuyerSearchRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    merchant_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=50)

class BuyerSearchResponse(BaseModel):
    message: str
    intent: BuyerIntent
    results: list[SearchResultOut]
    total: int

class ToolCallOut(BaseModel):
    id: UUID | None = None
    tool_name: str
    tool_input: dict = Field(default_factory=dict)
    tool_output: dict | None = None
    success: bool
    error: str | None = None
    duration_ms: int

class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    merchant_id: UUID
    session_id: UUID | None = None
    cart_id: UUID | None = None
    product_id: UUID | None = None
    variant_id: UUID | None = None
    quantity: int | None = Field(default=None, gt=0)
    limit: int = Field(default=20, ge=1, le=50)

class RankedProductOut(SearchResultOut):
    rank: int
    reasons: list[str] = Field(default_factory=list)

class AgentChatResponse(BaseModel):
    session_id: UUID
    intent: BuyerIntent
    response: str
    products: list[RankedProductOut]
    recommendations: list["RecommendationOut"] = Field(default_factory=list)
    cart: dict | None = None
    checkout: dict | None = None
    tool_calls: list[ToolCallOut]
    provider: str

class NegotiationRequest(BaseModel):
    merchant_id: UUID
    variant_id: UUID
    offered_price: Decimal = Field(gt=0)
    session_id: UUID | None = None

class NegotiationResponse(BaseModel):
    decision: str
    original_price: Decimal
    offered_price: Decimal
    approved_price: Decimal | None = None
    counter_offer: Decimal | None = None
    reason: str
    policy_decision_id: UUID | None = None

class RecommendationOut(BaseModel):
    product_id: UUID
    variant_id: UUID
    name: str
    description: str | None = None
    category: str | None = None
    sku: str
    price: Decimal
    available_quantity: int
    score: int
    reason: str

class RecommendationResponse(BaseModel):
    source_product_id: UUID
    recommendation_type: str
    results: list[RecommendationOut]
    total: int

class ExperimentAssignmentResponse(BaseModel):
    experiment_name: str
    session_id: UUID
    variant: str
    enabled: bool
    config: dict = Field(default_factory=dict)

class CartCreate(BaseModel):
    merchant_id: UUID
    buyer_session_id: str = Field(min_length=1, max_length=120)

class CartItemCreate(BaseModel):
    product_variant_id: UUID
    quantity: int = Field(gt=0)

class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)

class CartItemOut(BaseModel):
    id: UUID
    product_variant_id: UUID
    product_id: UUID
    product_name: str
    sku: str
    attributes: dict = Field(default_factory=dict)
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    available_quantity: int

class CartOut(BaseModel):
    id: UUID
    merchant_id: UUID
    buyer_session_id: str
    status: str
    items: list[CartItemOut]
    subtotal: Decimal
    total_amount: Decimal
    total_item_count: int
    currency: str = "INR"
    created_at: datetime
    updated_at: datetime

class CheckoutRequest(BaseModel):
    cart_id: UUID
    merchant_id: UUID
    buyer_session_id: str | None = Field(default=None, max_length=120)

class RazorpayCheckoutOut(BaseModel):
    key_id: str
    order_id: str
    amount: int
    currency: str
    mode: str

class CheckoutResponse(BaseModel):
    order_id: UUID
    payment_id: UUID
    amount: Decimal
    currency: str
    status: str
    razorpay: RazorpayCheckoutOut

class OrderItemOut(BaseModel):
    id: UUID
    product_variant_id: UUID | None
    product_name: str
    variant_sku: str
    variant_attributes: dict = Field(default_factory=dict)
    quantity: int
    unit_price: Decimal
    line_total: Decimal

class OrderOut(BaseModel):
    id: UUID
    merchant_id: UUID
    cart_id: UUID | None
    buyer_session_id: str
    subtotal: Decimal
    total_amount: Decimal
    currency: str
    status: str
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime

class OrderListResponse(BaseModel):
    merchant_id: UUID
    orders: list[OrderOut]
    total: int
    limit: int
    offset: int

class PaymentAttemptOut(BaseModel):
    id: UUID
    provider: str
    provider_payment_id: str | None = None
    provider_order_id: str
    amount: Decimal | None = None
    amount_minor: int | None = None
    currency: str | None = None
    status: str
    failure_reason: str | None = None
    failure_code: str | None = None
    created_at: datetime
    updated_at: datetime

class PaymentOut(BaseModel):
    id: UUID
    order_id: UUID
    merchant_id: UUID
    provider: str
    provider_order_id: str
    provider_mode: str
    amount: Decimal
    amount_minor: int
    currency: str
    status: str
    inventory_deducted: bool
    attempts: list[PaymentAttemptOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

class PaymentListResponse(BaseModel):
    merchant_id: UUID
    payments: list[PaymentOut]
    total: int
    limit: int
    offset: int

class PaymentVerifyRequest(BaseModel):
    merchant_id: UUID
    payment_id: UUID
    razorpay_payment_id: str = Field(min_length=1, max_length=120)
    razorpay_order_id: str = Field(min_length=1, max_length=120)
    razorpay_signature: str = Field(min_length=1, max_length=256)

class MockPaymentSuccessRequest(BaseModel):
    merchant_id: UUID
    payment_id: UUID
    provider_payment_id: str | None = Field(default=None, max_length=120)

class PaymentFailureRequest(BaseModel):
    merchant_id: UUID
    payment_id: UUID
    provider_payment_id: str | None = Field(default=None, max_length=120)
    failure_reason: str = Field(min_length=1, max_length=500)
    failure_code: str | None = Field(default=None, max_length=80)

class PaymentActionResponse(BaseModel):
    payment: PaymentOut
    idempotent_replay: bool = False
    message: str

class PublicConfigResponse(BaseModel):
    app_name: str
    environment: str
    payment_provider: str
    payment_mode: str
    razorpay_configured: bool
    llm_provider: str

class DemoSeedResponse(BaseModel):
    merchant_id: UUID
    merchant_slug: str
    products: int
    orders: int
    payments: int
    audit_events: int
    message: str

class AuditEventOut(BaseModel):
    id: UUID
    merchant_id: UUID
    event_type: str
    entity_type: str
    entity_id: str | None = None
    actor_type: str
    actor_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime

class AuditEventListResponse(BaseModel):
    merchant_id: UUID
    events: list[AuditEventOut]
    total: int
    limit: int
    offset: int

class DashboardOverviewResponse(BaseModel):
    merchant_id: UUID
    total_revenue: Decimal
    currency: str = "INR"
    successful_payments: int
    failed_payments: int
    total_orders: int
    completed_orders: int
    pending_orders: int
    average_order_value: Decimal
    total_products: int
    active_products: int
    low_stock_products: int
    total_inventory_units: int
    total_agent_sessions: int
    total_negotiations: int

class RevenueDataPoint(BaseModel):
    period: str
    revenue: Decimal
    successful_payments: int

class DashboardRevenueResponse(BaseModel):
    merchant_id: UUID
    total_revenue: Decimal
    currency: str = "INR"
    grouping: str
    data: list[RevenueDataPoint]

class DashboardOrdersResponse(BaseModel):
    merchant_id: UUID
    total_orders: int
    orders_by_status: dict
    successful_payments: int
    failed_payments: int
    pending_payments: int
    payment_success_rate: Decimal
    average_order_value: Decimal

class TopProductOut(BaseModel):
    product_id: UUID
    product_name: str
    units_sold: int
    revenue_generated: Decimal

class DashboardProductsResponse(BaseModel):
    merchant_id: UUID
    total_products: int
    active_products: int
    product_variants: int
    top_products: list[TopProductOut]

class LowStockItemOut(BaseModel):
    product_id: UUID
    product_name: str
    variant_id: UUID
    sku: str
    available_quantity: int
    threshold: int
    status: str

class DashboardInventoryResponse(BaseModel):
    merchant_id: UUID
    total_inventory_units: int
    in_stock_variants: int
    out_of_stock_variants: int
    low_stock_variants: int
    low_stock_items: list[LowStockItemOut]

class ToolMetricOut(BaseModel):
    tool_name: str
    calls: int
    success_rate: Decimal

class RecentAgentActivityOut(BaseModel):
    session_id: UUID
    tool_name: str
    success: bool
    created_at: datetime

class DashboardAgentActivityResponse(BaseModel):
    merchant_id: UUID
    total_agent_sessions: int
    total_tool_calls: int
    successful_tool_calls: int
    failed_tool_calls: int
    tools: list[ToolMetricOut]
    recent_activity: list[RecentAgentActivityOut]

class DashboardNegotiationsResponse(BaseModel):
    merchant_id: UUID
    total_negotiations: int
    accepted_negotiations: int
    rejected_negotiations: int
    counter_offers: int
    acceptance_rate: Decimal
    average_discount_offered: Decimal

class DashboardRecommendationsResponse(BaseModel):
    merchant_id: UUID
    total_recommendations: int
    upsell_recommendations: int
    cross_sell_recommendations: int
    recommendation_events: int
    experiment_variants_used: dict
