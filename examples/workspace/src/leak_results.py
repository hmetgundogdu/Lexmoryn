"""Persist leak test results produced by the pressure sensor bench."""


def persist_measurement(sample):
    return {"pressure_drop": sample, "table": "leak_test_results"}
