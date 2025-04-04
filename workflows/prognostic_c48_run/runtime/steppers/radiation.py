import dataclasses
from typing import Optional, Literal, Union, Tuple
import cftime
import xarray as xr
from runtime.steppers.machine_learning import MachineLearningConfig, PureMLStepper
from runtime.steppers.prescriber import PrescriberConfig, Prescriber
from runtime.types import State, Diagnostics
from radiation import Radiation


@dataclasses.dataclass
class RadiationStepperConfig:
    """Configuration for a stepper object to run the python radiation scheme.


    Attributes:
        kind: "python" is the only current option
        input_generator: optional configuration for a prescriber or machine learning
            model, which will be used to provide the inputs for the radiation scheme

    """

    kind: Literal["python"]
    input_generator: Optional[Union[PrescriberConfig, MachineLearningConfig]] = None


class RadiationStepper:

    label = "radiation"

    def __init__(
        self,
        radiation: Radiation,
        input_generator: Optional[Union[PureMLStepper, Prescriber]] = None,
    ):
        self._radiation = radiation
        self._input_generator = input_generator

    def __call__(
        self, time: cftime.DatetimeJulian, state: State,
    ):
        state = self._generate_inputs(state, time)
        diagnostics = self._radiation(time, state)
        return {}, diagnostics, {}

    def get_diagnostics(self, state, tendency) -> Tuple[Diagnostics, xr.DataArray]:
        return {}, xr.DataArray()

    def _generate_inputs(self, state: State, time: cftime.DatetimeJulian) -> State:
        required_names = self._radiation.input_variables
        inputs = {name: state[name] for name in required_names}
        if self._input_generator is not None:
            _, _, state_updates = self._input_generator(time, state)
            return {**inputs, **state_updates}
        else:
            return inputs
