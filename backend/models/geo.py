from sqlalchemy import Integer, String, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin

class Country(Base, PublicIdMixin):
    __tablename__ = "countries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    # ISO 3166-1 alpha-2. NOT NULL + unique: every real country has one, and
    # it's the natural external identifier for country lookups (matched
    # against `cities.json`'s `country_code`) -- previously nullable, which
    # would have let a row exist that no city or lookup could ever match.
    code: Mapped[str] = mapped_column(String(2), unique=True, index=True, nullable=False)
    cities: Mapped[List["City"]] = relationship(
        "City",
        back_populates="country",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

class City(Base, PublicIdMixin):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # The GeoNames identifier for seeded rows -- unique so re-running the
    # seeder is a genuine idempotency check, not just "insert and hope".
    # Nullable, and a plain unique index tolerates that in Postgres (NULLs
    # are never considered equal to each other): a city added by hand
    # through the API, rather than sourced from GeoNames, has none.
    geoname_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True)
    # A city with no country is not a usable location -- tightened from
    # nullable now that real seed data exists to populate it correctly.
    country_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("countries.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    population: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Denormalized IANA zone name (e.g. "Europe/Andorra"), copied straight
    # from GeoNames at seed time -- lets a client default a new user's
    # timezone from their chosen city without a second lookup.
    timezone: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    country: Mapped[Country] = relationship(Country, back_populates="cities", lazy="selectin")
    users: Mapped[List["User"]] = relationship("User", back_populates="current_city", lazy="selectin")

class TimeZone(Base):
    """IANA time zone names. `code` (e.g. "America/New_York") is the natural,
    stable, already-unique identifier -- no synthetic public_id needed, the
    same reasoning already applied to Role/Permission in this codebase."""

    __tablename__ = "time_zones"
    code: Mapped[str] = mapped_column(String(150), primary_key=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
