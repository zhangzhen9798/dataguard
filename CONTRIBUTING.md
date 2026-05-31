# Contributing to DataGuard

First off, thank you for considering contributing to DataGuard! 🎉

## How to Contribute

### Report Bugs

- Open an issue on [GitHub Issues](https://github.com/zhangzhen9798/dataguard/issues)
- Include: Python version, OS, steps to reproduce, expected vs actual behavior

### Suggest Features

- Open an issue with the `enhancement` label
- Describe the use case and expected behavior

### Submit Code

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass: `pytest`
6. Commit with a descriptive message
7. Push and open a Pull Request

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/dataguard.git
cd dataguard

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black dataguard tests
ruff check dataguard tests
```

### Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Use [Black](https://github.com/psf/black) for formatting
- Use [Ruff](https://github.com/astral-sh/ruff) for linting
- Add type hints for public APIs

### Commit Messages

- Use present tense: "Add feature" not "Added feature"
- Be descriptive but concise

## Code of Conduct

Be respectful and constructive. We're all here to make DataGuard better.
