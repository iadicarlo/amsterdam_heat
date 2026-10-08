from amsterdam_heat.tile_inputs import TileSpec


def test_tile_geometry():
    spec = TileSpec(121500, 485000)
    assert spec.bbox == (121400, 484900, 122100, 485600)
    assert spec.shape == (700, 700)
    assert spec.name == "121500_485000"
    assert spec.transform.c == 121400 and spec.transform.f == 485600
