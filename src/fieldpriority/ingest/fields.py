"""Load and validate field polygons (QGIS shapefile)."""
import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon

# Shapefile column names are cut to 10 chars; map the v1 results to readable names.
V1_COLUMNS = {
    "Temp_C": "ref_temperature_c",
    "Rainfall_A": "ref_rainfall_anomaly_mm",
    "SoilMoistu": "ref_soil_moisture_score",
    "Temp_Str": "ref_temperature_score",
    "NDVI_Mean": "ref_ndvi_composite",
    "Soil_Moist": "ref_soil_moisture",
    "Field_Prio": "ref_priority",
    "S1_VV_dB": "ref_s1_vv_db",
    "S1_VV_Rela": "ref_s1_vv_relative",
    "Rainfall_S": "ref_rainfall_score",
    "NDVI_Stres": "ref_greenness_score",
    "S1_VV_Cont": "ref_s1_context",
    "Integrated": "ref_integrated_score",
}


def _polygons_only(geom):
    """Keep polygon parts only (drops stray LineStrings from GeometryCollections)."""
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    if not parts:
        raise ValueError("geometry has no polygon part")
    out = parts[0]
    for p in parts[1:]:
        out = out.union(p)
    return out


def load_fields(shp_path, id_col="Field_ID"):
    """Return (fields GeoDataFrame in EPSG:4326, v1 reference DataFrame)."""
    g = gpd.read_file(shp_path)
    if g.crs is None:
        raise ValueError(f"{shp_path} has no CRS (.prj missing?)")
    if id_col not in g.columns:
        raise ValueError(f"id column '{id_col}' not found; columns: {list(g.columns)}")
    g = g.to_crs(4326)
    if g[id_col].duplicated().any():
        raise ValueError("duplicate Field_ID values in shapefile")
    g["geometry"] = g.geometry.apply(lambda x: x if x.is_valid else x.buffer(0)).apply(_polygons_only)
    g = g[~g.geometry.is_empty].copy()
    g["area_ha"] = g.to_crs(g.estimate_utm_crs()).area / 1e4

    ref = g.drop(columns=["geometry", "area_ha"]).rename(columns=V1_COLUMNS)
    fields = g[[id_col, "area_ha", "geometry"]].reset_index(drop=True)
    return fields, ref.reset_index(drop=True)
