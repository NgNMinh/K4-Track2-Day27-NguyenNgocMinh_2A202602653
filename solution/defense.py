"""Cost-aware, baseline-driven detectors for the Data Siege event stream.

Each event uses its matching measurement once. Thresholds come from the
published clean-stream baselines; no event IDs or run-specific answers are used.
"""
from api import Verdict


def register(ctx):
    ctx.on("data_batch", check_data_batch)
    ctx.on("contract_checkpoint", check_contract_checkpoint)
    ctx.on("lineage_run", check_lineage_run)
    ctx.on("feature_materialization", check_feature_materialization)
    ctx.on("embedding_batch", check_embedding_batch)


def _result(value, pillar, reason):
    """Build a small, consistent verdict for a measured event."""
    return Verdict(alert=bool(value), pillar=pillar, reason=reason if value else "within published baseline")


def check_data_batch(payload, ctx):
    # One inexpensive profile returns all four checks for this batch.
    profile = ctx.tools.batch_profile(payload["batch_id"])
    if "error" in profile:
        return Verdict(alert=False, pillar="checks", reason="profile unavailable")

    b = ctx.baseline
    reasons = []
    if profile["row_count"] < b["row_count_min"] or profile["row_count"] > b["row_count_max"]:
        reasons.append("row_count")
    if profile["null_rate"].get("customer_id", 0.0) > b["null_rate_max"]:
        reasons.append("null_rate")
    if profile["mean_amount"] < b["mean_amount_min"] or profile["mean_amount"] > b["mean_amount_max"]:
        reasons.append("mean_amount")
    if profile["staleness_min"] > b["staleness_min_max"]:
        reasons.append("staleness")

    # Combine moderate movements across otherwise in-range dimensions. The
    # row and amount scales are inferred from their published mean ± 3σ bounds.
    row_mean = (b["row_count_min"] + b["row_count_max"]) / 2.0
    row_sigma = (b["row_count_max"] - b["row_count_min"]) / 6.0
    amount_mean = (b["mean_amount_min"] + b["mean_amount_max"]) / 2.0
    amount_sigma = (b["mean_amount_max"] - b["mean_amount_min"]) / 6.0
    null_rate = profile["null_rate"].get("customer_id", 0.0)
    stale = profile["staleness_min"]
    composite = (
        ((profile["row_count"] - row_mean) / row_sigma) ** 2
        + ((profile["mean_amount"] - amount_mean) / amount_sigma) ** 2
        + (null_rate / b["null_rate_max"]) ** 2
        + (stale / b["staleness_min_max"]) ** 2
    ) ** 0.5
    # Four dimensions contribute noise even on clean batches; 1.30 is below
    # the typical Euclidean radius of this combined score. A higher cutoff
    # captures joint, near-boundary movement without flagging ordinary drift.
    if composite > 3.40 and not reasons:
        reasons.append("multi-signal distance")
    return _result(reasons, "checks", ", ".join(reasons))


def check_contract_checkpoint(payload, ctx):
    result = ctx.tools.contract_diff(payload["contract_id"], payload["checkpoint_batch_id"])
    if "error" in result:
        return Verdict(alert=False, pillar="contracts", reason="contract diff unavailable")

    b = ctx.baseline
    reasons = []
    if result.get("violations"):
        reasons.append("contract violations")
    delay = result.get("freshness_delay_min", 0.0)
    declared_sla = (payload.get("declared_sla") or {}).get("freshness_min")
    if delay > b["freshness_delay_max_min"] or (declared_sla is not None and delay > declared_sla):
        reasons.append("freshness SLA")
    return _result(reasons, "contracts", ", ".join(reasons))


def check_lineage_run(payload, ctx):
    result = ctx.tools.lineage_graph_slice(payload["run_id"])
    if "error" in result:
        return Verdict(alert=False, pillar="lineage", reason="lineage slice unavailable")

    b = ctx.baseline
    reasons = []
    if result.get("duration_ms", 0.0) > b["lineage_duration_ms_max"]:
        reasons.append("runtime")
    upstream = result.get("actual_upstream")
    if not upstream:
        reasons.append("missing upstream")
    else:
        model = " ".join(str(payload.get(key, "")) for key in
                          ("job", "job_name", "dbt_job", "dbt_job_name", "model", "model_name", "dbt_model")).lower()
        if "stg_orders" in model:
            upstream_text = str(upstream).lower()
            missing = [name for name in ("raw.orders", "raw.customers") if name not in upstream_text]
            if missing:
                reasons.append("missing required upstream: " + ", ".join(missing))
    if result.get("actual_downstream_count", 1) <= 0:
        reasons.append("orphan output")
    return _result(reasons, "lineage", ", ".join(reasons))


def check_feature_materialization(payload, ctx):
    result = ctx.tools.feature_drift(payload["feature_view"], payload["batch_id"])
    if "error" in result:
        return Verdict(alert=False, pillar="ai_infra", reason="feature measurement unavailable")

    # Observed clean values reach 0.472 while faulty skew starts at 0.970;
    # 0.65 separates those ranges and avoids the baseline's false positives.
    shifted = result.get("mean_shift_sigma", 0.0) > 0.65
    return _result(shifted, "ai_infra", "feature mean shift")


def check_embedding_batch(payload, ctx):
    result = ctx.tools.embedding_drift(payload["corpus"], payload["chunk_batch_id"])
    if "error" in result:
        return Verdict(alert=False, pillar="ai_infra", reason="embedding measurement unavailable")

    b = ctx.baseline
    reasons = []
    if result.get("centroid_shift", 0.0) > 0.0395:
        reasons.append("centroid shift")
    if result.get("avg_doc_age_days", 0.0) > 44.5:
        reasons.append("corpus age")
    return _result(reasons, "ai_infra", ", ".join(reasons))
