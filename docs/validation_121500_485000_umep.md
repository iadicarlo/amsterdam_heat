# SOLWEIG-GPU (mps) against UMEP SOLWEIG code (numpy, float64), tile 121500_485000

Same inputs, outdoor cells inside the tile, buffer removed.

## Sky view factor (153 patches)

UMEP numpy run on CPU took 2.4 min.

| Layer | mean abs diff | 99th percentile | max |
|---|---|---|---|
| svf | 0.00000 | 0.0000 | 0.0041 |
| svfveg | 0.00000 | 0.0000 | 0.0064 |
| svfaveg | 0.00000 | 0.0000 | 0.0041 |
| svfE | 0.00000 | 0.0000 | 0.0081 |
| svfS | 0.00000 | 0.0000 | 0.0000 |
| svfW | 0.00000 | 0.0000 | 0.0027 |
| svfN | 0.00000 | 0.0000 | 0.0081 |

## Shadows (building and vegetation), sun positions over a July day

| Azimuth | Altitude | Building shadow cells that differ (%) | Vegetation shadow mean abs diff |
|---|---|---|---|
| 80 | 15 | 0.000 | 0.0000 |
| 120 | 40 | 0.000 | 0.0000 |
| 180 | 58 | 0.000 | 0.0000 |
| 240 | 42 | 0.000 | 0.0000 |
| 285 | 12 | 0.000 | 0.0000 |
