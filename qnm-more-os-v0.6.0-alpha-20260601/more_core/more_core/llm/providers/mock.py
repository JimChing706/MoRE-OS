"""Mock LLM provider for development/testing when no real provider is configured.

Returns structured, deterministic responses based on prompt content.
Useful for testing iteration flows, output creation, and UI without real LLM backends.
"""

from __future__ import annotations

import time
from typing import AsyncIterator

from ..provider import LLMProvider, LLMRequest, LLMResponse


class MockProvider(LLMProvider):
    """Deterministic mock provider that generates plausible responses."""

    name = "mock"
    model = "mock-dev-1.0"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        content = self._generate_response(request)
        latency_ms = (time.perf_counter() - start) * 1000
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            prompt_tokens=len(request.prompt) // 4,
            completion_tokens=len(content) // 4,
            latency_ms=latency_ms,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        content = self._generate_response(request)
        for chunk in content.split(" "):
            yield chunk + " "

    async def health(self) -> bool:
        return True

    def _generate_response(self, request: LLMRequest) -> str:
        prompt = request.prompt.lower()
        
        # Code improvement patterns
        if any(kw in prompt for kw in ["improve", "iterate", "add type", "error handling"]):
            return self._generate_improved_code(request.prompt)
        
        # Code generation patterns
        if any(kw in prompt for kw in ["generate", "create", "write", "implement"]):
            return self._generate_code(request.prompt)
        
        # Default response
        return self._default_response(request.prompt)

    def _generate_improved_code(self, original: str) -> str:
        """Generate improved code with type hints and error handling."""
        return '''Here is the improved version with type annotations and error handling:

```python
from typing import Union

def calculate_sum(a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
    """Calculate the sum of two numbers with type validation.
    
    Args:
        a: First number (int or float)
        b: Second number (int or float)
        
    Returns:
        Sum of a and b
        
    Raises:
        TypeError: If inputs are not numbers
    """
    if not isinstance(a, (int, float)):
        raise TypeError(f"Expected int or float for 'a', got {type(a).__name__}")
    if not isinstance(b, (int, float)):
        raise TypeError(f"Expected int or float for 'b', got {type(b).__name__}")
    return a + b


def calculate_product(a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
    """Calculate the product of two numbers with type validation.
    
    Args:
        a: First number (int or float)
        b: Second number (int or float)
        
    Returns:
        Product of a and b
        
    Raises:
        TypeError: If inputs are not numbers
    """
    if not isinstance(a, (int, float)):
        raise TypeError(f"Expected int or float for 'a', got {type(a).__name__}")
    if not isinstance(b, (int, float)):
        raise TypeError(f"Expected int or float for 'b', got {type(b).__name__}")
    return a * b
```

## Unit Tests

```python
import pytest
from math_utils import calculate_sum, calculate_product

class TestCalculateSum:
    def test_integers(self):
        assert calculate_sum(3, 4) == 7
    
    def test_floats(self):
        assert calculate_sum(1.5, 2.5) == 4.0
    
    def test_negative(self):
        assert calculate_sum(-1, 1) == 0
    
    def test_type_error(self):
        with pytest.raises(TypeError):
            calculate_sum("3", 4)

class TestCalculateProduct:
    def test_integers(self):
        assert calculate_product(3, 4) == 12
    
    def test_floats(self):
        assert calculate_product(1.5, 2.0) == 3.0
    
    def test_zero(self):
        assert calculate_product(5, 0) == 0
    
    def test_type_error(self):
        with pytest.raises(TypeError):
            calculate_product("3", 4)
```

## Improvements Made

1. **Type Annotations**: Added `Union[int, float]` for parameters and return types
2. **Input Validation**: Added `isinstance` checks with descriptive `TypeError` messages
3. **Docstrings**: Enhanced with Args, Returns, and Raises sections
4. **Unit Tests**: Added comprehensive test coverage for both functions
5. **Edge Cases**: Tests for integers, floats, negatives, zeros, and type errors
'''

    def _generate_code(self, prompt: str) -> str:
        """Generate code based on prompt keywords."""
        if "hello" in prompt:
            return '''Here is the implementation:

```python
def greet(name: str = "World") -> str:
    """Generate a greeting message.
    
    Args:
        name: The name to greet (default: "World")
        
    Returns:
        A greeting string
    """
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet())
    print(greet("Developer"))
```

## Usage

Run the script directly:
```bash
python greet.py
```

Or import as a module:
```python
from greet import greet
message = greet("Alice")
print(message)  # Output: Hello, Alice!
```
'''
        return self._default_response(prompt)

    def _default_response(self, prompt: str) -> str:
        """Generate a default response for unmatched prompts."""
        snippet = prompt[:100]
        ellipsis = "..." if len(prompt) > 100 else ""
        return (
            "Based on your request, here is the generated output:\n\n"
            "## Analysis\n\n"
            f'Your prompt: "{snippet}{ellipsis}"\n\n'
            "## Generated Content\n\n"
            "```python\n"
            "# Generated implementation\n"
            "def process():\n"
            '    """Process the request based on the prompt."""\n'
            "    result = {\n"
            '        "status": "success",\n'
            '        "message": "Task completed successfully",\n'
            '        "details": "Generated by mock provider for development"\n'
            "    }\n"
            "    return result\n\n"
            'if __name__ == "__main__":\n'
            "    print(process())\n"
            "```\n\n"
            "## Notes\n\n"
            "- This is a development mock response\n"
            "- Configure a real LLM provider (LM Studio, Ollama, OpenAI, etc.) for production use\n"
            "- Set environment variables like `MORE_LMSTUDIO_ENDPOINT` or `MORE_OPENAI_API_KEY`\n"
        )


__all__ = ["MockProvider"]
