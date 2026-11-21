"""Resep yang sedang aktif, disimpan di strategi.json (ikut di-commit ke repo)."""
import copy
import json
import os
import recipes

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategi.json")


def load() -> dict:
    data = copy.deepcopy(recipes.DEFAULT)
    try:
        with open(FILE) as f:
            data.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # Buang nama resep yang tidak dikenal (mis. file diedit manual)
    if data["BSJP"] not in recipes.BSJP:
        data["BSJP"] = recipes.DEFAULT["BSJP"]
    if data["BPJS"] not in recipes.BPJS:
        data["BPJS"] = recipes.DEFAULT["BPJS"]
    data["SWING"] = [t for t in data["SWING"] if t in recipes.SWING_SEMUA] or list(recipes.SWING_AWAL)
    return data


def save(data: dict) -> None:
    with open(FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
