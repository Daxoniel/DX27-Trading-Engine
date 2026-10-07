"""Offline bibliographic sidecar validation; no network or runtime gate changes."""
import json
from pathlib import Path
from dx27.intelligence.sentinel.identity import stable_content_hash


def validate_reference_library(directory: Path, protocol: dict) -> dict:
    library = json.loads((directory/'library.json').read_text())
    links = json.loads((directory/'sensor_links.json').read_text())
    refs = library['references']
    known = {r['reference_id'] for r in refs}
    if len(known) != len(refs) or any(not r['reference_id'].startswith('REF-') for r in refs):
        raise ValueError('unique stable reference IDs required')
    if links['protocol_digest'] != stable_content_hash(protocol):
        raise ValueError('reference sidecar points at wrong frozen protocol')
    if set(links['feeds']) != {f['feed_id'] for f in protocol['feeds']}:
        raise ValueError('every feed requires reference coverage')
    sensors = links['sensors']
    if len(sensors) != len(protocol['sensors']) or {s['sensor_id'] for s in sensors} != {s['sensor_id'] for s in protocol['sensors']}:
        raise ValueError('every sensor contract requires exactly one mapping')
    groups = list(links['feeds'].values())+[s['reference_ids'] for s in sensors]+list(links['composites'].values())
    if any(not ids or not set(ids) <= known for ids in groups):
        raise ValueError('unresolved reference ID')
    for r in refs:
        if not all(r.get(k) for k in ('title','author','url','kind','verification_status','verified_on','supported_claim')):
            raise ValueError('incomplete reference metadata')
    return {'references':len(refs),'feeds':len(links['feeds']),'sensors':len(sensors),
            'library_digest':stable_content_hash(library),'links_digest':stable_content_hash(links)}


def references_for_sensor(directory: Path, protocol: dict, descriptor) -> dict:
    """Resolve descriptor-to-contract-to-literature without mutating frozen v1."""
    verified=validate_reference_library(directory,protocol)
    links=json.loads((directory/'sensor_links.json').read_text())
    rows=[s for s in links['sensors'] if s['sensor_id']==descriptor.sensor_id]
    if len(rows)!=1:raise ValueError('unregistered sensor descriptor')
    return {'sensor_id':descriptor.sensor_id,'descriptor_version':descriptor.descriptor_version,
            'protocol_digest':links['protocol_digest'],'reference_library_digest':verified['library_digest'],
            'sensor_links_digest':verified['links_digest'],'reference_ids':tuple(rows[0]['reference_ids'])}
