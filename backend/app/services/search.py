from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_
from sqlalchemy.orm import Session

from app.models import Inventory, Merchant, Product, ProductVariant


@dataclass(frozen=True)
class SearchCriteria:
    query: str | None = None
    merchant_id: UUID | None = None
    category: str | None = None
    brand: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    in_stock: bool | None = None
    attributes: dict | None = None
    limit: int = 20


@dataclass(frozen=True)
class SearchResult:
    product_id: UUID
    merchant_id: UUID
    merchant_name: str
    name: str
    description: str | None
    category: str | None
    brand: str | None
    variant_id: UUID
    sku: str
    attributes: dict
    price: Decimal
    available_quantity: int
    available: bool
    score: int


class RankingService:
    def score(self, result: SearchResult, query: str | None, category: str | None, attributes: dict | None) -> int:
        score = 0
        normalized_query = normalize_text(query)
        terms = normalized_query.split()
        name = normalize_text(result.name)
        description = normalize_text(result.description)
        result_category = normalize_text(result.category)
        sku = normalize_text(result.sku)
        attr_text = normalize_text(" ".join(str(value) for value in result.attributes.values()))

        if normalized_query and name == normalized_query:
            score += 100
        if normalized_query and normalized_query in name:
            score += 60
        score += sum(15 for term in terms if term in name)
        if category and result_category == normalize_text(category):
            score += 35
        score += sum(8 for term in terms if term in description)
        score += sum(8 for term in terms if term in attr_text)
        score += sum(4 for term in terms if term in sku)
        if attributes:
            for key, value in attributes.items():
                if value is None:
                    continue
                result_value = result.attributes.get(key)
                if isinstance(value, list):
                    score += sum(10 for item in value if item and normalize_text(item) in attr_text)
                elif result_value is not None and normalize_text(result_value) == normalize_text(value):
                    score += 20
        if result.available:
            score += 5
        return score


class SearchService:
    def __init__(self, db: Session):
        self.db = db
        self.ranking = RankingService()

    def search(self, criteria: SearchCriteria) -> list[SearchResult]:
        normalized_query = normalize_text(criteria.query)
        query = (
            self.db.query(Product, ProductVariant, Inventory, Merchant)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .join(Merchant, Merchant.id == Product.merchant_id)
            .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
            .filter(Product.is_active.is_(True))
            .filter(ProductVariant.is_active.is_(True))
            .filter(Merchant.is_active.is_(True))
        )

        if criteria.merchant_id:
            query = query.filter(Product.merchant_id == criteria.merchant_id)
        if criteria.category:
            query = query.filter(func.lower(Product.category) == normalize_text(criteria.category))
        if criteria.brand:
            query = query.filter(func.lower(Product.brand) == normalize_text(criteria.brand))
        if criteria.min_price is not None:
            query = query.filter(ProductVariant.price >= criteria.min_price)
        if criteria.max_price is not None:
            query = query.filter(ProductVariant.price <= criteria.max_price)
        if criteria.in_stock is True:
            query = query.filter(and_(Inventory.id.is_not(None), Inventory.available_quantity > 0))
        elif criteria.in_stock is False:
            query = query.filter(or_(Inventory.id.is_(None), Inventory.available_quantity <= 0))

        if normalized_query:
            terms = normalized_query.split()
            searchable_attributes = cast(ProductVariant.attributes, String)
            for term in terms:
                pattern = f"%{term}%"
                query = query.filter(
                    or_(
                        Product.name.ilike(pattern),
                        Product.description.ilike(pattern),
                        Product.category.ilike(pattern),
                        Product.brand.ilike(pattern),
                        ProductVariant.sku.ilike(pattern),
                        searchable_attributes.ilike(pattern),
                    )
                )

        if criteria.attributes:
            searchable_attributes = cast(ProductVariant.attributes, String)
            for key, value in criteria.attributes.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    continue
                else:
                    query = query.filter(ProductVariant.attributes[key].astext.ilike(f"%{normalize_text(value)}%"))

        rows = query.limit(max(criteria.limit * 4, criteria.limit)).all()
        results = [
            SearchResult(
                product_id=product.id,
                merchant_id=product.merchant_id,
                merchant_name=merchant.name,
                name=product.name,
                description=product.description,
                category=product.category,
                brand=product.brand,
                variant_id=variant.id,
                sku=variant.sku,
                attributes=variant.attributes or {},
                price=variant.price,
                available_quantity=inventory.available_quantity if inventory else 0,
                available=bool(inventory and inventory.available_quantity > 0),
                score=0,
            )
            for product, variant, inventory, merchant in rows
        ]

        ranked = [
            result.__class__(
                **{
                    **result.__dict__,
                    "score": self.ranking.score(result, criteria.query, criteria.category, criteria.attributes),
                }
            )
            for result in results
        ]
        ranked.sort(key=lambda item: (-item.score, item.price, item.name.lower(), item.sku.lower()))
        return ranked[: criteria.limit]


def normalize_text(value: object | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).lower().strip().split())
