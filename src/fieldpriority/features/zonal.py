"""Zonal statistics of rasters over field polygons, with quality counters."""
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask, raster_geometry_mask


def zonal_stats(path, fields, id_col="Field_ID", valid_range=None,
                all_touched=True, coarse_res_deg=0.01):
    """One row per field: mean, median, valid_fraction, n_pixels, n_valid, cell_id, coarse."""
    rows = []
    with rasterio.open(path) as src:
        coarse = bool(src.crs.is_geographic and abs(src.res[0]) > coarse_res_deg)
        gdf = fields.to_crs(src.crs)
        for fid, geom in zip(gdf[id_col], gdf.geometry):
            rec = {id_col: fid, "mean": np.nan, "median": np.nan, "valid_fraction": np.nan,
                   "n_pixels": 0, "n_valid": 0, "cell_id": None, "coarse": coarse}
            try:
                arr, _ = mask(src, [geom], crop=True, all_touched=all_touched, filled=False)
            except ValueError:
                rows.append(rec)  # polygon outside raster
                continue
            data = np.ma.getdata(arr[0]).astype("float64")
            vals = data[~np.ma.getmaskarray(arr[0])]
            ok = np.isfinite(vals)
            if valid_range is not None:
                ok &= (vals >= valid_range[0]) & (vals <= valid_range[1])
            v = vals[ok]
            rec.update(n_pixels=int(vals.size), n_valid=int(v.size))
            if v.size:
                rec.update(mean=float(v.mean()), median=float(np.median(v)),
                           valid_fraction=float(v.size / vals.size))
            elif vals.size:
                rec["valid_fraction"] = 0.0
            if coarse:
                m, _, _ = raster_geometry_mask(src, [geom], all_touched=all_touched, crop=False)
                cells = np.argwhere(~m)
                rec["cell_id"] = ";".join(f"r{r}c{c}" for r, c in cells)
            rows.append(rec)
    return pd.DataFrame(rows)
