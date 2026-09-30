"""Real node-level LangGraph orchestration over RepoPilot's shared transitions."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict

try:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:
    raise ValueError("LangGraph runtime requires: pip install -e '.[langgraph]' (from the RepoPilot checkout)") from exc

from repopilot.agent.agent import FinalAction, parse_action
from repopilot.agent.state import AgentState

if TYPE_CHECKING:
    from repopilot.agent.agent import RepoPilot


class GraphState(TypedDict):
    """JSON-compatible snapshots; no tools, model clients or credentials are serialized."""
    agent: dict
    mapped: str
    relevant: list[tuple[str, int]]
    action: dict | None
    route: str


class LangGraphRuntime:
    """Run one shared transition per node, with conditional and bounded feedback edges.

    InMemorySaver supports node-level inspection/resume within this process. The
    shared SessionStore is the cross-process bridge, resuming at the next decision.
    Neither mechanism promises exactly-once tool execution after a process crash.
    """

    def __init__(self, owner: RepoPilot):
        self.owner = owner
        self.checkpointer = InMemorySaver()
        builder = StateGraph(GraphState)
        for name in ("prepare_repo_context", "plan", "agent_decide", "tool_execute", "verify", "finalize"):
            builder.add_node(name, self._node(name))
        builder.add_edge(START, "prepare_repo_context")
        for source, destinations in {
            "prepare_repo_context": ["plan", "finalize"],
            "plan": ["agent_decide", "finalize"],
            "agent_decide": ["tool_execute", "verify", "finalize"],
            "tool_execute": ["agent_decide", "verify", "finalize"],
            "verify": ["agent_decide", "finalize"],
        }.items():
            builder.add_conditional_edges(source, lambda state: state["route"],
                                          {name: name for name in destinations})
        builder.add_edge("finalize", END)
        self.graph = builder.compile(checkpointer=self.checkpointer)

    @staticmethod
    def input(state: AgentState) -> GraphState:
        """Create graph input for a new invocation or the JSON session bridge."""
        return {"agent": state.model_dump(mode="json"), "mapped": "", "relevant": [],
                "action": None, "route": "plan"}

    def config(self, state: AgentState) -> dict:
        """Bound node transitions independently of the shared decision-step budget."""
        return {"configurable": {"thread_id": state.id},
                "recursion_limit": self.owner.settings.max_steps * 3 + 10}

    def _node(self, name: str):
        def transition(snapshot: GraphState) -> dict:
            state = AgentState.model_validate(snapshot["agent"])
            mapped, relevant = snapshot["mapped"], snapshot["relevant"]
            action = parse_action(json.dumps(snapshot["action"])) if snapshot["action"] else None
            route = "finalize"
            try:
                if name == "prepare_repo_context":
                    mapped, relevant = self.owner._prepare_context(state)
                    route = "plan"
                elif name == "plan":
                    self.owner._plan(state, mapped, relevant)
                    route = "agent_decide"
                elif name == "agent_decide":
                    action = self.owner._decide(state, mapped, relevant)
                    route = ("verify" if isinstance(action, FinalAction) else "tool_execute") if action else "finalize"
                elif name == "tool_execute":
                    route, action = self.owner._tool_step(state, action)
                elif name == "verify":
                    route = "finalize" if self.owner._verify(state) else "agent_decide"
                elif name == "finalize":
                    self.owner._finalize(state, action)
            except Exception as exc:
                self.owner._fail(state, exc)
            self.owner.store.save(state)
            return {"agent": state.model_dump(mode="json"), "mapped": mapped,
                    "relevant": relevant, "action": action.model_dump() if action else None, "route": route}
        transition.__name__ = name
        return transition

    def run(self, state: AgentState) -> AgentState:
        """Execute the compiled graph; retain the latest state if orchestration fails."""
        for snapshot in self.graph.stream(self.input(state), self.config(state), stream_mode="values"):
            current = AgentState.model_validate(snapshot["agent"])
            state.__dict__.update(current.__dict__)
        return state
