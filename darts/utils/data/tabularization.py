from typing import Optional, Sequence, Union

import numpy as np
import pandas as pd

from darts.logging import raise_if
from darts.models.forecasting.forecasting_model import ForecastingModel
from darts.timeseries import TimeSeries
from darts.utils.utils import series2seq


def _create_lagged_data(
    target_series: Union[TimeSeries, Sequence[TimeSeries]],
    output_chunk_length: int,
    past_covariates: Optional[Union[TimeSeries, Sequence[TimeSeries]]] = None,
    future_covariates: Optional[Union[TimeSeries, Sequence[TimeSeries]]] = None,
    lags: Optional[Sequence[int]] = None,
    lags_past_covariates: Optional[Sequence[int]] = None,
    lags_future_covariates: Optional[Sequence[int]] = None,
    max_samples_per_ts: Optional[int] = None,
    is_training: Optional[bool] = True,  # other option: 'inference
    multi_models: Optional[bool] = True,
):
    """
    Helper function that creates training/validation matrices (X and y as required in sklearn), given series and
    max_samples_per_ts.

    X has the following structure:
    lags_target | lags_past_covariates | lags_future_covariates

    Where each lags_X has the following structure (lags_X=[-2,-1] and X has 2 components):
    lag_-2_comp_1_X | lag_-2_comp_2_X | lag_-1_comp_1_X | lag_-1_comp_2_X

    y has the following structure (output_chunk_length=4 and target has 2 components):
    lag_+0_comp_1_target | lag_+0_comp_2_target | ... | lag_+3_comp_1_target | lag_+3_comp_2_target

    Parameters
    ----------
    target_series
        The target series of the regression model.
    output_chunk_length
        The output_chunk_length of the regression model.
    past_covariates
        Optionally, the past covariates of the regression model.
    future_covariates
        Optionally, the future covariates of the regression model.
    lags
        Optionally, the lags of the target series to be used as features.
    lags_past_covariates
        Optionally, the lags of the past covariates to be used as features.
    lags_future_covariates
        Optionally, the lags of the future covariates to be used as features.
    max_samples_per_ts
        Optionally, the maximum number of samples to be drawn for training/validation
        The kept samples are the most recent ones.
    is_training
        Optionally, whether the data is used for training or inference.
        If inference, the rows where the future_target_lags are NaN are not removed from X,
        as we are only interested in the X matrix to infer the future target values.
    """

    # ensure list of TimeSeries format
    if isinstance(target_series, TimeSeries):
        target_series = [target_series]
        past_covariates = [past_covariates] if past_covariates else None
        future_covariates = [future_covariates] if future_covariates else None

    Xs, ys, Ts = [], [], []

    # iterate over series
    for idx, target_ts in enumerate(target_series):
        covariates = [
            (
                past_covariates[idx].pd_dataframe(copy=False)
                if past_covariates
                else None,
                lags_past_covariates,
            ),
            (
                future_covariates[idx].pd_dataframe(copy=False)
                if future_covariates
                else None,
                lags_future_covariates,
            ),
        ]

        df_X = []
        df_y = []
        df_target = target_ts.pd_dataframe(copy=False)

        # y: output chunk length lags of target
        if multi_models:
            for future_target_lag in range(output_chunk_length):
                df_y.append(
                    df_target.shift(-future_target_lag).rename(
                        columns=lambda x: f"{x}_horizon_lag{future_target_lag}"
                    )
                )
        else:
            df_y.append(
                df_target.shift(-output_chunk_length + 1).rename(
                    columns=lambda x: f"{x}_horizon_lag{output_chunk_length-1}"
                )
            )

        if lags:
            for lag in lags:
                df_X.append(
                    df_target.shift(-lag).rename(
                        columns=lambda x: f"{x}_target_lag{lag}"
                    )
                )

        # X: covariate lags
        for covariate_name, (df_cov, lags_cov) in zip(["past", "future"], covariates):
            if lags_cov:
                if not is_training:
                    # We extend the covariates dataframe
                    # so that when we create the lags with shifts
                    # we don't have nan on the last (or first) rows. Only useful for inference.
                    df_cov = df_cov.reindex(df_target.index.union(df_cov.index))

                for lag in lags_cov:
                    df_X.append(
                        df_cov.shift(-lag).rename(
                            columns=lambda x: f"{x}_{covariate_name}_cov_lag{lag}"
                        )
                    )

        # combine lags
        df_X = pd.concat(df_X, axis=1)
        df_y = pd.concat(df_y, axis=1)
        df_X_y = pd.concat([df_X, df_y], axis=1)
        if is_training:
            df_X_y = df_X_y.dropna()
        # We don't need to drop where y are none for inference, as we just care for X
        else:
            df_X_y = df_X_y.dropna(subset=df_X.columns)

        Ts.append(df_X_y.index)
        X_y = df_X_y.values

        # keep most recent max_samples_per_ts samples
        if max_samples_per_ts:
            X_y = X_y[-max_samples_per_ts:]
            Ts[-1] = Ts[-1][-max_samples_per_ts:]

        raise_if(
            X_y.shape[0] == 0,
            "Unable to build any training samples of the target series "
            + (f"at index {idx} " if len(target_series) > 1 else "")
            + "and the corresponding covariate series; "
            "There is no time step for which all required lags are available and are not NaN values.",
        )

        X, y = np.split(X_y, [df_X.shape[1]], axis=1)

        Xs.append(X)
        ys.append(y)

    # combine samples from all series
    X = np.concatenate(Xs, axis=0)
    y = np.concatenate(ys, axis=0)

    return X, y, Ts


def _add_static_covariates(
    model: ForecastingModel,
    features: np.array,
    target_series: Union[TimeSeries, Sequence[TimeSeries]],
    min_target_lag: int,
    output_chunk_length: int,
    min_past_cov_lag: Optional[int] = None,
    min_future_cov_lag: Optional[int] = None,
    max_future_cov_lag: Optional[int] = None,
    past_covariates: Optional[Union[TimeSeries, Sequence[TimeSeries]]] = None,
    future_covariates: Optional[Union[TimeSeries, Sequence[TimeSeries]]] = None,
    max_samples_per_ts: Optional[int] = None,
):
    """
    Add static covariates to the features' table for RegressionModels.
    Accounts for series with potentially different static covariates by padding with 0 to accomodate for the maximum
    number of available static_covariates in any of the given series in the sequence.
    If no static covariates are provided for a given series, its corresponding features are padded with 0.
    Accounts for the case where the model is trained with series with static covariates and then used to predict
    on series without static covariates by padding with 0 the corresponding features of the series without
    static covariates.

    Parameters
    ----------
    model
        The regression model. Should be an instance of darts.models.RegressionModel.
    features
        The features' numpy array to which the static covariates will be added.
    target_series
        The target series from which to read the static covariates.
    min_target_lag
        The minimum past lag of the target series.
    output_chunk_length
        The model's output chunk length.
    min_past_cov_lag
        The minimum past lag of the past covariates.
    min_future_cov_lag
        The minimum past lag of the future covariates.
    max_future_cov_lag
        The maximum future lag of the future covariates.
    max_samples_per_ts
        Optionally, the maximum number of samples to be drawn for training or inference.
        It is set to 1 for inference (i.e., auto-regressively predict one step at a time, hence generate one
        feature vector at a time).
    """

    model = model.model

    target_series = series2seq(target_series)
    past_covariates = series2seq(past_covariates)
    future_covariates = series2seq(future_covariates)

    n_comps = target_series[0].n_components

    max_past_lag = max(
        [
            abs(v)
            for v in [min_target_lag, min_past_cov_lag, min_future_cov_lag]
            if v is not None
        ]
    )

    # collect static covariates info
    scovs_map = {"covs_exist": False, "df": [], "reps": [], "names": set()}

    for idx, ts in enumerate(target_series):
        len_target_features = len(ts) - max_past_lag - (output_chunk_length - 1)
        len_past_cov_features = (
            (len(past_covariates[idx]) - max_past_lag)
            if past_covariates is not None
            else None
        )
        len_future_cov_features = (
            (len(future_covariates[idx]) - max_past_lag - max_future_cov_lag)
            if future_covariates is not None
            else None
        )
        len_shortest_features = min(
            [
                v
                for v in [
                    len_target_features,
                    len_past_cov_features,
                    len_future_cov_features,
                ]
                if v is not None
            ]
        )

        if ts.static_covariates is not None:

            scovs_map["names"].update(set(ts.static_covariates.columns))
            scovs_map["covs_exist"] = True
            scovs_map["df"].append(ts.static_covariates)
            scovs_map["reps"].append(
                max_samples_per_ts
                if max_samples_per_ts is not None
                else len_shortest_features
            )
        else:
            scovs_map["df"].append(pd.DataFrame())
            scovs_map["reps"].append(
                max_samples_per_ts
                if max_samples_per_ts is not None
                else len_shortest_features
            )

    if not scovs_map["covs_exist"]:
        if (
            hasattr(model, "n_features_in_")
            and model.n_features_in_ is not None
            and model.n_features_in_ > features.shape[1]
        ):
            # for when series in prediction do not have static covariates but some of the training series did
            pad_zeros = np.zeros((1, model.n_features_in_ - features.shape[1]))
            return np.concatenate(
                [features, np.tile(pad_zeros, reps=(features.shape[0], 1))], axis=1
            )
        else:
            return features

    else:
        # at least one series in the sequence has static covariates
        static_covs = []
        col_names = list(scovs_map["names"])
        # build static covariates array
        for i in range(len(target_series)):
            df = scovs_map["df"][i]

            if not df.empty:
                df = df.reindex(col_names, axis=1, fill_value=0.0, copy=True)
                # reshape with order="F" to ensure that the covariates are read column wise
                scovs = df.values.reshape(1, -1, order="F")
                static_covs.append(np.tile(scovs, reps=(scovs_map["reps"][i], 1)))
            else:
                pad_zeros = np.zeros((1, len(col_names) * n_comps))
                static_covs.append(np.tile(pad_zeros, reps=(scovs_map["reps"][i], 1)))
        static_covs = np.concatenate(static_covs, axis=0)

        # concatenate static covariates to features
        return np.concatenate([features, static_covs], axis=1)