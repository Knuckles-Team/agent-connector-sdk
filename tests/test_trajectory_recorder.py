"""Recorder uses the pinned generated operations, not a local engine substitute."""

from __future__ import annotations

from typing import Any

import pytest
from epistemic_graph.generated import models

from agent_connector_sdk.writeback import (
    TrajectoryRecorder,
    TrajectoryStep,
    TrajectoryWriteUncertainError,
)


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    async def _send(
        self,
        method: str,
        params: dict[str, Any],
        graph: str | None,
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        self.calls.append((method, params, graph))
        return {
            "StartTrajectory": "traj-1",
            "AppendStep": "ok",
            "DiscountedReturn": 1.5,
            "BestTrajectory": "traj-1",
            "DsGrpoSurrogate": {"grad": [0.1], "loss": 0.2},
            "DsDpoLoss": {"grad_chosen": [0.1], "grad_rejected": [-0.1], "loss": 0.3},
            "MineText": {
                "doc_terms": [],
                "doc_topics": [],
                "n_docs": 0,
                "topics": [],
                "written_back": 0,
            },
        }[method]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R781.1")
async def test_trajectory_recorder_routes_generated_engine_calls() -> None:
    engine = _Engine()
    recorder = TrajectoryRecorder(engine, graph_name="training")
    trajectory = await recorder.record_one(
        b"props", (TrajectoryStep(0, b"action", 1.0), TrajectoryStep(1, b"next", 0.5))
    )
    assert trajectory == "traj-1"
    assert await recorder.discounted_return(trajectory, 0.9) == 1.5
    assert await recorder.best_trajectory([trajectory], 0.9) == trajectory
    grpo = models.MethodDsGrpoSurrogateParams(
        advantage=[1.0], clip_eps=0.2, logprob=[0.1], old_logprob=[0.0]
    )
    dpo = models.MethodDsDpoLossParams(
        beta=0.1,
        policy_chosen=[1.0],
        policy_rejected=[0.0],
        ref_chosen=[0.8],
        ref_rejected=[0.2],
    )
    assert (await recorder.grpo(grpo)).loss == 0.2
    assert (await recorder.dpo(dpo)).loss == 0.3
    assert (await recorder.mine_text(models.MethodMineTextParams(docs=[]))).n_docs == 0
    assert [method for method, _, _ in engine.calls] == [
        "StartTrajectory",
        "AppendStep",
        "AppendStep",
        "DiscountedReturn",
        "BestTrajectory",
        "DsGrpoSurrogate",
        "DsDpoLoss",
        "MineText",
    ]
    assert all(graph == "training" for _, _, graph in engine.calls)
    assert all(
        params["traj_id"] == trajectory
        for method, params, _ in engine.calls
        if method == "AppendStep"
    )
    assert engine.calls[5][1] == grpo.model_dump()
    assert engine.calls[6][1] == dpo.model_dump()


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R781.1")
async def test_recorder_does_not_retry_an_uncertain_append() -> None:
    class FailingEngine(_Engine):
        async def _send(
            self,
            method: str,
            params: dict[str, Any],
            graph: str | None,
            *,
            idempotency_key: str | None = None,
        ) -> Any:
            if method == "AppendStep":
                self.calls.append((method, params, graph))
                raise TimeoutError("unknown engine outcome")
            return await super()._send(
                method, params, graph, idempotency_key=idempotency_key
            )

    engine = FailingEngine()
    with pytest.raises(TrajectoryWriteUncertainError) as exc:
        await TrajectoryRecorder(engine).record_one(
            b"props", (TrajectoryStep(0, b"action", 1.0),)
        )
    assert exc.value.trajectory_id == "traj-1"
    assert [method for method, _, _ in engine.calls] == [
        "StartTrajectory",
        "AppendStep",
    ]
