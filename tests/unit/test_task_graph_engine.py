"""Unit tests verifying TaskGraphEngine DAG validation, cycle detection, parallel dispatch, and failure cascading."""

import pytest
from atlas_core.contracts.graph import (
    DependencyType,
    NodeStatus,
    TaskGraph,
    TaskNode,
)
from atlas_orchestration.graph_engine import (
    CyclicDependencyError,
    NodeNotFoundError,
    TaskGraphEngine,
)


def test_dag_cycle_detection():
    """Verify that cyclic dependencies are detected and rejected with CyclicDependencyError."""
    # A -> B -> C -> A
    node_a = TaskNode(
        node_id="node_a",
        task_id="task_1",
        name="Node A",
        dependencies=["node_c"],  # Cycle!
    )
    node_b = TaskNode(
        node_id="node_b",
        task_id="task_1",
        name="Node B",
        dependencies=["node_a"],
    )
    node_c = TaskNode(
        node_id="node_c",
        task_id="task_1",
        name="Node C",
        dependencies=["node_b"],
    )

    graph = TaskGraph(
        graph_id="graph_cycle",
        task_id="task_1",
        nodes={"node_a": node_a, "node_b": node_b, "node_c": node_c},
    )

    with pytest.raises(CyclicDependencyError):
        TaskGraphEngine(graph)


def test_dag_missing_dependency_detection():
    """Verify references to non-existent parent nodes raise NodeNotFoundError."""
    node = TaskNode(
        node_id="node_1",
        task_id="task_1",
        name="Node 1",
        dependencies=["phantom_node"],
    )
    graph = TaskGraph(
        graph_id="graph_missing",
        task_id="task_1",
        nodes={"node_1": node},
    )

    with pytest.raises(NodeNotFoundError) as exc:
        TaskGraphEngine(graph)
    assert "phantom_node" in str(exc.value)


def test_topological_execution_batches():
    """Verify execution batches correctly group parallelizable branches."""
    #        root
    #       /    \
    #    branch1  branch2
    #       \    /
    #        join
    root = TaskNode(node_id="root", task_id="task_1", name="Root")
    b1 = TaskNode(node_id="b1", task_id="task_1", name="Branch 1", dependencies=["root"])
    b2 = TaskNode(node_id="b2", task_id="task_1", name="Branch 2", dependencies=["root"])
    join = TaskNode(node_id="join", task_id="task_1", name="Join", dependencies=["b1", "b2"])

    graph = TaskGraph(
        graph_id="graph_diamond",
        task_id="task_1",
        nodes={"root": root, "b1": b1, "b2": b2, "join": join},
    )

    engine = TaskGraphEngine(graph)
    batches = engine.get_execution_batches()

    assert len(batches) == 3
    assert batches[0] == ["root"]
    assert batches[1] == ["b1", "b2"]
    assert batches[2] == ["join"]


def test_dependency_readiness_and_state_progression():
    """Verify nodes transition to ready only when dependencies complete."""
    root = TaskNode(node_id="root", task_id="task_1", name="Root")
    child = TaskNode(node_id="child", task_id="task_1", name="Child", dependencies=["root"])

    graph = TaskGraph(
        graph_id="graph_seq",
        task_id="task_1",
        nodes={"root": root, "child": child},
    )
    engine = TaskGraphEngine(graph)

    # Initial ready nodes: only root
    ready = engine.get_ready_nodes()
    assert [n.node_id for n in ready] == ["root"]

    # Mark root running, then completed
    engine.mark_running("root", agent_id="agent_1")
    assert engine.is_node_ready("child") is False

    engine.mark_completed("root", output={"result": "data"})
    assert engine.is_node_ready("child") is True

    ready_after = engine.get_ready_nodes()
    assert [n.node_id for n in ready_after] == ["child"]


def test_failure_retry_and_cascading_cancellation():
    """Verify failing a node retries according to limit, and terminal failure cascades cancellation."""
    root = TaskNode(node_id="root", task_id="task_1", name="Root", retry_limit=1)
    child = TaskNode(node_id="child", task_id="task_1", name="Child", dependencies=["root"])
    grandchild = TaskNode(
        node_id="grandchild", task_id="task_1", name="Grandchild", dependencies=["child"]
    )

    graph = TaskGraph(
        graph_id="graph_cascade",
        task_id="task_1",
        nodes={"root": root, "child": child, "grandchild": grandchild},
    )
    engine = TaskGraphEngine(graph)

    engine.mark_running("root", agent_id="agent_1")

    # First failure -> retried
    engine.mark_failed("root", error="Transient timeout")
    assert graph.nodes["root"].status == NodeStatus.READY
    assert graph.nodes["root"].retry_count == 1

    # Re-run and fail again -> terminal failure
    engine.mark_running("root", agent_id="agent_1")
    engine.mark_failed("root", error="Permanent error")
    assert graph.nodes["root"].status == NodeStatus.FAILED

    # Downstream nodes automatically CANCELLED
    assert graph.nodes["child"].status == NodeStatus.CANCELLED
    assert "failed" in graph.nodes["child"].error.lower()
    assert graph.nodes["grandchild"].status == NodeStatus.CANCELLED

    progress = engine.get_progress()
    assert progress["failed"] == 1
    assert progress["cancelled"] == 2
    assert progress["has_failures"] is True


def test_conditional_branching_evaluation():
    """Verify conditional nodes evaluate parent output predicate."""
    parent = TaskNode(node_id="parent", task_id="task_1", name="Parent")
    cond_true = TaskNode(
        node_id="cond_true",
        task_id="task_1",
        name="Cond True",
        dependencies=["parent"],
        dependency_type=DependencyType.CONDITIONAL,
        condition_expr="output.get('status') == 'success'",
    )
    cond_false = TaskNode(
        node_id="cond_false",
        task_id="task_1",
        name="Cond False",
        dependencies=["parent"],
        dependency_type=DependencyType.CONDITIONAL,
        condition_expr="output.get('status') == 'error'",
    )

    graph = TaskGraph(
        graph_id="graph_cond",
        task_id="task_1",
        nodes={"parent": parent, "cond_true": cond_true, "cond_false": cond_false},
    )
    engine = TaskGraphEngine(graph)

    engine.mark_running("parent", agent_id="agent_1")
    engine.mark_completed("parent", output={"status": "success"})

    assert engine.is_node_ready("cond_true") is True
    assert engine.is_node_ready("cond_false") is False


def test_dynamic_replanning_increments_version():
    """Verify dynamically adding new nodes updates version and validates graph."""
    node_1 = TaskNode(node_id="node_1", task_id="task_1", name="Node 1")
    graph = TaskGraph(
        graph_id="graph_replan",
        task_id="task_1",
        nodes={"node_1": node_1},
    )
    engine = TaskGraphEngine(graph)
    assert graph.version == 1

    new_node = TaskNode(node_id="node_2", task_id="task_1", name="Node 2", dependencies=["node_1"])
    engine.replan([new_node])

    assert graph.version == 2
    assert "node_2" in graph.nodes
    assert len(engine.get_execution_batches()) == 2
