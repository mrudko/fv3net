import argparse
import sys
import dacite
from dataclasses import dataclass, field
import fsspec
import json
import logging
from fv3fit.emulation.zhao_carr.loss import ZhaoCarrLoss
from fv3net.artifacts.metadata import StepMetadata, log_fact_json
import numpy as np
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Union
from fv3fit._shared.training_config import (
    register_training_function,
    get_arg_updated_config_dict,
    to_nested_dict,
)
from fv3fit.emulation.models import Model
from fv3fit.emulation.transforms.zhao_carr import PrecpdOnly
from fv3fit.dataclasses import asdict_with_enum as _asdict_with_enum
from fv3fit.emulation.data.transforms import expand_single_dim_data
from fv3fit import tfdataset

import tensorflow as tf
import yaml

from fv3fit import set_random_seed
from fv3fit._shared import put_dir
from fv3fit._shared.config import OptimizerConfig
from fv3fit._shared.hyperparameters import Hyperparameters
from fv3fit.emulation.layers.normalization2 import MeanMethod, StdDevMethod
from fv3fit.keras._models.shared.pure_keras import PureKerasDictPredictor
from fv3fit.keras.jacobian import compute_jacobians, nondimensionalize_jacobians

from fv3fit.data.netcdf.load import nc_dir_to_tfdataset

from fv3fit.emulation.transforms.factories import ConditionallyScaled
from fv3fit.emulation.types import LossFunction, TensorDict
from fv3fit.emulation import train, ModelCheckpointCallback
from fv3fit.emulation.data import TransformConfig
from fv3fit.emulation.data.config import SliceConfig
from fv3fit.emulation.layers import ArchitectureConfig
from fv3fit.emulation.keras import save_model
from fv3fit.emulation.losses import CustomLoss
from fv3fit.emulation.models import (
    transform_model,
    MicrophysicsConfig,
)
from fv3fit.emulation.transforms import (
    ComposedTransformFactory,
    Difference,
    TensorTransform,
    TransformedVariableConfig,
    CloudWaterDiffPrecpd,
    MicrophysicsClasssesV1,
    MicrophysicsClassesV1OneHot,
    GscondRoute,
)
from fv3fit.emulation.transforms.zhao_carr import (
    CloudLimiter,
    RelativeHumidity,
)
from fv3fit.emulation.zhao_carr.models import PrecpdModelConfig
from fv3fit.emulation.zhao_carr.filters import HighAntarctic
from fv3fit.emulation.flux import TendencyToFlux, MoistStaticEnergyTransform

from fv3fit.emulation.layers.normalization import standard_deviation_all_features
from fv3fit.wandb import (
    WandBConfig,
    store_model_artifact,
    plot_all_output_sensitivities,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TransformedParameters",
    "MicrophysicsConfig",
    "CustomLoss",
    "TransformedVariableConfig",
    "ConditionallyScaled",
    "Difference",
    "WandBConfig",
    "ArchitectureConfig",
    "SliceConfig",
    "TransformT",
    "OptimizerConfig",
]

TransformT = Union[
    TransformedVariableConfig,
    ConditionallyScaled,
    Difference,
    CloudWaterDiffPrecpd,
    MicrophysicsClasssesV1,
    MicrophysicsClassesV1OneHot,
    TendencyToFlux,
    MoistStaticEnergyTransform,
    GscondRoute,
    PrecpdOnly,
    CloudLimiter,
    RelativeHumidity,
]

FilterT = Union[HighAntarctic]


def load_config_yaml(path: str) -> Dict[str, Any]:
    """
    Load yaml from local/remote location
    """

    with fsspec.open(path, "r") as f:
        d = yaml.safe_load(f)

    return d


@dataclass
class TransformedParameters(Hyperparameters):
    """
    Configuration for training a microphysics emulator

    Args:
        transform: Data preprocessing TransformConfig
        tensor_transform: specification of differerentiable tensorflow
            transformations to apply before and after data is passed to models and
            losses.
        model: MicrophysicsConfig used to build the keras model
        use_wandb: Enable wandb logging of training, requires that wandb is installed
            and initialized
        wandb: WandBConfig to set up the wandb logged run
        loss:  Configuration of the keras loss to prepare and use for training
        epochs: Number of training epochs
        batch_size: batch size applied to tf datasets during training
        valid_freq: How often to score validation data (in epochs)
        verbose: Verbosity of keras fit output
        shuffle_buffer_size: How many samples to keep in the keras shuffle buffer
            during training
        out_url:  where to save checkpoints
        checkpoint_model: if true, save a checkpoint after each epoch

    Example:

    .. code-block:: yaml

        model_type: transformed
        hyperparameters:
            epochs: 1
            loss:
                loss_variables: [dQ2]
            model:
                architecture:
                    name: dense
                direct_out_variables:
                - dQ2
                input_variables:
                - air_temperature
                - specific_humidity
                - cos_zenith_angle
            use_wandb: false

    """

    tensor_transform: List[TransformT] = field(default_factory=list)
    filters: List[FilterT] = field(default_factory=list)
    model: Union[PrecpdModelConfig, MicrophysicsConfig, None] = None
    loss: Union[CustomLoss, ZhaoCarrLoss] = field(default_factory=CustomLoss)
    epochs: int = 1
    batch_size: int = 128
    valid_freq: int = 5
    verbose: int = 2
    shuffle_buffer_size: Optional[int] = 13824
    # only model checkpoints are saved at out_url, but need to keep these name
    # for backwards compatibility
    checkpoint_model: bool = True
    checkpoint_interval: int = 1
    out_url: str = ""
    # ideally will refactor these out, but need to insert the callback somehow
    use_wandb: bool = True
    wandb: WandBConfig = field(default_factory=WandBConfig)

    @property
    def filter_variables(self) -> Set[str]:
        out = set()
        for f in self.filters:
            out |= f.input_variables

        return out

    def prepare_flat_data(self, batched: tf.data.Dataset) -> tf.data.Dataset:
        unbatched = (
            batched.map(tfdataset.apply_to_mapping(tfdataset.float64_to_float32))
            .map(expand_single_dim_data)
            .unbatch()
        )
        for filter in self.filters:
            unbatched = unbatched.filter(filter)
        return unbatched

    @property
    def transform_factory(self) -> ComposedTransformFactory:
        return ComposedTransformFactory(self.tensor_transform)

    def build_transform(self, sample: TensorDict) -> TensorTransform:
        return self.transform_factory.build(sample)

    @property
    def _model(self,) -> Model:
        if self.model:
            return self.model
        else:
            raise ValueError(".model not provided.")

    def build_model(
        self, data: Mapping[str, tf.Tensor], transform: TensorTransform
    ) -> tf.keras.Model:
        inputs = {
            name: tf.keras.Input(
                data[name].shape[1:], name=name, dtype=data[name].dtype
            )
            for name in self.input_variables
        }
        inner_model = self._model.build(transform.forward(data))
        return transform_model(inner_model, transform, inputs)

    def build_loss(
        self, data: Mapping[str, tf.Tensor], transform: TensorTransform
    ) -> LossFunction:
        return self.loss.build(transform.forward(data))

    @property
    def input_variables(self) -> Set[str]:
        backward_transform_inputs = self.transform_factory.backward_input_names()
        model_inputs = set(self._model.input_variables)
        model_outputs = set(self._model.output_variables)

        required_for_model = self.transform_factory.backward_names(model_inputs)
        required_for_backward = self.transform_factory.backward_names(
            backward_transform_inputs - model_outputs
        )
        return required_for_model | required_for_backward

    @property
    def model_variables(self) -> Set[str]:
        names_forward_must_make = (
            set(self.loss.loss_variables)
            - self.transform_factory.backward_output_names()
        )
        loss_variables = self.transform_factory.backward_names(names_forward_must_make)

        return (
            self.transform_factory.backward_names(
                set(self._model.input_variables)
                | set(self._model.output_variables)
                | self.transform_factory.backward_input_names()
                | loss_variables
            )
            | self.filter_variables
        )

    @property
    def variables(self) -> Set[str]:
        return self.model_variables

    @classmethod
    def init_testing(cls, input_variables, output_variables) -> "TransformedParameters":
        """used for testing"""
        return TransformedParameters(
            model=MicrophysicsConfig(
                input_variables=input_variables,
                direct_out_variables=output_variables,
                architecture=ArchitectureConfig("dense"),
            ),
            loss=CustomLoss(loss_variables=output_variables),
            use_wandb=False,
        )


# Temporarily subclass from the hyperparameters object for backwards compatibility
# we can delete this class once usage has switched to fv3fit.train
@dataclass
class TrainConfig(TransformedParameters):
    """
    Configuration for training a microphysics emulator

    Attributes:

        train_url: Path to training data (already in [sample x feature] format)
        test_url: Path to validation data (already in [sample x feature] format)
        transform: Data preprocessing TransformConfig
        nfiles: Number of files to use from train_url
        nfiles_valid: Number of files to use from test_url
        log_level: what logging level to use
        save_only: If true, don't train, but save the train and test data with
            tf.data.experimental.save to ``out_url``
        data_format: one of ['nc', 'tf']. The data format of datasets at
            ``train_url`` and ``test_url``.
    """

    train_url: str = ""
    test_url: str = ""
    transform: TransformConfig = field(default_factory=TransformConfig)
    nfiles: Optional[int] = None
    nfiles_valid: Optional[int] = None
    log_level: str = "INFO"
    save_only: bool = False
    data_format: str = "nc"
    nc_file_match: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrainConfig":
        """Standard init from nested dictionary"""
        # casting necessary for 'from_args' which all come in as string
        # TODO: should this be just a json parsed??
        config = dacite.Config(
            strict=True, cast=[bool, str, int, float, StdDevMethod, MeanMethod]
        )
        return dacite.from_dict(cls, d, config=config)

    @classmethod
    def from_flat_dict(cls, d: Dict[str, Any]) -> "TrainConfig":
        """
        Init from a dictionary flattened in the style of wandb configs
        where all nested mapping keys are flattened to the top level
        by joining with a '.'

        E.g.:
        {
            "test_url": "gs://bucket/path/to/blobs",
            "model.input_variables": ["var1", "var2"],
            "model.architecture.name": "rnn",
            ...
        }
        """
        d = to_nested_dict(d)
        return cls.from_dict(d)

    @classmethod
    def from_yaml_path(cls, path: str) -> "TrainConfig":
        """Init from path to yaml file"""
        d = load_config_yaml(path)
        return cls.from_dict(d)

    @classmethod
    def from_args(cls, args: Optional[Sequence[str]] = None):
        """
        Init from commandline arguments (or provided arguments).  If no args
        are provided, uses sys.argv to parse.

        Note: A current limitation of this init style is that we cannot provide
        arbitrary arguments to the parser.  Therefore, value being updated should
        either be a member of the default config or the file specified by
        --config-path

        Args:
            args: A list of arguments to be parsed.  If not provided, uses
                sys.argv

                Requires "--config-path"

                Note: arguments should be in the flat style used by wandb where all
                nested mappings are at the top level with '.' joined keys. E.g.,
                "--model.architecture.name rnn"
        """

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--config-path", required=True, help="Path to training config yaml.",
        )

        path_arg, unknown_args = parser.parse_known_args(args=args)
        config = cls.from_yaml_path(path_arg.config_path)

        if unknown_args:
            updated = get_arg_updated_config_dict(
                unknown_args, _asdict_with_enum(config)
            )
            config = cls.from_dict(updated)

        return config

    def to_yaml(self) -> str:
        return yaml.safe_dump(_asdict_with_enum(self))

    def _open_dataset(
        self,
        url: str,
        nfiles: Optional[int],
        required_variables: Set[str],
        nc_file_match: Optional[str] = None,
    ) -> tf.data.Dataset:
        pipeline = self.transform.get_pipeline(required_variables)
        return nc_dir_to_tfdataset(
            url,
            convert=pipeline,
            nfiles=nfiles,
            shuffle=True,
            random_state=np.random.RandomState(0),
            match=nc_file_match,
        )

    def open_dataset(
        self,
        url: str,
        nfiles: Optional[int],
        required_variables: Set[str],
        nc_file_match: Optional[str] = None,
    ) -> tf.data.Dataset:
        if self.data_format == "nc":
            return self._open_dataset(
                url, nfiles, required_variables, nc_file_match=nc_file_match
            )
        elif self.data_format == "tf":
            # needs to be batched
            return tf.data.experimental.load(url).batch(1)
        else:
            raise NotImplementedError(self.data_format)

    def open_train_test(self):
        train = self.open_dataset(
            self.train_url,
            self.nfiles,
            self.model_variables,
            nc_file_match=self.nc_file_match,
        )
        test = self.open_dataset(
            self.test_url,
            self.nfiles_valid,
            self.model_variables,
            nc_file_match=self.nc_file_match,
        )
        train_ds = self.prepare_flat_data(train)
        test_ds = self.prepare_flat_data(test) if test else None
        return train_ds, test_ds


def save_jacobians(std_jacobians, dir_, filename="jacobians.npz"):
    with put_dir(dir_) as tmpdir:
        dumpable = {
            f"{out_name}/{in_name}": data
            for out_name, sensitivities in std_jacobians.items()
            for in_name, data in sensitivities.items()
        }
        np.savez(os.path.join(tmpdir, filename), **dumpable)


@register_training_function("transformed", TransformedParameters)
def train_function(
    hyperparameters: TransformedParameters,
    train_batches: tf.data.Dataset,
    validation_batches: Optional[tf.data.Dataset],
) -> PureKerasDictPredictor:
    train = hyperparameters.prepare_flat_data(train_batches)
    validation = (
        hyperparameters.prepare_flat_data(validation_batches)
        if validation_batches
        else None
    )
    return _train_function_unbatched(hyperparameters, train, validation)


def _train_function_unbatched(
    config: TransformedParameters,
    train_ds: tf.data.Dataset,
    test_ds: Optional[tf.data.Dataset],
) -> PureKerasDictPredictor:
    # callbacks that are always active
    callbacks = [tf.keras.callbacks.TerminateOnNaN()]

    if config.use_wandb:
        config.wandb.init(config=_asdict_with_enum(config))
        callbacks.append(config.wandb.get_callback())

    if config.shuffle_buffer_size is not None:
        train_ds = train_ds.shuffle(config.shuffle_buffer_size)

    train_set = next(iter(train_ds.batch(150_000)))

    transform = config.build_transform(train_set)

    train_ds = train_ds.map(transform.forward)

    model = config.build_model(train_set, transform)

    if config.checkpoint_model:
        callbacks.append(
            ModelCheckpointCallback(
                filepath=os.path.join(
                    config.out_url, "checkpoints", "epoch.{epoch:03d}.tf"
                ),
                interval=config.checkpoint_interval,
            )
        )

    train_ds_batched = train_ds.batch(config.batch_size).prefetch(tf.data.AUTOTUNE)

    if test_ds is not None:
        test_ds = test_ds.map(transform.forward)
        test_ds_batched = test_ds.batch(config.batch_size).prefetch(tf.data.AUTOTUNE)
    else:
        test_ds_batched = None

    history = train(
        model,
        train_ds_batched,
        config.build_loss(train_set, transform),
        optimizer=config.loss.optimizer.instance,
        epochs=config.epochs,
        validation_data=test_ds_batched,
        validation_freq=config.valid_freq,
        verbose=config.verbose,
        callbacks=callbacks,
    )

    return PureKerasDictPredictor(
        model, passthrough=(model, transform, history, train_set)
    )


def train_main(config: TrainConfig):
    start = time.perf_counter()
    train_ds = config.open_dataset(
        config.train_url, config.nfiles, config.model_variables
    )
    test_ds = config.open_dataset(
        config.test_url, config.nfiles_valid, config.model_variables
    )

    StepMetadata(
        job_type="train",
        url=config.out_url,
        dependencies={"train_data": config.train_url, "test_data": config.test_url},
        args=sys.argv[1:],
    ).print_json()

    predictor = train_function(config, train_ds, test_ds)
    model, transform, history, train_set = predictor.passthrough  # type: ignore

    logger.debug("Training complete")

    with put_dir(config.out_url) as tmpdir:

        with open(os.path.join(tmpdir, "history.json"), "w") as f:
            json.dump(history.params, f)

        with open(os.path.join(tmpdir, "config.yaml"), "w") as f:
            f.write(config.to_yaml())

        local_model_path = save_model(model, tmpdir)

        if config.use_wandb:
            store_model_artifact(local_model_path, name=config._model.name)

    end = time.perf_counter()
    log_fact_json(data={"train_time_seconds": end - start})

    # Jacobians after model storing in case of "out of memory" errors
    sample = transform.forward(train_set)
    jacobians = compute_jacobians(model, sample, config.input_variables)
    std_factors = {
        name: np.array(float(standard_deviation_all_features(data)))
        for name, data in sample.items()
        if data.dtype != tf.bool
    }
    std_jacobians = nondimensionalize_jacobians(jacobians, std_factors)

    save_jacobians(std_jacobians, config.out_url, "jacobians.npz")
    if config.use_wandb:
        plot_all_output_sensitivities(std_jacobians)


def save(config: TrainConfig):
    path = config.out_url
    logger.info(f"saving training and validation data to {path}")
    train, test = config.open_train_test()
    path = path.rstrip("/")
    tf.data.experimental.save(train, f"{path}/train")
    tf.data.experimental.save(test, f"{path}/test")

    # upload config
    with put_dir(config.out_url) as tmpdir:
        with open(os.path.join(tmpdir, "config.yaml"), "w") as f:
            f.write(config.to_yaml())


def main(config: TrainConfig, seed: int = 0):
    logging.basicConfig(level=getattr(logging, config.log_level))
    set_random_seed(seed)
    if config.save_only:
        return save(config)
    else:
        return train_main(config)


if __name__ == "__main__":

    config = TrainConfig.from_args()
    main(config)
