"""ATLAS Process Simulation and Controlled Optimization Engine.

Enables safe, side-effect-free execution of process definitions against synthetic or historical
distributions to identify capacity constraints, predict SLA impacts, and compare workflow versions.
"""

from __future__ import annotations

import random

from pydantic import BaseModel

from atlas_process.definitions import ProcessDefinition


class SimulationResult(BaseModel):
    """Aggregate outcomes of a process simulation run."""

    definition_id: str
    version: str
    iterations: int
    avg_simulated_duration_seconds: float
    simulated_failure_rate: float
    simulated_bottleneck_task_id: str | None = None
    side_effects_triggered: int = 0  # Invariant: Must always be 0!


class ProcessSimulationEngine:
    """Executes synthetic, isolated process simulation runs with zero external side effects."""

    def simulate(
        self,
        definition: ProcessDefinition,
        iterations: int = 50,
        task_duration_distributions: dict[str, tuple[float, float]]
        | None = None,  # task_id -> (mean, std)
        task_failure_probabilities: dict[str, float] | None = None,  # task_id -> prob
    ) -> SimulationResult:
        """Execute Monte-Carlo simulations of process execution without triggering external mutations."""
        durations = task_duration_distributions or {}
        fail_probs = task_failure_probabilities or {}

        total_simulated_times: list[float] = []
        failure_count = 0
        task_cumulative_durations: dict[str, float] = {}

        for _ in range(iterations):
            run_time = 0.0
            run_failed = False

            # Simulate DAG tasks sequentially / in dependency order
            for task in definition.tasks:
                mean, std = durations.get(task.task_def_id, (10.0, 2.0))
                sim_dur = max(0.1, random.gauss(mean, std))
                run_time += sim_dur
                task_cumulative_durations[task.task_def_id] = (
                    task_cumulative_durations.get(task.task_def_id, 0.0) + sim_dur
                )

                prob_fail = fail_probs.get(task.task_def_id, 0.0)
                if random.random() < prob_fail:
                    run_failed = True
                    break

            total_simulated_times.append(run_time)
            if run_failed:
                failure_count += 1

        avg_duration = (
            sum(total_simulated_times) / len(total_simulated_times)
            if total_simulated_times
            else 0.0
        )
        sim_failure_rate = failure_count / iterations if iterations > 0 else 0.0

        bottleneck_task = (
            max(task_cumulative_durations.items(), key=lambda x: x[1])[0]
            if task_cumulative_durations
            else None
        )

        return SimulationResult(
            definition_id=definition.definition_id,
            version=definition.version,
            iterations=iterations,
            avg_simulated_duration_seconds=round(avg_duration, 2),
            simulated_failure_rate=round(sim_failure_rate, 4),
            simulated_bottleneck_task_id=bottleneck_task,
            side_effects_triggered=0,  # Zero side-effects guarantee
        )
