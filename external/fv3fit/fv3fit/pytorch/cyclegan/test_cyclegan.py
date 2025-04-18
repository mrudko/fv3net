import numpy as np
import xarray as xr
from typing import Sequence
from fv3fit.pytorch.cyclegan import (
    CycleGANHyperparameters,
    CycleGANNetworkConfig,
    CycleGANTrainingConfig,
    train_cyclegan,
)
from fv3fit.data import CycleGANLoader, SyntheticWaves, SyntheticNoise
import fv3fit.tfdataset
import collections
import os
import fv3fit.pytorch
import fv3fit
import matplotlib.pyplot as plt
import pytest
import fv3fit.wandb


def get_tfdataset(nsamples, nbatch, ntime, nx, nz):
    config = CycleGANLoader(
        domain_configs=[
            SyntheticWaves(
                nsamples=nsamples,
                nbatch=nbatch,
                ntime=ntime,
                nx=nx,
                nz=nz,
                scalar_names=["var_2d"],
                scale_min=0.5,
                scale_max=1.0,
                period_min=8,
                period_max=16,
                wave_type="sinusoidal",
            ),
            SyntheticWaves(
                nsamples=nsamples,
                nbatch=nbatch,
                ntime=ntime,
                nx=nx,
                nz=nz,
                scalar_names=["var_2d"],
                scale_min=0.5,
                scale_max=1.0,
                period_min=8,
                period_max=16,
                wave_type="square",
            ),
        ]
    )
    dataset = config.open_tfdataset(
        local_download_path=None, variable_names=["var_3d", "var_2d"]
    )
    return dataset


def get_noise_tfdataset(nsamples, nbatch, ntime, nx, nz):
    config = CycleGANLoader(
        domain_configs=[
            SyntheticNoise(
                nsamples=nsamples,
                nbatch=nbatch,
                ntime=ntime,
                nx=nx,
                nz=nz,
                scalar_names=["var_2d"],
                noise_amplitude=1.0,
            ),
            SyntheticNoise(
                nsamples=nsamples,
                nbatch=nbatch,
                ntime=ntime,
                nx=nx,
                nz=nz,
                scalar_names=["var_2d"],
                noise_amplitude=1.0,
            ),
        ]
    )
    dataset = config.open_tfdataset(
        local_download_path=None, variable_names=["var_3d", "var_2d"]
    )
    return dataset


def tfdataset_to_xr_dataset(tfdataset, dims: Sequence[str]):
    """
    Returns a [time, tile, x, y, z] dataset needed for evaluation.

    Assumes input samples have shape [sample, time, tile, x, y(, z)], will
    concatenate samples along the time axis before returning.
    """
    data_sequences = collections.defaultdict(list)
    for sample in tfdataset:
        for name, value in sample.items():
            data_sequences[name].append(
                value.numpy().reshape(
                    [value.shape[0] * value.shape[1]] + list(value.shape[2:])
                )
            )
    data_vars = {}
    for name in data_sequences:
        data = np.concatenate(data_sequences[name])
        data_vars[name] = xr.DataArray(data, dims=dims[: len(data.shape)])
    return xr.Dataset(data_vars)


@pytest.mark.skip("test is designed to run manually to visualize results")
def test_cyclegan_visual(tmpdir):
    fv3fit.set_random_seed(0)
    # run the test in a temporary directory to delete artifacts when done
    os.chdir(tmpdir)
    # need a larger nx, ny for the sample data here since we're training
    # on whether we can autoencode sin waves, and need to resolve full cycles
    nx = 32
    sizes = {"nbatch": 1, "ntime": 1, "nx": nx, "nz": 2}
    state_variables = ["var_3d", "var_2d"]
    train_tfdataset = get_tfdataset(nsamples=200, **sizes)
    val_tfdataset = get_tfdataset(nsamples=20, **sizes)
    hyperparameters = CycleGANHyperparameters(
        state_variables=state_variables,
        network=CycleGANNetworkConfig(
            generator=fv3fit.pytorch.GeneratorConfig(
                n_convolutions=2, n_resnet=5, max_filters=128, kernel_size=3
            ),
            generator_optimizer=fv3fit.pytorch.OptimizerConfig(
                name="Adam", kwargs={"lr": 0.001}
            ),
            discriminator=fv3fit.pytorch.DiscriminatorConfig(kernel_size=3),
            discriminator_optimizer=fv3fit.pytorch.OptimizerConfig(
                name="Adam", kwargs={"lr": 0.001}
            ),
            identity_weight=0.01,
            cycle_weight=10.0,
            generator_weight=1.0,
            discriminator_weight=0.5,
        ),
        training=CycleGANTrainingConfig(
            n_epoch=30, samples_per_batch=20, validation_batch_size=10
        ),
    )
    with fv3fit.wandb.disable_wandb():
        predictor = train_cyclegan(hyperparameters, train_tfdataset, val_tfdataset)
    # for test, need one continuous series so we consistently flip sign
    real_a = tfdataset_to_xr_dataset(
        train_tfdataset.map(lambda a, b: a), dims=["time", "tile", "x", "y", "z"]
    )
    real_b = tfdataset_to_xr_dataset(
        train_tfdataset.map(lambda a, b: b), dims=["time", "tile", "x", "y", "z"]
    )
    output_a = predictor.predict(real_b, reverse=True)
    reconstructed_b = predictor.predict(output_a)
    output_b = predictor.predict(real_a)
    reconstructed_a = predictor.predict(output_b, reverse=True)
    iz = 0
    i = 0
    fig, ax = plt.subplots(3, 2, figsize=(8, 8))
    vmin = -1.5
    vmax = 1.5
    ax[0, 0].imshow(real_a["var_3d"][0, i, :, :, iz].values, vmin=vmin, vmax=vmax)
    ax[0, 1].imshow(real_b["var_3d"][0, i, :, :, iz].values, vmin=vmin, vmax=vmax)
    ax[1, 0].imshow(output_b["var_3d"][0, i, :, :, iz].values, vmin=vmin, vmax=vmax)
    ax[1, 1].imshow(output_a["var_3d"][0, i, :, :, iz].values, vmin=vmin, vmax=vmax)
    ax[2, 0].imshow(
        reconstructed_a["var_3d"][0, i, :, :, iz].values, vmin=vmin, vmax=vmax
    )
    ax[2, 1].imshow(
        reconstructed_b["var_3d"][0, i, :, :, iz].values, vmin=vmin, vmax=vmax
    )
    ax[0, 0].set_title("real a")
    ax[0, 1].set_title("real b")
    ax[1, 0].set_title("output b")
    ax[1, 1].set_title("output a")
    ax[2, 0].set_title("reconstructed a")
    ax[2, 1].set_title("reconstructed b")
    plt.tight_layout()
    plt.show()


@pytest.mark.slow
@pytest.mark.parametrize("conv_type", ["conv2d", "halo_conv2d"])
def test_cyclegan_runs_without_errors(tmpdir, conv_type: str, regtest):
    fv3fit.set_random_seed(0)
    # run the test in a temporary directory to delete artifacts when done
    os.chdir(tmpdir)
    # need a larger nx, ny for the sample data here since we're training
    # on whether we can autoencode sin waves, and need to resolve full cycles
    nx = 32
    sizes = {"nbatch": 1, "ntime": 1, "nx": nx, "nz": 2}
    state_variables = ["var_3d", "var_2d"]
    train_tfdataset = get_tfdataset(nsamples=5, **sizes)
    val_tfdataset = get_tfdataset(nsamples=2, **sizes)
    hyperparameters = CycleGANHyperparameters(
        state_variables=state_variables,
        network=CycleGANNetworkConfig(
            generator=fv3fit.pytorch.GeneratorConfig(
                n_convolutions=2, n_resnet=5, max_filters=128, kernel_size=3
            ),
            optimizer=fv3fit.pytorch.OptimizerConfig(name="Adam", kwargs={"lr": 0.001}),
            discriminator=fv3fit.pytorch.DiscriminatorConfig(kernel_size=3),
            convolution_type=conv_type,
            identity_weight=0.01,
            cycle_weight=10.0,
            generator_weight=1.0,
            discriminator_weight=0.5,
        ),
        training=CycleGANTrainingConfig(
            n_epoch=2, samples_per_batch=2, validation_batch_size=2
        ),
    )
    with fv3fit.wandb.disable_wandb():
        predictor = train_cyclegan(hyperparameters, train_tfdataset, val_tfdataset)
    # for test, need one continuous series so we consistently flip sign
    real_a = tfdataset_to_xr_dataset(
        train_tfdataset.map(lambda a, b: a), dims=["time", "tile", "x", "y", "z"]
    )
    real_b = tfdataset_to_xr_dataset(
        train_tfdataset.map(lambda a, b: b), dims=["time", "tile", "x", "y", "z"]
    )
    output_a = predictor.predict(real_b, reverse=True)
    reconstructed_b = predictor.predict(output_a)  # noqa: F841
    output_b = predictor.predict(real_a)
    reconstructed_a = predictor.predict(output_b, reverse=True)  # noqa: F841
    # We can't use regtest because the output is not deterministic between platforms,
    # but you can un-comment this and use local-only (do not commit to git) regtest
    # outputs when refactoring the code to ensure you don't change results.
    # import json
    # import vcm.testing
    # regtest.write(json.dumps(vcm.testing.checksum_dataarray_mapping(output_a)))
    # regtest.write(json.dumps(vcm.testing.checksum_dataarray_mapping(reconstructed_b)))
    # regtest.write(json.dumps(vcm.testing.checksum_dataarray_mapping(output_b)))
    # regtest.write(json.dumps(vcm.testing.checksum_dataarray_mapping(reconstructed_a)))
