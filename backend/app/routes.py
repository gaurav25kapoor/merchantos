from datetime import datetime
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import Inventory, Merchant, MerchantPolicy, Order, Product, ProductVariant, User, Payment
from app.schemas import *
from app.services.analytics import AnalyticsError, AnalyticsService
from app.services.audit import AuditService
from app.services.cart import CartError, CartService
from app.services.checkout import CheckoutError, CheckoutService
from app.services.experiments import GrowthExperimentService
from app.services.intent import IntentExtractor
from app.services.merchant_agent import MerchantAgent
from app.services.negotiation import NegotiationError, NegotiationService
from app.services.payments import PaymentError, PaymentService
from app.services.razorpay_service import PaymentProviderError
from app.services.recommendations import RecommendationError, RecommendationService
from app.services.search import SearchCriteria, SearchService
from app.seed import seed as seed_demo_data

router = APIRouter(prefix="/api/v1")

def one(db, model, item_id):
    item = db.get(model, item_id)
    if not item: raise HTTPException(404, detail=f"{model.__name__} not found")
    return item
def commit(db, item):
    db.add(item)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, detail="A record with this unique value already exists")
    db.refresh(item); return item
def audit_out(event):
    return AuditEventOut(
        id=event.id,
        merchant_id=event.merchant_id,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        metadata=event.metadata_json or {},
        created_at=event.created_at,
    )

@router.post("/merchants", response_model=MerchantOut, status_code=status.HTTP_201_CREATED)
def create_merchant(payload: MerchantCreate, db: Session = Depends(get_db)):
    item = commit(db, Merchant(**payload.model_dump()))
    AuditService(db).log_event(item.id, "merchant_created", "merchant", item.id, metadata={"slug": item.slug, "name": item.name})
    db.commit()
    return item
@router.get("/merchants", response_model=list[MerchantOut])
def list_merchants(db: Session = Depends(get_db)): return db.query(Merchant).order_by(Merchant.created_at).all()
@router.get("/merchants/{merchant_id}", response_model=MerchantOut)
def get_merchant(merchant_id: UUID, db: Session = Depends(get_db)): return one(db, Merchant, merchant_id)

@router.put("/merchants/{merchant_id}/policy", response_model=PolicyOut)
def put_policy(merchant_id: UUID, payload: PolicyUpsert, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id); item = db.query(MerchantPolicy).filter_by(merchant_id=merchant_id).one_or_none()
    if item: [setattr(item, key, value) for key, value in payload.model_dump().items()]
    else: item = MerchantPolicy(merchant_id=merchant_id, **payload.model_dump()); db.add(item)
    item = commit(db, item)
    AuditService(db).log_event(merchant_id, "policy_updated", "merchant_policy", item.id, metadata=payload.model_dump(mode="json"))
    db.commit()
    return item
@router.get("/merchants/{merchant_id}/policy", response_model=PolicyOut)
def get_policy(merchant_id: UUID, db: Session = Depends(get_db)):
    item = db.query(MerchantPolicy).filter_by(merchant_id=merchant_id).one_or_none()
    if not item: raise HTTPException(404, detail="MerchantPolicy not found")
    return item

@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    one(db, Merchant, payload.merchant_id)
    item = commit(db, Product(**payload.model_dump()))
    AuditService(db).log_event(item.merchant_id, "product_created", "product", item.id, metadata={"name": item.name, "category": item.category, "brand": item.brand})
    db.commit()
    return item
@router.get("/products", response_model=list[ProductOut])
def list_products(merchant_id: UUID | None = None, db: Session = Depends(get_db)):
    query = db.query(Product); return query.filter_by(merchant_id=merchant_id).all() if merchant_id else query.all()
@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: UUID, db: Session = Depends(get_db)): return one(db, Product, product_id)
@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: UUID, payload: ProductUpdate, db: Session = Depends(get_db)):
    item = one(db, Product, product_id)
    was_active = item.is_active
    changes = payload.model_dump(exclude_unset=True)
    [setattr(item, k, v) for k,v in changes.items()]
    item = commit(db, item)
    event_type = "product_deactivated" if was_active and item.is_active is False else "product_updated"
    AuditService(db).log_event(item.merchant_id, event_type, "product", item.id, metadata=changes)
    db.commit()
    return item

@router.post("/variants", response_model=VariantOut, status_code=status.HTTP_201_CREATED)
def create_variant(payload: VariantCreate, db: Session = Depends(get_db)):
    product = one(db, Product, payload.product_id)
    item = commit(db, ProductVariant(**payload.model_dump()))
    AuditService(db).log_event(product.merchant_id, "variant_created", "product_variant", item.id, metadata={"product_id": str(product.id), "sku": item.sku, "price": str(item.price)})
    db.commit()
    return item
@router.get("/products/{product_id}/variants", response_model=list[VariantOut])
def list_variants(product_id: UUID, db: Session = Depends(get_db)):
    one(db, Product, product_id); return db.query(ProductVariant).filter_by(product_id=product_id).all()
@router.patch("/variants/{variant_id}", response_model=VariantOut)
def update_variant(variant_id: UUID, payload: VariantUpdate, db: Session = Depends(get_db)):
    item=one(db, ProductVariant, variant_id)
    changes = payload.model_dump(exclude_unset=True)
    [setattr(item,k,v) for k,v in changes.items()]
    item = commit(db,item)
    AuditService(db).log_event(item.product.merchant_id, "variant_updated", "product_variant", item.id, metadata=changes)
    db.commit()
    return item

@router.post("/inventory", response_model=InventoryOut, status_code=status.HTTP_201_CREATED)
def create_inventory(payload: InventoryCreate, db: Session = Depends(get_db)):
    variant = one(db, ProductVariant, payload.variant_id)
    item = commit(db, Inventory(**payload.model_dump()))
    AuditService(db).log_event(variant.product.merchant_id, "inventory_created", "inventory", item.id, metadata={"variant_id": str(variant.id), "available_quantity": item.available_quantity, "reserved_quantity": item.reserved_quantity})
    db.commit()
    return item
@router.get("/inventory/{variant_id}", response_model=InventoryOut)
def get_inventory(variant_id: UUID, db: Session = Depends(get_db)):
    item=db.query(Inventory).filter_by(variant_id=variant_id).one_or_none()
    if not item: raise HTTPException(404, detail="Inventory not found")
    return item
@router.patch("/inventory/{variant_id}", response_model=InventoryOut)
def update_inventory(variant_id: UUID, payload: InventoryUpdate, db: Session = Depends(get_db)):
    item=get_inventory(variant_id,db)
    changes = payload.model_dump(exclude_unset=True)
    [setattr(item,k,v) for k,v in changes.items()]
    item = commit(db,item)
    AuditService(db).log_event(item.variant.product.merchant_id, "inventory_updated", "inventory", item.id, metadata={"variant_id": str(variant_id), **changes})
    db.commit()
    return item
@router.post("/inventory/{variant_id}/reserve", response_model=InventoryOut)
def reserve_inventory(variant_id: UUID, payload: QuantityChange, db: Session = Depends(get_db)):
    item=get_inventory(variant_id,db)
    if item.available_quantity < payload.quantity: raise HTTPException(409, detail="Insufficient available inventory")
    item.available_quantity -= payload.quantity; item.reserved_quantity += payload.quantity
    item = commit(db,item)
    AuditService(db).log_event(item.variant.product.merchant_id, "inventory_reserved", "inventory", item.id, metadata={"variant_id": str(variant_id), "quantity": payload.quantity, "available_quantity": item.available_quantity, "reserved_quantity": item.reserved_quantity})
    db.commit()
    return item
@router.post("/inventory/{variant_id}/release", response_model=InventoryOut)
def release_inventory(variant_id: UUID, payload: QuantityChange, db: Session = Depends(get_db)):
    item=get_inventory(variant_id,db)
    if item.reserved_quantity < payload.quantity: raise HTTPException(409, detail="Cannot release more inventory than reserved")
    item.reserved_quantity -= payload.quantity; item.available_quantity += payload.quantity
    item = commit(db,item)
    AuditService(db).log_event(item.variant.product.merchant_id, "inventory_released", "inventory", item.id, metadata={"variant_id": str(variant_id), "quantity": payload.quantity, "available_quantity": item.available_quantity, "reserved_quantity": item.reserved_quantity})
    db.commit()
    return item

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if payload.merchant_id: one(db, Merchant, payload.merchant_id)
    return commit(db, User(**payload.model_dump()))
@router.get("/users", response_model=list[UserOut])
def list_users(merchant_id: UUID | None = None, db: Session = Depends(get_db)):
    query=db.query(User); return query.filter_by(merchant_id=merchant_id).all() if merchant_id else query.all()
@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: UUID, db: Session = Depends(get_db)): return one(db, User, user_id)

@router.get("/search", response_model=SearchResponse)
def search_catalog(
    q: str | None = None,
    merchant_id: UUID | None = None,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    in_stock: bool | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 50: raise HTTPException(422, detail="limit must be between 1 and 50")
    if min_price is not None and max_price is not None and max_price < min_price: raise HTTPException(422, detail="max_price must be greater than or equal to min_price")
    if merchant_id: one(db, Merchant, merchant_id)
    service = SearchService(db)
    results = service.search(SearchCriteria(query=q, merchant_id=merchant_id, category=category, min_price=min_price, max_price=max_price, in_stock=in_stock, limit=limit))
    return SearchResponse(query=q, results=[SearchResultOut(**result.__dict__) for result in results], total=len(results))

@router.post("/buyer/intent", response_model=IntentExtractionResponse)
def extract_buyer_intent(payload: IntentExtractionRequest):
    extractor = IntentExtractor()
    return IntentExtractionResponse(intent=extractor.extract(payload.message), provider=extractor.provider.name)

@router.post("/buyer/search", response_model=BuyerSearchResponse)
def buyer_search(payload: BuyerSearchRequest, db: Session = Depends(get_db)):
    if payload.merchant_id: one(db, Merchant, payload.merchant_id)
    extractor = IntentExtractor()
    intent = extractor.extract(payload.message)
    if not intent.query and not intent.category and not intent.brand:
        return BuyerSearchResponse(
            message="I couldn't determine exactly what you're looking for. Try specifying a product, category, or price range.",
            intent=intent,
            results=[],
            total=0,
        )
    service = SearchService(db)
    results = service.search(
        SearchCriteria(
            query=intent.query,
            merchant_id=payload.merchant_id,
            category=intent.category,
            brand=intent.brand,
            min_price=intent.min_price,
            max_price=intent.max_price,
            in_stock=intent.requires_in_stock,
            attributes=intent.attributes,
            limit=payload.limit,
        )
    )
    response_results = [SearchResultOut(**result.__dict__) for result in results]
    return BuyerSearchResponse(
        message=buyer_response_message(intent, response_results),
        intent=intent,
        results=response_results,
        total=len(response_results),
    )

def buyer_response_message(intent: BuyerIntent, results: list[SearchResultOut]) -> str:
    if not results:
        descriptor = intent.query or intent.category or "matching products"
        return f"I couldn't find {descriptor} for those filters."
    descriptor = intent.query or intent.category or "matching products"
    price_part = f" under ₹{intent.max_price}" if intent.max_price is not None else ""
    stock_part = " that are in stock" if intent.requires_in_stock else ""
    return f"I found {len(results)} {descriptor}{price_part}{stock_part}."

@router.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(payload: AgentChatRequest, db: Session = Depends(get_db)):
    try:
        return MerchantAgent(db).chat(
            merchant_id=payload.merchant_id,
            message=payload.message,
            session_id=payload.session_id,
            cart_id=payload.cart_id,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            quantity=payload.quantity,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc))

@router.post("/negotiation", response_model=NegotiationResponse)
def negotiate_price(payload: NegotiationRequest, db: Session = Depends(get_db)):
    one(db, Merchant, payload.merchant_id)
    try:
        result = NegotiationService(db).negotiate(payload.merchant_id, payload.variant_id, payload.offered_price, payload.session_id)
        db.commit()
        return NegotiationResponse(**result)
    except NegotiationError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.get("/products/{product_id}/upsells", response_model=RecommendationResponse)
def get_product_upsells(product_id: UUID, merchant_id: UUID, limit: int = 3, session_id: UUID | None = None, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        results = RecommendationService(db).upsells(merchant_id, product_id, limit, session_id)
        db.commit()
        return RecommendationResponse(source_product_id=product_id, recommendation_type="upsell", results=results, total=len(results))
    except RecommendationError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.get("/products/{product_id}/cross-sells", response_model=RecommendationResponse)
def get_product_cross_sells(product_id: UUID, merchant_id: UUID, limit: int = 3, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        results = RecommendationService(db).cross_sells(merchant_id, product_id, limit)
        db.commit()
        return RecommendationResponse(source_product_id=product_id, recommendation_type="cross_sell", results=results, total=len(results))
    except RecommendationError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.get("/experiments/{experiment_name}/assignment", response_model=ExperimentAssignmentResponse)
def get_experiment_assignment(experiment_name: str, session_id: UUID, merchant_id: UUID, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    service = GrowthExperimentService()
    variant = service.assign_variant(session_id, experiment_name)
    return ExperimentAssignmentResponse(
        experiment_name=experiment_name,
        session_id=session_id,
        variant=variant,
        enabled=service.is_feature_enabled(session_id, experiment_name),
        config=service.get_experiment_config(experiment_name),
    )

@router.post("/carts", response_model=CartOut, status_code=status.HTTP_201_CREATED)
def create_cart(payload: CartCreate, db: Session = Depends(get_db)):
    try:
        service = CartService(db)
        cart = service.create_cart(payload.merchant_id, payload.buyer_session_id)
        db.commit()
        db.refresh(cart)
        return service.serialize(cart)
    except CartError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.get("/carts/{cart_id}", response_model=CartOut)
def get_cart(cart_id: UUID, merchant_id: UUID | None = None, db: Session = Depends(get_db)):
    try:
        service = CartService(db)
        return service.serialize(service.get_cart(cart_id, merchant_id))
    except CartError as exc:
        raise HTTPException(404, detail=str(exc))

@router.post("/carts/{cart_id}/items", response_model=CartOut, status_code=status.HTTP_201_CREATED)
def add_cart_item(cart_id: UUID, payload: CartItemCreate, db: Session = Depends(get_db)):
    try:
        service = CartService(db)
        cart = service.add_item(cart_id, payload.product_variant_id, payload.quantity)
        db.commit()
        return service.serialize(cart)
    except CartError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="Cart item could not be saved")

@router.patch("/carts/{cart_id}/items/{item_id}", response_model=CartOut)
def update_cart_item(cart_id: UUID, item_id: UUID, payload: CartItemUpdate, db: Session = Depends(get_db)):
    try:
        service = CartService(db)
        cart = service.update_item(cart_id, item_id, payload.quantity)
        db.commit()
        return service.serialize(cart)
    except CartError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.delete("/carts/{cart_id}/items/{item_id}", response_model=CartOut)
def remove_cart_item(cart_id: UUID, item_id: UUID, db: Session = Depends(get_db)):
    try:
        service = CartService(db)
        cart = service.remove_item(cart_id, item_id)
        db.commit()
        return service.serialize(cart)
    except CartError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.delete("/carts/{cart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart(cart_id: UUID, merchant_id: UUID | None = None, db: Session = Depends(get_db)):
    try:
        CartService(db).delete_cart(cart_id, merchant_id)
        db.commit()
        return None
    except CartError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc))

@router.post("/checkout", response_model=CheckoutResponse)
def checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    one(db, Merchant, payload.merchant_id)
    try:
        response = CheckoutService(db).checkout(payload.cart_id, payload.merchant_id, payload.buyer_session_id)
        db.commit()
        return response
    except (CheckoutError, CartError, PaymentProviderError) as exc:
        db.rollback()
        raise HTTPException(409, detail=str(exc))

@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: UUID, merchant_id: UUID, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).filter(Order.merchant_id == merchant_id).one_or_none()
    if not order:
        raise HTTPException(404, detail="Order not found")
    return OrderOut(
        id=order.id,
        merchant_id=order.merchant_id,
        cart_id=order.cart_id,
        buyer_session_id=order.buyer_session_id,
        subtotal=order.subtotal,
        total_amount=order.total_amount,
        currency=order.currency,
        status=order.status,
        items=[OrderItemOut(id=item.id, product_variant_id=item.product_variant_id, product_name=item.product_name, variant_sku=item.variant_sku, variant_attributes=item.variant_attributes, quantity=item.quantity, unit_price=item.unit_price, line_total=item.line_total) for item in order.items],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )

@router.get("/orders", response_model=OrderListResponse)
def list_orders(merchant_id: UUID, status_filter: str | None = None, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    query = db.query(Order).filter(Order.merchant_id == merchant_id)
    if status_filter:
        query = query.filter(Order.status == status_filter)
    total = query.count()
    orders = query.order_by(Order.created_at.desc()).offset(offset).limit(limit).all()
    return OrderListResponse(
        merchant_id=merchant_id,
        orders=[
            OrderOut(
                id=order.id,
                merchant_id=order.merchant_id,
                cart_id=order.cart_id,
                buyer_session_id=order.buyer_session_id,
                subtotal=order.subtotal,
                total_amount=order.total_amount,
                currency=order.currency,
                status=order.status,
                items=[
                    OrderItemOut(
                        id=item.id,
                        product_variant_id=item.product_variant_id,
                        product_name=item.product_name,
                        variant_sku=item.variant_sku,
                        variant_attributes=item.variant_attributes,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        line_total=item.line_total,
                    )
                    for item in order.items
                ],
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
            for order in orders
        ],
        total=total,
        limit=limit,
        offset=offset,
    )

@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: UUID, merchant_id: UUID, db: Session = Depends(get_db)):
    try:
        return PaymentService(db).serialize(PaymentService(db).get_payment(payment_id, merchant_id))
    except PaymentError as exc:
        raise HTTPException(404, detail=str(exc))

@router.get("/payments", response_model=PaymentListResponse)
def list_payments(merchant_id: UUID, status_filter: str | None = None, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    query = db.query(Payment).join(Order, Order.id == Payment.order_id).filter(Order.merchant_id == merchant_id)
    if status_filter:
        query = query.filter(Payment.status == status_filter)
    total = query.count()
    service = PaymentService(db)
    payments = query.order_by(Payment.created_at.desc()).offset(offset).limit(limit).all()
    return PaymentListResponse(merchant_id=merchant_id, payments=[service.serialize(payment) for payment in payments], total=total, limit=limit, offset=offset)

@router.post("/payments/verify", response_model=PaymentActionResponse)
def verify_payment(payload: PaymentVerifyRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    try:
        payment, replay = PaymentService(db).verify(payload.merchant_id, payload.payment_id, payload.razorpay_payment_id, payload.razorpay_order_id, payload.razorpay_signature, idempotency_key)
        db.commit()
        return PaymentActionResponse(payment=payment, idempotent_replay=replay, message="Payment verified successfully")
    except (PaymentError, PaymentProviderError) as exc:
        db.rollback()
        raise HTTPException(400, detail=str(exc))

@router.post("/payments/mock-success", response_model=PaymentActionResponse)
def mock_payment_success(payload: MockPaymentSuccessRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    try:
        payment, replay = PaymentService(db).mock_success(payload.merchant_id, payload.payment_id, payload.provider_payment_id, idempotency_key)
        db.commit()
        return PaymentActionResponse(payment=payment, idempotent_replay=replay, message="Mock payment marked successful")
    except PaymentError as exc:
        db.rollback()
        raise HTTPException(400, detail=str(exc))

@router.post("/payments/fail", response_model=PaymentActionResponse)
def fail_payment(payload: PaymentFailureRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    try:
        payment, replay = PaymentService(db).fail_payment(payload.merchant_id, payload.payment_id, payload.failure_reason, payload.failure_code, payload.provider_payment_id, idempotency_key)
        db.commit()
        return PaymentActionResponse(payment=payment, idempotent_replay=replay, message="Payment failure recorded")
    except PaymentError as exc:
        db.rollback()
        raise HTTPException(400, detail=str(exc))

@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    body = await request.body()
    try:
        response, _replay = PaymentService(db).process_webhook(body, x_razorpay_signature, idempotency_key)
        db.commit()
        return response
    except (PaymentError, PaymentProviderError, ValueError) as exc:
        db.rollback()
        raise HTTPException(400, detail=str(exc))


@router.get("/audit-events", response_model=AuditEventListResponse)
def list_audit_events(
    merchant_id: UUID,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    one(db, Merchant, merchant_id)
    try:
        AnalyticsService(db).validate_date_range(start_date, end_date)
        events, total = AuditService(db).list_events(merchant_id, event_type, entity_type, entity_id, start_date, end_date, limit, offset)
        return AuditEventListResponse(merchant_id=merchant_id, events=[audit_out(event) for event in events], total=total, limit=limit, offset=offset)
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
def dashboard_overview(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardOverviewResponse(**AnalyticsService(db).overview(merchant_id, start_date, end_date))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/revenue", response_model=DashboardRevenueResponse)
def dashboard_revenue(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, grouping: str = "day", db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardRevenueResponse(**AnalyticsService(db).revenue(merchant_id, start_date, end_date, grouping))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/orders", response_model=DashboardOrdersResponse)
def dashboard_orders(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardOrdersResponse(**AnalyticsService(db).orders(merchant_id, start_date, end_date))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/products", response_model=DashboardProductsResponse)
def dashboard_products(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, limit: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardProductsResponse(**AnalyticsService(db).products(merchant_id, start_date, end_date, limit))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/inventory", response_model=DashboardInventoryResponse)
def dashboard_inventory(merchant_id: UUID, low_stock_threshold: int = Query(default=5, ge=0, le=1000), db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    return DashboardInventoryResponse(**AnalyticsService(db).inventory(merchant_id, low_stock_threshold))


@router.get("/dashboard/agent-activity", response_model=DashboardAgentActivityResponse)
def dashboard_agent_activity(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardAgentActivityResponse(**AnalyticsService(db).agent_activity(merchant_id, start_date, end_date))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/negotiations", response_model=DashboardNegotiationsResponse)
def dashboard_negotiations(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardNegotiationsResponse(**AnalyticsService(db).negotiations(merchant_id, start_date, end_date))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/dashboard/recommendations", response_model=DashboardRecommendationsResponse)
def dashboard_recommendations(merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, db: Session = Depends(get_db)):
    one(db, Merchant, merchant_id)
    try:
        return DashboardRecommendationsResponse(**AnalyticsService(db).recommendations(merchant_id, start_date, end_date))
    except AnalyticsError as exc:
        raise HTTPException(422, detail=str(exc))


@router.get("/config/public", response_model=PublicConfigResponse)
def public_config():
    return PublicConfigResponse(
        app_name=settings.app_name,
        environment=settings.environment,
        payment_provider=settings.payment_provider,
        payment_mode=settings.payment_mode,
        razorpay_configured=bool(settings.razorpay_key_id),
        llm_provider=settings.llm_provider,
    )


@router.post("/dev/seed-demo-data", response_model=DemoSeedResponse)
def seed_demo(db: Session = Depends(get_db)):
    if settings.environment == "production":
        raise HTTPException(403, detail="Demo seed is disabled in production")
    result = seed_demo_data(db)
    return DemoSeedResponse(**result, message="Deterministic demo data is ready")
