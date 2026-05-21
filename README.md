# Applied AI

Applied AI is a Python 3.12 project managed with
[uv](https://docs.astral.sh/uv/). The current app entry point is `main.py`.

## Project Layout

```text
.
|-- .python-version    # Python version pin for uv
|-- DockerFile         # Container build for running the app with uv
|-- main.py            # Application entry point
|-- pyproject.toml     # Project metadata and Python dependencies
`-- README.md          # Project guide
```

## Prerequisites

Install these tools before running the project locally:

- Python 3.12
- uv
- Docker, only if you want to build and run the container

Install uv on macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify the installation:

```bash
uv --version
python --version
```

## Local Setup

From the project root:

```bash
uv python install 3.12
uv python pin 3.12
uv sync
```

Run the application:

```bash
uv run python main.py
```

Expected output:

```text
Hello from applied-ai!
```

## Managing Dependencies

Use uv for Python dependencies:

```bash
uv add package-name
uv remove package-name
uv sync
```

After dependency changes, commit both `pyproject.toml` and `uv.lock`.

If `uv.lock` does not exist yet, generate it with:

```bash
uv lock
```

## System Dependencies

The Dockerfile currently installs these operating system packages:

- `ffmpeg`
- `libpq-dev`

Keep Python packages in `pyproject.toml`. Keep non-Python system packages in
the Dockerfile, and document any local install requirements here.

Ubuntu or Debian example:

```bash
sudo apt update
sudo apt install ffmpeg libpq-dev
```

macOS example:

```bash
brew install ffmpeg libpq
```

## Docker

The Docker build expects `uv.lock` to exist. Generate it before building:

```bash
uv lock
docker build -f DockerFile -t applied-ai .
```

Run the container:

```bash
docker run --rm applied-ai
```

Expected output:

```text
Hello from applied-ai!
```

## Development Workflow

Use this loop for normal development:

```bash
uv sync
uv run python main.py
```

When adding dependencies:

```bash
uv add package-name
uv run python main.py
```

When preparing a Docker build:

```bash
uv lock
docker build -f DockerFile -t applied-ai .
```

## Future Project Setup Guide

Use this section as a quick decision guide when starting this project or another
Python project.

### Creating a New uv Project

```bash
uv init project-name
cd project-name
uv python install 3.12
uv python pin 3.12
uv add package-name
uv run python main.py
```

### Tool Selection Rule

| Project type | Recommended setup |
| --- | --- |
| Pure Python projects, APIs, CLIs, automation, or web apps | uv only |
| Python project with a few system tools like `ffmpeg`, `tesseract`, or `libpq` | uv plus OS package manager |
| Data science, ML, geospatial, scientific computing, GPU, or native-library-heavy projects | Conda, Mamba, or Pixi |
| Production deployment or team reproducibility | Docker plus uv |

### Practical Recommendation

Use this default stack unless the project has a strong reason to do otherwise:

| Need | Tool |
| --- | --- |
| Python dependency management | uv |
| Local system packages | Homebrew, apt, choco, or the platform package manager |
| Cross-language scientific dependencies | Pixi, Conda, or Mamba |
| Reproducible production runtime | Docker |

In other words, do not replace uv for normal Python package management. Pair it
with the right tool when the project needs non-Python dependencies.

### Normal App, Backend, or API Development

Use `uv` plus the operating system package manager. This is the best fit for
most Python applications.

macOS example:

```bash
brew install ffmpeg
uv add moviepy
```

Ubuntu or Debian example:

```bash
sudo apt update
sudo apt install ffmpeg
uv add moviepy
```

PostgreSQL example:

```bash
sudo apt update
sudo apt install libpq-dev
uv add psycopg2
```

Use this approach when the non-Python dependency list is small and easy to
document.

Recommended project convention:

- Python packages are managed by `uv`.
- System packages are documented in `README.md`.
- Production system packages are installed in `DockerFile` or `Dockerfile`.

### Data Science, Geospatial, ML, and Scientific Computing

Use Conda, Mamba, or Pixi when the project needs many native, scientific, GPU,
or cross-language dependencies. These tools can manage Python versions,
compiled libraries, and non-Python packages in one environment.

Conda example:

```bash
conda create -n geo python=3.12 geopandas gdal rasterio
conda activate geo
```

Pixi example:

```bash
pixi init
pixi add python=3.12 gdal geopandas
pixi add --pypi fastapi
pixi run python app.py
```

Prefer Conda, Mamba, or Pixi when the project depends heavily on packages or
tools such as:

- `gdal`
- `proj`
- `geos`
- `cuda`
- `ffmpeg`
- `java`
- `r-base`
- `gcc`
- `postgresql`
- `graphviz`

## Troubleshooting

If Python 3.12 is missing:

```bash
uv python install 3.12
```

If Docker fails because `uv.lock` is missing:

```bash
uv lock
```

If a Python package needs native libraries, install the matching system package
with your OS package manager or add it to `DockerFile`.
