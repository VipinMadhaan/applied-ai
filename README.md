# Applied AI

A Python 3.12 data science project managed with [Miniconda](https://docs.conda.io/en/latest/miniconda.html).

---

## Quick Start

```bash
conda env create -f environment.yml
conda activate main
```

---

## Stack

| Library | Purpose |
|---|---|
| `pandas` 2.2.2 | Data manipulation and analysis |
| `numpy` 1.26.4 | Numerical computing |
| `matplotlib` 3.10.0 | Plotting and visualization |
| `seaborn` 0.13.2 | Statistical data visualization |
| `scikit-learn` 1.3.0 | Machine learning |
| `xlrd` | Excel file reading |
| `ipykernel` | Jupyter notebook support |

---

## Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) — Python and package management
- [Docker](https://docs.docker.com/get-docker/) — only needed for container builds

### Install Miniconda

**Linux:**

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
source ~/.bashrc
```

**macOS (Apple Silicon):**

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh
source ~/.zshrc
```

**macOS (Intel):**

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh
source ~/.zshrc
```

Verify:

```bash
conda --version
python --version
```

---

## Local Setup

```bash
# 1. Create the environment from the lock file
conda env create -f environment.yml

# 2. Activate it
conda activate main
```

---

## Managing Dependencies

All dependencies live in `environment.yml`. Edit that file, then sync the environment:

```bash
# After adding or removing a package in environment.yml:
conda env update -f environment.yml --prune
```

Commit `environment.yml` after every dependency change.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `conda: command not found` | Re-run the Miniconda installer and reload your shell |
| Environment missing | `conda env create -f environment.yml` |
| Package version conflict | `conda env update -f environment.yml --prune` |
| Docker build fails | Verify `environment.yml` exists; run `conda env create -f environment.yml --dry-run` |