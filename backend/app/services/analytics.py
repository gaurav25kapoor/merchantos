from collections import Counter
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from app.models import (
    AgentSession,
    AgentToolCall,
    Inventory,
    Order,
    OrderItem,
    Payment,
    PolicyDecision,
    Product,
    ProductVariant,
    Recommendation,
    UpsellEvent,
)


class AnalyticsError(ValueError):
    pass


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def validate_date_range(self, start_date: datetime | None, end_date: datetime | None) -> None:
        if start_date and end_date and start_date > end_date:
            raise AnalyticsError("start_date must be before or equal to end_date")

    def overview(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
        self.validate_date_range(start_date, end_date)
        successful_revenue = self._payment_query(merchant_id, start_date, end_date).filter(Payment.status == "SUCCESS")
        total_revenue = money(successful_revenue.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar())
        successful_payments = successful_revenue.count()
        failed_payments = self._payment_query(merchant_id, start_date, end_date).filter(Payment.status == "FAILED").count()

        order_query = self._order_query(merchant_id, start_date, end_date)
        total_orders = order_query.count()
        completed_orders = order_query.filter(Order.status == "PAID").count()
        pending_orders = order_query.filter(Order.status == "PENDING_PAYMENT").count()

        low_stock_product_count = (
            self.db.query(func.count(distinct(Product.id)))
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .join(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(Product.merchant_id == merchant_id)
            .filter(Inventory.available_quantity <= 5)
            .scalar()
            or 0
        )
        total_inventory_units = (
            self._inventory_query(merchant_id)
            .with_entities(func.coalesce(func.sum(Inventory.available_quantity), 0))
            .scalar()
            or 0
        )

        return {
            "merchant_id": merchant_id,
            "total_revenue": total_revenue,
            "successful_payments": successful_payments,
            "failed_payments": failed_payments,
            "total_orders": total_orders,
            "completed_orders": completed_orders,
            "pending_orders": pending_orders,
            "average_order_value": average(total_revenue, successful_payments),
            "total_products": self.db.query(Product).filter(Product.merchant_id == merchant_id).count(),
            "active_products": self.db.query(Product).filter(Product.merchant_id == merchant_id).filter(Product.is_active.is_(True)).count(),
            "low_stock_products": int(low_stock_product_count),
            "total_inventory_units": int(total_inventory_units),
            "total_agent_sessions": self._agent_session_query(merchant_id, start_date, end_date).count(),
            "total_negotiations": self._negotiation_query(merchant_id, start_date, end_date).count(),
        }

    def revenue(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, grouping: str = "day") -> dict:
        self.validate_date_range(start_date, end_date)
        if grouping not in {"day", "week", "month"}:
            raise AnalyticsError("grouping must be one of: day, week, month")
        period = func.date_trunc(grouping, Payment.created_at).label("period")
        rows = (
            self._payment_query(merchant_id, start_date, end_date)
            .filter(Payment.status == "SUCCESS")
            .with_entities(period, func.coalesce(func.sum(Payment.amount), 0), func.count(Payment.id))
            .group_by(period)
            .order_by(period.asc())
            .all()
        )
        data = [{"period": row[0].date().isoformat(), "revenue": money(row[1]), "successful_payments": int(row[2])} for row in rows]
        return {"merchant_id": merchant_id, "total_revenue": money(sum((point["revenue"] for point in data), Decimal("0.00"))), "grouping": grouping, "data": data}

    def orders(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
        self.validate_date_range(start_date, end_date)
        order_rows = self._order_query(merchant_id, start_date, end_date).with_entities(Order.status, func.count(Order.id)).group_by(Order.status).all()
        payment_query = self._payment_query(merchant_id, start_date, end_date)
        successful = payment_query.filter(Payment.status == "SUCCESS").count()
        failed = payment_query.filter(Payment.status == "FAILED").count()
        pending = payment_query.filter(Payment.status.in_(["CREATED", "PENDING", "PROCESSING"])).count()
        total_revenue = money(self._payment_query(merchant_id, start_date, end_date).filter(Payment.status == "SUCCESS").with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar())
        payment_attempts = successful + failed + pending
        return {
            "merchant_id": merchant_id,
            "total_orders": sum(int(row[1]) for row in order_rows),
            "orders_by_status": {row[0]: int(row[1]) for row in order_rows},
            "successful_payments": successful,
            "failed_payments": failed,
            "pending_payments": pending,
            "payment_success_rate": percentage(successful, payment_attempts),
            "average_order_value": average(total_revenue, successful),
        }

    def products(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None, limit: int = 10) -> dict:
        self.validate_date_range(start_date, end_date)
        top_rows = (
            self._order_item_query(merchant_id, start_date, end_date)
            .with_entities(Product.id, Product.name, func.coalesce(func.sum(OrderItem.quantity), 0), func.coalesce(func.sum(OrderItem.line_total), 0))
            .group_by(Product.id, Product.name)
            .order_by(func.sum(OrderItem.quantity).desc(), func.sum(OrderItem.line_total).desc())
            .limit(limit)
            .all()
        )
        return {
            "merchant_id": merchant_id,
            "total_products": self.db.query(Product).filter(Product.merchant_id == merchant_id).count(),
            "active_products": self.db.query(Product).filter(Product.merchant_id == merchant_id).filter(Product.is_active.is_(True)).count(),
            "product_variants": self.db.query(ProductVariant).join(Product, Product.id == ProductVariant.product_id).filter(Product.merchant_id == merchant_id).count(),
            "top_products": [
                {"product_id": row[0], "product_name": row[1], "units_sold": int(row[2]), "revenue_generated": money(row[3])}
                for row in top_rows
            ],
        }

    def inventory(self, merchant_id: UUID, low_stock_threshold: int = 5) -> dict:
        rows = self._inventory_query(merchant_id).all()
        low_stock = [row for row in rows if row[2].available_quantity <= low_stock_threshold]
        return {
            "merchant_id": merchant_id,
            "total_inventory_units": sum(int(inventory.available_quantity) for _product, _variant, inventory in rows),
            "in_stock_variants": sum(1 for _product, _variant, inventory in rows if inventory.available_quantity > 0),
            "out_of_stock_variants": sum(1 for _product, _variant, inventory in rows if inventory.available_quantity <= 0),
            "low_stock_variants": len(low_stock),
            "low_stock_items": [
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "variant_id": variant.id,
                    "sku": variant.sku,
                    "available_quantity": inventory.available_quantity,
                    "threshold": low_stock_threshold,
                    "status": "out_of_stock" if inventory.available_quantity <= 0 else "low_stock",
                }
                for product, variant, inventory in sorted(low_stock, key=lambda row: (row[2].available_quantity, row[0].name.lower(), row[1].sku))[:25]
            ],
        }

    def agent_activity(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
        self.validate_date_range(start_date, end_date)
        calls = self._tool_call_query(merchant_id, start_date, end_date)
        tool_rows = calls.with_entities(
            AgentToolCall.tool_name,
            func.count(AgentToolCall.id),
            func.coalesce(func.sum(case((AgentToolCall.success.is_(True), 1), else_=0)), 0),
        ).group_by(AgentToolCall.tool_name).all()
        recent = calls.order_by(AgentToolCall.created_at.desc()).limit(10).all()
        successful = calls.filter(AgentToolCall.success.is_(True)).count()
        total = calls.count()
        return {
            "merchant_id": merchant_id,
            "total_agent_sessions": self._agent_session_query(merchant_id, start_date, end_date).count(),
            "total_tool_calls": total,
            "successful_tool_calls": successful,
            "failed_tool_calls": total - successful,
            "tools": [{"tool_name": row[0], "calls": int(row[1]), "success_rate": percentage(int(row[2]), int(row[1]))} for row in tool_rows],
            "recent_activity": [{"session_id": call.session_id, "tool_name": call.tool_name, "success": call.success, "created_at": call.created_at} for call in recent],
        }

    def negotiations(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
        self.validate_date_range(start_date, end_date)
        decisions = self._negotiation_query(merchant_id, start_date, end_date).all()
        accepted = sum(1 for item in decisions if item.decision == "ACCEPT")
        rejected = sum(1 for item in decisions if item.decision == "REJECT")
        counter = sum(1 for item in decisions if item.decision == "COUNTER_OFFER")
        discounts = []
        for item in decisions:
            if item.original_price and item.offered_price and item.original_price > 0:
                discounts.append((Decimal(item.original_price) - Decimal(item.offered_price)) / Decimal(item.original_price) * Decimal("100"))
        return {
            "merchant_id": merchant_id,
            "total_negotiations": len(decisions),
            "accepted_negotiations": accepted,
            "rejected_negotiations": rejected,
            "counter_offers": counter,
            "acceptance_rate": percentage(accepted, len(decisions)),
            "average_discount_offered": money(sum(discounts, Decimal("0")) / len(discounts)) if discounts else Decimal("0.00"),
        }

    def recommendations(self, merchant_id: UUID, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
        self.validate_date_range(start_date, end_date)
        query = self._recommendation_query(merchant_id, start_date, end_date)
        total = query.count()
        experiment_counter: Counter[str] = Counter()
        experiment_calls = self._tool_call_query(merchant_id, start_date, end_date).filter(AgentToolCall.tool_name == "get_growth_experiment_variant").all()
        for call in experiment_calls:
            output = call.tool_output or {}
            variant = output.get("variant")
            if variant:
                experiment_counter[str(variant)] += 1
        return {
            "merchant_id": merchant_id,
            "total_recommendations": total,
            "upsell_recommendations": query.filter(Recommendation.recommendation_type == "upsell").count(),
            "cross_sell_recommendations": query.filter(Recommendation.recommendation_type == "cross_sell").count(),
            "recommendation_events": self._upsell_event_query(merchant_id, start_date, end_date).count(),
            "experiment_variants_used": dict(experiment_counter),
        }

    def _payment_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(Payment).join(Order, Order.id == Payment.order_id).filter(Order.merchant_id == merchant_id)
        return apply_date_range(query, Payment.created_at, start_date, end_date)

    def _order_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(Order).filter(Order.merchant_id == merchant_id)
        return apply_date_range(query, Order.created_at, start_date, end_date)

    def _order_item_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = (
            self.db.query(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .join(ProductVariant, ProductVariant.id == OrderItem.product_variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(Order.merchant_id == merchant_id)
            .filter(Order.status == "PAID")
        )
        return apply_date_range(query, Order.created_at, start_date, end_date)

    def _inventory_query(self, merchant_id: UUID):
        return (
            self.db.query(Product, ProductVariant, Inventory)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .join(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(Product.merchant_id == merchant_id)
        )

    def _agent_session_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(AgentSession).filter(AgentSession.merchant_id == merchant_id)
        return apply_date_range(query, AgentSession.created_at, start_date, end_date)

    def _tool_call_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(AgentToolCall).filter(AgentToolCall.merchant_id == merchant_id)
        return apply_date_range(query, AgentToolCall.created_at, start_date, end_date)

    def _negotiation_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(PolicyDecision).filter(PolicyDecision.merchant_id == merchant_id).filter(PolicyDecision.decision_type == "negotiation")
        return apply_date_range(query, PolicyDecision.created_at, start_date, end_date)

    def _recommendation_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(Recommendation).filter(Recommendation.merchant_id == merchant_id)
        return apply_date_range(query, Recommendation.created_at, start_date, end_date)

    def _upsell_event_query(self, merchant_id: UUID, start_date: datetime | None, end_date: datetime | None):
        query = self.db.query(UpsellEvent).filter(UpsellEvent.merchant_id == merchant_id)
        return apply_date_range(query, UpsellEvent.created_at, start_date, end_date)


def apply_date_range(query, column, start_date: datetime | None, end_date: datetime | None):
    if start_date:
        query = query.filter(column >= start_date)
    if end_date:
        query = query.filter(column <= end_date)
    return query


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def average(total: Decimal, count: int) -> Decimal:
    return money(total / count) if count else Decimal("0.00")


def percentage(numerator: int, denominator: int) -> Decimal:
    return money((Decimal(numerator) / Decimal(denominator)) * Decimal("100")) if denominator else Decimal("0.00")
