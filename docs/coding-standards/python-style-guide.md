# Python Style Guide

This document defines the Python coding style conventions enforced across all code produced by agents in the system. The style is based on PEP 8 with project-specific extensions.

## Line Length

**Rule:** Maximum line length is **88 characters** (Black formatter default), not the PEP 8 default of 79.

**Why:** Modern displays handle 88 characters comfortably and reduce artificial line breaks that hurt readability.

**Good:**
```python
result = compute_aggregated_metrics(user_input, configuration_options, debug=False)
```

**Bad:**
```python
result = compute_aggregated_metrics(
    user_input, configuration_options, debug=False
)  # unnecessary wrap when line is under 88 chars
```

## Indentation

**Rule:** Use **4 spaces** per indentation level. Never use tabs. Never mix tabs and spaces.

**Why:** Consistent indentation prevents `IndentationError` and ensures code displays identically across editors.

**Good:**
```python
def calculate_total(items):
    total = 0
    for item in items:
        total += item.price
    return total
```

## Imports

**Rule:** Imports must follow this order, separated by blank lines:
1. Standard library imports
2. Related third-party imports
3. Local application/library imports

Each group must be sorted alphabetically.

**Why:** Predictable import order makes dependencies visible at a glance.

**Good:**
```python
import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.config import settings
from app.models import User
```

**Bad:**
```python
from app.models import User
import os
import httpx
import json
from app.config import settings
from pathlib import Path
from pydantic import BaseModel
```

## Avoid Wildcard Imports

**Rule:** Never use `from module import *`.

**Why:** Wildcard imports pollute the namespace and make it impossible to track where a name comes from. They break static analysis tools.

**Good:**
```python
from collections import defaultdict, OrderedDict
```

**Bad:**
```python
from collections import *
```

## Whitespace

**Rule:** Use whitespace consistently to enhance readability.

- Two blank lines between top-level functions and class definitions.
- One blank line between method definitions inside a class.
- No trailing whitespace on any line.
- Single space after commas and around operators.
- No space inside parentheses or brackets adjacent to content.

**Good:**
```python
def foo(a, b, c):
    return a + b + c


def bar(x, y):
    return foo(x, y, 0)


class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
```

**Bad:**
```python
def foo( a,b,c ):
    return a+b+c
def bar(x,y):
    return foo( x , y , 0 )
class Calculator:
    def add(self,a,b):
        return a+b
    def subtract(self,a,b):
        return a-b
```

## String Quotes

**Rule:** Use double quotes `"..."` for all strings unless the string contains double quotes itself.

**Why:** Consistent quote style (Black default) reduces noise in diffs and removes decision fatigue.

**Good:**
```python
name = "Alice"
greeting = "Hello, world!"
quoted = 'She said "hello"'
```

**Bad:**
```python
name = 'Alice'
greeting = 'Hello, world!'
```

## F-Strings Over Format

**Rule:** Use f-strings for string interpolation. Avoid `%` formatting and `.format()`.

**Why:** F-strings are more readable, faster, and harder to misuse.

**Good:**
```python
name = "Alice"
age = 30
message = f"{name} is {age} years old"
```

**Bad:**
```python
message = "%s is %d years old" % (name, age)
message = "{} is {} years old".format(name, age)
```

## Trailing Commas

**Rule:** Use trailing commas in multi-line collections, function arguments, and parameter lists.

**Why:** Trailing commas make diffs cleaner when adding new items and prevent syntax errors during refactoring.

**Good:**
```python
config = {
    "host": "localhost",
    "port": 11434,
    "timeout": 30,
}

def create_user(
    name: str,
    email: str,
    role: str = "user",
):
    ...
```

**Bad:**
```python
config = {
    "host": "localhost",
    "port": 11434,
    "timeout": 30
}
```

## Comparison Operators

**Rule:** Use `is` and `is not` only for comparisons to `None`, `True`, `False`, or other singletons. Use `==` and `!=` for value comparison.

**Why:** `is` checks identity (memory address), not equality. Using `is` for value comparison produces unreliable results.

**Good:**
```python
if user is None:
    raise ValueError("User required")

if status == "active":
    process(user)
```

**Bad:**
```python
if user == None:
    raise ValueError("User required")

if status is "active":  # CPython implementation detail, not guaranteed
    process(user)
```

## Avoid Mutable Default Arguments

**Rule:** Never use mutable objects (`list`, `dict`, `set`) as default function arguments.

**Why:** Default arguments are evaluated once at function definition time. A mutable default is shared across all calls, causing subtle bugs.

**Good:**
```python
def append_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
```

**Bad:**
```python
def append_item(item, items=[]):  # BUG: shared across all calls
    items.append(item)
    return items
```

## Boolean Comparisons

**Rule:** Do not compare boolean values to `True` or `False` with `==`. Use the value directly.

**Why:** Direct boolean usage is idiomatic and clearer.

**Good:**
```python
if is_active:
    process()

if not is_admin:
    raise PermissionError
```

**Bad:**
```python
if is_active == True:
    process()

if is_admin == False:
    raise PermissionError
```

## Constants

**Rule:** Module-level constants must be `UPPER_SNAKE_CASE` and declared at the top of the module.

**Why:** Visual distinction from variables. Signals immutability intent.

**Good:**
```python
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
API_BASE_URL = "https://api.example.com"


def fetch_with_retry(url):
    for _ in range(MAX_RETRIES):
        ...
```

## Tool Enforcement

The following tools enforce this style guide automatically:

- **Black** — code formatter (`black --line-length 88`)
- **Ruff** — fast linter (`ruff check`)
- **isort** — import sorter (handled by Ruff in this project)

Configuration lives in `pyproject.toml`. Code that fails these checks must not be merged.
