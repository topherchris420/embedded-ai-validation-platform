# CI/CD Module

GitHub Actions workflows for automated testing and validation.

## Workflows

### Main CI Pipeline

```bash
# Triggered on: push, pull_request
# Jobs:
#   - lint: Code quality checks
#   - test: Unit tests
#   - build-firmware: Compile all firmware
#   - integration: Integration tests
```

### Firmware Build

```bash
# Triggered on: push to firmware/
# Jobs:
#   - esp32: PlatformIO build
#   - stm32: PlatformIO build
#   - rpi-pico: PlatformIO build
```

### Benchmark Regression

```bash
# Triggered on: push to main
# Runs benchmarks and compares with baseline
# Posts results as PR comment
```

## Workflow Files

```
ci/
├── workflows/
│   ├── ci.yml           # Main CI pipeline
│   ├── firmware.yml     # Firmware builds
│   ├── benchmarks.yml   # Benchmark runs
│   ├── docs.yml         # Documentation builds
│   └──hil.yml          # Hardware-in-the-loop
├── scripts/
│   ├── build.sh        # Build script
│   ├── test.sh         # Test runner
│   └── benchmark.sh    # Benchmark runner
└── configs/
    └── ci-config.yml   # CI configuration
```

## Running Locally

```bash
# Run full CI locally
./ci/scripts/ci-local.sh

# Run specific job
./ci/scripts/test.sh

# Run with Docker
docker run --rm -v $(pwd):/workspace ghcr.io/eaiv/ci:latest
```

## Configuration

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run ruff
        run: ruff check .
      - name: Run mypy
        run: mypy src/
```

## Adding New Jobs

1. Add job to `.github/workflows/ci.yml`
2. Add script to `ci/scripts/`
3. Update this documentation

## Secrets

Required secrets for full CI:

- `PYPI_TOKEN` - For package publishing
- `CODECOV_TOKEN` - For coverage reports
- `SLACK_WEBHOOK` - For notifications