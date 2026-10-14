"""Vector file readers without GDAL: zipped Shapefile (pyshp) and GeoPackage
(stdlib sqlite3 + GPKG binary geometry parser). Output: EPSG:4326 GeoJSON."""
from __future__ import annotations
import io
import json
import sqlite3
import struct
import tempfile
import os
import zipfile


# ---------------------------------------------------------------- shapefile ---
def read_zipped_shapefile(raw: bytes) -> tuple[dict, dict]:
    """Returns (feature_collection, info). Raises ValueError on problems."""
    import shapefile  # pyshp, pure python
    with tempfile.TemporaryDirectory(prefix="mwamba_shp_") as tmp:
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
            names = zf.namelist()
        except Exception:
            raise ValueError("Upload is not a readable zip file")
        shps = [n for n in names if n.lower().endswith(".shp")]
        if not shps:
            raise ValueError("Zip contains no .shp file")
        if len(shps) > 1:
            raise ValueError(f"Zip contains {len(shps)} shapefiles ({shps}); upload one layer per zip")
        zf.extractall(tmp)
        base = os.path.join(tmp, shps[0])
        try:
            reader = shapefile.Reader(base)
        except Exception as e:
            raise ValueError(f"Cannot read shapefile: {e}")
        fields = [f[0] for f in reader.fields[1:]]  # skip DeletionFlag
        feats = []
        for sr in reader.iterShapeRecords():
            geom = _shp_geom(sr.shape)
            if geom is None:
                continue
            props = {k: (v.decode(errors="replace") if isinstance(v, bytes) else v)
                     for k, v in zip(fields, sr.record)}
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
        # .prj lookup (best effort, reported not assumed)
        prj = [n for n in names if n.lower().endswith(".prj")]
        info = {"n_shapes": reader.numRecords, "shape_type": reader.shapeTypeName,
                "fields": fields, "prj_present": bool(prj)}
        try:
            reader.close()  # release file handles (Windows cannot delete open files)
        except Exception:
            pass
        return {"type": "FeatureCollection", "features": feats}, info


def _shp_geom(shp) -> dict | None:
    st = shp.shapeTypeName
    pts = shp.points
    if st == "POINT":
        return {"type": "Point", "coordinates": list(pts[0])} if pts else None
    if st == "MULTIPOINT":
        return {"type": "MultiPoint", "coordinates": [list(p) for p in pts]}
    if st in ("POLYLINE", "POLYLINEZ", "POLYLINEM"):
        parts = _parts(pts, list(shp.parts) + [len(pts)])
        if st == "POLYLINE" and len(parts) == 1:
            return {"type": "LineString", "coordinates": parts[0]}
        return {"type": "MultiLineString", "coordinates": parts}
    if st in ("POLYGON", "POLYGONZ", "POLYGONM"):
        parts = _parts(pts, list(shp.parts) + [len(pts)])
        if not parts:
            return None
        # pyshp rings: outer CCW? GeoJSON wants outer CCW — enforce ring closure only;
        # validity is checked downstream by the validator.
        rings = []
        for ring in parts:
            r = [list(p[:2]) for p in ring]
            if r and r[0] != r[-1]:
                r.append(r[0])
            rings.append(r)
        return {"type": "Polygon", "coordinates": rings}
    return None


def _parts(pts, breaks):
    return [[list(p[:2]) for p in pts[a:b]] for a, b in zip(breaks, breaks[1:]) if b > a]


# ---------------------------------------------------------------- GeoPackage --
def read_geopackage(raw: bytes, layer: str | None = None) -> tuple[dict, dict]:
    """Read (Multi)Point/LineString/Polygon layers from a .gpkg (SQLite)."""
    with tempfile.TemporaryDirectory(prefix="mwamba_gpkg_") as tmp:
        path = os.path.join(tmp, "in.gpkg")
        with open(path, "wb") as f:
            f.write(raw)
        con = sqlite3.connect(path)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT table_name FROM gpkg_geometry_columns")]
        except Exception as e:
            raise ValueError(f"Not a GeoPackage (no gpkg_geometry_columns): {e}")
        finally:
            con.close()
        if not tables:
            raise ValueError("GeoPackage has no geometry layers")
        if layer is None:
            if len(tables) > 1:
                raise ValueError(f"GeoPackage has layers {tables}; pick one via 'layer' param")
            layer = tables[0]
        if layer not in tables:
            raise ValueError(f"Layer {layer!r} not in {tables}")
        meta = con.execute(
            "SELECT column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns "
            "WHERE table_name=?", (layer,)).fetchone()
        geom_col, geom_type, srs_id = meta
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({layer})")]
        feats = []
        try:
            rows = list(con.execute(f"SELECT * FROM {layer}"))
        finally:
            con.close()
        for row in rows:
            rec = dict(zip(cols, row))
            blob = rec.pop(geom_col, None)
            if blob is None:
                continue
            geom = _gpkg_geom(bytes(blob))
            if geom is None:
                continue
            props = {k: v for k, v in rec.items()}
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
        info = {"layer": layer, "layers": tables, "geometry_type": geom_type,
                "srs_id": srs_id, "n_features": len(feats)}
        return {"type": "FeatureCollection", "features": feats}, info


def _gpkg_geom(blob: bytes) -> dict | None:
    """Parse GPKG v1 geometry blob (little-endian). Returns GeoJSON geometry."""
    try:
        if blob[0:2] != b"GP":
            return None
        flags = blob[3]
        little = not (flags & 0b1)
        endian = "<" if little else ">"
        srs_id = struct.unpack(endian + "i", blob[4:8])[0]
        if srs_id not in (4326, 0, -1):
            raise ValueError(f"GeoPackage layer uses SRS {srs_id}; only EPSG:4326 supported "
                             f"(reproject first or declare via ingest wizard)")
        off = 8
        # envelope size from envelope indicator (low 3 bits... actually bits 1-3)
        env_ind = (flags >> 1) & 0b111
        off += {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env_ind]
        wkb = blob[off:]
        return _wkb_geom(wkb, little)
    except ValueError:
        raise
    except Exception:
        return None


def _wkb_geom(wkb: bytes, little: bool) -> dict | None:
    endian = "<" if little else ">"
    gtype = struct.unpack(endian + "I", wkb[1:5])[0] % 1000
    off = 5
    if gtype == 1:  # Point
        x, y = struct.unpack(endian + "dd", wkb[off:off + 16])
        return {"type": "Point", "coordinates": [x, y]}
    if gtype in (2, 5, 6):  # LineString / Polygon / MultiPoint
        n = struct.unpack(endian + "I", wkb[off:off + 4])[0]
        off += 4
        pts = [list(struct.unpack(endian + "dd", wkb[off + i * 16:off + i * 16 + 16])) for i in range(n)]
        if gtype == 2:
            return {"type": "LineString", "coordinates": pts}
        if gtype == 6:
            return {"type": "MultiPoint", "coordinates": pts}
        return {"type": "Polygon", "coordinates": [pts]}
    if gtype == 4:  # MultiLineString
        n = struct.unpack(endian + "I", wkb[off:off + 4])[0]
        off += 4
        lines = []
        for _ in range(n):
            off += 5
            m = struct.unpack(endian + "I", wkb[off:off + 4])[0]
            off += 4
            lines.append([list(struct.unpack(endian + "dd", wkb[off + i * 16:off + i * 16 + 16])) for i in range(m)])
            off += m * 16
        return {"type": "MultiLineString", "coordinates": lines}
    return None


def list_gpkg_layers(raw: bytes) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="mwamba_gpkg_") as tmp:
        path = os.path.join(tmp, "in.gpkg")
        with open(path, "wb") as f:
            f.write(raw)
        con = sqlite3.connect(path)
        try:
            return [r[0] for r in con.execute("SELECT table_name FROM gpkg_geometry_columns")]
        except Exception as e:
            raise ValueError(f"Not a GeoPackage: {e}")
        finally:
            con.close()
