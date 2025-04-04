import numpy as np
from scipy import sparse

from fv3fit.reservoir import (
    ReservoirComputingModel,
    ReservoirComputingReadout,
    Reservoir,
    ReservoirHyperparameters,
)
from fv3fit.reservoir.config import (
    ReadoutHyperparameters,
    BatchLinearRegressorHyperparameters,
)


def generic_readout(**readout_kwargs):
    lr_config = BatchLinearRegressorHyperparameters(
        l2=0, add_bias_term=True, use_least_squares_solve=True
    )
    readout_hyperparameters = ReadoutHyperparameters(
        linear_regressor_config=lr_config, square_half_hidden_state=False
    )
    return ReservoirComputingReadout(readout_hyperparameters, **readout_kwargs)


class MultiOutputMeanRegressor:
    def __init__(self, n_outputs: int):
        self.n_outputs = n_outputs

    def predict(self, input):
        # returns array of shape (1, n_outputs), with each element
        # the mean of the input vector elements
        return np.full(self.n_outputs, np.mean(input)).reshape(1, -1)


def _sparse_allclose(A, B, atol=1e-8):
    # https://stackoverflow.com/a/47771340
    r1, c1, v1 = sparse.find(A)
    r2, c2, v2 = sparse.find(B)
    index_match = np.array_equal(r1, r2) & np.array_equal(c1, c2)
    if index_match == 0:
        return False
    else:
        return np.allclose(v1, v2, atol=atol)


def test_dump_load_preserves_matrices(tmpdir):
    input_size = 10
    state_size = 150
    hyperparameters = ReservoirHyperparameters(
        state_size=state_size,
        adjacency_matrix_sparsity=0.0,
        spectral_radius=1.0,
        input_coupling_sparsity=0,
    )
    reservoir = Reservoir(hyperparameters, input_size=input_size)
    readout = generic_readout(
        coefficients=np.random.rand(input_size, state_size),
        intercepts=np.random.rand(input_size),
    )
    predictor = ReservoirComputingModel(reservoir=reservoir, readout=readout,)
    output_path = f"{str(tmpdir)}/predictor"
    predictor.dump(output_path)

    loaded_predictor = ReservoirComputingModel.load(output_path)
    assert _sparse_allclose(loaded_predictor.reservoir.W_in, predictor.reservoir.W_in)
    assert _sparse_allclose(loaded_predictor.reservoir.W_res, predictor.reservoir.W_res)
    np.testing.assert_array_almost_equal(
        loaded_predictor.readout.coefficients, predictor.readout.coefficients
    )
    np.testing.assert_array_almost_equal(
        loaded_predictor.readout.intercepts, predictor.readout.intercepts
    )


def test_prediction_shape():
    input_size = 15
    hyperparameters = ReservoirHyperparameters(
        state_size=1000,
        adjacency_matrix_sparsity=0.9,
        spectral_radius=1.0,
        input_coupling_sparsity=0,
    )
    reservoir = Reservoir(hyperparameters, input_size=input_size)
    reservoir.reset_state(input_shape=(input_size,))
    readout = generic_readout()
    readout.fit(reservoir.state.reshape(1, -1), np.ones((1, input_size)))
    predictor = ReservoirComputingModel(reservoir=reservoir, readout=readout,)
    # ReservoirComputingModel.predict reshapes the prediction to remove
    # the first dim of length 1 (sklearn regressors predict 2D arrays)
    assert predictor.predict().shape == (input_size,)


def test_ReservoirComputingModel_state_increment():
    input_size = 2
    state_size = 3
    hyperparameters = ReservoirHyperparameters(
        state_size=state_size,
        adjacency_matrix_sparsity=0.0,
        spectral_radius=1.0,
        input_coupling_sparsity=0,
    )
    reservoir = Reservoir(hyperparameters, input_size=input_size)
    reservoir.W_in = sparse.coo_matrix(np.ones(reservoir.W_in.shape))
    reservoir.W_res = sparse.coo_matrix(np.ones(reservoir.W_res.shape))

    readout = MultiOutputMeanRegressor(n_outputs=input_size)
    predictor = ReservoirComputingModel(reservoir=reservoir, readout=readout,)

    input = np.array([0.5, 0.5])
    predictor.reservoir.reset_state(input_shape=input.shape)
    predictor.reservoir.increment_state(input)
    state_before_prediction = predictor.reservoir.state
    prediction = predictor.predict()
    np.testing.assert_array_almost_equal(prediction, np.tanh(np.array([1.0, 1.0])))
    assert not np.allclose(state_before_prediction, predictor.reservoir.state)


def test_prediction_after_load(tmpdir):
    input_size = 15
    state_size = 1000
    hyperparameters = ReservoirHyperparameters(
        state_size=state_size,
        adjacency_matrix_sparsity=0.9,
        spectral_radius=1.0,
        input_coupling_sparsity=0,
    )
    reservoir = Reservoir(hyperparameters, input_size=input_size)
    readout = generic_readout()
    readout.fit(np.random.rand(1, state_size), np.ones((1, input_size)))
    predictor = ReservoirComputingModel(reservoir=reservoir, readout=readout,)
    predictor.reservoir.reset_state(input_shape=(input_size,))

    ts_sync = [np.ones(input_size) for i in range(20)]
    predictor.reservoir.synchronize(ts_sync)
    for i in range(10):
        prediction0 = predictor.predict()

    output_path = f"{str(tmpdir)}/predictor"
    predictor.dump(output_path)
    loaded_predictor = ReservoirComputingModel.load(output_path)
    loaded_predictor.reservoir.reset_state(input_shape=(input_size,))

    loaded_predictor.reservoir.synchronize(ts_sync)
    for i in range(10):
        prediction1 = loaded_predictor.predict()

    np.testing.assert_array_almost_equal(prediction0, prediction1)
