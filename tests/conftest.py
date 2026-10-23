import pytest

import testdata


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    """All synthetic test files, written once per run."""
    d = tmp_path_factory.mktemp("testdata")
    testdata.write(str(d))
    return d


@pytest.fixture(scope="session")
def reference():
    """name -> exact reference geometry (independent of the parsers), for every file that has one."""
    ref = {name: geom for name, (_, geom) in testdata.TESTS.items()}
    ref.update({name: geom for name, (_, geom) in testdata.DRILLS.items()})
    return ref


@pytest.fixture(scope="session")
def synth():
    """The synthetic 80 x 50 mm board: (files, exact reference geometries)."""
    return testdata.synth_board()
