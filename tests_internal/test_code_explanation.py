"""Tests for statically discovered call paths."""

from pathlib import Path

from src.code_explanation import find_static_call_path


SOURCE_ROOT = Path("demo_project")
CHANGED_FILE = Path("demo_project/app/coupon.py")


def test_finds_coupon_test_call_path():
    path = find_static_call_path(
        source_root=SOURCE_ROOT,
        test_nodeid=(
            "demo_project/tests/test_coupon.py"
            "::test_percent_discount_truncates_partial_cent"
        ),
        changed_file=CHANGED_FILE,
        changed_function="_round_percent",
    )

    assert path == [
        "tests.test_coupon.test_percent_discount_truncates_partial_cent",
        "app.coupon.discount_for",
        "app.coupon._round_percent",
    ]


def test_finds_indirect_checkout_call_path():
    path = find_static_call_path(
        source_root=SOURCE_ROOT,
        test_nodeid=(
            "demo_project/tests/test_checkout.py"
            "::test_percent_coupon_changes_total"
        ),
        changed_file=CHANGED_FILE,
        changed_function="_round_percent",
    )

    assert path == [
        "tests.test_checkout.test_percent_coupon_changes_total",
        "app.checkout.build_order",
        "app.coupon.apply_coupon",
        "app.coupon.discount_for",
        "app.coupon._round_percent",
    ]


def test_does_not_invent_a_call_path(tmp_path):
    root = tmp_path / "project"
    root.mkdir()

    changed_file = root / "app.py"
    changed_file.write_text(
        "def changed():\n"
        "    return 1\n\n"
        "def unrelated():\n"
        "    return 2\n",
        encoding="utf-8",
    )

    test_file = root / "test_demo.py"
    test_file.write_text(
        "from app import unrelated\n\n"
        "def test_unrelated():\n"
        "    assert unrelated() == 2\n",
        encoding="utf-8",
    )

    path = find_static_call_path(
        source_root=root,
        test_nodeid=f"{test_file}::test_unrelated",
        changed_file=changed_file,
        changed_function="changed",
    )

    assert path is None
