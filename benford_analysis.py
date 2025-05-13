import pandas as pd
from benfordslaw import benfordslaw
import matplotlib.pyplot as plt
import sys
import os

# ---------- CONFIGURATION ----------
DATA_FILE = "data/us_state_population_2020.csv"
COLUMN_NAME = "Population"
PLOT_SAVE_PATH = "output/benford_plot.png"
REPORT_SAVE_PATH = "output/benford_test_report.txt"
# ----------------------------------

def run_benford_analysis(csv_path, column):
    if not os.path.exists(csv_path):
        print(f"[ERROR] File not found: {csv_path}")
        sys.exit(1)

    # Load data
    df = pd.read_csv(csv_path)

    if column not in df.columns:
        print(f"[ERROR] Column '{column}' not found in dataset.")
        print(f"[INFO] Available columns: {df.columns.tolist()}")
        sys.exit(1)

    # Drop NaN values
    series = df[column].dropna()

    # Initialize and fit Benford's Law
    bl = benfordslaw()
    bl.fit(series)

    # Plot comparison of actual vs expected
    bl.plot(title=f"Benford's Law - {column}")
    plt.savefig(PLOT_SAVE_PATH)
    print(f"[INFO] Plot saved to {PLOT_SAVE_PATH}")

    # Print and save statistics
    stats = bl.get_stats()
    print(f"\n[RESULT] Benford Statistics:\n{stats}")

    with open(REPORT_SAVE_PATH, 'w') as f:
        f.write(f"Benford's Law Test Report for column: {column}\n\n")
        for key, value in stats.items():
            f.write(f"{key}: {value}\n")

    print(f"[INFO] Report saved to {REPORT_SAVE_PATH}")

if __name__ == "__main__":
    run_benford_analysis(DATA_FILE, COLUMN_NAME)
