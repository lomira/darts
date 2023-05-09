"""
This is the main file for the benchmarking experiment.
"""

import os

from sklearn.preprocessing import StandardScaler

from darts.dataprocessing.transformers import Scaler
from darts.datasets import (
    AirPassengersDataset,
    ETTh1Dataset,
    ExchangeRateDataset,
    GasRateCO2Dataset,
    SunspotsDataset,
    USGasolineDataset,
    WeatherDataset,
)
from darts.models import (
    ARIMA,
    FFT,
    LightGBMModel,
    LinearRegressionModel,
    NaiveSeasonal,
    NBEATSModel,
    NHiTSModel,
    NLinearModel,
    Prophet,
    TCNModel,
)
from darts.utils import missing_values
from experiments.benchmark_tools import convert_to_ts, experiment

# Loading the models to benchmark


models = [
    NaiveSeasonal,
    FFT,
    Prophet,
    NLinearModel,
    LightGBMModel,  # some warnings for boosting and num_iterations overriding some parameters but it works
    TCNModel,
    NHiTSModel,
    NBEATSModel,
    LinearRegressionModel,
    ARIMA,  # Raytune gets stuck on this one
]

# loading the datasets to use for the benchmark
max_ts_length = 7000
scaler = Scaler(StandardScaler())

datasets = []
ds = scaler.fit_transform(convert_to_ts(GasRateCO2Dataset().load()["CO2%"]))[
    :max_ts_length
]
datasets += [{"series": ds, "dataset_name": "GasRateCO2"}]

ds = scaler.fit_transform(
    missing_values.fill_missing_values(WeatherDataset().load().resample("1h"))
)[:max_ts_length]
datasets += [
    {
        "dataset_name": "Weather",
        "series": ds["T (degC)"],  # type: ignore
        "past_covariates": ds[  # type: ignore
            [
                "p (mbar)",
                "rh (%)",
                "VPmax (mbar)",
                "VPact (mbar)",
                "VPdef (mbar)",
                "H2OC (mmol/mol)",
                "rho (g/m**3)",
                "wv (m/s)",
                "wd (deg)",
                "rain (mm)",
                "raining (s)",
                "SWDR (W/m²)",
            ]
        ],
        "has_past_cov": True,
    }
]

ds = scaler.fit_transform(missing_values.fill_missing_values(ETTh1Dataset().load()))[
    :max_ts_length
]
datasets += [
    {
        "dataset_name": "ETTh1",
        "series": ds["OT"],  # type: ignore
        "future_covariates": ds[["HUFL", "HULL", "MUFL", "MULL", "LUFL", "LULL"]],  # type: ignore
        "has_future_cov": True,
    }
]

ds = scaler.fit_transform(
    missing_values.fill_missing_values(
        convert_to_ts(ExchangeRateDataset().load()["0"])
    )[:max_ts_length]
)
datasets += [{"series": ds, "dataset_name": "ExchangeRate"}]

ds = scaler.fit_transform(
    missing_values.fill_missing_values(SunspotsDataset().load()["Sunspots"])
)[:max_ts_length]
datasets += [{"series": ds, "dataset_name": "Sunspots"}]

ds = scaler.fit_transform(
    missing_values.fill_missing_values(AirPassengersDataset().load()["#Passengers"])
)[:max_ts_length]
datasets += [{"series": ds, "dataset_name": "Air passengers"}]
ds = scaler.fit_transform(
    missing_values.fill_missing_values(USGasolineDataset().load()["Gasoline"])
)[:max_ts_length]
datasets += [{"series": ds, "dataset_name": "USGasoline"}]
datasets = datasets


if __name__ == "main":

    experiment(
        datasets=datasets,
        models=models,
        grid_search=True,
        forecast_horizon=1000,
        time_budget=180,
        experiment_dir=os.path.join(os.getcwd(), "results_long_forecast"),
    )