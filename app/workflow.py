from langgraph.graph import END, START, StateGraph

from app import agents, nodes
from app.log import logged
from app.state import ReviewState


def build_graph():
    g = StateGraph(ReviewState)

    g.add_node("safety", logged("safety", agents.safety_agent))
    g.add_node("analysis", logged("analysis", agents.code_analysis_agent))
    g.add_node("decision", logged("decision", agents.execution_decision))
    g.add_node("compile_test", logged("compile_test", nodes.compile_test_tool))
    g.add_node("review", logged("review", agents.review_agent))
    g.add_node("scoring", logged("scoring", nodes.deterministic_scoring))
    g.add_node("fix", logged("fix", agents.fix_agent))
    g.add_node("apply_fix", logged("apply_fix", nodes.apply_fix))
    g.add_node("accepted", logged("accepted", nodes.mark_accepted))
    g.add_node("human_review", logged("human_review", nodes.mark_human_review))
    g.add_node("rejected", logged("rejected", nodes.mark_rejected))
    g.add_node("max_iterations", logged("max_iterations", nodes.mark_max_iterations))

    g.add_edge(START, "safety")
    g.add_conditional_edges(
        "safety", nodes.route_after_safety, {"analysis": "analysis", "rejected": "rejected"}
    )
    g.add_edge("analysis", "decision")
    g.add_conditional_edges(
        "decision", nodes.route_after_decision, {"compile_test": "compile_test", "review": "review"}
    )
    g.add_edge("compile_test", "review")
    g.add_edge("review", "scoring")
    g.add_conditional_edges(
        "scoring",
        nodes.route_after_scoring,
        {
            "accepted": "accepted",
            "human_review": "human_review",
            "max_iterations": "max_iterations",
            "fix": "fix",
        },
    )
    # Fix loop: review -> scoring -> fix -> apply_fix -> compile_test -> review
    g.add_edge("fix", "apply_fix")
    g.add_conditional_edges(
        "apply_fix",
        nodes.route_after_apply,
        {"compile_test": "compile_test", "human_review": "human_review"},
    )

    for terminal in ("accepted", "rejected", "human_review", "max_iterations"):
        g.add_edge(terminal, END)

    return g.compile()
