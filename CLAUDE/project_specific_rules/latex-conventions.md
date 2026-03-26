## LaTeX

### conventions

- Standard packages: amsmath, booktabs, natbib, hyperref, cleveref
- Custom macros: `\figmaybe`, `\figpairmaybe` for conditional figure inclusion

### Building Paper (REVIEW FIRST - copied from Dave Holtz)

```bash
cd latex
pdflatex moltbook_analysis.tex
bibtex moltbook_analysis
pdflatex moltbook_analysis.tex
pdflatex moltbook_analysis.tex
```