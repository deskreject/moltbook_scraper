## Project Overview

Academic research project for scraping and econometrically analyzing Moltbook, an AI-agent-only social network. The project produces a working paper analyzing the social graph structure, conversation dynamics, and content patterns of AI agent interactions.

**Research Question**: Is posting activity on Moltbook meaningfully social, or is it largely an as-if performance?

## Repository Structure

```
moltbook_scraper/
├── src/                     # Python scraper (core data collection)
│   ├── cli.py               # CLI entry point
│   ├── client.py            # Moltbook API client with exponential backoff retry
│   ├── database.py          # SQLite schema and operations
│   └── scraper.py           # Scraping orchestration
├── analysis/
│   ├── R/                   # R analysis scripts (run sequentially)
│   │   ├── utils.R          # Shared utilities (themes, Gini, Jaccard, etc.)
│   │   ├── 01_load_data.R   # Load SQLite snapshots into R dataframes
│   │   ├── 02_structural.R  # Platform growth, concentration metrics
│   │   ├── 03_conversation.R # Thread depth, reply patterns
│   │   ├── 04_lexical.R     # Zipf analysis, duplicates, n-grams
│   │   ├── 05_topics.R      # Theme classification, key phrases
│   │   ├── 06_network_deep.R # Reply network (reciprocity, clustering)
│   │   └── 07_owner_analysis.R # Agent-owner relationships
│   ├── data/                # Processed .rds files (gitignored)
│   └── output/              # Figures and tables (gitignored)
├── latex/
│   └── moltbook_analysis.tex # Paper source (natbib, booktabs)
├── scripts/
│   ├── weekly_scrape.sh     # Weekly incremental (Hetzner VM cron, Mon 02:00 UTC)
│   ├── monthly_rescrape.sh  # Monthly full re-scrape (Hetzner VM cron, 1st 02:00 UTC)
│   ├── status.sh            # VM status dashboard (manual SSH)
│   ├── daily_scrape.ps1     # Windows PowerShell daily scrape (legacy)
│   ├── daily_scrape.sh      # Bash daily scrape (legacy reference)
│   └── run_on_hpc.sh        # HPC cluster job (unused)
└── tests/                   # pytest unit tests
```

## Setup

### Scraper (Python)

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set API key (get from Moltbook)
echo "MOLTBOOK_API_KEY=your_key_here" > .env
```

### Analysis (R)

Required R packages:
- tidyverse, DBI, RSQLite
- igraph, tidygraph, ggraph
- tidytext, topicmodels
- scales, ggrepel, patchwork

```r
install.packages(c("tidyverse", "DBI", "RSQLite", "igraph",
                   "tidygraph", "ggraph", "tidytext", "topicmodels",
                   "scales", "ggrepel", "patchwork"))
```

## Usage

### Scraping

```bash
# Scrape posts
python -m src.cli posts --db moltbook.db

# Scrape comments
python -m src.cli comments --db moltbook.db

# Enrich agent metadata
python -m src.cli enrich --db moltbook.db

# Create snapshots for reproducibility
python -m src.cli snapshots --db moltbook.db
```

### Analysis

Run R scripts in order from the `analysis/R/` directory:

```bash
cd analysis/R
Rscript 01_load_data.R
Rscript 02_structural.R
# ... etc.
```

Scripts output figures to `analysis/output/figures/` and tables to `analysis/output/tables/`.

## Data

The SQLite database (`moltbook.db`) and generated outputs (figures, tables) are excluded from this repository. The scraper creates the database schema automatically on first run.

## Citation

If you use this code or data, please cite the associated paper (citation TBD).

## License

MIT
