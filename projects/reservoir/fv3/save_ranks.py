import argparse
import intake
import logging
import os
from tempfile import NamedTemporaryFile
import toolz

from .cubed_sphere import CubedSphereDivider
import vcm

logging.basicConfig()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "data_path", type=str, default=None, help=("Path with training data zarr."),
    )
    parser.add_argument(
        "output_path",
        type=str,
        help="Local or remote path where output will be written.",
    )
    parser.add_argument(
        "layout_width",
        type=int,
        default=1,
        help=(
            "Width of rank layout within each tile, ex. layout_width=2 corresponds "
            "to (2,2) layout with four ranks per tile. Defaults to 1 rank per tile."
        ),
    )
    parser.add_argument(
        "overlap",
        type=int,
        help="Number of grid cells overlapping between training subdomains.",
    )
    parser.add_argument(
        "--start-time",
        type=str,
        default=None,
        help=(
            "First timestep in time series. Provide a string 'YYYYMMDD.HHMMSS'. "
            "If not provided, will use the first timestep in dataset."
        ),
    )
    parser.add_argument(
        "--stop-time",
        type=str,
        default=None,
        help=(
            "Last timestep in time series. Provide a string 'YYYYMMDD.HHMMSS'. "
            "If not provided, will use the last timestep in dataset."
        ),
    )
    parser.add_argument(
        "--time-chunks",
        type=int,
        default=None,
        help=("Number of timesteps to save per rank netcdf."),
    )
    parser.add_argument("--variables", type=str, nargs="+", default=[])

    return parser


def get_ordered_dims_extent(dims: dict):
    # tile must be first in dims list
    dims_, extent_ = [], []

    for d in ["tile", "x", "y"]:
        dims_.append(d)
        extent_.append(dims.pop(d))
    for k, v in dims.items():
        dims_.append(k)
        extent_.append(v)
    return dims_, extent_


if __name__ == "__main__":
    parser = _get_parser()
    args = parser.parse_args()

    if len(args.variables) == 0:
        raise ValueError("--variables must be provided via list of string names.")

    data = intake.open_zarr(args.data_path).to_dask()

    tstart = (
        data.time.values[0]
        if args.start_time is None
        else vcm.parse_datetime_from_str(args.start_time)
    )
    tstop = (
        data.time.values[-1]
        if args.stop_time is None
        else vcm.parse_datetime_from_str(args.stop_time)
    )

    data = data[args.variables].sel(time=slice(tstart, tstop))
    dims, extent = get_ordered_dims_extent(dict(data.dims))

    cubedsphere_divider = CubedSphereDivider(
        tile_layout=(args.layout_width, args.layout_width),
        global_dims=dims,
        global_extent=extent,
    )

    data_times = data.time.values
    if args.time_chunks:
        time_chunks = [
            list(t) for t in toolz.partition_all(args.time_chunks, data_times)
        ]
    else:
        time_chunks = [list(data_times)]

    for t, time_chunk in enumerate(time_chunks):
        data_time_slice = data.sel(time=time_chunk).load()
        for r in range(cubedsphere_divider.total_ranks):
            output_dir = os.path.join(args.output_path, f"rank_{r}")
            rank_output_path = os.path.join(output_dir, f"{t}.nc")
            rank_data = cubedsphere_divider.get_rank_data(
                data_time_slice, rank=r, overlap=args.overlap
            )

            with NamedTemporaryFile() as tmpfile:
                rank_data.to_netcdf(tmpfile.name)
                vcm.get_fs(output_dir).put(tmpfile.name, rank_output_path)
            logger.info(f"Writing netcdf to {rank_output_path}")
