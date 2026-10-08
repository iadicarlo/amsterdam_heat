"""Downloads from open Dutch data services.

Every download writes a sidecar ``<file>.source.json`` with the request URL,
fetch time and licence, so the raw folder documents itself.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import requests

AHN_WCS = "https://service.pdok.nl/rws/ahn/wcs/v1_0"
BAG_WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
CIR_WMS = "https://service.pdok.nl/hwh/luchtfotocir/wms/v1_0"
KNMI_HOURLY = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
AMS_WMS = "https://map.data.amsterdam.nl/service/"
AMS_TREES_WFS = "https://api.data.amsterdam.nl/v1/wfs/bomen/"

LICENCES = {
    "ahn": "AHN4, Rijkswaterstaat / Het Waterschapshuis via PDOK, CC0",
    "bag": "BAG, Kadaster via PDOK, CC0",
    "cir": "Luchtfoto Beeldmateriaal Nederland, Kadaster via PDOK, CC BY 4.0",
    "knmi": "KNMI hourly station data, CC BY 4.0",
    "ams_lufo": "Luchtfoto's Gemeente Amsterdam (Kernregistratie Luchtfoto's), CC BY 4.0",
    "ams_trees": "Bomen, Gemeente Amsterdam, data.amsterdam.nl",
}


def _record(path: Path, url: str, params: dict, licence: str) -> None:
    meta = {
        "url": url,
        "params": params,
        "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "licence": licence,
    }
    path.with_suffix(path.suffix + ".source.json").write_text(json.dumps(meta, indent=2))


def _get(url: str, params: dict, timeout: int = 300) -> requests.Response:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def ahn_geotiff(coverage: str, bbox: tuple[float, float, float, float], out: Path) -> Path:
    """AHN4 raster (``dsm_05m`` or ``dtm_05m``) for an RD New bounding box (xmin, ymin, xmax, ymax)."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "SERVICE": "WCS",
        "VERSION": "2.0.1",
        "REQUEST": "GetCoverage",
        "COVERAGEID": coverage,
        "SUBSET": [f"x({xmin},{xmax})", f"y({ymin},{ymax})"],
        "FORMAT": "image/tiff",
    }
    r = _get(AHN_WCS, params)
    if not r.headers.get("Content-Type", "").startswith("image/tiff"):
        raise RuntimeError(f"AHN WCS returned {r.headers.get('Content-Type')}: {r.text[:300]}")
    out.write_bytes(r.content)
    _record(out, AHN_WCS, params, LICENCES["ahn"])
    return out


def bag_footprints(bbox: tuple[float, float, float, float], out: Path, page: int = 1000) -> Path:
    """BAG building footprints (pand) intersecting the box, as GeoJSON in EPSG:28992."""
    xmin, ymin, xmax, ymax = bbox
    features, start = [], 0
    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "bag:pand",
            "bbox": f"{xmin},{ymin},{xmax},{ymax},EPSG:28992",
            "srsName": "EPSG:28992",
            "outputFormat": "application/json",
            "count": page,
            "startIndex": start,
        }
        batch = _get(BAG_WFS, params).json()["features"]
        features += batch
        if len(batch) < page:
            break
        start += page
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    _record(out, BAG_WFS, {**params, "startIndex": "paged"}, LICENCES["bag"])
    return out


def cir_orthophoto(
    bbox: tuple[float, float, float, float], res: float, layer: str, out: Path
) -> Path:
    """Colour infrared aerial photo (bands: NIR, red, green) as GeoTIFF at ``res`` metres.

    The PDOK WMS only serves JPEG, so the image is georeferenced here from the
    request box. JPEG compression adds some noise; fine for an NDVI threshold.
    """
    import io

    import rasterio
    from PIL import Image
    from rasterio.transform import from_origin

    xmin, ymin, xmax, ymax = bbox
    width, height = round((xmax - xmin) / res), round((ymax - ymin) / res)
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": "EPSG:28992",
        "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
        "WIDTH": width,
        "HEIGHT": height,
        "FORMAT": "image/jpeg",
    }
    r = _get(CIR_WMS, params)
    if not r.headers.get("Content-Type", "").startswith("image/jpeg"):
        raise RuntimeError(f"CIR WMS returned {r.headers.get('Content-Type')}: {r.text[:300]}")
    img = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).transpose(2, 0, 1)
    with rasterio.open(
        out, "w", driver="GTiff", width=width, height=height, count=3, dtype="uint8",
        crs="EPSG:28992", transform=from_origin(xmin, ymax, res, res), compress="deflate",
    ) as dst:
        dst.write(img)
    _record(out, CIR_WMS, params, LICENCES["cir"])
    return out


def knmi_hourly(station: int, start_utc: str, end_utc: str, out: Path) -> Path:
    """KNMI hourly station data as JSON. Times are 'YYYYMMDDHH' in UT, hour = end of the hour."""
    params = {
        "start": start_utc,
        "end": end_utc,
        "vars": "DD:FH:T:Q:P:U:N",
        "stns": str(station),
        "fmt": "json",
    }
    r = requests.post(KNMI_HOURLY, data=params, timeout=120)
    r.raise_for_status()
    out.write_text(r.text)
    _record(out, KNMI_HOURLY, params, LICENCES["knmi"])
    return out


def amsterdam_aerial(
    bbox: tuple[float, float, float, float], res: float, layer: str, out: Path
) -> Path:
    """Gemeente Amsterdam aerial photo (for example ``infrarood2023``, a leaf-on summer
    colour infrared flight with bands NIR, red, green) as GeoTIFF at ``res`` metres.

    Requested as PNG, so there are no JPEG artefacts in the NDVI.
    """
    import io

    import rasterio
    from PIL import Image
    from rasterio.transform import from_origin

    xmin, ymin, xmax, ymax = bbox
    width, height = round((xmax - xmin) / res), round((ymax - ymin) / res)
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "SRS": "EPSG:28992",
        "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
        "WIDTH": width,
        "HEIGHT": height,
        "FORMAT": "image/png",
    }
    r = _get(AMS_WMS, params)
    if not r.headers.get("Content-Type", "").startswith("image/png"):
        raise RuntimeError(f"Amsterdam WMS returned {r.headers.get('Content-Type')}: {r.text[:300]}")
    img = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).transpose(2, 0, 1)
    with rasterio.open(
        out, "w", driver="GTiff", width=width, height=height, count=3, dtype="uint8",
        crs="EPSG:28992", transform=from_origin(xmin, ymax, res, res), compress="deflate",
    ) as dst:
        dst.write(img)
    _record(out, AMS_WMS, params, LICENCES["ams_lufo"])
    return out


def amsterdam_trees(bbox: tuple[float, float, float, float], out: Path) -> Path:
    """Municipal tree register (stamgegevens) inside the box, GeoJSON points in EPSG:28992.

    Only trees managed by the Gemeente; private garden trees are not in it.
    """
    xmin, ymin, xmax, ymax = bbox
    crs = "urn:ogc:def:crs:EPSG::28992"
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "stamgegevens",
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},{crs}",
        "SRSNAME": crs,
        "OUTPUTFORMAT": "geojson",
        "COUNT": 50000,
    }
    r = _get(AMS_TREES_WFS, params)
    out.write_text(r.text)
    _record(out, AMS_TREES_WFS, params, LICENCES["ams_trees"])
    return out


BGT_OGC = "https://api.pdok.nl/lv/bgt/ogc/v1/collections"
RD = "http://www.opengis.net/def/crs/EPSG/0/28992"


def bgt_collection(collection: str, bbox: tuple[float, float, float, float], out: Path) -> Path:
    """Current objects of one BGT collection (for example ``wegdeel``) in the box, as
    GeoJSON in EPSG:28992. The API also returns retired versions; those are dropped."""
    xmin, ymin, xmax, ymax = bbox
    url = f"{BGT_OGC}/{collection}/items"
    params = {"f": "json", "limit": 1000, "bbox": f"{xmin},{ymin},{xmax},{ymax}",
              "bbox-crs": RD, "crs": RD}
    features, next_url = [], None
    while True:
        r = _get(next_url, {}) if next_url else _get(url, params)
        page = r.json()
        features += [f for f in page["features"] if f["properties"].get("eind_registratie") is None]
        next_url = next((link["href"] for link in page.get("links", []) if link["rel"] == "next"), None)
        if not next_url:
            break
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    _record(out, url, params, "BGT, Kadaster via PDOK, CC0")
    return out


def amsterdam_walking_network(out: Path) -> Path:
    """Amsterdam main networks (plusnetten en hoofdnetten); column VOET marks the
    pedestrian PLUS and HOOFD routes. Whole city, WGS84 GeoJSON."""
    url = "https://maps.amsterdam.nl/open_geodata/geojson_lnglat.php"
    params = {"KAARTLAAG": "PLUSHOOFDNETTEN", "THEMA": "plushoofdnetten"}
    out.write_text(_get(url, params).text)
    _record(out, url, params, "Gemeente Amsterdam open geodata")
    return out


def amsterdam_buurten(bbox: tuple[float, float, float, float], out: Path) -> Path:
    """Current Amsterdam neighbourhoods (buurten) intersecting the box, EPSG:28992."""
    xmin, ymin, xmax, ymax = bbox
    crs = "urn:ogc:def:crs:EPSG::28992"
    url = "https://api.data.amsterdam.nl/v1/wfs/gebieden/"
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
              "TYPENAMES": "buurten", "BBOX": f"{xmin},{ymin},{xmax},{ymax},{crs}",
              "SRSNAME": crs, "OUTPUTFORMAT": "geojson", "COUNT": 1000}
    data = _get(url, params).json()
    data["features"] = [f for f in data["features"] if f["properties"].get("eind_geldigheid") is None]
    out.write_text(json.dumps(data))
    _record(out, url, params, "Gebieden, Gemeente Amsterdam, data.amsterdam.nl")
    return out


LIANDER_ARCGIS = "https://services1.arcgis.com/v6W5HAVrpgSg3vts/arcgis/rest/services"
LIANDER_LAYERS = {
    "ls": ("Liander_Open_Data_Elektra", 112),  # laagspanningskabel, main grid only
    "ms": ("Liander_Open_Data_Elektra", 424),  # middenspanningskabel
    "hs": ("Liander_Open_Data_Elektra", 632),  # hoogspanningskabel, underground
    "gas": ("Liander_Open_Data_Gas", 0),  # gasleiding, no pressure or diameter
    "station_hs": ("Liander_Open_Data_Elektra", 641),  # hoogspanningsstation, points
    "station_ms": ("Liander_Open_Data_Elektra", 642),  # middenspanningsstation, points
    "station_ls": ("Liander_Open_Data_Elektra", 643),  # LS kast, points
}


def liander_network(layer: str, bbox: tuple[float, float, float, float], out: Path,
                    page: int = 2000) -> Path:
    """Liander cables or gas pipes (``ls``, ``ms``, ``hs`` or ``gas``) crossing the box,
    or stations and LS cabinets as points (``station_hs``, ``station_ms``, ``station_ls``),
    GeoJSON in EPSG:28992. House connections are not in the open set."""
    service, lid = LIANDER_LAYERS[layer]
    url = f"{LIANDER_ARCGIS}/{service}/FeatureServer/{lid}/query"
    xmin, ymin, xmax, ymax = bbox
    params = {"where": "1=1", "geometry": f"{xmin},{ymin},{xmax},{ymax}",
              "geometryType": "esriGeometryEnvelope", "inSR": 28992,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "outSR": 28992,
              "orderByFields": "OBJECTID", "resultRecordCount": page, "f": "geojson"}
    features, start = [], 0
    while True:
        batch = _get(url, {**params, "resultOffset": start}).json()["features"]
        features += batch
        if len(batch) < page:
            break
        start += page
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    _record(out, url, {**params, "resultOffset": "paged"},
            "Liander Open Data (liggingsgegevens), CC BY 4.0")
    return out


def amsterdam_underground(table: str, out: Path, dataset: str = "leidingeninfrastructuur",
                          bbox: tuple[float, float, float, float] | None = None,
                          page: int = 5000, near: str | None = "geometrie") -> Path:
    """One open table of the city's cables and pipes dataset, for example
    ``waternet_rioolleidingen`` (sewers) or ``amsterdam_ovl_ondergrondse_kabels``
    (street lighting), as GeoJSON in EPSG:28992. The REST API only filters by distance
    to a point (field ``near``, only on LineString tables; pass None to page the whole
    city), so the circle around ``bbox`` is fetched and clipped to the box here.
    The ``klic_*`` tables need a city login and are not open."""
    url = f"https://api.data.amsterdam.nl/v1/{dataset}/{table}/"
    params = {"_format": "geojson", "_pageSize": page}
    if bbox and near:
        xmin, ymin, xmax, ymax = bbox
        radius = int(np.ceil(np.hypot(xmax - xmin, ymax - ymin) / 2)) + 1
        params[f"{near}[within]"] = f"POINT({(xmin + xmax) / 2} {(ymin + ymax) / 2}),{radius}"
    headers = {"Accept-Crs": "EPSG:28992", "Content-Crs": "EPSG:28992"}
    features, next_url = [], None
    while True:
        r = requests.get(next_url or url, params=None if next_url else params, headers=headers,
                         timeout=600)
        r.raise_for_status()
        data = r.json()
        features += data["features"]
        links = data.get("_links", [])
        next_url = next((link["href"] for link in links if link.get("rel") == "next"), None)
        if not next_url:
            break
    if bbox:
        from shapely.geometry import box, shape

        b = box(*bbox)
        features = [f for f in features if f["geometry"] and shape(f["geometry"]).intersects(b)]
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    _record(out, url, {**params, "bbox": bbox}, "Gemeente Amsterdam, data.amsterdam.nl, CC BY")
    return out


def amsterdam_heat_network(out: Path) -> Path:
    """Vattenfall district heating and cooling pipes (NETTYPE), whole city, WGS84
    GeoJSON from Maps Amsterdam open geodata. Snapshot of May 2025."""
    url = "https://maps.amsterdam.nl/open_geodata/geojson_lnglat.php"
    params = {"KAARTLAAG": "STADSWARMTEKOUDE", "THEMA": "stadswarmtekoude"}
    out.write_text(_get(url, params).text)
    _record(out, url, params, "Vattenfall Warmte via Gemeente Amsterdam open geodata")
    return out


def bgt_utility_points(bbox: tuple[float, float, float, float], out: Path) -> Path:
    """Fire hydrants (BGT ``put`` with plus-type brandkraan) and street cabinets (BGT
    ``kast``) in the box, one GeoJSON with column ``kind``. Amsterdam leaves the cabinet
    type empty, so electricity, telecom and traffic cabinets are not told apart.
    Hydrants sit on a branch of a drinking water main, the only open trace of that network."""
    features = []
    for collection, kind in (("put", "hydrant"), ("kast", "cabinet")):
        tmp = out.with_name(f"{out.stem}_{collection}.geojson")
        bgt_collection(collection, bbox, tmp)
        for f in json.loads(tmp.read_text())["features"]:
            plus = f["properties"].get("plus_type")
            if collection == "put" and plus != "brandkraan / -put":
                continue
            features.append({"type": "Feature", "geometry": f["geometry"],
                             "properties": {"kind": kind, "plus_type": plus,
                                            "lokaal_id": f["properties"].get("lokaal_id")}})
        tmp.unlink()
        tmp.with_suffix(tmp.suffix + ".source.json").unlink(missing_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    _record(out, f"{BGT_OGC}/put,kast/items", {"bbox": bbox}, "BGT, Kadaster via PDOK, CC0")
    return out
