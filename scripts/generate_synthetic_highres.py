import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from pathlib import Path

np.random.seed(42)

W, H = 1024, 1024
LAT_MIN, LAT_MAX = 12.90, 13.10
LON_MIN, LON_MAX = 77.55, 77.75

def perlin_noise(w, h, scale=8, octaves=6, persistence=0.5, lacunarity=2.0, seed=0):
    np.random.seed(seed)
    noise = np.zeros((h, w))
    amplitude = 1.0
    frequency = 1.0
    max_val = 0
    for _ in range(octaves):
        xs = np.linspace(0, scale * frequency, w)
        ys = np.linspace(0, scale * frequency, h)
        gx = np.random.randn(int(scale * frequency) + 2, int(scale * frequency) + 2)
        from scipy.ndimage import zoom
        gz = zoom(gx, (h / gx.shape[0], w / gx.shape[1]), order=3)
        noise += gz * amplitude
        max_val += amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return noise / max_val

def make_bengaluru_image(year):
    from scipy.ndimage import gaussian_filter, zoom

    terrain = perlin_noise(W, H, scale=6, octaves=7, persistence=0.55, seed=1)
    terrain2 = perlin_noise(W, H, scale=3, octaves=5, persistence=0.45, seed=2)
    terrain = (terrain * 0.7 + terrain2 * 0.3)
    terrain = (terrain - terrain.min()) / (terrain.max() - terrain.min())

    xx, yy = np.meshgrid(np.linspace(0,1,W), np.linspace(0,1,H))
    
    urban_core = np.exp(-((xx - 0.65)**2 + (yy - 0.45)**2) / 0.04)
    whitefield = np.exp(-((xx - 0.78)**2 + (yy - 0.35)**2) / 0.06)
    sarjapur = np.exp(-((xx - 0.60)**2 + (yy - 0.72)**2) / 0.05)
    krpuram = np.exp(-((xx - 0.50)**2 + (yy - 0.55)**2) / 0.035)
    old_center = np.exp(-((xx - 0.40)**2 + (yy - 0.50)**2) / 0.03)

    urban_base = (urban_core * 0.9 + whitefield * 0.7 + sarjapur * 0.6 +
                  krpuram * 0.8 + old_center * 0.7)
    urban_base = np.clip(urban_base, 0, 1)

    if year == 2019:
        urban_map = urban_base * 0.55
        urban_map[urban_map < 0.25] *= 0.3
    else:
        urban_map = urban_base * 0.90
        sprawl = perlin_noise(W, H, scale=4, octaves=4, seed=10)
        sprawl = (sprawl - sprawl.min()) / (sprawl.max() - sprawl.min())
        sprawl = sprawl * 0.35
        urban_map = np.clip(urban_map + sprawl * (1 - urban_base * 0.5), 0, 1)

    urban_map = gaussian_filter(urban_map, sigma=12)
    urban_map = (urban_map - urban_map.min()) / (urban_map.max() - urban_map.min())

    lake = np.exp(-((xx - 0.65)**2 + (yy - 0.85)**2) / 0.012)
    lake += np.exp(-((xx - 0.70)**2 + (yy - 0.82)**2) / 0.008)
    lake = gaussian_filter(np.clip(lake, 0, 1), sigma=6)
    lake = (lake > 0.15).astype(float)
    lake = gaussian_filter(lake, sigma=4)

    lake2 = np.exp(-((xx - 0.15)**2 + (yy - 0.20)**2) / 0.006)
    lake2 = gaussian_filter(np.clip(lake2, 0, 1), sigma=3)
    lake2 = (lake2 > 0.2).astype(float) * gaussian_filter(lake2, sigma=2)

    veg_noise = perlin_noise(W, H, scale=10, octaves=6, seed=5)
    veg_noise = (veg_noise - veg_noise.min()) / (veg_noise.max() - veg_noise.min())
    if year == 2019:
        veg = np.clip(veg_noise * (1 - urban_map * 0.6) * 1.3, 0, 1)
    else:
        veg = np.clip(veg_noise * (1 - urban_map * 0.85) * 0.9, 0, 1)

    road_h1 = np.exp(-(np.abs(yy - 0.50) / 0.008)**2)
    road_h2 = np.exp(-(np.abs(yy - 0.35) / 0.006)**2)
    road_v1 = np.exp(-(np.abs(xx - 0.50) / 0.007)**2)
    road_v2 = np.exp(-(np.abs(xx - 0.70) / 0.006)**2)
    roads = np.clip(road_h1 + road_h2 + road_v1 + road_v2, 0, 1)
    roads = gaussian_filter(roads, sigma=2)

    fine = perlin_noise(W, H, scale=20, octaves=4, seed=year)
    fine = (fine - fine.min()) / (fine.max() - fine.min())

    urban_r = 170 + fine * 30 + terrain * 20
    urban_g = 155 + fine * 25 + terrain * 15
    urban_b = 140 + fine * 20 + terrain * 10

    if year == 2019:
        veg_r = 55 + fine * 25 + terrain * 15
        veg_g = 95 + fine * 30 + terrain * 20
        veg_b = 40 + fine * 15 + terrain * 10
    else:
        veg_r = 75 + fine * 30 + terrain * 20
        veg_g = 95 + fine * 25 + terrain * 18
        veg_b = 45 + fine * 15 + terrain * 8

    lake_r = 25 + fine * 10
    lake_g = 40 + fine * 12
    lake_b = 65 + fine * 15

    r = urban_map * urban_r + veg * veg_r * (1 - urban_map) + roads * 200
    g = urban_map * urban_g + veg * veg_g * (1 - urban_map) + roads * 195
    b = urban_map * urban_b + veg * veg_b * (1 - urban_map) + roads * 185

    water_mask = np.clip(lake + lake2, 0, 1)
    r = r * (1 - water_mask) + lake_r * water_mask
    g = g * (1 - water_mask) + lake_g * water_mask
    b = b * (1 - water_mask) + lake_b * water_mask

    if year == 2024:
        haze = 0.06
        r = r * (1 - haze) + 200 * haze
        g = g * (1 - haze) + 195 * haze
        b = b * (1 - haze) + 185 * haze

    noise = np.random.normal(0, 3, (H, W))
    r = np.clip(r + noise, 0, 255).astype(np.uint8)
    g = np.clip(g + noise * 0.9, 0, 255).astype(np.uint8)
    b = np.clip(b + noise * 0.8, 0, 255).astype(np.uint8)

    return np.stack([r, g, b])


def save_geotiff(data, path, bands=3):
    transform = from_bounds(LON_MIN, LAT_MIN, LON_MAX, LAT_MAX, W, H)
    crs = CRS.from_epsg(4326)
    with rasterio.open(
        path, 'w',
        driver='GTiff',
        height=H, width=W,
        count=bands,
        dtype=np.uint8,
        crs=crs,
        transform=transform,
        compress='deflate',
        photometric='RGB' if bands == 3 else 'MINISBLACK'
    ) as dst:
        for i in range(bands):
            dst.write(data[i], i + 1)
    print(f"  Saved {path} ({Path(path).stat().st_size // 1024} KB)")


OUT = Path("sample_data")
OUT.mkdir(exist_ok=True)

print("Generating 2019 optical baseline (pre-expansion, vegetation-rich)...")
img_2019 = make_bengaluru_image(2019)
save_geotiff(img_2019, OUT / "isro_optical_2022.tif")

print("Generating 2024 optical observation (post-expansion, urbanized)...")
img_2024 = make_bengaluru_image(2024)
save_geotiff(img_2024, OUT / "isro_optical_2026.tif")

print("Generating 2024 SAR (derived from 2024 optical)...")
from scipy.ndimage import gaussian_filter
r24, g24, b24 = img_2024[0].astype(float), img_2024[1].astype(float), img_2024[2].astype(float)
vv = (r24 * 0.4 + g24 * 0.4 + b24 * 0.2)
vv = np.clip(vv + np.random.normal(0, 8, vv.shape), 0, 255).astype(np.uint8)
vh = np.clip(g24 * 0.7 + np.random.normal(0, 6, vv.shape), 0, 255).astype(np.uint8)
sar = np.stack([vv, vh])
save_geotiff(sar, OUT / "isro_sar_2026.tif", bands=2)

print("\nDone!")
