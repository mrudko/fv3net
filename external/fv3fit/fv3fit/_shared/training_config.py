import argparse
import copy
import dataclasses
import os
from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
    Tuple,
    Union,
    Sequence,
    Set,
    List,
    Type,
    Dict,
    MutableMapping,
    TypeVar,
)

from fv3fit.typing import Dataclass
from fv3fit.emulation.layers.normalization2 import MeanMethod, StdDevMethod
from fv3fit._shared.config import CacheConfig, PackerConfig
import xarray as xr
from .predictor import Dumpable
from .hyperparameters import Hyperparameters
import dacite
import numpy as np
import random
import warnings
import vcm
import torch

# TODO: move all keras configs under fv3fit.keras
import tensorflow as tf


TrainingFunction = Callable[
    [Dataclass, Sequence[xr.Dataset], Sequence[xr.Dataset]], Dumpable
]

TF = TypeVar("TF", bound=TrainingFunction)


def set_random_seed(seed: Union[float, int] = 0):
    # https://stackoverflow.com/questions/32419510/how-to-get-reproducible-results-in-keras
    os.environ["PYTHONHASHSEED"] = str(seed)
    np.random.seed(seed + 1)
    random.seed(seed + 2)
    tf.random.set_seed(seed + 3)
    torch.manual_seed(seed + 4)


# TODO: delete this routine by refactoring the tests to no longer depend on it
def get_keras_model(name):
    return TRAINING_FUNCTIONS[name][0]


@dataclasses.dataclass
class TrainingConfig:
    """Convenience wrapper for model training parameters and file info

    Attributes:
        model_type: sklearn model type or keras model class to initialize
        hyperparameters: model_type-specific training configuration
        sample_dim_name: deprecated, internal name used for sample dimension
            when training and predicting
        random_seed: value to use to initialize randomness
        derived_output_variables: optional list of prediction variables that
            are not directly predicted by the ML model but instead are derived
            using the ML-predicted output_variables
        output_transforms: if given, apply these output transformations in the
            saved Predictor
        cache: configuration for local caching of input data
    """

    model_type: str
    hyperparameters: Hyperparameters
    sample_dim_name: str = "sample"
    random_seed: Union[float, int] = 0
    derived_output_variables: List[str] = dataclasses.field(default_factory=list)
    output_transforms: Sequence[vcm.DataTransform] = dataclasses.field(
        default_factory=list
    )
    cache: CacheConfig = dataclasses.field(default_factory=lambda: CacheConfig())

    @property
    def variables(self):
        return self.hyperparameters.variables

    @classmethod
    def from_dict(cls, kwargs) -> "TrainingConfig":
        kwargs = {**kwargs}  # make a copy to avoid mutating the input
        if "input_variables" in kwargs:
            warnings.warn(
                "input_variables is no longer a top-level TrainingConfig "
                "parameter, pass it under hyperparameters instead",
                DeprecationWarning,
            )
            kwargs["hyperparameters"]["input_variables"] = kwargs.pop("input_variables")
        if "output_variables" in kwargs:
            warnings.warn(
                "output_variables is no longer a top-level TrainingConfig "
                "parameter, pass it under hyperparameters instead",
                DeprecationWarning,
            )
            kwargs["hyperparameters"]["output_variables"] = kwargs.pop(
                "output_variables"
            )
        hyperparameter_class = get_hyperparameter_class(kwargs["model_type"])
        # custom enums must be specified for dacite to handle correctly
        dacite_config = dacite.Config(
            strict=True, cast=[bool, str, int, float, StdDevMethod, MeanMethod]
        )
        kwargs["hyperparameters"] = dacite.from_dict(
            data_class=hyperparameter_class,
            data=kwargs.get("hyperparameters", {}),
            config=dacite_config,
        )
        return dacite.from_dict(
            data_class=cls, data=kwargs, config=dacite.Config(strict=True)
        )


TRAINING_FUNCTIONS: Dict[str, Tuple[TrainingFunction, Type[Dataclass]]] = {}


def get_hyperparameter_class(model_type: str):
    if model_type in TRAINING_FUNCTIONS:
        _, subclass = TRAINING_FUNCTIONS[model_type]
    else:
        raise ValueError(f"unknown model_type {model_type}")
    return subclass


def get_training_function(model_type: str) -> TrainingFunction:
    if model_type in TRAINING_FUNCTIONS:
        estimator_class, _ = TRAINING_FUNCTIONS[model_type]
    else:
        raise ValueError(f"unknown model_type {model_type}")
    return estimator_class


def register_training_function(name: str, hyperparameter_class: type):
    """
    Returns a decorator that will register the given training function
    to be usable in training configuration.
    """

    def decorator(func: TF) -> TF:
        TRAINING_FUNCTIONS[name] = (func, hyperparameter_class)
        return func

    return decorator


def _bool_from_str(value: str):
    affirmatives = ["y", "yes", "true", "t"]
    negatives = ["n", "no", "false", "f"]

    if value.lower() in affirmatives:
        return True
    elif value.lower() in negatives:
        return False
    else:
        raise ValueError(
            f"Unrecognized value encountered in boolean conversion: {value}"
        )


def _add_items_to_parser_arguments(
    d: Mapping[str, Any], parser: argparse.ArgumentParser
):
    """
    Take a dictionary and add all the keys as an ArgumentParser
    argument with the value as a default.  Does no casting so
    any non-defaults will likely be strings.  Instead relies on the
    dataclasses to do the validation and type casting.
    """

    for key, value in d.items():
        if isinstance(value, Mapping):
            raise ValueError(
                "Adding a mapping as an argument to the parse is not "
                "currently supported.  Make sure you are passing a "
                "'flattened' dictionary to this function. If you are trying "
                "to override a value in a 'kwargs' setting, make sure a value "
                "is given in the configuration yaml."
            )
        elif not isinstance(value, str) and isinstance(value, Sequence):
            parser.add_argument(f"--{key}", nargs="*", default=copy.copy(value))
        elif isinstance(value, bool):
            parser.add_argument(f"--{key}", type=_bool_from_str, default=value)
        elif isinstance(value, int):
            parser.add_argument(f"--{key}", type=int, default=value)
        elif isinstance(value, float):
            parser.add_argument(f"--{key}", type=float, default=value)
        else:
            parser.add_argument(f"--{key}", default=value)


def to_flat_dict(d: dict):
    """
    Converts any nested dictionaries to a flat version with
    the nested keys joined with a '.', e.g., {a: {b: 1}} ->
    {a.b: 1}
    """

    new_flat = {}
    for k, v in d.items():
        if isinstance(v, dict):
            sub_d = to_flat_dict(v)
            for sk, sv in sub_d.items():
                new_flat[".".join([k, sk])] = sv
        else:
            new_flat[k] = v

    return new_flat


def to_nested_dict(d: dict):
    """
    Converts a flat dictionary with '.' joined keys back into
    a nested dictionary, e.g., {a.b: 1} -> {a: {b: 1}}
    """

    new_config: MutableMapping[str, Any] = {}

    for k, v in d.items():
        if "." in k:
            sub_keys = k.split(".")
            sub_d = new_config
            for sk in sub_keys[:-1]:
                sub_d = sub_d.setdefault(sk, {})
            sub_d[sub_keys[-1]] = v
        else:
            new_config[k] = v

    return new_config


# Small modification to the arg parser so that the error raised by
# providing invalid args is clearer and does not print a confusing
# system exit error.
class ArgumentError(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def get_arg_updated_config_dict(args: Sequence[str], config_dict: Dict[str, Any]):
    """
    Update a configuration dictionary with keyword arguments through an ArgParser.

    Note: A current limitation of this update style is that we cannot provide
        arbitrary arguments to the parser.  Therefore, value being updated should
        either be a member of passed in configuration

    Args:
        args: a list of argument strings to parse
        config_dict: the configuration to update
    """
    config = to_flat_dict(config_dict)
    parser = ArgumentParser()
    _add_items_to_parser_arguments(config, parser)
    try:
        updates = parser.parse_args(args)
    except ArgumentError as e:
        raise e

    update_dict = vars(updates)
    config.update(update_dict)
    return to_nested_dict(config)


@dataclasses.dataclass
class RandomForestHyperparameters(Hyperparameters):
    """
    Configuration for training a random forest based model.

    Trains one random forest for each training batch provided.

    For more information about these settings, see documentation for
    `sklearn.ensemble.RandomForestRegressor`.

    Args:
        input_variables: names of variables to use as inputs
        output_variables: names of variables to use as outputs
        scaler_type: scaler to use for training, must be "standard" or "mass"
        scaler_kwargs: keyword arguments to pass to scaler initialization
        n_jobs: number of jobs to run in parallel when training a single random forest
        random_state: random seed to use when building trees, will be
            deterministically perturbed for each training batch
        n_estimators: the number of trees in each forest
        max_depth: maximum depth of each tree, by default is unlimited
        min_samples_split: minimum number of samples required to split an internal node
        min_samples_leaf: minimum number of samples required to be at a leaf node
        max_features: number of features to consider when looking for the best split,
            if string should be "sqrt", "log2", or "auto" (default), which correspond
            to the square root, log base 2, or total number of features respectively
        max_samples: if bootstrap is True, number of samples to draw
            for each base estimator
        bootstrap: whether bootstrap samples are used when building trees.
            If False, the whole dataset is used to build each tree.
        packer_config: configuration of dataset packing.
        predict_columns: If true (default), assume vertical dimension is unstacked when
            making predictions. If False, stack all dimensions.
    """

    input_variables: List[str]
    output_variables: List[str]

    scaler_type: str = "standard"
    scaler_kwargs: Optional[Mapping] = None

    # don't set default to -1 because it causes non-reproducible training
    n_jobs: int = 8
    random_state: int = 0
    n_estimators: int = 100
    max_depth: Optional[int] = None
    min_samples_split: Union[int, float] = 2
    min_samples_leaf: Union[int, float] = 1
    max_features: Union[str, int, float] = "auto"
    max_samples: Optional[Union[int, float]] = None
    bootstrap: bool = True
    packer_config: PackerConfig = dataclasses.field(
        default_factory=lambda: PackerConfig({})
    )
    predict_columns: bool = True

    @property
    def variables(self) -> Set[str]:
        if self.scaler_type == "mass":
            additional_variables = ["pressure_thickness_of_atmospheric_layer"]
        else:
            additional_variables = []
        return (
            set(self.input_variables)
            .union(self.output_variables)
            .union(additional_variables)
        )


@dataclasses.dataclass
class MinMaxNoveltyDetectorHyperparameters(Hyperparameters):
    """
    Configuration for training a min-max novelty detection algorithm.

    Args:
        input_variables: names of variables to use as inputs.
        packer_config: configuration of dataset packing.
    """

    input_variables: List[str]
    packer_config: PackerConfig = dataclasses.field(
        default_factory=lambda: PackerConfig({})
    )

    @property
    def variables(self) -> Set[str]:
        return set(self.input_variables)

    @classmethod
    def init_testing(
        cls, input_variables, output_variables
    ) -> "MinMaxNoveltyDetectorHyperparameters":
        """Initialize a default instance for a given input/output problem"""
        hyperparameters = cls(input_variables=input_variables)
        return hyperparameters


@dataclasses.dataclass
class OCSVMNoveltyDetectorHyperparameters(Hyperparameters):
    """
    Configuration for training an OCSVM detection algorithm with an RBF kernel. See
    https://scikit-learn.org/stable/modules/generated/sklearn.svm.OneClassSVM.html
    for a discussion of some parameters for the sklearn model.

    Args:
        input_variables: names of variables to use as inputs.
        packer_config: configuration of dataset packing.
        gamma: kernel coefficient, default = 1 / #features
        nu: fraction of training samples as support vectors, default = 0.1
        max_iter: maximum number of iterations to convergence, default = -1 (unlimited)
    """

    input_variables: List[str]
    packer_config: PackerConfig = dataclasses.field(
        default_factory=lambda: PackerConfig({})
    )
    gamma: Union[float, str] = "auto"
    nu: float = 0.01
    max_iter: int = -1

    @property
    def variables(self) -> Set[str]:
        return set(self.input_variables)

    @classmethod
    def init_testing(
        cls, input_variables, output_variables
    ) -> "OCSVMNoveltyDetectorHyperparameters":
        """Initialize a default instance for a given input/output problem"""
        hyperparameters = cls(input_variables=input_variables)
        return hyperparameters
