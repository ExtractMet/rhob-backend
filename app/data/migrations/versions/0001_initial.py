"""initial schema: heats, simulations, trajectories, lab_samples, alarms, recommendations,
optimizations, audit_log, idempotency_keys, model_versions

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("heats", sa.Column("id", sa.Integer, primary_key=True), sa.Column("plant_id", sa.String(64), index=True),
                    sa.Column("heat_id", sa.String(64), index=True), sa.Column("grade_id", sa.String(64)), sa.Column("payload", sa.JSON),
                    sa.Column("provenance", sa.String(32)), sa.Column("created_at", sa.DateTime(timezone=True), index=True),
                    sa.Column("created_by", sa.String(64)))
    op.create_table("simulations", sa.Column("simulation_id", sa.String(64), primary_key=True), sa.Column("plant_id", sa.String(64), index=True),
                    sa.Column("heat_id", sa.String(64), index=True), sa.Column("mode", sa.String(48)), sa.Column("scenario_name", sa.String(128)),
                    sa.Column("status", sa.String(32)), sa.Column("request", sa.JSON), sa.Column("summary", sa.JSON), sa.Column("sim_time_s", sa.Float),
                    sa.Column("version", sa.Integer), sa.Column("model_version", sa.String(32)), sa.Column("config_version", sa.String(64)),
                    sa.Column("source_hash", sa.String(80)), sa.Column("git_sha", sa.String(80)), sa.Column("seed", sa.Integer),
                    sa.Column("result_checksum", sa.String(80)), sa.Column("created_at", sa.DateTime(timezone=True), index=True),
                    sa.Column("updated_at", sa.DateTime(timezone=True)), sa.Column("created_by", sa.String(64)))
    op.create_index("ix_sim_plant_heat", "simulations", ["plant_id", "heat_id"])
    op.create_table("trajectories", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("simulation_id", sa.String(64), sa.ForeignKey("simulations.simulation_id", ondelete="CASCADE"), index=True),
                    sa.Column("kind", sa.String(16)), sa.Column("records", sa.JSON), sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_table("lab_samples", sa.Column("id", sa.Integer, primary_key=True), sa.Column("simulation_id", sa.String(64), index=True),
                    sa.Column("heat_id", sa.String(64), index=True), sa.Column("t_sample_s", sa.Float), sa.Column("t_available_s", sa.Float),
                    sa.Column("values", sa.JSON), sa.Column("source", sa.String(32)), sa.Column("applied", sa.Boolean),
                    sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_table("alarms", sa.Column("id", sa.Integer, primary_key=True), sa.Column("simulation_id", sa.String(64), index=True),
                    sa.Column("t_s", sa.Float), sa.Column("hazard_id", sa.String(8)), sa.Column("severity", sa.String(16)), sa.Column("message", sa.Text),
                    sa.Column("acknowledged_by", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), index=True))
    op.create_table("recommendations", sa.Column("id", sa.Integer, primary_key=True), sa.Column("simulation_id", sa.String(64), index=True),
                    sa.Column("payload", sa.JSON), sa.Column("acknowledged_by", sa.String(64)), sa.Column("decision", sa.String(16)),
                    sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_table("optimizations", sa.Column("job_id", sa.String(64), primary_key=True), sa.Column("simulation_id", sa.String(64), index=True),
                    sa.Column("status", sa.String(16)), sa.Column("result", sa.JSON), sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_table("audit_log", sa.Column("id", sa.Integer, primary_key=True), sa.Column("ts", sa.DateTime(timezone=True), index=True),
                    sa.Column("user", sa.String(64)), sa.Column("role", sa.String(32)), sa.Column("action", sa.String(64), index=True),
                    sa.Column("target", sa.String(128)), sa.Column("detail", sa.JSON))
    op.create_table("idempotency_keys", sa.Column("key", sa.String(128), primary_key=True), sa.Column("response", sa.JSON),
                    sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_table("model_versions", sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(64)),
                    sa.Column("version", sa.String(32)), sa.Column("status", sa.String(16)), sa.Column("approved_by", sa.String(64)),
                    sa.Column("meta", sa.JSON), sa.Column("created_at", sa.DateTime(timezone=True)))


def downgrade():
    for t in ["model_versions", "idempotency_keys", "audit_log", "optimizations", "recommendations", "alarms", "lab_samples",
              "trajectories", "simulations", "heats"]:
        op.drop_table(t)
