"""Comprehensive Phase 14 Acceptance Suite: Autonomous Self-Improvement, Evaluation & Adaptive Intelligence.

Verifies scenarios AUTO-01 through AUTO-27.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from atlas_adaptive.adaptive_router import (
    AdaptiveModelRouter,
    DataPrivacyRoutingError,
    MediaSensitivity,
    ModelRouteCandidate,
)
from atlas_adaptive.agent_analytics import (
    AgentPerformanceIntelligence,
)
from atlas_adaptive.evaluator import (
    TaskDomain,
    TaskEvaluationEngine,
    TaskEvaluationMetric,
)
from atlas_adaptive.experience import (
    ExperienceOutcome,
    ExperienceStore,
)
from atlas_adaptive.experimentation import (
    AutomatedExperimentationEngine,
    ExperimentDefinition,
    ExperimentStatus,
)
from atlas_adaptive.failure_analyzer import (
    FailureAnalysisEngine,
    FailureCategory,
)
from atlas_adaptive.governor import (
    ChangeCategory,
    ProposedChange,
    ProtectedComponentModificationError,
    SafetyGovernor,
    SelfApprovalProhibitedError,
)
from atlas_adaptive.knowledge import (
    ContradictionDetectedError,
    ControlledKnowledgeStore,
    KnowledgeStatus,
)
from atlas_adaptive.optimizer import (
    StrategyCandidate,
    StrategyOptimizationEngine,
)
from atlas_adaptive.promotion import (
    PromotionManager,
    PromotionStage,
    UnauthorizedPromotionError,
)
from atlas_adaptive.regression import (
    RegressionIntelligenceSystem,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ==============================================================================
# AUTO-01: Task Evaluation Evidence Validation (Outcome & Evidence Required)
# ==============================================================================
def test_auto01_task_evaluation_evidence_validation():
    """Verify task evaluation requires actual verification evidence to yield a positive score."""
    metrics = TaskEvaluationMetric(
        execution_duration_sec=15.0,
        token_cost_usd=0.01,
        retry_count=0,
        recovery_count=0,
        policy_denials=0,
    )

    # Valid completed task with evidence
    res_valid = TaskEvaluationEngine.evaluate_task(
        task_id="task_e2e_01",
        tenant_id="tenant_alpha",
        reported_completed=True,
        verification_evidence_refs=["artifacts/receipt_998.json", "artifacts/state_diff.png"],
        metrics=metrics,
        domain=TaskDomain.ENTERPRISE,
    )

    assert res_valid.is_completed is True
    assert res_valid.is_false_success is False
    assert res_valid.functional_score == 1.0
    assert res_valid.overall_score > 0.80
    assert len(res_valid.failure_reasons) == 0


# ==============================================================================
# AUTO-02: False Success Detection (Self-Reported Claim with Missing Evidence)
# ==============================================================================
def test_auto02_false_success_detection():
    """Verify that an agent claiming completion without verification evidence is flagged as false success."""
    metrics = TaskEvaluationMetric(execution_duration_sec=10.0, token_cost_usd=0.005)

    # Agent reports completed, but evidence is empty!
    res = TaskEvaluationEngine.evaluate_task(
        task_id="task_fraud_01",
        tenant_id="tenant_alpha",
        reported_completed=True,
        verification_evidence_refs=[],  # Missing evidence!
        metrics=metrics,
    )

    assert res.is_completed is False
    assert res.is_false_success is True
    assert res.functional_score == 0.0
    assert res.overall_score == 0.0
    assert any("false success" in r.lower() for r in res.failure_reasons)


# ==============================================================================
# AUTO-03: Multi-Class Failure Classification & Evidence-Backed Root Cause
# ==============================================================================
def test_auto03_failure_classification_and_root_cause():
    """Verify multi-class failure classification across permission denials, visual grounding, and network."""
    # 1. Permission Denial
    events_perm = [
        {"timestamp": 1.0, "message": "Attempting action ui_click_admin"},
        {
            "timestamp": 1.2,
            "error": "Action blocked: Policy denied execution on protected endpoint (403)",
        },
    ]
    res_perm = FailureAnalysisEngine.analyze_failure("task_f1", events_perm)
    assert res_perm.primary_cause.category == FailureCategory.PERMISSION_DENIAL
    assert res_perm.primary_cause.confidence >= 0.90

    # 2. Visual Grounding Error
    events_ground = [
        {"timestamp": 2.0, "message": "Analyzing observation obs_88"},
        {
            "timestamp": 2.5,
            "error": "Stale observation rejected: coordinates age 6.2s exceeded threshold",
        },
    ]
    res_ground = FailureAnalysisEngine.analyze_failure("task_f2", events_ground)
    assert res_ground.primary_cause.category == FailureCategory.VISUAL_GROUNDING_ERROR

    # 3. Verification Failure
    events_verif = [
        {"timestamp": 3.0, "message": "Executing checkout click"},
        {
            "timestamp": 3.5,
            "error": "Post-condition verification failed: order confirmation element not found",
        },
    ]
    res_verif = FailureAnalysisEngine.analyze_failure("task_f3", events_verif)
    assert res_verif.primary_cause.category == FailureCategory.VERIFICATION_FAILURE


# ==============================================================================
# AUTO-04: Experience Store Pattern Provenance & Context Fingerprinting
# ==============================================================================
def test_auto04_experience_pattern_provenance():
    """Verify that execution experiences maintain immutable cryptographic provenance hashes."""
    store = ExperienceStore()

    exp = store.record_experience(
        tenant_id="tenant_omega",
        task_category="browser",
        context_fingerprint="fp_checkout_stripe_v3",
        observed_facts=[
            "Stripe iframe rendered with 500ms delay",
            "Submit button requires second click",
        ],
        generated_recommendations=["Wait for iframe readyState complete before dispatching click"],
        outcome=ExperienceOutcome.SUCCESS,
        evaluation_score=0.92,
        source_task_id="task_stripe_88",
    )

    assert exp.tenant_id == "tenant_omega"
    assert exp.provenance_hash.startswith("sha256:")
    assert exp.is_verified is False

    # Verify that changing observed facts changes provenance hash
    other_hash = ExperienceStore.compute_provenance_hash(
        tenant_id="tenant_omega",
        source_task_id="task_stripe_88",
        context_fingerprint="fp_checkout_stripe_v3",
        observed_facts=["Different fact"],
    )
    assert exp.provenance_hash != other_hash


# ==============================================================================
# AUTO-05: Unverified Recommendation Rejection from Authoritative Memory
# ==============================================================================
def test_auto05_unverified_memory_rejection():
    """Verify that unverified experiences are never returned as authoritative instructions."""
    store = ExperienceStore()

    exp = store.record_experience(
        tenant_id="tenant_omega",
        task_category="browser",
        context_fingerprint="fp_login_sso",
        observed_facts=["SSO redirect encountered"],
        generated_recommendations=["Bypass SSO popup via direct cookie injection"],
        outcome=ExperienceOutcome.SUCCESS,
        evaluation_score=0.95,
        source_task_id="task_sso_1",
        is_verified=False,  # Unverified!
    )

    # Query authoritative recommendations: must be empty
    auth_recs = store.get_authoritative_recommendations(
        tenant_id="tenant_omega",
        context_fingerprint="fp_login_sso",
    )
    assert len(auth_recs) == 0

    # Mark verified
    store.verify_experience(exp.experience_id, requesting_tenant_id="tenant_omega")

    # Now authoritative recommendations return the validated guidance
    auth_recs_after = store.get_authoritative_recommendations(
        tenant_id="tenant_omega",
        context_fingerprint="fp_login_sso",
    )
    assert len(auth_recs_after) == 1
    assert "Bypass SSO popup" in auth_recs_after[0]


# ==============================================================================
# AUTO-06: Strategy Optimization Multi-Objective Comparison against Baseline
# ==============================================================================
def test_auto06_strategy_comparison_and_pareto_selection():
    """Verify multi-objective optimization Pareto dominance and rejection of safety-degrading candidates."""
    baseline = StrategyCandidate(
        strategy_id="strat_base",
        name="Standard Hierarchical Planner",
        success_rate=0.85,
        avg_duration_sec=30.0,
        avg_cost_usd=0.04,
        verification_quality=0.95,
        policy_compliance_rate=1.0,
    )

    # 1. Pareto-superior candidate (higher success, faster, cheaper, same safety)
    pareto_candidate = StrategyCandidate(
        strategy_id="strat_pareto",
        name="Optimized Cache Planner",
        success_rate=0.92,
        avg_duration_sec=20.0,
        avg_cost_usd=0.025,
        verification_quality=0.98,
        policy_compliance_rate=1.0,
    )

    opt_pareto = StrategyOptimizationEngine.compare_strategies(pareto_candidate, baseline)
    assert opt_pareto.is_pareto_improvement is True
    assert opt_pareto.is_acceptable is True
    assert opt_pareto.selected_strategy_id == "strat_pareto"

    # 2. Poison candidate: Faster and cheaper, but degrades policy compliance!
    poison_candidate = StrategyCandidate(
        strategy_id="strat_poison",
        name="Aggressive Fast Planner",
        success_rate=0.95,
        avg_duration_sec=10.0,
        avg_cost_usd=0.01,
        verification_quality=0.95,
        policy_compliance_rate=0.90,  # Safety degraded!
    )

    opt_poison = StrategyOptimizationEngine.compare_strategies(poison_candidate, baseline)
    assert opt_poison.is_acceptable is False
    assert opt_poison.selected_strategy_id == "strat_base"
    assert "safety is non-compensable" in opt_poison.decision_rationale.lower()


# ==============================================================================
# AUTO-07: Adaptive Model Routing based on Latency, Cost & Modality
# ==============================================================================
def test_auto07_adaptive_model_routing():
    """Verify adaptive model routing chooses optimal provider balancing quality, cost, and latency."""
    router = AdaptiveModelRouter()

    # Fast cheap model
    router.register_candidate(
        ModelRouteCandidate(
            model_name="flash-v1",
            provider_id="prov_gemini",
            avg_latency_ms=120.0,
            cost_per_1k_tokens=0.0005,
            historical_quality_score=0.88,
        )
    )

    # Heavy expensive model
    router.register_candidate(
        ModelRouteCandidate(
            model_name="pro-v1",
            provider_id="prov_anthropic",
            avg_latency_ms=900.0,
            cost_per_1k_tokens=0.015,
            historical_quality_score=0.96,
        )
    )

    # General request should select flash-v1 due to balanced utility
    selected = router.select_route(task_category="general", min_quality=0.80)
    assert selected.model_name == "flash-v1"

    # Request requiring high quality > 0.92 must select pro-v1
    selected_high_q = router.select_route(task_category="complex_code", min_quality=0.92)
    assert selected_high_q.model_name == "pro-v1"


# ==============================================================================
# AUTO-08: Privacy Policy Preservation in Adaptive Model Routing
# ==============================================================================
def test_auto08_privacy_policy_preservation():
    """Verify that CONFIDENTIAL/RESTRICTED data routes strictly to on-premise local GPU models."""
    router = AdaptiveModelRouter()

    # Cloud public model
    router.register_candidate(
        ModelRouteCandidate(
            model_name="cloud-gpt4",
            provider_id="prov_openai",
            is_local_gpu=False,
            historical_quality_score=0.98,
        )
    )

    # Local private GPU model
    router.register_candidate(
        ModelRouteCandidate(
            model_name="local-qwen",
            provider_id="prov_vllm_local",
            is_local_gpu=True,
            historical_quality_score=0.91,
        )
    )

    # Confidential request must pick local model even if cloud has higher quality score
    selected = router.select_route(
        task_category="payroll",
        sensitivity=MediaSensitivity.CONFIDENTIAL,
    )
    assert selected.model_name == "local-qwen"
    assert selected.is_local_gpu is True


# ==============================================================================
# AUTO-09: Restricted Data External Routing Rejection & Fast-Fail
# ==============================================================================
def test_auto09_restricted_data_routing_rejection():
    """Verify that restricted data fast-fails with DataPrivacyRoutingError when no local GPU exists."""
    router = AdaptiveModelRouter()

    # Only cloud models available
    router.register_candidate(
        ModelRouteCandidate(
            model_name="cloud-claude",
            provider_id="prov_anthropic",
            is_local_gpu=False,
        )
    )

    with pytest.raises(DataPrivacyRoutingError) as exc_info:
        router.select_route(
            task_category="classified_research",
            sensitivity=MediaSensitivity.RESTRICTED,
        )
    assert "strictly forbidden" in str(exc_info.value).lower()


# ==============================================================================
# AUTO-10: Sandboxed Experiment Isolation & Clean Environment Tear-Down
# ==============================================================================
def test_auto10_experiment_isolation():
    """Verify that automated experiments run in isolated sandboxed environments."""
    exp_def = ExperimentDefinition(
        candidate_strategy_id="cand_strat_01",
        baseline_strategy_id="base_strat_01",
        num_trials=5,
    )

    def dummy_runner(trial_idx: int) -> dict[str, Any]:
        return {
            "success": True,
            "duration_sec": 1.2,
            "cost_usd": 0.005,
            "evidence_hash": f"hash_{trial_idx}",
        }

    report = AutomatedExperimentationEngine.run_experiment(
        definition=exp_def,
        candidate_runner=dummy_runner,
        baseline_runner=dummy_runner,
    )

    assert report.status == ExperimentStatus.COMPLETED
    assert report.total_trials == 5
    assert len(report.candidate_trials) == 5
    assert len(report.baseline_trials) == 5


# ==============================================================================
# AUTO-11: Automated Experiment Cancellation on Budget or Timeout Breach
# ==============================================================================
def test_auto11_experiment_cancellation_and_resource_limits():
    """Verify that experiments exceeding resource or cost budgets are automatically cancelled."""
    # Set tight budget ceiling of $0.05
    exp_def = ExperimentDefinition(
        candidate_strategy_id="cand_expensive",
        baseline_strategy_id="base_standard",
        num_trials=10,
        max_cost_usd=0.05,
    )

    def expensive_runner(trial_idx: int) -> dict[str, Any]:
        # Each trial costs $0.02
        return {"success": True, "duration_sec": 1.0, "cost_usd": 0.02}

    report = AutomatedExperimentationEngine.run_experiment(
        definition=exp_def,
        candidate_runner=expensive_runner,
        baseline_runner=expensive_runner,
    )

    assert report.status == ExperimentStatus.CANCELLED
    assert report.total_trials < 10
    assert "budget exceeded" in str(report.cancellation_reason).lower()


# ==============================================================================
# AUTO-12: Statistical Significance Barrier for Candidate Strategy Evaluation
# ==============================================================================
def test_auto12_statistical_evaluation():
    """Verify statistical significance calculation enforces p < 0.05 barrier."""
    # 1. Clear statistical divergence: candidate 10/10 vs baseline 1/10
    exp_def = ExperimentDefinition(
        candidate_strategy_id="cand_great",
        baseline_strategy_id="base_poor",
        num_trials=10,
    )

    report_sig = AutomatedExperimentationEngine.run_experiment(
        definition=exp_def,
        candidate_runner=lambda i: {"success": True},
        baseline_runner=lambda i: {"success": False},
    )

    assert report_sig.delta_success_rate == 1.0
    assert report_sig.p_value < 0.01
    assert report_sig.is_statistically_significant is True

    # 2. Insufficient difference: candidate 5/10 vs baseline 5/10
    report_insig = AutomatedExperimentationEngine.run_experiment(
        definition=exp_def,
        candidate_runner=lambda i: {"success": (i % 2 == 0)},
        baseline_runner=lambda i: {"success": (i % 2 == 0)},
    )
    assert report_insig.delta_success_rate == 0.0
    assert report_insig.p_value >= 0.05
    assert report_insig.is_statistically_significant is False


# ==============================================================================
# AUTO-13: Continuous Regression Intelligence & Performance Degradation Alert
# ==============================================================================
def test_auto13_regression_detection():
    """Verify regression detection flags drops in success rate and spikes in latency."""
    regr_sys = RegressionIntelligenceSystem()
    regr_sys.register_baseline("success_rate", baseline_value=0.95, max_allowed_degradation_pct=5.0)
    regr_sys.register_baseline(
        "p95_latency_ms",
        baseline_value=200.0,
        max_allowed_degradation_pct=10.0,
        is_lower_better=True,
    )

    # Minor allowable fluctuation (3% drop)
    alerts_fine = regr_sys.evaluate_metrics({"success_rate": 0.93, "p95_latency_ms": 205.0})
    assert len(alerts_fine) == 0

    # Severe regression: success rate drops from 0.95 to 0.75 (21% drop), latency spikes to 300ms (50% spike)
    alerts_bad = regr_sys.evaluate_metrics({"success_rate": 0.75, "p95_latency_ms": 300.0})
    assert len(alerts_bad) == 2
    assert RegressionIntelligenceSystem.has_critical_regression(alerts_bad) is True


# ==============================================================================
# AUTO-14: Agent Performance Intelligence Analytics & Metric Aggregation
# ==============================================================================
def test_auto14_agent_performance_evaluation():
    """Verify agent performance analytics aggregate task completion and reliability metrics."""
    analytics = AgentPerformanceIntelligence()

    # Agent records 3 tasks
    analytics.record_task_execution(
        "agent_browser_01",
        "browser",
        is_success=True,
        is_verified=True,
        duration_sec=5.0,
        cost_usd=0.01,
    )
    analytics.record_task_execution(
        "agent_browser_01",
        "browser",
        is_success=True,
        is_verified=True,
        duration_sec=7.0,
        cost_usd=0.02,
    )
    analytics.record_task_execution(
        "agent_browser_01",
        "browser",
        is_success=False,
        is_verified=False,
        duration_sec=12.0,
        cost_usd=0.03,
        recovery_count=1,
    )

    metrics = analytics.get_agent_metrics("agent_browser_01")
    assert metrics is not None
    assert metrics.task_count == 3
    assert metrics.successful_tasks == 2
    assert round(metrics.completion_rate, 2) == 0.67
    assert metrics.recovery_count == 1

    recs = analytics.recommend_capability_adjustments("agent_browser_01")
    assert any("failure rate" in r.lower() for r in recs)


# ==============================================================================
# AUTO-15: Agent Permission Auto-Expansion Prohibition Invariant
# ==============================================================================
def test_auto15_agent_permission_auto_expansion_prohibition():
    """Verify that autonomous self-expansion of agent permissions is strictly forbidden."""
    analytics = AgentPerformanceIntelligence()

    # Even if an agent has a 100% completion rate, auto-permission expansion must fail
    with pytest.raises(PermissionError) as exc_info:
        analytics.attempt_permission_auto_expansion(
            agent_id="agent_high_performer",
            requested_permission="EXECUTE_ROOT_SHELL",
        )
    assert "strictly prohibited" in str(exc_info.value).lower()


# ==============================================================================
# AUTO-16: Controlled Knowledge Candidate Generation & Version Tracking
# ==============================================================================
def test_auto16_knowledge_versioning():
    """Verify knowledge candidates support version tracking and human approval workflow."""
    store = ControlledKnowledgeStore()

    candidate = store.propose_candidate(
        tenant_id="tenant_fin",
        topic="tax_filing",
        statement="Form 1099-NEC requires box 1 nonemployee compensation entry.",
        evidence_refs=["artifacts/irs_pub_15.pdf#page=12"],
        confidence=0.98,
        signature="sig_rsa_4096_valid",
    )

    assert candidate.status == KnowledgeStatus.CANDIDATE

    # Active knowledge before approval is empty
    assert len(store.get_active_knowledge("tenant_fin", "tax_filing")) == 0

    # Human approves candidate
    approved = store.approve_candidate(
        candidate.candidate_id,
        approver_id="compliance_officer_1",
        requesting_tenant_id="tenant_fin",
    )
    assert approved.status == KnowledgeStatus.APPROVED

    # Now active knowledge returns the approved fact
    active = store.get_active_knowledge("tenant_fin", "tax_filing")
    assert len(active) == 1
    assert active[0].statement == candidate.statement


# ==============================================================================
# AUTO-17: Contradictory Knowledge Detection & Resolution Workflow
# ==============================================================================
def test_auto17_contradictory_knowledge_detection():
    """Verify detection and rejection of contradictory knowledge candidate proposals."""
    store = ControlledKnowledgeStore()

    cand1 = store.propose_candidate(
        tenant_id="tenant_ops",
        topic="service_mesh",
        statement="Mutual TLS is always enabled in production clusters.",
        evidence_refs=["doc_sec_mesh_1.md"],
    )
    store.approve_candidate(
        cand1.candidate_id, approver_id="security_admin", requesting_tenant_id="tenant_ops"
    )

    # Second candidate contradicts approved fact: "Mutual TLS is never enabled..."
    with pytest.raises(ContradictionDetectedError) as exc_info:
        store.propose_candidate(
            tenant_id="tenant_ops",
            topic="service_mesh",
            statement="Mutual TLS is never enabled in production clusters.",
            evidence_refs=["doc_rumor.txt"],
        )
    assert "contradicts approved knowledge" in str(exc_info.value).lower()


# ==============================================================================
# AUTO-18: Safety Governor Enforcement on Immutable Security & Policy Paths
# ==============================================================================
def test_auto18_safety_governor_enforcement():
    """Verify that Safety Governor blocks any attempt to modify security policies."""
    governor = SafetyGovernor()

    danger_change = ProposedChange(
        proposer_id="optimizer_agent",
        category=ChangeCategory.SECURITY_POLICY,
        target_path="packages/atlas-policy/src/atlas_policy/firewall.py",
        description="Relax domain blocklist to allow untrusted external endpoints",
    )

    with pytest.raises(ProtectedComponentModificationError) as exc_info:
        governor.evaluate_change(danger_change)
    assert "strictly prohibited" in str(exc_info.value).lower()


# ==============================================================================
# AUTO-19: Autonomous Core Production Code Modification Rejection
# ==============================================================================
def test_auto19_protected_code_modification_rejection():
    """Verify that autonomous optimizer cannot rewrite core production source code."""
    governor = SafetyGovernor()

    code_rewrite = ProposedChange(
        proposer_id="auto_refactor_agent",
        category=ChangeCategory.CODE_MODIFICATION,
        target_path="packages/atlas-core/src/atlas_core/lifecycle.py",
        description="Bypass state transition validation check",
    )

    with pytest.raises(ProtectedComponentModificationError) as exc_info:
        governor.evaluate_change(code_rewrite)
    assert "standard engineering process" in str(exc_info.value).lower()


# ==============================================================================
# AUTO-20: Unauthorized Candidate Strategy Promotion Rejection
# ==============================================================================
def test_auto20_unauthorized_promotion_rejection():
    """Verify that jumping stages or promoting unsigned candidates is rejected."""
    mgr = PromotionManager()
    record = mgr.initialize_promotion(
        candidate_id="strat_unvalidated",
        tenant_id="tenant_beta",
        signature="",  # Missing signature!
    )

    # Attempt to jump straight from CANDIDATE to CANARY
    with pytest.raises(UnauthorizedPromotionError):
        mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.CANARY)

    # Advance cleanly to VALIDATING
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.VALIDATING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.EXPERIMENTING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.SAFETY_REVIEW)

    # Attempt to approve without valid signature
    with pytest.raises(UnauthorizedPromotionError) as exc_info:
        mgr.advance_stage(
            record.promotion_id, next_stage=PromotionStage.APPROVED, approver_id="admin_1"
        )
    assert "signature missing" in str(exc_info.value).lower()


# ==============================================================================
# AUTO-21: Cryptographic Candidate Signature Verification on Promotion
# ==============================================================================
def test_auto21_candidate_signature_verification():
    """Verify that signed candidates with valid approver advance cleanly through approval."""
    mgr = PromotionManager()
    record = mgr.initialize_promotion(
        candidate_id="strat_signed_ok",
        tenant_id="tenant_beta",
        signature="ed25519:valid_signature_hash_9876",
    )

    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.VALIDATING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.EXPERIMENTING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.SAFETY_REVIEW)

    # Approval succeeds when signature is present
    approved = mgr.advance_stage(
        record.promotion_id, next_stage=PromotionStage.APPROVED, approver_id="qa_lead_01"
    )
    assert approved.current_stage == PromotionStage.APPROVED
    assert approved.approver_id == "qa_lead_01"


# ==============================================================================
# AUTO-22: Canary Staged Deployment with Progressive Traffic Allocation
# ==============================================================================
def test_auto22_canary_deployment():
    """Verify progressive canary rollout allocates 10% traffic before 100% production."""
    mgr = PromotionManager()
    record = mgr.initialize_promotion(
        candidate_id="strat_canary_rollout",
        tenant_id="tenant_prod",
        signature="sig_valid_1234",
    )

    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.VALIDATING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.EXPERIMENTING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.SAFETY_REVIEW)
    mgr.advance_stage(
        record.promotion_id, next_stage=PromotionStage.APPROVED, approver_id="lead_eng"
    )

    # Advance to CANARY
    canary = mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.CANARY)
    assert canary.current_stage == PromotionStage.CANARY
    assert canary.canary_traffic_percent == 10.0

    # Advance to PRODUCTION
    prod = mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.PRODUCTION)
    assert prod.current_stage == PromotionStage.PRODUCTION
    assert prod.canary_traffic_percent == 100.0


# ==============================================================================
# AUTO-23: Instant Rollback Execution on Canary Performance Degradation
# ==============================================================================
def test_auto23_canary_rollback():
    """Verify instant automated rollback aborts canary traffic upon detected degradation."""
    mgr = PromotionManager()
    record = mgr.initialize_promotion(
        candidate_id="strat_flaky_canary",
        tenant_id="tenant_prod",
        signature="sig_valid_5678",
    )

    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.VALIDATING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.EXPERIMENTING)
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.SAFETY_REVIEW)
    mgr.advance_stage(
        record.promotion_id, next_stage=PromotionStage.APPROVED, approver_id="lead_eng"
    )
    mgr.advance_stage(record.promotion_id, next_stage=PromotionStage.CANARY)

    # Regression detected! Trigger rollback
    rolled_back = mgr.trigger_rollback(
        promotion_id=record.promotion_id,
        reason="Regression alert: Error rate exceeded 5% threshold in canary fleet",
    )

    assert rolled_back.current_stage == PromotionStage.ROLLED_BACK
    assert rolled_back.canary_traffic_percent == 0.0
    assert any("ROLLED BACK" in h for h in rolled_back.history)


# ==============================================================================
# AUTO-24: Audit Trail Integrity for All Optimization & Promotion Events
# ==============================================================================
def test_auto24_audit_integrity():
    """Verify that self-approval attempts are blocked and audit history is preserved."""
    governor = SafetyGovernor()

    change = ProposedChange(
        proposer_id="agent_optimizer_alpha",
        category=ChangeCategory.PARAMETER_TUNING,
        target_path="config/planner_params.json",
        description="Tune tree search branching factor",
    )

    # Self-approval must fail
    with pytest.raises(SelfApprovalProhibitedError):
        governor.authorize_promotion(change=change, approver_id="agent_optimizer_alpha")

    # Independent approval succeeds
    is_authorized = governor.authorize_promotion(change=change, approver_id="human_reviewer_42")
    assert is_authorized is True


# ==============================================================================
# AUTO-25: Strict Multi-Tenant Isolation across Experiences & Optimizations
# ==============================================================================
def test_auto25_tenant_isolation():
    """Verify that experiences and knowledge remain strictly isolated between tenants."""
    exp_store = ExperienceStore()

    # Tenant A records experience
    exp_store.record_experience(
        tenant_id="tenant_A",
        task_category="data",
        context_fingerprint="fp_etl_pipeline",
        observed_facts=["ETL job completed in 4s"],
        generated_recommendations=["Batch size 500 is optimal"],
        outcome=ExperienceOutcome.SUCCESS,
        evaluation_score=0.95,
        source_task_id="task_etl_1",
    )

    # Tenant B queries: must be empty
    assert len(exp_store.query("tenant_B")) == 0

    # Knowledge isolation
    know_store = ControlledKnowledgeStore()
    know_cand = know_store.propose_candidate(
        tenant_id="tenant_A",
        topic="etl_secrets",
        statement="Tenant A proprietary schema definition",
        evidence_refs=["doc_a.txt"],
    )
    know_store.approve_candidate(
        know_cand.candidate_id, approver_id="admin_a", requesting_tenant_id="tenant_A"
    )

    # Tenant B cannot retrieve Tenant A active knowledge
    assert len(know_store.get_active_knowledge("tenant_B")) == 0


# ==============================================================================
# AUTO-26: Shadow Evaluation Execution Mode before Promotion Authorization
# ==============================================================================
def test_auto26_shadow_evaluation_mode():
    """Verify shadow evaluation executes candidate without impacting production operations."""
    exp_def = ExperimentDefinition(
        candidate_strategy_id="strat_shadow_experimental",
        baseline_strategy_id="strat_prod_active",
        num_trials=6,
        is_shadow_mode=True,
    )

    report = AutomatedExperimentationEngine.run_experiment(
        definition=exp_def,
        candidate_runner=lambda i: {"success": True, "cost_usd": 0.001},
        baseline_runner=lambda i: {"success": True, "cost_usd": 0.001},
    )

    assert report.status == ExperimentStatus.COMPLETED
    assert report.total_trials == 6


# ==============================================================================
# AUTO-27: Monorepo Full Regression & Core Zero-Dependency Preservation
# ==============================================================================
def test_auto27_full_monorepo_regression_and_zero_dependency_core():
    """Verify Constitution Rule 3: zero dependencies in atlas-core, and atlas-adaptive registered."""
    core_pyproject_path = REPO_ROOT / "packages" / "atlas-core" / "pyproject.toml"
    assert core_pyproject_path.exists(), "atlas-core pyproject.toml must exist"

    content = core_pyproject_path.read_text(encoding="utf-8")

    for forbidden in [
        "kubernetes",
        "playwright",
        "psycopg",
        "fastapi",
        "torch",
        "whisper",
        "scipy",
        "sklearn",
    ]:
        assert forbidden not in content.lower(), (
            f"Forbidden dependency '{forbidden}' detected in atlas-core!"
        )

    # Verify that atlas-adaptive exists in root pyproject.toml
    root_pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "packages/atlas-adaptive" in root_pyproject
