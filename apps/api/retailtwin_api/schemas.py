"""Public request and response models for the day-0 API."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: Literal["retailtwin-api"]
    environment: str
    app_env: str
    store_id: str
    fixture_loaded: bool


class ReadyResponse(BaseModel):
    """Readiness probe response — used by Cloud Run load-balancer routing decisions."""

    ready: Literal[True]
    service: Literal["retailtwin-api"]
    store_id: str
    correlation_id: str


class ProductInventory(BaseModel):
    store_id: str
    sku: str
    shelf_id: str
    slot_id: str
    facings: int
    shelf_quantity: int
    backroom_quantity: int
    version: int


class StoreResponse(BaseModel):
    store_id: str
    context_version: str
    version: str
    products: list[ProductInventory]


class FixtureProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: str = Field(min_length=1)
    shelf_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    facings: int = Field(ge=0)
    shelf_quantity: int = Field(ge=0)
    backroom_quantity: int = Field(ge=0)


class FixtureFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    store_id: str = Field(min_length=1)
    version: str
    products: list[FixtureProduct]


class StoreEvent(BaseModel):
    """Minimum normalized store event from the domain model."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    occurred_at: AwareDatetime
    source: str = Field(min_length=1)

    @field_validator(
        "event_id",
        "correlation_id",
        "event_type",
        "store_id",
        "sku",
        "source",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class EventReceipt(BaseModel):
    accepted: Literal[True] = True
    duplicate: bool
    event: StoreEvent
