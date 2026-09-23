#!/usr/bin/env python3
"""site/ に置いてよいものだけを通す門番。git commit のたびに自動で走る。

■ なぜ要るのか
  site/ は GitHub Pages で全世界に公開される公開リポジトリ。
  **一度コミットしたものは、削除しても履歴に残り続ける。** 取り消せない。
  だから「うっかり置いた」を、コミットの時点で止める。

■ 考え方
  禁止リスト方式（危ないものを列挙）は必ず漏れる。
  だから**許可リスト方式**にする。置いていい拡張子だけを通し、あとは全部止める。

  そのうえで、許可した拡張子の中身も検査する。
  HTMLにAPIキーを書くことはできてしまうので。

usage:
  python3 公開前チェック.py            # 変更をステージした状態で実行
  python3 公開前チェック.py --all      # いまある全ファイルを検査
終了コード: 0=通過 / 1=公開してはいけないものがある
"""
from __future__ import annotations

import re
import subprocess as sp
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ── 置いてよい拡張子。ここに無いものは理由を問わず止める ──────────────
ALLOW_SUFFIX = {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg",
                ".webp", ".ico", ".woff2"}
# 拡張子なしで例外的に許すもの（独自ドメインを当てるときに使う）
ALLOW_NAME = {"CNAME", ".gitignore", "公開前チェック.py", "公開してよいもの.md"}

# ── 中身の検査。ここに当たったら止める ────────────────────────
NG_PATTERNS: list[tuple[str, str]] = [
    # 個人の特定に繋がるもの
    (r"r[_-]?orimoto", "個人アカウント名"),
    (r"/Users/[a-zA-Z0-9_]+/", "ローカルの絶対パス（利用者名が出る）"),
    (r"1997[-/年]?11[-/月]?15", "ミサキの生年月日（設定の内部値・公開禁止）"),
    (r"(丁丑|辛亥|辛酉).{0,40}(丁丑|辛亥|辛酉)", "四柱の併記（生年月日が逆算できる）"),
    # 認証情報
    (r"sk-[A-Za-z0-9]{20,}", "APIキーらしき文字列"),
    (r"gh[pousr]_[A-Za-z0-9]{20,}", "GitHubトークン"),
    (r"AKIA[0-9A-Z]{16}", "AWSキー"),
    (r"(api[_-]?key|secret|password|passwd)\s*[:=]\s*[\"'][^\"']{8,}", "認証情報の直書き"),
    # 事業の内部情報
    (r"(売上|購入者|購入明細|顧客|会員リスト)[\s\S]{0,20}(一覧|データ|csv)", "事業の内部データ"),
    (r"ultimate_fortune_sanctuary|to_kantei|posted_drafts", "非公開スクリプトの名前"),
]

# 外部への通信。判定ページは「生年月日を送らない」が売りなので、増えたら気づけるようにする
# rel="canonical" と rel="alternate" は通信しない（検索エンジンへの申告）ので除く。
# 通信するのは stylesheet / preconnect / dns-prefetch など。
NET_PATTERNS = [r"\bfetch\s*\(", r"XMLHttpRequest", r"sendBeacon", r"new\s+Image\s*\(",
                r"<script[^>]+src=",
                r"<link(?![^>]*rel=[\"'](canonical|alternate)[\"'])[^>]+href=[\"']https?://"]
# 計測。**生年月日は送っていない**（送るのはイベント名と日干だけ）。
#   gc.zgo.at は GoatCounter 公式の count.js の配布元。
#   外部スクリプトはこの1本だけと決めている。増やすときは必ず中身を読むこと。
NET_ALLOW = ["goatcounter.com", "gc.zgo.at"]


def staged_files() -> list[Path]:
    r = sp.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
               cwd=BASE, capture_output=True, text=True)
    return [BASE / f for f in r.stdout.split() if (BASE / f).exists()]


def all_files() -> list[Path]:
    r = sp.run(["git", "ls-files"], cwd=BASE, capture_output=True, text=True)
    return [BASE / f for f in r.stdout.split() if (BASE / f).exists()]


def check(files: list[Path]) -> list[str]:
    ng: list[str] = []
    for f in files:
        rel = f.relative_to(BASE)
        # ① 拡張子の許可リスト
        if f.name not in ALLOW_NAME and f.suffix.lower() not in ALLOW_SUFFIX:
            ng.append(f"【置いてはいけない種類】{rel}\n"
                      f"    site/ に置いてよいのは {'・'.join(sorted(ALLOW_SUFFIX))} だけ。\n"
                      f"    データ・スクリプト・メモは占い/ の他の場所へ。")
            continue
        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff2"}:
            continue
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # ② 中身の検査
        for pat, why in NG_PATTERNS:
            for m in re.finditer(pat, t, re.IGNORECASE):
                ln = t[:m.start()].count("\n") + 1
                ng.append(f"【{why}】{rel}:{ln}\n    …{m.group(0)[:60]}…")
        # ③ 外部通信の棚卸し
        for pat in NET_PATTERNS:
            for m in re.finditer(pat, t):
                ln = t[:m.start()].count("\n") + 1
                # 前後の窓。**狭すぎると誤検知する**（2026-09-23 実測）
                #   計測処理にコメントを数行足しただけで、送信行と goatcounter.com の
                #   距離が200字を超え、許可済みのはずの通信が止まった。
                #   広げすぎると別の送信先を見逃すので、関数1つに収まる幅にしてある。
                around = t[max(0, m.start() - 600): m.start() + 300]
                if any(a in around for a in NET_ALLOW):
                    continue
                ng.append(f"【要確認・外部通信】{rel}:{ln}\n"
                          f"    …{m.group(0)[:50]}…\n"
                          f"    生年月日を送っていないか確認すること。"
                          f"問題なければ NET_ALLOW に追記する。")
    return ng


def main() -> int:
    files = all_files() if "--all" in sys.argv else staged_files()
    if not files:
        return 0
    ng = check(files)
    if not ng:
        print(f"公開前チェック: {len(files)}ファイル 問題なし")
        return 0
    print("\n" + "=" * 62)
    print("  公開してはいけないものが含まれています。コミットを止めました。")
    print("=" * 62)
    for x in ng:
        print("\n  " + x.replace("\n", "\n  "))
    print("\n" + "=" * 62)
    print("  site/ は全世界に公開され、**一度コミットすると履歴から消せません。**")
    print("  どうしても通す必要がある場合だけ  git commit --no-verify")
    print("=" * 62 + "\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
