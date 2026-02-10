# Contributing

Thanks for your interest in contributing! Here's how to get started.

## Development setup

```bash
git clone https://github.com/your-org/mkdocs-cdoc.git
cd mkdocs-cdoc
pip install -e ".[dev]"
```

For full clang-based parsing, install libclang:

```bash
# Ubuntu/Debian
sudo apt install python3-clang libclang-dev

# macOS
brew install llvm
pip install clang
```

## Running tests

```bash
pytest tests/ -v
```

## Code style

This project uses **Black** for formatting, **flake8** for linting, and **pylint** for static analysis.

```bash
black mkdocs_cdoc/ tests/
flake8 mkdocs_cdoc/ --max-line-length=120
pylint mkdocs_cdoc/
```

## Building the example docs

The `example/` directory contains a sample MkDocs project you can use to test changes:

```bash
cd example
pip install -e ..
mkdocs build    # or: mkdocs serve
```

## Pull requests

1. Fork the repo and create a feature branch.
2. Make your changes with tests where appropriate.
3. Run the full test suite and linting.
4. Open a PR with a clear description of what changed and why.
