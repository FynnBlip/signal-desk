# -*- coding: utf-8 -*-
"""Typed HTTP contracts for the run-producing endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvaluateRunRequest(BaseModel):
    mode: Literal["comparison", "directory"] = "comparison"
    folder: str | None = None
    settings: dict[str, Any] | None = None


class ChannelRunRequest(BaseModel):
    input_wav: str = Field(min_length=1)
    noise_scenes: list[str] | None = None
    bandwidth: Literal["narrowband", "wideband", "superwideband", "fullband"] = "wideband"
    bitrate_kbps: int = Field(default=16, ge=6, le=128)
    cbr: bool = False
    seed: int = 42


class VoiceRegressionRequest(BaseModel):
    candidate_cohort_id: str
    baseline_cohort_id: str | None = None
    cluster: int = Field(ge=0, le=31)


class LoopRunRequest(BaseModel):
    force: bool = False


class LoopListenRequest(BaseModel):
    run_id: str
    stem: str
    pick: Literal["A", "B", "tie"]
    note: str = Field(default="", max_length=500)


class LoopApplyRequest(BaseModel):
    decision: dict[str, Any]
