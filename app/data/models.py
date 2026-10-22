"""Relational schema (SQLAlchemy 2.0). SQLite for demo, PostgreSQL in production.
Indices on plant_id / heat_id / timestamps; every row carries audit metadata."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Heat(Base):
    __tablename__ = "heats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(64), index=True)
    heat_id: Mapped[str] = mapped_column(String(64), index=True)
    grade_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(32), default="SYNTHETIC")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")


class Simulation(Base):
    __tablename__ = "simulations"
    simulation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(64), index=True)
    heat_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(48))
    scenario_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    request: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    sim_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    model_version: Mapped[str] = mapped_column(String(32))
    config_version: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(80))
    git_sha: Mapped[str] = mapped_column(String(80))
    seed: Mapped[int] = mapped_column(Integer)
    result_checksum: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="system")


class Trajectory(Base):
    __tablename__ = "trajectories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.simulation_id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # twin | plant
    records: Mapped[list] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LabSample(Base):
    __tablename__ = "lab_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(64), index=True)
    heat_id: Mapped[str] = mapped_column(String(64), index=True)
    t_sample_s: Mapped[float] = mapped_column(Float)
    t_available_s: Mapped[float] = mapped_column(Float)
    values: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32))  # LAB ANALYZED (synthetic) | USER-DEFINED
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alarm(Base):
    __tablename__ = "alarms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(64), index=True)
    t_s: Mapped[float] = mapped_column(Float)
    hazard_id: Mapped[str] = mapped_column(String(8))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    acknowledged_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    acknowledged_by: Mapped[str] = mapped_column(String(64), default="")
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OptimizationJob(Base):
    __tablename__ = "optimizations"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # shadow | approved | retired
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_sim_plant_heat", Simulation.plant_id, Simulation.heat_id)
