"""
The preprocessing function of the dataset PhysionNet2012 for BenchPOTS.
"""

# Created by Wenjie Du <wenjay.du@gmail.com>
# License: BSD-3-Clause

import numpy as np
import pandas as pd
import tsdb
from pypots.utils.logging import logger
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from .utils import create_missingness, print_final_dataset_info


def preprocess_physionet2012(rate, pattern: str = "point", subset="all", **kwargs):
    """Generate a fully-prepared PhysioNet2012 dataset for benchmarking and validating POTS models.

    Parameters
    ----------
    rate: float,
        The additional missing rate to artificially add to the dataset.
        If the dataset has original missing values, this rate won't be applied to them.
        If the dataset originally has no missing data, this rate will be applied to the dataset.

    pattern

    subset

    Returns
    -------
    processed_dataset: dict,
        A dictionary containing the processed PhysioNet-2012 dataset.

    """

    def apply_func(df_temp):  # pad and truncate to set the max length of samples as 48
        missing = list(set(range(0, 48)).difference(set(df_temp["Time"])))
        missing_part = pd.DataFrame({"Time": missing})
        df_temp = pd.concat(
            [df_temp, missing_part], ignore_index=False, sort=False
        )  # pad the sample's length to 48 if it doesn't have enough time steps
        df_temp = df_temp.set_index("Time").sort_index().reset_index()
        df_temp = df_temp.iloc[:48]  # truncate
        return df_temp

    all_subsets = ["all", "set-a", "set-b", "set-c"]
    assert (
        subset.lower() in all_subsets
    ), f"subset should be one of {all_subsets}, but got {subset}"
    assert 0 <= rate < 1, f"rate must be in [0, 1), but got {rate}"

    # read the raw data
    data = tsdb.load("physionet_2012")
    data["static_features"].remove("ICUType")  # keep ICUType for now

    if subset != "all":
        df = data[subset]
        X = df.reset_index(drop=True)
        unique_ids = df["RecordID"].unique()
        y = data[f"outcomes-{subset.split('-')[-1]}"]
        y = y.loc[unique_ids]
    else:
        df = pd.concat([data["set-a"], data["set-b"], data["set-c"]], sort=True)
        X = df.reset_index(drop=True)
        unique_ids = df["RecordID"].unique()
        y = pd.concat([data["outcomes-a"], data["outcomes-b"], data["outcomes-c"]])
        y = y.loc[unique_ids]

    # remove the other static features, e.g. age, gender
    X = X.drop(data["static_features"], axis=1)
    X = X.groupby("RecordID").apply(apply_func)
    X = X.drop("RecordID", axis=1)
    X = X.reset_index()
    ICUType = X[["RecordID", "ICUType"]].set_index("RecordID").dropna()
    X = X.drop(["level_1", "ICUType"], axis=1)

    # PhysioNet2012 is an imbalanced dataset, hence, we separate positive and negative samples here for later splitting
    # This is to ensure positive and negative ratios are similar in train/val/test sets
    all_recordID = X["RecordID"].unique()
    positive = (y == 1)["In-hospital_death"]
    positive_sample_IDs = y.loc[positive].index.to_list()
    negative_sample_IDs = np.setxor1d(all_recordID, positive_sample_IDs)
    assert len(positive_sample_IDs) + len(negative_sample_IDs) == len(all_recordID)

    # split the dataset into the train, val, and test sets
    train_positive_set_ids, test_positive_set_ids = train_test_split(
        positive_sample_IDs, test_size=0.2
    )
    train_positive_set_ids, val_positive_set_ids = train_test_split(
        train_positive_set_ids, test_size=0.2
    )
    train_negative_set_ids, test_negative_set_ids = train_test_split(
        negative_sample_IDs, test_size=0.2
    )
    train_negative_set_ids, val_negative_set_ids = train_test_split(
        train_negative_set_ids, test_size=0.2
    )
    train_set_ids = np.concatenate([train_positive_set_ids, train_negative_set_ids])
    val_set_ids = np.concatenate([val_positive_set_ids, val_negative_set_ids])
    test_set_ids = np.concatenate([test_positive_set_ids, test_negative_set_ids])
    train_set_ids.sort()
    val_set_ids.sort()
    test_set_ids.sort()
    train_set = X[X["RecordID"].isin(train_set_ids)].sort_values(["RecordID", "Time"])
    val_set = X[X["RecordID"].isin(val_set_ids)].sort_values(["RecordID", "Time"])
    test_set = X[X["RecordID"].isin(test_set_ids)].sort_values(["RecordID", "Time"])

    # remove useless columns and turn into numpy arrays
    train_set = train_set.drop(["RecordID", "Time"], axis=1)
    val_set = val_set.drop(["RecordID", "Time"], axis=1)
    test_set = test_set.drop(["RecordID", "Time"], axis=1)
    train_X, val_X, test_X = (
        train_set.to_numpy(),
        val_set.to_numpy(),
        test_set.to_numpy(),
    )

    # normalization
    scaler = StandardScaler()
    train_X = scaler.fit_transform(train_X)
    val_X = scaler.transform(val_X)
    test_X = scaler.transform(test_X)

    # reshape into time series samples
    train_X = train_X.reshape(len(train_set_ids), 48, -1)
    val_X = val_X.reshape(len(val_set_ids), 48, -1)
    test_X = test_X.reshape(len(test_set_ids), 48, -1)

    # fetch labels for train/val/test sets
    train_y = y[y.index.isin(train_set_ids)].sort_index()
    val_y = y[y.index.isin(val_set_ids)].sort_index()
    test_y = y[y.index.isin(test_set_ids)].sort_index()
    train_y, val_y, test_y = train_y.to_numpy(), val_y.to_numpy(), test_y.to_numpy()

    # fetch ICUType for train/val/test sets
    train_ICUType = ICUType[ICUType.index.isin(train_set_ids)].sort_index()
    val_ICUType = ICUType[ICUType.index.isin(val_set_ids)].sort_index()
    test_ICUType = ICUType[ICUType.index.isin(test_set_ids)].sort_index()
    train_ICUType, val_ICUType, test_ICUType = (
        train_ICUType.to_numpy(),
        val_ICUType.to_numpy(),
        test_ICUType.to_numpy(),
    )

    # assemble the final processed data into a dictionary
    processed_dataset = {
        # general info
        "n_classes": 2,
        "n_steps": 48,
        "n_features": train_X.shape[-1],
        "scaler": scaler,
        # train set
        "train_X": train_X,
        "train_y": train_y.flatten(),
        "train_ICUType": train_ICUType.flatten(),
        # val set
        "val_X": val_X,
        "val_y": val_y.flatten(),
        "val_ICUType": val_ICUType.flatten(),
        # test set
        "test_X": test_X,
        "test_y": test_y.flatten(),
        "test_ICUType": test_ICUType.flatten(),
    }

    if rate > 0:
        logger.warning(
            "Note that physionet_2012 has sparse observations in the time series, "
            "hence we don't add additional missing values to the training dataset. "
        )

        # hold out ground truth in the original data for evaluation
        val_X_ori = val_X
        test_X_ori = test_X

        # mask values in the validation set as ground truth
        val_X = create_missingness(val_X, rate, pattern, **kwargs)
        # mask values in the test set as ground truth
        test_X = create_missingness(test_X, rate, pattern, **kwargs)

        processed_dataset["train_X"] = train_X

        processed_dataset["val_X"] = val_X
        processed_dataset["val_X_ori"] = val_X_ori

        processed_dataset["test_X"] = test_X
        # test_X_ori is for error calc, not for model input, hence mustn't have NaNs
        processed_dataset["test_X_ori"] = np.nan_to_num(
            test_X_ori
        )  # fill NaNs for later error calc
        processed_dataset["test_X_indicating_mask"] = np.isnan(test_X_ori) ^ np.isnan(
            test_X
        )
    else:
        logger.warning("rate is 0, no missing values are artificially added.")

    print_final_dataset_info(train_X, val_X, test_X)
    return processed_dataset
