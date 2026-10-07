"""Scenario transformations of synthetic measurement evidence, not live observations."""
from dataclasses import replace


def replace_measurements(state, measurements):
    ids={old.measurement_id:new.measurement_id for old,new in zip(state.measurements,measurements)}
    dims=tuple(replace(d,measurement_ids=tuple(ids[i] for i in d.measurement_ids),required_measurement_ids=tuple(ids[i] for i in d.required_measurement_ids)) for d in state.snapshot.dimensions)
    snap=replace(state.snapshot,dimensions=dims,relationships=tuple(ids[i] for i in state.snapshot.relationships))
    return replace(state,snapshot=snap,measurements=measurements)
