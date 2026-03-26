## R

### coding conventions 

- `theme_paper()` for publication-ready figures
- Save helpers: `save_figure()`, `save_table()`
- Database connection via `connect_db()` utility

### Analysis (R) - NEEDS TO BE REVIEWED (copied from Dave Holtz)

Run from `analysis/R/` directory in order:

```bash
Rscript 01_load_data.R   # Creates analysis/data/*.rds
Rscript 02_structural.R  # Power-law fits, Gini, growth plots
Rscript 03_conversation.R # Thread shapes, depth distribution
Rscript 04_lexical.R     # Zipf, duplicates, loops
Rscript 05_topics.R      # Keyword themes, key phrases
Rscript 06_network_deep.R # igraph metrics, community detection
Rscript 07_owner_analysis.R # "my human" patterns
```