import os
from typing import Optional, Dict, Any

import pandas as pd
from benfordslaw import benfordslaw
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

class BenfordAnalyzer:
    """
    A class to perform Benford's Law analysis on a column of a CSV file.
    """

    def __init__(self, csv_path: str, column: str, plot_path: Optional[str] = None, report_path: Optional[str] = None):
        """
        Initializes the BenfordAnalyzer.

        :param csv_path: Path to the CSV file.
        :param column: The name of the column to analyze.
        :param plot_path: Optional path to save the analysis plot.
        :param report_path: Optional path to save the analysis report.
        """
        self.csv_path = csv_path
        self.column = column
        self.plot_path = plot_path
        self.report_path = report_path
        self.df: Optional[pd.DataFrame] = None
        self.results: Optional[Dict[str, Any]] = None

    def load_data(self) -> pd.Series:
        """
        Loads data from the CSV file and returns the specified column as a Series.

        :return: A pandas Series with NaN values dropped.
        :raises FileNotFoundError: If the CSV file does not exist.
        :raises ValueError: If the specified column is not in the CSV file.
        """
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"File not found: {self.csv_path}")
        self.df = pd.read_csv(self.csv_path)
        if self.column not in self.df.columns:
            raise ValueError(f"Column '{self.column}' not found in {self.csv_path}")
        series = pd.to_numeric(self.df[self.column], errors='coerce').dropna()
        if series.empty:
            raise ValueError(f"Column '{self.column}' is not numeric or contains no numeric values.")
        return series

    def run(self) -> Dict[str, Any]:
        """
        Runs the Benford's Law analysis.

        :return: A dictionary containing the results of the analysis.
        """
        series = self.load_data()
        bl = benfordslaw()
        self.results = bl.fit(series)

        self._save_plot(bl)
        self._save_report(bl)
        return self.results

    def _save_plot(self, bl: benfordslaw) -> None:
        """
        Saves the Benford's Law plot if a path is provided.

        :param bl: The benfordslaw object containing the analysis results.
        """
        if self.plot_path:
            bl.plot(title=f"Benford's Law - {self.column}")
            plt.savefig(self.plot_path)
            plt.close()

    def _save_report(self, bl: benfordslaw) -> None:
        """
        Saves the Benford's Law report if a path is provided.

        :param bl: The benfordslaw object containing the analysis results.
        """
        if self.report_path:
            with open(self.report_path, 'w') as f:
                f.write(f"Benford's Law Report for: {self.column}\n\n")
                f.write(f"Chi-squared statistic: {bl.tstat:.5f}\n")
                f.write(f"P-value: {bl.p:.5f}\n")
                f.write(f"Conclusion: {'No anomaly detected' if bl.p > 0.05 else 'Anomaly detected'}\n")
