"""Smoke tests — confirm the judge module imports and the heuristic path works
without any network or browser. Real Playwright/HTTP tests live in separate
files behind markers once Phase 1 lands.
"""

from __future__ import annotations

import json

import pytest

from foundry.config import FoundryConfig
from foundry.judge import HeuristicJudge, make_judge
from foundry.judge.clients import JUDGE_SYSTEM_PROMPT, _coerce_score_dict, _extract_json


def test_heuristic_returns_canonical_shape():
    j = HeuristicJudge()
    user = (
        "--- WIKIPEDIA GROUND TRUTH ---\n"
        "Kalman filters estimate state from noisy observations. "
        "They are recursive and use a prediction-update cycle.\n"
        "--- ELF CANDIDATE ---\n"
        "Kalman filters estimate state from noisy observations. They use "
        "a prediction step and a measurement update."
    )
    out = j.score(JUDGE_SYSTEM_PROMPT, user)
    for k in ("accuracy_score", "style_score", "overall_score", "critique"):
        assert k in out
    for k in ("accuracy_score", "style_score", "overall_score"):
        assert 0.0 <= out[k] <= 1.0
    assert "heuristic" in out["critique"].lower()


def test_heuristic_handles_empty_blocks():
    j = HeuristicJudge()
    out = j.score(JUDGE_SYSTEM_PROMPT, "no markers here just text")
    assert isinstance(out["overall_score"], float)


def test_make_judge_offline_falls_back_to_heuristic():
    cfg = FoundryConfig(
        anthropic_api_key=None,
        gemini_api_key=None,
        mercury_api_key=None,
        openai_api_key=None,
    )
    j = make_judge("claude", cfg)
    assert isinstance(j, HeuristicJudge)
    assert "fallback" in j.name


def test_make_judge_unknown_raises():
    cfg = FoundryConfig()
    with pytest.raises(Exception):
        make_judge("bogus-provider", cfg)


def test_extract_json_strips_fences():
    text = '```json\n{"accuracy_score": 0.5, "style_score": 0.6}\n```'
    parsed = _extract_json(text)
    assert parsed["accuracy_score"] == 0.5


def test_extract_json_finds_embedded_object():
    text = 'Reasoning: blah blah\n{"accuracy_score": 0.9, "style_score": 0.8}\nDone.'
    parsed = _extract_json(text)
    assert parsed["style_score"] == 0.8


def test_coerce_clamps_out_of_range():
    out = _coerce_score_dict({"accuracy_score": 1.7, "style_score": -0.4})
    assert out["accuracy_score"] == 1.0
    assert out["style_score"] == 0.0


def test_coerce_computes_overall_when_missing():
    out = _coerce_score_dict({"accuracy_score": 0.8, "style_score": 0.5})
    # 0.6 * 0.8 + 0.4 * 0.5 == 0.68
    assert abs(out["overall_score"] - 0.68) < 1e-6


def test_config_has_provider_logic():
    cfg = FoundryConfig(
        anthropic_api_key="sk-test",
        gemini_api_key=None,
    )
    assert cfg.has_provider("heuristic")
    assert cfg.has_provider("lmstudio")
    assert cfg.has_provider("claude")
    assert not cfg.has_provider("gemini")
    assert not cfg.has_provider("mercury")
