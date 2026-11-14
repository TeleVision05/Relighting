"""tools/slim_ply.py: what it keeps, what it drops, and how it fails."""

import sys

import numpy as np

sys.path.insert(0, "tools")
import slim_ply  # noqa: E402

FULL = [(n, "<f4") for n in ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]]
FULL += [(f"f_rest_{i}", "<f4") for i in range(24)]
FULL += [(n, "<f4") for n in ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]]


def write_full(path, n=100):
    data = np.zeros(n, dtype=np.dtype(FULL))
    rng = np.random.default_rng(1)
    for name, _ in FULL:
        data[name] = rng.normal(size=n)
    data["x"] = np.arange(n)  # identifies each splat
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {n}\n"
    header += "".join(f"property float {k}\n" for k, _ in FULL) + "end_header\n"
    path.write_bytes(header.encode() + data.tobytes())
    return data


def test_the_output_drops_sh_and_normals_and_keeps_the_most_significant_splats(tmp_path):
    src, dst = tmp_path / "in.ply", tmp_path / "out.ply"
    full = write_full(src)
    target_mb = (1024 + 40 * 56) / 1e6  # room for 40 splats
    assert slim_ply.main([str(src), str(dst), "--target-mb", str(target_mb)]) == 0
    out, names = slim_ply.read_ply(dst)
    assert names == slim_ply.KEEP and len(out) == 40
    expected = set(np.argsort(slim_ply.contribution(full))[::-1][:40])
    assert set(out["x"].astype(int)) == expected
    assert list(out["x"]) == sorted(out["x"])  # original order


def test_a_budget_larger_than_the_scene_keeps_every_splat(tmp_path):
    src, dst = tmp_path / "in.ply", tmp_path / "out.ply"
    write_full(src)
    assert slim_ply.main([str(src), str(dst), "--target-mb", "15"]) == 0
    assert len(slim_ply.read_ply(dst)[0]) == 100


def test_an_lfs_pointer_gets_a_plain_message(tmp_path, capsys):
    src = tmp_path / "lfs.ply"
    src.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n")
    assert slim_ply.main([str(src), str(tmp_path / "out.ply")]) == 1
    assert "git lfs pull" in capsys.readouterr().err


def test_a_file_without_splat_properties_is_refused(tmp_path, capsys):
    src = tmp_path / "plain.ply"
    src.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 1\nproperty float x\nend_header\n\0\0\0\0")
    assert slim_ply.main([str(src), str(tmp_path / "out.ply")]) == 1
    assert "3DGS" in capsys.readouterr().err
