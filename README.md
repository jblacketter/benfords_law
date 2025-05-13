# Benford's Law Analyzer

This project demonstrates how to use Python and the `benfordslaw` package to analyze real-world data for compliance with Benford's Law.


## 🔧 Setup

```bash
pip install -r requirements.txt
```
🚀 Usage

Run from terminal:

python scripts/run_analysis.py \
  --csv data/us_state_population_2020.csv \
  --column Population \
  --plot output/benford_plot.png \
  --report output/benford_test_report.txt

📊 Output

    A bar plot comparing actual and expected digit frequencies.

    A report file with:

        Chi-squared test

        p-value

        MAD (Mean Absolute Deviation)

📌 Notes

    Works best with naturally occurring data across multiple magnitudes (e.g., financial records, population counts).
