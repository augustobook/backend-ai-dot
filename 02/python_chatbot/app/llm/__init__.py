"""LLM layer: prompts, conversation history storage and the LCEL chain."""

import warnings

# Since langchain-core 1.6, `RunnableWithMessageHistory` and
# `InMemoryChatMessageHistory` emit a deprecation warning recommending LangGraph
# persistence. The project requirements ask for exactly these classes, they work
# as expected, and langchain-core is pinned below 2.0 (where they will be
# removed) in pyproject.toml. Only these two known warnings are silenced; any
# other deprecation is still reported.
warnings.filterwarnings(
    "ignore", message="RunnableWithMessageHistory is deprecated", category=DeprecationWarning
)
warnings.filterwarnings(
    "ignore",
    message="The class `InMemoryChatMessageHistory` was deprecated",
    category=DeprecationWarning,
)
