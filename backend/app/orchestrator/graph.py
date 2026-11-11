"""A small state-graph runner with the LangGraph call shape.

The production deployment swaps this module for `langgraph.graph.StateGraph`
(same add_node / add_conditional_edges / ainvoke surface). It is kept
dependency-free here so the whole pipeline runs offline, deterministically,
inside the hackathon sandbox.

Failure handling mirrors blueprint section 22: a checker that times out or
raises is recorded as missing, the review is marked partial and it can never
be treated as a passing review.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("brandsetgo.graph")

Node = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
END = "END"


class StateGraph:
    def __init__(self, name: str = "graph") -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}
        self.conditionals: dict[str, tuple[Callable[[dict], str], dict[str, str]]] = {}
        self.entry: str | None = None

    def add_node(self, name: str, fn: Node) -> "StateGraph":
        self.nodes[name] = fn
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges[src] = dst
        return self

    def add_conditional_edges(
        self, src: str, router: Callable[[dict], str], mapping: dict[str, str]
    ) -> "StateGraph":
        self.conditionals[src] = (router, mapping)
        return self

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        node = self.entry
        trace: list[str] = []
        guard = 0
        while node and node != END:
            guard += 1
            if guard > 50:
                raise RuntimeError("graph exceeded step budget")
            trace.append(node)
            state = await self.nodes[node](state)
            if node in self.conditionals:
                router, mapping = self.conditionals[node]
                node = mapping.get(router(state), END)
            else:
                node = self.edges.get(node, END)
        state["_trace"] = trace
        return state


async def fan_out(
    tasks: dict[str, Callable[[], Any]], timeout: float = 8.0
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run independent checkers concurrently; isolate failures per checker."""

    async def _run(name: str, fn: Callable[[], Any]) -> Any:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)

    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    names = list(tasks)
    outcomes = await asyncio.gather(
        *[_run(n, tasks[n]) for n in names], return_exceptions=True
    )
    for name, outcome in zip(names, outcomes):
        if isinstance(outcome, BaseException):
            errors[name] = f"{type(outcome).__name__}: {outcome}"
            log.warning("checker %s failed: %s", name, outcome)
        else:
            results[name] = outcome
    return results, errors
