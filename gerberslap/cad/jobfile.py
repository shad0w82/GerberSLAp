"""The Gerber job file (.gbrjob), a JSON that KiCad and EAGLE write next to the layers. It states the board's size, which the
importer cross-checks against the outline. The two programs lay it out differently."""
import json


def job_info(probes, members) -> dict:
    """{"job_size_mm": (x, y)} if a job file with a size is among the files; {} otherwise (a damaged file is not an error)."""
    for p in probes:
        if not p.basename.lower().endswith(".gbrjob"):
            continue
        try:
            body = json.loads(members[p.name].decode("utf-8", errors="replace"))
            for section in ("Overall", "GeneralSpecs"):                     # EAGLE writes the first, KiCad the second
                size = body.get(section, {}).get("Size")
                if size:
                    return {"job_size_mm": (float(size["X"]), float(size["Y"]))}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return {}
