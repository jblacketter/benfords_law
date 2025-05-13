import sys
import os

# Add the parent directory of 'scripts/' to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


import argparse
from benford.analyzer import BenfordAnalyzer

def main():
    parser = argparse.ArgumentParser(description="Run Benford's Law analysis on a CSV file.")
    parser.add_argument('--csv', required=True, help='Path to CSV file')
    parser.add_argument('--column', required=True, help='Numeric column name to analyze')
    parser.add_argument('--plot', default='output/benford_plot.png', help='Output plot path')
    parser.add_argument('--report', default='output/benford_test_report.txt', help='Output report path')
    args = parser.parse_args()

    analyzer = BenfordAnalyzer(
        csv_path=args.csv,
        column=args.column,
        plot_path=args.plot,
        report_path=args.report
    )

    try:
        stats = analyzer.run()
        print("[RESULT] Analysis complete.")
        for k, v in stats.items():
            print(f"{k}: {v}")
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    main()
