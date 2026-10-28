"""Thin typed recorder over the engine's generated trajectory operations.

The engine owns storage, authorization and computation. This helper never
retries a write after an uncertain result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from epistemic_graph.generated import compute, graph, models

__all__ = ["TrajectoryRecorder", "TrajectoryStep", "TrajectoryWriteUncertainError"]


class TrajectoryWriteUncertainError(RuntimeError):
    """An append failed after trajectory creation; its state needs reconciliation."""

    def __init__(self, trajectory_id: str) -> None:
        self.trajectory_id = trajectory_id
        super().__init__("trajectory append outcome is uncertain")


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """One supplied action and reward in a recorded trajectory."""

    t: int
    action_msgpack: bytes
    reward: float
    state_ref: str | None = None
    next_state_ref: str | None = None


class TrajectoryRecorder:
    """Use the generated engine contract for trajectory and training operations."""

    def __init__(self, client: Any, *, graph_name: str | None = None) -> None:
        self._client = client
        self._graph = graph_name

    async def record_one(
        self, properties_msgpack: bytes, steps: Sequence[TrajectoryStep]
    ) -> str:
        """Start one trajectory and append supplied steps in order, without retry."""
        params = models.MethodStartTrajectoryParams(props_msgpack=properties_msgpack)
        prepared = tuple(
            models.MethodAppendStepParams(
                traj_id="preflight",
                t=step.t,
                action_msgpack=step.action_msgpack,
                reward=step.reward,
                state_ref=step.state_ref,
                next_state_ref=step.next_state_ref,
            )
            for step in steps
        )
        traj_id = await graph.send_start_trajectory(
            self._client, params.model_dump(), self._graph
        )
        for step in prepared:
            append = step.model_copy(update={"traj_id": traj_id})
            try:
                result = await graph.send_append_step(
                    self._client, append.model_dump(), self._graph
                )
                graph.decode_append_step(result)
            except Exception:
                raise TrajectoryWriteUncertainError(traj_id) from None
        return traj_id

    async def discounted_return(self, trajectory_id: str, gamma: float) -> float:
        """Read a discounted return from the engine."""
        params = models.MethodDiscountedReturnParams(traj_id=trajectory_id, gamma=gamma)
        return await graph.send_discounted_return(
            self._client, params.model_dump(), self._graph
        )

    async def best_trajectory(
        self, trajectory_ids: list[str], gamma: float
    ) -> str | None:
        """Read the engine's selected trajectory."""
        params = models.MethodBestTrajectoryParams(traj_ids=trajectory_ids, gamma=gamma)
        result = await graph.send_best_trajectory(
            self._client, params.model_dump(), self._graph
        )
        return graph.decode_best_trajectory(result)

    async def grpo(
        self, params: models.MethodDsGrpoSurrogateParams
    ) -> models.GrpoResult:
        """Pass a generated GRPO request through the engine."""
        result = await compute.send_ds_grpo_surrogate(
            self._client, params.model_dump(), self._graph
        )
        return compute.decode_ds_grpo_surrogate(result)

    async def dpo(self, params: models.MethodDsDpoLossParams) -> models.DpoResult:
        """Pass a generated DPO request through the engine."""
        result = await compute.send_ds_dpo_loss(
            self._client, params.model_dump(), self._graph
        )
        return compute.decode_ds_dpo_loss(result)

    async def mine_text(
        self, params: models.MethodMineTextParams
    ) -> models.TextMiningResult:
        """Pass a generated text-mining request through the engine."""
        result = await compute.send_mine_text(
            self._client, params.model_dump(exclude_none=True), self._graph
        )
        return compute.decode_mine_text(result)
