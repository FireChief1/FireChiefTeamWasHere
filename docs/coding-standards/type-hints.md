# Type Hints

All new Python code in this project must use type hints. Type hints are not optional. They are documentation, they enable static analysis with `mypy` or `pyright`, and they help LLM agents reason about code structure.

## When Type Hints Are Required

**Rule:** Type hints are required for:
- Every function parameter (except `self` and `cls`)
- Every function return type
- All module-level constants
- All class attributes (declared in `__init__` or as class variables)

**Why:** Partial typing creates blind spots. Full coverage lets static analysis catch real bugs before runtime.

## Basic Types

**Rule:** Use built-in types directly: `int`, `float`, `str`, `bool`, `bytes`, `list`, `dict`, `set`, `tuple`. Do not import from `typing` for these.

**Why:** Since Python 3.9, built-in generics are supported natively. Importing `List` from `typing` is legacy style.

**Good:**
```python
def count_words(text: str) -> dict[str, int]:
    words = text.split()
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    return counts
```

**Bad:**
```python
from typing import Dict, List

def count_words(text: str) -> Dict[str, int]:  # legacy style
    words: List[str] = text.split()
    ...
```

## Optional and Union Types

**Rule:** Use the `|` operator (PEP 604) for union types. Use `T | None` instead of `Optional[T]`.

**Why:** Pipe syntax is shorter, more readable, and the modern standard (Python 3.10+).

**Good:**
```python
def find_user(user_id: int) -> User | None:
    ...

def parse(value: int | str | bytes) -> ParsedValue:
    ...
```

**Bad:**
```python
from typing import Optional, Union

def find_user(user_id: int) -> Optional[User]:
    ...

def parse(value: Union[int, str, bytes]) -> ParsedValue:
    ...
```

## Generic Functions

**Rule:** Use `TypeVar` (or PEP 695 syntax in 3.12+) for generic functions and classes.

**Why:** Generics preserve type information across function boundaries.

**Good (PEP 695, Python 3.12+):**
```python
def first[T](items: list[T]) -> T:
    return items[0]

def safe_get[K, V](mapping: dict[K, V], key: K, default: V) -> V:
    return mapping.get(key, default)
```

**Good (pre-3.12):**
```python
from typing import TypeVar

T = TypeVar("T")

def first(items: list[T]) -> T:
    return items[0]
```

**Bad:**
```python
def first(items: list) -> object:  # loses type info
    return items[0]
```

## Callable

**Rule:** Use `Callable[[Arg1Type, Arg2Type], ReturnType]` from `collections.abc` for function-valued parameters.

**Why:** `Callable` documents the signature contract for callbacks and higher-order functions.

**Good:**
```python
from collections.abc import Callable

def apply_filter(items: list[int], predicate: Callable[[int], bool]) -> list[int]:
    return [item for item in items if predicate(item)]
```

**Bad:**
```python
def apply_filter(items, predicate):  # what does predicate take? return?
    return [item for item in items if predicate(item)]
```

## Iterable, Sequence, Mapping

**Rule:** For function parameters that only need to iterate or read, use abstract types from `collections.abc`: `Iterable`, `Sequence`, `Mapping`. For return types, use concrete types: `list`, `dict`.

**Why:** Accepting abstract types makes functions more flexible. Returning concrete types tells callers exactly what they get.

**Good:**
```python
from collections.abc import Iterable, Mapping

def sum_values(values: Iterable[int]) -> int:
    return sum(values)

def reverse_mapping(mapping: Mapping[str, int]) -> dict[int, str]:
    return {v: k for k, v in mapping.items()}
```

## TypedDict for Structured Dicts

**Rule:** When a dict has a fixed set of keys, use `TypedDict` instead of `dict[str, Any]`.

**Why:** `TypedDict` documents the shape and enables key validation by static checkers.

**Good:**
```python
from typing import TypedDict

class UserData(TypedDict):
    id: int
    email: str
    name: str
    is_active: bool

def serialize(user: User) -> UserData:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_active": user.is_active,
    }
```

**Bad:**
```python
def serialize(user: User) -> dict:  # what keys? what types?
    return {...}
```

## Pydantic for Validation

**Rule:** When data crosses a trust boundary (user input, API response, file parsing), validate it with Pydantic. Internal data structures with no validation needs can use `TypedDict` or `dataclass`.

**Why:** Pydantic combines type hints with runtime validation. Internal-only data does not need the overhead.

**Good (boundary):**
```python
from pydantic import BaseModel, EmailStr

class UserCreateRequest(BaseModel):
    email: EmailStr
    name: str
    age: int

@app.post("/users")
def create_user(request: UserCreateRequest) -> User:
    # request is validated at this point
    ...
```

**Good (internal):**
```python
from dataclasses import dataclass

@dataclass
class CacheEntry:
    key: str
    value: bytes
    expires_at: float
```

## Protocols for Duck Typing

**Rule:** When you need structural typing (duck typing with static checks), use `Protocol`.

**Why:** Protocols let you type "anything with a `.read()` method" without requiring inheritance.

**Good:**
```python
from typing import Protocol

class SupportsRead(Protocol):
    def read(self, size: int = -1) -> bytes:
        ...

def parse_stream(source: SupportsRead) -> Document:
    data = source.read()
    return Document.parse(data)

# Works with any file-like object: open(), io.BytesIO, network sockets, etc.
```

## Avoid `Any`

**Rule:** Avoid `Any` unless dealing with genuinely dynamic data and there is no better alternative. Use `object` for "any object, but check types before using".

**Why:** `Any` disables static analysis for that value. Every `Any` is a hole in your type coverage.

**Good:**
```python
from typing import Any
import json

def parse_json_field(raw: str, field: str) -> Any:  # genuinely dynamic
    return json.loads(raw)[field]

def log_event(payload: object) -> None:  # accepts anything, no operations
    logger.info("event", payload=str(payload))
```

**Bad:**
```python
def process(data: Any) -> Any:  # what does this take? return?
    return data["users"]
```

## Type Hint Class Attributes

**Rule:** Declare class attribute types either as class-level annotations or in `__init__`.

**Why:** Without annotations, attributes have no documented type and static checkers cannot help.

**Good (class-level):**
```python
class Service:
    name: str
    max_retries: int = 3
    _client: HTTPClient

    def __init__(self, name: str):
        self.name = name
        self._client = HTTPClient()
```

**Good (in `__init__`):**
```python
class Service:
    def __init__(self, name: str):
        self.name: str = name
        self.max_retries: int = 3
        self._client: HTTPClient = HTTPClient()
```

## Forward References

**Rule:** Use string forward references for types not yet defined in the file, or enable `from __future__ import annotations` at the top of the module.

**Why:** Avoids `NameError` for self-referential or circular types.

**Good (future annotations):**
```python
from __future__ import annotations

class Node:
    def __init__(self, value: int, next_node: Node | None = None):
        self.value = value
        self.next_node = next_node
```

**Good (string):**
```python
class Node:
    def __init__(self, value: int, next_node: "Node | None" = None):
        self.value = value
        self.next_node = next_node
```

## Static Analysis Tools

The project enforces type hints with:
- **mypy** — slower, more thorough
- **pyright** — fast, used in IDEs

Configuration in `pyproject.toml`. Type errors must be fixed before merging.
