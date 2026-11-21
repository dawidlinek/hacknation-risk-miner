"""LLM layer (session L): gateway with sensitivity routing, quote + number verifier, tasks.

Public entry points:
    from riskminer.llm import LLMRequest, run, run_many
    from riskminer.llm.tasks.extract_features import extract_features, feature_items
    from riskminer.llm.tasks.redpen_scan import redpen_scan
"""
from riskminer.llm.gateway import LLMRequest, LLMResult, run, run_many  # noqa: F401
