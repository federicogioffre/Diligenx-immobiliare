from sqlalchemy import String, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class PropertyProfile(TimestampMixin, Base):
    """What one document states about one property unit.

    Written by the property-identity stage: one row per unit per source
    document (a deed covering a flat and a garage yields two rows). The
    report consolidates the rows into one identification table per unit,
    and the consistency stage compares them across documents — the deed
    against the cadastral extract, the floor plan against the permit.

    Every field is nullable and stored as the document writes it; nothing is
    normalised here, because a difference in spelling between two sources
    is exactly what the consistency stage has to see.
    """

    __tablename__ = "property_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    # Document type the routing stage assigned to the source (atto_provenienza,
    # visura_catastale, planimetria, …): it ranks the source's authority.
    source_kind: Mapped[str | None] = mapped_column(String(40))

    unit_label: Mapped[str | None] = mapped_column(String(200))
    # Cadastral identification
    comune: Mapped[str | None] = mapped_column(String(200))
    sezione: Mapped[str | None] = mapped_column(String(40))
    foglio: Mapped[str | None] = mapped_column(String(40))
    particella: Mapped[str | None] = mapped_column(String(60))
    subalterno: Mapped[str | None] = mapped_column(String(40))
    categoria: Mapped[str | None] = mapped_column(String(40))
    classe: Mapped[str | None] = mapped_column(String(40))
    consistenza: Mapped[str | None] = mapped_column(String(100))
    superficie: Mapped[str | None] = mapped_column(String(100))
    rendita: Mapped[str | None] = mapped_column(String(100))
    # Location
    indirizzo: Mapped[str | None] = mapped_column(String(500))
    piano: Mapped[str | None] = mapped_column(String(100))
    # Holders the document names: [{"name", "tax_code", "share", "right"}].
    intestatari: Mapped[list | None] = mapped_column(JSON)
    # The title the document records (e.g. "compravendita, notaio X, rep. 123").
    titolo: Mapped[str | None] = mapped_column(String(500))
    data_titolo: Mapped[str | None] = mapped_column(String(40))

    confidence: Mapped[float | None] = mapped_column(Float)

    deal = relationship("Deal", back_populates="property_profiles")
    source_document = relationship("Document")
