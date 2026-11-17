# SPDX-License-Identifier: AGPL-3.0-only
"""Demo personas: the preview dataset is written for Saffron Tiffins (Kothrud); a second demo tenant gets its own identity.

``localize`` rewrites every string of a built dataset in ONE regex pass (so Kothrud -> Baner and Baner -> Aundh never chain).
The seeder uses the same maps so the real customers/staff of a persona match what the preview modules show.
"""

from __future__ import annotations

import re

from mealtally.preview import data as pv

DEFAULT = "saffron"
BY_SLUG = {"demo-fresh": "green", "e2e-tiffin": "e2e"}  # e2e: same story as Saffron Tiffins, its own phone range

GREEN_PASS_NAMES = [
    "Aisha Merchant", "Dev Patel", "Ishita Banerjee", "Kabir Malhotra", "Lakshmi Iyer", "Mihir Desai", "Naina Chopra",
    "Pranav Rao", "Radhika Menon", "Samar Khanna", "Tara Fernandes", "Utkarsh Tiwari", "Vidya Krishnan", "Yuvraj Bedi",
    "Zainab Qazi", "Arvind Nambiar", "Bhumika Shah", "Chirag Vora", "Diya Sethi", "Eshan Dutta", "Fiona D'Souza",
    "Gautam Reddy", "Heena Parekh", "Ishaan Gill", "Jaya Venkatesh",
]  # fmt: skip
GREEN_EXTRA_SUB_NAMES = [
    "Kriti Sanon Jr", "Lokesh Pillai", "Mansi Doshi", "Nitin Bajaj", "Ojas Kulshreshtha", "Parul Arora", "Qasim Ansari",
    "Rhea Kapadia", "Sahil Wadhwa", "Trisha Mukherjee", "Umang Saxena", "Vandana Rawat", "Wasim Lone", "Xena Pinto",
    "Yash Goyal", "Zara Contractor", "Abhay Bhatia", "Bani Walia", "Chaitra Hegde", "Darshan Naik", "Ela Shetty",
    "Firoz Mulla",
]  # fmt: skip
GREEN_EXTRA_SUB_NAMES[0] = "Kriti Anand"  # avoid a celebrity look-alike

STAFF_NAMES = {  # Saffron staff -> Leafline Bowls staff (display names; also used by the seeder)
    "Sunita Kulkarni": "Meera Trivedi",
    "Prakash Joshi": "Dhruv Shah",
    "Seema Pawar": "Kajal Parmar",
    "Imran Shaikh": "Faizal Qureshi",
    "Ganesh Bhosale": "Rakesh Nambiar",
    "Ramesh Gawade": "Anil Chandak",
    "Sunil Bhor": "Vinod Ranade",
}
GREEN_ADDRESS = "Unit 12, Sai Square, Baner Road, Pune 411045"
GREEN_PHONE = "+91 20 4000 2201"
OLD_ADDRESS = "Shop 4, Shivaji Society, Kothrud, Pune 411038"

_STRINGS = {
    OLD_ADDRESS: GREEN_ADDRESS,
    "+91 20 4000 1101": GREEN_PHONE,
    "Baner Pickup Point": "Aundh Pickup Point",
    "Kothrud Kitchen": "Baner Kitchen",
    "Karve Nagar": "Balewadi",
    "Erandwane": "Pashan",
    "Warje": "Sus",
    "Baner": "Aundh",
    "Aundh": "Wakad",
    "Bavdhan": "Pimple Saurabh",
    "Paud Road": "Hinjewadi Road",
    "Kothrud": "Baner",
    "Shivaji Society": "Lotus Court",
    "Gandhi Nagar": "Orchid Lane",
    "Om Residency": "Palm Meadows",
    "Ganesh Apartments": "Cedar Heights",
    "Rutu Heights": "Sky Vista",
    "Saffron Tiffins & Mess": "Leafline Bowls Kitchen",
    "Saffron Tiffins": "Leafline Bowls",
    "saffrontiffins": "leaflinebowls",
    "Ghar jaisa khana, roz.": "Fresh bowls, made today.",
    "Fresh home-style tiffins from our": "Fresh salads, grain bowls and light meals from our",
    "Pune's students and working families since 2016. Small batches, low oil, no shortcuts.": (
        "Baner's office crowd and fitness regulars since 2019. Seasonal produce, cold-pressed oils, no shortcuts."
    ),
    "MH12 AB 4021": "MH12 EF 3305",
    "MH12 CD 7718": "MH12 GH 5512",
    **STAFF_NAMES,
    **dict(zip(pv.PASS_NAMES, GREEN_PASS_NAMES, strict=True)),
    **dict(zip(pv.EXTRA_SUB_NAMES, GREEN_EXTRA_SUB_NAMES, strict=True)),
}
_RX = re.compile("|".join(re.escape(k) for k in sorted(_STRINGS, key=len, reverse=True)))
_PHONE = re.compile(r"\+91 90000 1(\d{4})")


def persona_for(slug: str) -> str:
    return BY_SLUG.get(slug, DEFAULT)


def phone_format(persona: str) -> str:
    return {"green": "+91 90000 3{:04d}", "e2e": "+91 90001 1{:04d}"}.get(persona, pv.PASS_PHONE)


def pass_names(persona: str) -> list[str]:
    return GREEN_PASS_NAMES if persona == "green" else pv.PASS_NAMES


def staff_name(persona: str, name: str) -> str:
    return STAFF_NAMES.get(name, name) if persona == "green" else name


def _fix(s: str) -> str:
    return _PHONE.sub(r"+91 90000 3\1", _RX.sub(lambda m: _STRINGS[m.group(0)], s))


def _fix_phone_only(s: str) -> str:
    return _PHONE.sub(r"+91 90001 1\1", s)


def _walk(x, fix=_fix):
    if isinstance(x, pv.Real):  # the tenant's own records are never rewritten (D03.9)
        return x
    if isinstance(x, str):
        return fix(x)
    if isinstance(x, dict):
        return {(fix(k) if isinstance(k, str) else k): _walk(v, fix) for k, v in x.items()}
    if isinstance(x, list):
        return [_walk(v, fix) for v in x]
    if isinstance(x, tuple):
        return tuple(_walk(v, fix) for v in x)
    return x


def localize(D: dict, persona: str) -> dict:
    if persona == "e2e":
        return _walk(D, _fix_phone_only)
    return D if persona == DEFAULT else _walk(D)
