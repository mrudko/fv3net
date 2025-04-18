"""
Transforms operate on diagnostic function inputs to adjust data before
diagnostic values are calculated.

A transform should take in the transform-specific arguments with a diagnostic
function argument tuple as the final argument and return the adjusted
diagnostic function arguments.
"""

import logging
from typing import Sequence, Tuple, Callable, Optional
import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime, timedelta
import cftime
from vcm import interpolate_to_pressure_levels, minus_column_integrated_moistening

from .constants import HORIZONTAL_DIMS, VERTICAL_DIM, DiagArg

_TRANSFORM_FNS = {}

logger = logging.getLogger(__name__)

SURFACE_TYPE_CODES = {"sea": (0, 2), "land": (1,), "seaice": (2,)}


def add_to_input_transform_fns(func):

    _TRANSFORM_FNS[func.__name__] = func

    return func


def apply(
    transform_func: Callable[[DiagArg], DiagArg],
    *transform_args_partial,
    **transform_kwargs,
):
    """
    Wrapper to apply transform to input diagnostic arguments (tuple of three datasets).
    Transform arguments are specified per diagnostic function to enable a query-style
    operation on input data.

    apply -> wraps diagnostic function in save_prognostic_run_diags and
    returns a new function with an input transform prepended to the diagnostic call.

    I.e., call to diagnostic_function becomes::

        input_transform(*diag_args):
            adjusted_args = transform(*diagargs)
            diagnostic_function(*adjusted_args)

    Args:
        transform_key: name of transform function to call
        transform_args_partial: All transform function specific arguments preceding the
            final diagnostic argument tuple, e.g., [freq_label] for resample_time
        transform_kwargs: Any transform function keyword arguments

    Note: I tried memoizing the current transforms but am unsure
    if it will work on highly mutable datasets.
    """

    def _apply_to_diag_func(diag_func):
        def transform(diag_args):

            logger.debug(
                f"Adding transform, {transform_func.__name__}, "
                f"to diagnostic function: {diag_func.__name__}"
                f"\n\targs: {transform_args_partial}"
                f"\n\tkwargs: {transform_kwargs}"
            )

            # append diagnostic function input to be transformed
            transform_args = (*transform_args_partial, diag_args)

            transformed_diag_args = transform_func(*transform_args, **transform_kwargs)

            return diag_func(transformed_diag_args)

        return transform

    return _apply_to_diag_func


@add_to_input_transform_fns
def resample_time(
    freq_label: str,
    arg: DiagArg,
    time_slice=slice(None, -1),
    inner_join: bool = False,
    method: str = "nearest",
) -> DiagArg:
    """
    Subset times in prognostic and verification data

    Args:
        arg: input arguments to transform prior to the diagnostic calculation
        freq_label: Time resampling frequency label (should be valid input for xarray's
            resampling function)
        time_slice: Index slice to reduce times after frequency resampling.  Omits final
            time by default to work with crashed simulations.
        inner_join: Subset times to the intersection of prognostic and verification
            data. Defaults to False.
        method: how to do resampling. Can be "nearest" or "mean".
    """
    prognostic, verification, grid = arg.prediction, arg.verification, arg.grid
    prognostic = _downsample_only(prognostic, freq_label, method)
    verification = _downsample_only(verification, freq_label, method)

    prognostic = prognostic.isel(time=time_slice)
    if inner_join:
        prognostic, verification = _inner_join_time(prognostic, verification)
    return DiagArg(prognostic, verification, grid)


def _downsample_only(ds: xr.Dataset, freq_label: str, method: str) -> xr.Dataset:
    """Resample in time, only if given freq_label is lower frequency than time
    sampling of given dataset ds"""
    ds_freq = ds.time.values[1] - ds.time.values[0]
    if ds_freq < pd.to_timedelta(freq_label):
        resampled = ds.resample(time=freq_label, label="right")
        if method == "nearest":
            return resampled.nearest()
        elif method == "mean":
            with xr.set_options(keep_attrs=True):
                return resampled.mean()
        else:
            raise ValueError(f"Don't know how to resample with method={method}.")
    else:
        return ds


@add_to_input_transform_fns
def skip_if_3d_output_absent(arg: DiagArg) -> DiagArg:
    prognostic, verification, grid = arg.prediction, arg.verification, arg.grid
    dummy_ds = xr.Dataset().assign_coords(
        {
            "time": [
                cftime.DatetimeJulian(2020, 1, 1, 12),
                cftime.DatetimeJulian(2020, 1, 1, 15, 30),
            ]
        }
    )
    prog = prognostic if len(prognostic) > 0 else dummy_ds
    verif = verification if len(verification) > 0 else dummy_ds

    return DiagArg(prog, verif, grid)


@add_to_input_transform_fns
def daily_mean(split: timedelta, arg: DiagArg) -> DiagArg:
    """Resample time to daily mean for all times after split.

    Args:
        split: time since start of prognostic run after which resampling occurs
        arg: input arguments to transform prior to the diagnostic calculation
    """
    prognostic, verification, grid = arg.prediction, arg.verification, arg.grid

    if "time" in prognostic and prognostic.time.size > 0:
        split_time = prognostic.time.values[0] + split
        prognostic = _resample_end(prognostic, split_time, "1D")
        verification = _resample_end(verification, split_time, "1D")
        return DiagArg(prognostic, verification, grid)
    else:
        return DiagArg(xr.Dataset(), xr.Dataset(), grid)


def _resample_end(ds: xr.Dataset, split: datetime, freq_label: str) -> xr.Dataset:
    start_segment = ds.sel(time=slice(None, split))
    end_segment = ds.sel(time=slice(split, None))
    if end_segment.sizes["time"] != 0:
        with xr.set_options(keep_attrs=True):
            end_segment = end_segment.resample(time=freq_label, label="right").mean()
    return xr.concat([start_segment, end_segment], dim="time")


def _inner_join_time(
    prognostic: xr.Dataset, verification: xr.Dataset
) -> Tuple[xr.Dataset, xr.Dataset]:
    """ Subset times within the prognostic data to be within the verification data,
    as necessary and vice versa, and return the subset datasets
    """

    inner_join_time = xr.merge(
        [
            prognostic.time.rename("prognostic_time"),
            verification.time.rename("verification_time"),
        ],
        join="inner",
    )

    return (
        prognostic.sel(time=inner_join_time.prognostic_time),
        verification.sel(time=inner_join_time.verification_time),
    )


def _mask_vars_with_horiz_dims(ds, surface_type, latitude, land_sea_mask):
    """
    Subset data to variables with specified dimensions before masking
    to prevent odd behavior from variables with non-compliant dims
    (e.g., interfaces)
    """

    spatial_ds_varnames = [
        var_name
        for var_name in ds.data_vars
        if set(HORIZONTAL_DIMS).issubset(set(ds[var_name].dims))
    ]
    masked = xr.Dataset()
    for var in spatial_ds_varnames:
        masked[var] = _mask_array(surface_type, ds[var], latitude, land_sea_mask)

    non_spatial_varnames = list(set(ds.data_vars) - set(spatial_ds_varnames))

    return masked.update(ds[non_spatial_varnames])


@add_to_input_transform_fns
def mask_to_sfc_type(surface_type: str, arg: DiagArg) -> DiagArg:
    """
    Mask prognostic run and verification data to the specified surface type.
    This function does not mask the grid area- if you are taking an
    area-weighted mean, use mask_area instead!

    Args:
        arg: input arguments to transform prior to the diagnostic calculation
        surface_type:  Type of grid locations to leave unmasked
    """
    prognostic, verification, grid = arg.prediction, arg.verification, arg.grid

    masked_prognostic = _mask_vars_with_horiz_dims(
        prognostic, surface_type, grid.lat, grid.land_sea_mask
    )

    masked_verification = _mask_vars_with_horiz_dims(
        verification, surface_type, grid.lat, grid.land_sea_mask
    )

    return DiagArg(masked_prognostic, masked_verification, grid)


@add_to_input_transform_fns
def mask_area(region: str, arg: DiagArg) -> DiagArg:
    """
    Set area variable to zero everywhere outside of specified region.

    Args:
        region: name of region to leave unmasked. Valid options are "global",
            "land", "sea", "seaice", "tropics", "tropics20",
            "positive_net_precipitation" and "negative_net_precipitation"
        arg: input arguments to transform prior to the diagnostic calculation
    """
    prognostic, verification, grid, delp = (
        arg.prediction,
        arg.verification,
        arg.grid,
        arg.delp,
    )

    net_precipitation = (
        _get_net_precipitation(verification, grid.area, delp)
        if "precipitation" in region
        else None
    )

    masked_area = _mask_array(
        region, grid.area, grid.lat, grid.land_sea_mask, net_precipitation
    )

    grid_copy = grid.copy()
    return DiagArg(prognostic, verification, grid_copy.update({"area": masked_area}))


def _get_net_precipitation(
    verification: xr.Dataset, area: xr.DataArray, delp: Optional[xr.DataArray]
) -> xr.DataArray:
    if delp is not None and "Q2" in verification.data_vars:
        return minus_column_integrated_moistening(verification["Q2"], delp)
    else:
        return xr.full_like(area, fill_value=np.nan, dtype=float)


def _mask_array(
    region: str,
    arr: xr.DataArray,
    latitude: xr.DataArray,
    land_sea_mask: xr.DataArray,
    net_precipitation: Optional[xr.DataArray] = None,
) -> xr.DataArray:
    """Mask given DataArray to a specific region."""
    if net_precipitation is None:
        net_precipitation = xr.full_like(arr, fill_value=np.nan)
    if region == "tropics":
        masked_arr = arr.where(abs(latitude) <= 10.0)
    elif region == "tropics15":
        masked_arr = arr.where(abs(latitude) <= 15.0)
    elif region == "tropics20":
        masked_arr = arr.where(abs(latitude) <= 20.0)
    elif region == "global":
        masked_arr = arr.copy()
    elif region == "positive_net_precipitation":
        masked_arr = arr.where(net_precipitation > 0.0)
    elif region == "negative_net_precipitation":
        masked_arr = arr.where(net_precipitation <= 0.0)
    elif region in SURFACE_TYPE_CODES:
        masks = [land_sea_mask == code for code in SURFACE_TYPE_CODES[region]]
        mask_union = masks[0]
        for mask in masks[1:]:
            mask_union = np.logical_or(mask_union, mask)
        masked_arr = arr.where(mask_union)
    else:
        raise ValueError(f"Masking procedure for region '{region}' is not defined.")
    return masked_arr


@add_to_input_transform_fns
def subset_variables(variables: Sequence, arg: DiagArg) -> DiagArg:
    """Subset the variables, without failing if a variable doesn't exist"""
    prognostic, verification, grid = (
        arg.prediction,
        arg.verification,
        arg.grid,
    )
    prognostic_vars = [var for var in variables if var in prognostic]
    verification_vars = [var for var in variables if var in verification]
    return DiagArg(
        prognostic[prognostic_vars], verification[verification_vars], grid, arg.delp,
    )


def _is_3d(da: xr.DataArray):
    return VERTICAL_DIM in da.dims


@add_to_input_transform_fns
def select_3d_variables(arg: DiagArg) -> DiagArg:
    prediction, target, grid, delp = (
        arg.prediction,
        arg.verification,
        arg.grid,
        arg.delp,
    )
    prediction_vars = [var for var in prediction if _is_3d(prediction[var])]
    return DiagArg(prediction[prediction_vars], target[prediction_vars], grid, delp)


@add_to_input_transform_fns
def select_2d_variables(arg: DiagArg) -> DiagArg:
    prediction, target, grid, delp = (
        arg.prediction,
        arg.verification,
        arg.grid,
        arg.delp,
    )
    prediction_vars = [var for var in prediction if not _is_3d(prediction[var])]
    return DiagArg(prediction[prediction_vars], target[prediction_vars], grid, delp)


@add_to_input_transform_fns
def regrid_zdim_to_pressure_levels(arg: DiagArg, vertical_dim=VERTICAL_DIM) -> DiagArg:
    # Regrids to the default pressure grid used in vcm.interpolate_to_pressure_levels,
    # which match those in the ERA-Interim reanalysis dataset
    prediction, target, grid, delp = (
        arg.prediction,
        arg.verification,
        arg.grid,
        arg.delp,
    )
    prediction_regridded, target_regridded = xr.Dataset(), xr.Dataset()
    vertical_prediction_fields = [var for var in prediction if _is_3d(prediction[var])]
    for var in vertical_prediction_fields:
        prediction_regridded[var] = interpolate_to_pressure_levels(
            delp=delp, field=prediction[var], dim=vertical_dim,
        )
        target_regridded[var] = interpolate_to_pressure_levels(
            delp=delp, field=target[var], dim=vertical_dim,
        )
    return DiagArg(prediction_regridded, target_regridded, grid, delp)
