"""Reproducible synthetic workload; results apply only to the measured host."""

import argparse
import json
import os
import platform
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import database
from catalog import product_detail, search_products
from trades import confirm_reservation, reserve


def measure(function, inputs, workers):
    """Measure end-to-end service latency, retaining failed calls in the denominator."""

    def request(value):
        start = time.perf_counter()
        try:
            function(value)
            return time.perf_counter() - start, True
        except Exception:
            return time.perf_counter() - start, False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(request, inputs))
    times = sorted(duration for duration, _ in results)
    return {
        "samples": len(results),
        "errors": sum(not ok for _, ok in results),
        "p95_seconds": times[max(0, (len(times) * 95 + 99) // 100 - 1)],
        "under_2s_ratio_including_errors": sum(ok and duration <= 2 for duration, ok in results)
        / len(results),
        "under_3s_ratio_including_errors": sum(ok and duration <= 3 for duration, ok in results)
        / len(results),
    }


def run(count, workers):
    """Seed 100k products into an isolated database and measure the stated operations."""
    original = database.DATABASE_PATH
    try:
        with tempfile.TemporaryDirectory() as folder:
            database.DATABASE_PATH = Path(folder) / "trading.db"
            database.initialize_database()
            with closing(database.connect_database()) as connection:
                with connection:
                    connection.executemany(
                        "INSERT INTO accounts(id,username,phone,password_hash) VALUES(?,?,?,'benchmark-no-login')",
                        [(number, f"user{number}", f"138{number:08d}") for number in range(1, 102)],
                    )
                    connection.execute(
                        "INSERT INTO account_roles SELECT a.id,r.id FROM accounts a CROSS JOIN roles r "
                        "WHERE r.name IN ('buyer','seller')"
                    )
                    category = connection.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
                    connection.executemany(
                        "INSERT INTO products(id,seller_id,category_id,title,description,"
                        "price_cents,status,first_published_at) "
                        "VALUES(?,1,?,?,'benchmark',1000,'published',"
                        "'2026-11-14T00:00:00.000Z')",
                        ((number, category, f"商品{number}") for number in range(1, count + 1)),
                    )
            results = {
                "host": {"platform": platform.platform(), "logical_cpus": os.cpu_count()},
                "products": count,
                "workers": workers,
                "note": "本机合成数据服务层测量，不等同于4核8GB指定环境验收，不含网络或GUI渲染。",
            }
            inputs = list(range(2, 102))
            results["list"] = measure(search_products, inputs, workers)
            results["detail"] = measure(lambda actor: product_detail(actor, actor), inputs, workers)
            results["reserve"] = measure(lambda actor: reserve(actor, actor), inputs, workers)
            with closing(database.connect_database()) as connection:
                reservations = [row[0] for row in connection.execute("SELECT id FROM reservations")]
            results["confirm"] = measure(
                lambda key: confirm_reservation(1, key), reservations, workers
            )
            return results
    finally:
        database.DATABASE_PATH = original


def main():
    """Write a portable JSON result for inspection."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=int, default=100_000)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()
    if args.products < 102 or not 1 <= args.workers <= 100:
        parser.error("products >= 102，workers 为 1～100")
    result = run(args.products, args.workers)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
