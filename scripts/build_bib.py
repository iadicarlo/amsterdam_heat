"""Build references/references.bib from CrossRef metadata so every entry is tied to a real DOI.

Usage: uv run python scripts/build_bib.py
Add a DOI to DOIS (or an arXiv entry to ARXIV) and rerun.
"""

import html
import re
import time
import unicodedata
from pathlib import Path

import requests

DOIS = {
    "lindberg2008solweig": "10.1007/s00484-008-0162-7",
    "lindberg2011vegetation": "10.1007/s00704-010-0382-8",
    "lindberg2018umep": "10.1016/j.envsoft.2017.09.020",
    "wallenberg2020anisotropic": "10.1016/j.uclim.2020.100589",
    "kamath2026solweiggpu": "10.21105/joss.09535",
    "zonato2026glidesol": "10.5194/gmd-19-7389-2026",
    "hoppe1999pet": "10.1007/s004840050118",
    "bernard2023urock": "10.5194/gmd-16-5703-2023",
    "brode2011utci": "10.1007/s00484-011-0454-1",
    "koopmans2020pet": "10.1016/j.buildenv.2020.106984",
    "briegel2023unet": "10.1016/j.uclim.2022.101359",
    "briegel2025projections": "10.1016/j.uclim.2025.102564",
    "wallenberg2022treeplanter": "10.5194/gmd-15-1107-2022",
    "tolan2024canopy": "10.1016/j.rse.2023.113888",
    "weinstein2020deepforest": "10.1111/2041-210X.13472",
    "wu2023samgeo": "10.21105/joss.05663",
    "ronneberger2015unet": "10.1007/978-3-319-24574-4_28",
}

# arXiv preprints without a journal DOI, checked against export.arxiv.org
ARXIV = {
    "schrodi2023treeplacement": {
        "title": "Climate-sensitive Urban Planning through Optimization of Tree Placements",
        "author": "Schrodi, Simon and Briegel, Ferdinand and Argus, Max and Christen, Andreas and Brox, Thomas",
        "year": "2023",
        "eprint": "2310.05691",
        "note": "NeurIPS 2023 Workshop on Tackling Climate Change with Machine Learning",
    },
    "snaiki2025windhierarchical": {
        "title": "A Hierarchical Deep Learning Model for Predicting Pedestrian-Level Urban Winds",
        "author": "Snaiki, Reda and Lu, Jiachen and Li, Shaopeng and Nazarian, Negin",
        "year": "2025",
        "eprint": "2510.27101",
        "note": "Preprint",
    },
    "huang2026inpaintingunet": {
        "title": "Inpainting U-Net for seamless pedestrian-level wind prediction across urban morphologies",
        "author": "Huang, Jingzi and Heaney, Claire E. and Li, Tao and Li, Xinzhe and Hughes, Graham O. "
        "and van Reeuwijk, Maarten",
        "year": "2026",
        "eprint": "2607.02560",
        "note": "Preprint",
    },
    "kirillov2023sam": {
        "title": "Segment Anything",
        "author": "Kirillov, Alexander and Mintun, Eric and Ravi, Nikhila and Mao, Hanzi and Rolland, Chloe "
        "and Gustafson, Laura and Xiao, Tete and Whitehead, Spencer and Berg, Alexander C. "
        "and Lo, Wan-Yen and Doll{\\'a}r, Piotr and Girshick, Ross",
        "year": "2023",
        "eprint": "2304.02643",
        "note": "ICCV 2023",
    },
}


def clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("\u2013", "--").replace("\u2014", "--")


def fetch(doi: str, tries: int = 6) -> dict:
    """CrossRef record for a DOI. Falls back to doi.org content negotiation, which serves
    the same CrossRef metadata as CSL JSON, because api.crossref.org is sometimes slow."""
    sources = [
        (f"https://api.crossref.org/works/{doi}", {}, lambda r: r.json()["message"]),
        (f"https://doi.org/{doi}", {"Accept": "application/vnd.citationstyles.csl+json"}, csl_to_crossref),
    ]
    for attempt in range(tries):
        url, headers, parse = sources[attempt % 2]
        try:
            r = requests.get(url, headers=headers, timeout=60)
            if r.ok:
                return parse(r)
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not fetch metadata for {doi}")


def csl_to_crossref(r: requests.Response) -> dict:
    m = r.json()
    m["title"] = [m["title"]] if isinstance(m["title"], str) else m["title"]
    ct = m.get("container-title", "")
    m["container-title"] = [ct] if isinstance(ct, str) else ct
    return m


def to_bib(key: str, m: dict) -> str:
    authors = " and ".join(
        f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in m.get("author", [])
    )
    kind = "incollection" if m["type"] == "book-chapter" else "article"
    venue_field = "booktitle" if kind == "incollection" else "journal"
    fields = {
        "title": "{" + clean(m["title"][0]) + "}",
        "author": authors,
        venue_field: clean((m.get("container-title") or [""])[-1]),
        "year": str(m["issued"]["date-parts"][0][0]),
        "volume": m.get("volume", ""),
        "number": m.get("issue", ""),
        "pages": clean(m.get("page", "")).replace("-", "--").replace("----", "--")
        or m.get("article-number", ""),
        "publisher": m.get("publisher", ""),
        "doi": m["DOI"],
    }
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@{kind}{{{key},\n{body}\n}}\n"


def arxiv_bib(key: str, f: dict) -> str:
    fields = {"title": "{" + f["title"] + "}", "author": f["author"], "year": f["year"],
              "eprint": f["eprint"], "archivePrefix": "arXiv", "note": f["note"],
              "doi": f"10.48550/arXiv.{f['eprint']}"}
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items())
    return f"@misc{{{key},\n{body}\n}}\n"


def main() -> None:
    out = []
    for key, doi in DOIS.items():
        out.append(to_bib(key, fetch(doi)))
        time.sleep(0.5)
    out += [arxiv_bib(k, f) for k, f in ARXIV.items()]
    text = unicodedata.normalize("NFC", "\n".join(out))
    path = Path(__file__).resolve().parents[1] / "references" / "references.bib"
    path.write_text(text)
    print(f"wrote {len(out)} entries to {path}")


if __name__ == "__main__":
    main()
