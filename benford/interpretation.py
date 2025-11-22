from typing import Optional, Dict


def interpret_results(
    p_value: Optional[float],
    chi_squared: Optional[float],
    dataset_name: Optional[str] = None,
    expectation: Optional[str] = None,
) -> Dict[str, str]:
    """
    Produce a plain-language interpretation of Benford test results.

    :param p_value: P-value from benfordslaw
    :param chi_squared: Chi-squared statistic from benfordslaw
    :param dataset_name: Optional dataset label to personalize messaging
    :param expectation: Optional expectation hint ('conform' or 'nonconform')
    """
    name = dataset_name or "this dataset"
    if p_value is None or chi_squared is None:
        return {
            "headline": f"Could not interpret results for {name}",
            "detail": "The analysis did not return a p-value or chi-squared statistic.",
            "guidance": "Re-run the analysis or verify the dataset contains numeric data."
        }

    outcome = "likely follows Benford's Law" if p_value > 0.05 else "likely does not follow Benford's Law"

    alignment = ""
    if expectation:
        if expectation == "conform" and p_value > 0.05:
            alignment = "This matches the expected behavior for this dataset."
        elif expectation == "nonconform" and p_value <= 0.05:
            alignment = "This deviation is expected for this dataset."
        else:
            alignment = "This result differs from the typical expectation—worth a closer look."

    guidance = (
        "No red flags detected. The first-digit distribution is close to the Benford curve."
        if p_value > 0.05 else
        "Significant deviation detected. Investigate the data generation process or potential anomalies."
    )

    return {
        "headline": f"{name} {outcome}",
        "detail": f"p-value: {p_value:.4f}, chi-squared: {chi_squared:.4f}. {alignment}".strip(),
        "guidance": guidance
    }
