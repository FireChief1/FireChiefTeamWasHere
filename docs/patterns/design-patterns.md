# Design Patterns

This document covers design patterns used in the project. The goal is not to apply every pattern but to recognize when a pattern fits the problem.

## Don't Over-Engineer

**Rule:** Apply patterns when they solve a real problem, not preemptively. A simple function is better than a needless class hierarchy.

**Why:** Premature abstraction is the root of much complexity. Three similar lines are better than a half-baked abstraction that locks in the wrong design.

**Bad (over-engineered):**
```python
class Greeter:
    def __init__(self, greeting: str = "Hello"):
        self.greeting = greeting

    def greet(self, name: str) -> str:
        return f"{self.greeting}, {name}!"


class GreeterFactory:
    @staticmethod
    def create_greeter(language: str) -> Greeter:
        return Greeter(greeting={"en": "Hello", "tr": "Merhaba"}[language])


greeter = GreeterFactory.create_greeter("en")
print(greeter.greet("Alice"))
```

**Good:**
```python
def greet(name: str, language: str = "en") -> str:
    greetings = {"en": "Hello", "tr": "Merhaba"}
    return f"{greetings[language]}, {name}!"


print(greet("Alice"))
```

## Factory Pattern

**When to use:** Object creation logic is complex, varies by input, or needs to be centralized.

**Good (LLM client factory):**
```python
def create_llm_client(node: LLMNode) -> ChatOllama:
    return ChatOllama(
        model=node.model,
        base_url=node.base_url,
        temperature=0.2,
        timeout=120,
    )


# usage
pc1_client = create_llm_client(node_pc1)
pc2_client = create_llm_client(node_pc2)
```

## Strategy Pattern

**When to use:** A class has multiple interchangeable algorithms. You want to swap them at runtime without modifying the class.

**Good (routing strategies):**
```python
from typing import Protocol


class RoutingStrategy(Protocol):
    def pick(self, nodes: list[LLMNode], request: Request) -> LLMNode: ...


class RoundRobinStrategy:
    def __init__(self):
        self._index = 0

    def pick(self, nodes: list[LLMNode], request: Request) -> LLMNode:
        node = nodes[self._index % len(nodes)]
        self._index += 1
        return node


class CapabilityAwareStrategy:
    def pick(self, nodes: list[LLMNode], request: Request) -> LLMNode:
        return next(n for n in nodes if n.capability == request.capability)


class LLMPool:
    def __init__(self, strategy: RoutingStrategy, nodes: list[LLMNode]):
        self.strategy = strategy
        self.nodes = nodes

    def get_node(self, request: Request) -> LLMNode:
        return self.strategy.pick(self.nodes, request)
```

## Observer Pattern (Event-Driven)

**When to use:** Multiple components need to react to events without tight coupling.

**Good:**
```python
from collections.abc import Callable

class EventBus:
    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}

    def subscribe(self, event: str, handler: Callable) -> None:
        self._listeners.setdefault(event, []).append(handler)

    def publish(self, event: str, payload: dict) -> None:
        for handler in self._listeners.get(event, []):
            handler(payload)


bus = EventBus()
bus.subscribe("agent_finished", lambda p: logger.info(f"agent done: {p['agent']}"))
bus.subscribe("agent_finished", lambda p: metrics.record(p))

# anywhere an agent finishes:
bus.publish("agent_finished", {"agent": "developer", "duration_ms": 1234})
```

## Dependency Injection

**Rule:** Pass dependencies into classes and functions explicitly rather than constructing them inside.

**Why:** Injectable dependencies are testable (you can pass mocks). They also make the dependency graph visible.

**Good:**
```python
class Developer:
    def __init__(self, llm_pool: LLMPool, rag_retriever: RAGRetriever):
        self.llm_pool = llm_pool
        self.rag_retriever = rag_retriever

    async def generate(self, task: str) -> str:
        context = await self.rag_retriever.search(task, k=5)
        return await self.llm_pool.generate(
            f"Task: {task}\nContext: {context}",
            capability=Capability.CODER,
        )


# easy to test:
def test_developer_uses_rag_context():
    mock_pool = MockLLMPool()
    mock_rag = MockRAGRetriever()
    developer = Developer(mock_pool, mock_rag)
    ...
```

**Bad:**
```python
class Developer:
    def __init__(self):
        self.llm_pool = LLMPool(...)  # hardcoded dependency
        self.rag_retriever = RAGRetriever(...)  # hardcoded

    # impossible to test in isolation
```

## Singleton (Use Sparingly)

**When to use:** A resource is genuinely global and expensive (HTTP client, database connection pool, configuration).

**Rule:** Implement as a module-level instance, not via metaclass tricks.

**Why:** Module-level singletons are explicit and easy to override in tests.

**Good:**
```python
# llm/pool.py
_pool: LLMPool | None = None


def get_pool() -> LLMPool:
    global _pool
    if _pool is None:
        _pool = LLMPool(nodes=load_node_config())
    return _pool


def set_pool(pool: LLMPool) -> None:  # for tests
    global _pool
    _pool = pool
```

**Bad:**
```python
class LLMPool:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    # implicit, hard to test, hard to reason about
```

## Repository Pattern

**When to use:** You want to decouple business logic from data persistence.

**Good:**
```python
from typing import Protocol


class UserRepository(Protocol):
    async def get(self, user_id: int) -> User | None: ...
    async def save(self, user: User) -> None: ...


class SqlUserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def save(self, user: User) -> None:
        self.session.add(user)
        await self.session.commit()


class InMemoryUserRepository:
    """Used in tests."""
    def __init__(self):
        self._store: dict[int, User] = {}

    async def get(self, user_id: int) -> User | None:
        return self._store.get(user_id)

    async def save(self, user: User) -> None:
        self._store[user.id] = user
```

## State Machine

**When to use:** An object has well-defined states with restricted transitions. Common in workflow orchestration.

**Good (agent state machine via LangGraph):**
```python
from langgraph.graph import StateGraph, END

graph = StateGraph(AgentState)
graph.add_node("analyst", analyst_node)
graph.add_node("developer", developer_node)
graph.add_node("reviewer", reviewer_node)
graph.add_node("qa", qa_node)
graph.add_node("supervisor", supervisor_node)

graph.set_entry_point("analyst")
graph.add_edge("analyst", "developer")
graph.add_conditional_edges(
    "supervisor",
    decide_next,
    {
        "developer": "developer",  # loop back
        "end": END,
    },
)
```

## Decorator Pattern

**When to use:** You want to add behavior to a function or class without modifying it.

**Good (timing decorator):**
```python
import functools
import time
from collections.abc import Callable


def timed(label: str | None = None):
    def decorator(func: Callable) -> Callable:
        name = label or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed = (time.monotonic() - start) * 1000
                logger.info(f"{name} took {elapsed:.1f}ms")

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = (time.monotonic() - start) * 1000
                logger.info(f"{name} took {elapsed:.1f}ms")

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


@timed()
async def fetch_user(user_id: int) -> User: ...
```

## Builder Pattern

**When to use:** Constructing objects with many optional parameters or step-by-step configuration.

**Good:**
```python
class WorkflowBuilder:
    def __init__(self):
        self._nodes: list[Node] = []
        self._edges: list[Edge] = []
        self._entry: str | None = None

    def add_agent(self, name: str, agent: Agent) -> "WorkflowBuilder":
        self._nodes.append(Node(name, agent))
        return self

    def connect(self, from_name: str, to_name: str) -> "WorkflowBuilder":
        self._edges.append(Edge(from_name, to_name))
        return self

    def entry(self, name: str) -> "WorkflowBuilder":
        self._entry = name
        return self

    def build(self) -> Workflow:
        if self._entry is None:
            raise ValueError("entry point not set")
        return Workflow(self._nodes, self._edges, self._entry)


workflow = (
    WorkflowBuilder()
    .add_agent("analyst", analyst_agent)
    .add_agent("developer", developer_agent)
    .connect("analyst", "developer")
    .entry("analyst")
    .build()
)
```

## Chain of Responsibility

**When to use:** A request must be processed by one of several handlers, each deciding whether to act or pass it along.

**Good (validation chain):**
```python
from typing import Protocol


class Validator(Protocol):
    def validate(self, value: str) -> str | None:
        """Return error message or None if valid."""


def chain(validators: list[Validator], value: str) -> list[str]:
    return [err for v in validators if (err := v.validate(value)) is not None]


errors = chain(
    [LengthValidator(min=1, max=100), EmailFormatValidator(), DomainValidator()],
    user_email,
)
if errors:
    raise ValidationError(errors)
```

## Anti-Pattern: God Object

**Symptom:** One class does everything: configuration, business logic, persistence, UI.

**Why it hurts:** Hard to test, hard to change, every bug touches it.

**Fix:** Split by responsibility. Each class should have one reason to change.

## Anti-Pattern: Stringly-Typed APIs

**Symptom:** Functions accept magic strings instead of enums or types.

**Why it hurts:** Typos pass type checks. Renames silently break callers.

**Bad:**
```python
def set_status(status: str) -> None:
    if status in ("pending", "active", "deleted"):
        ...

set_status("activ")  # typo, runtime error far away
```

**Good:**
```python
from enum import Enum

class Status(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DELETED = "deleted"


def set_status(status: Status) -> None: ...


set_status(Status.ACTIVE)
```
