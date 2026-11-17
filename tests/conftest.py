import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def data_dir(tmp_path):
    from glassx import config
    config.set_data_dir(str(tmp_path / "data"))
    yield tmp_path


def panels_of(result):
    return {(e["elev"], p["tag"]): (p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"], p["kind"])
            for e in result["elevations"] for p in e["panels"]}
