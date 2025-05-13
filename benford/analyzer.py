import pandas as pd
from benfordslaw import benfordslaw
import matplotlib.pyplot as plt
import os

class BenfordAnalyzer:
    def __init__(self, csv_path, column, plot_path=None, report_path=None):
        self.csv_path = csv_path
        self.column = column
        self.plot_path = plot_path
        self.report_path = report_path
        self.df = None
        self.results = None

    def load_data(self):
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"File not found: {self.csv_path}")
        self.df = pd.read_csv(self.csv_path)
        if self.column not in self.df.columns:
            raise ValueError(f"Column '{self.column}' not found in {self.csv_path}")
        return self.df[self.column].dropna()

    def run(self):
        series = self.load_data()
        bl = benfordslaw()
        self.results = bl.fit(series)  # This prints results and stores stats internally

        self._save_plot(bl)
        self._save_report(bl)
        return self.results

    def _save_plot(self, bl):
        if self.plot_path:
            bl.plot(title=f"Benford's Law - {self.column}")
            plt.savefig(self.plot_path)
            print(f"[INFO] Plot saved to {self.plot_path}")
            plt.close()

    def _save_report(self, bl):
        if self.report_path:
            with open(self.report_path, 'w') as f:
                f.write(f"Benford's Law Report for: {self.column}\n\n")
                f.write(f"Chi-squared statistic: {bl.tstat:.5f}\n")
                f.write(f"P-value: {bl.p:.5f}\n")
                f.write(f"Conclusion: {'No anomaly detected' if bl.p > 0.05 else 'Anomaly detected'}\n")
            print(f"[INFO] Report saved to {self.report_path}")
