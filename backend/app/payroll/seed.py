"""Payroll reference data (07c). Everything here is seeded into the database or settings and
edited there; code only provides the first values.

PPh 21 TER bulanan, PP 58/2023 lampiran: (category, upper bound of monthly gross, rate %).
The last band of each category has no upper bound (None). Verify against the official annex
before go-live and edit in Penggajian > Setelan if the regulation changes.
"""

from decimal import Decimal

D = Decimal
JT = 1_000_000


def _bands(rows: list[tuple[float | None, str]]) -> list[tuple[Decimal | None, Decimal]]:
    return [(None if up is None else D(str(up)) * JT, D(rate)) for up, rate in rows]


TER: dict[str, list[tuple[Decimal | None, Decimal]]] = {
    # A: TK/0, TK/1, K/0
    "A": _bands(
        [
            (5.4, "0"),
            (5.65, "0.25"),
            (5.95, "0.5"),
            (6.3, "0.75"),
            (6.75, "1"),
            (7.5, "1.25"),
            (8.55, "1.5"),
            (9.65, "1.75"),
            (10.05, "2"),
            (10.35, "2.25"),
            (10.7, "2.5"),
            (11.05, "3"),
            (11.6, "3.5"),
            (12.5, "4"),
            (13.75, "5"),
            (15.1, "6"),
            (16.95, "7"),
            (19.75, "8"),
            (24.15, "9"),
            (26.45, "10"),
            (28, "11"),
            (30.05, "12"),
            (32.4, "13"),
            (35.4, "14"),
            (39.1, "15"),
            (43.85, "16"),
            (47.8, "17"),
            (51.4, "18"),
            (56.3, "19"),
            (62.2, "20"),
            (68.6, "21"),
            (77.5, "22"),
            (89, "23"),
            (103, "24"),
            (125, "25"),
            (157, "26"),
            (206, "27"),
            (337, "28"),
            (454, "29"),
            (550, "30"),
            (695, "31"),
            (910, "32"),
            (1400, "33"),
            (None, "34"),
        ]
    ),
    # B: TK/2, TK/3, K/1, K/2
    "B": _bands(
        [
            (6.2, "0"),
            (6.5, "0.25"),
            (6.85, "0.5"),
            (7.3, "0.75"),
            (9.2, "1"),
            (10.75, "1.5"),
            (11.25, "2"),
            (11.6, "2.5"),
            (12.6, "3"),
            (13.6, "4"),
            (14.95, "5"),
            (16.4, "6"),
            (18.45, "7"),
            (21.85, "8"),
            (26, "9"),
            (27.7, "10"),
            (29.35, "11"),
            (31.45, "12"),
            (33.95, "13"),
            (37.1, "14"),
            (41.1, "15"),
            (45.8, "16"),
            (49.5, "17"),
            (53.8, "18"),
            (58.5, "19"),
            (64, "20"),
            (71, "21"),
            (80, "22"),
            (93, "23"),
            (109, "24"),
            (129, "25"),
            (163, "26"),
            (211, "27"),
            (374, "28"),
            (459, "29"),
            (555, "30"),
            (704, "31"),
            (957, "32"),
            (1405, "33"),
            (None, "34"),
        ]
    ),
    # C: K/3
    "C": _bands(
        [
            (6.6, "0"),
            (6.95, "0.25"),
            (7.35, "0.5"),
            (7.8, "0.75"),
            (8.85, "1"),
            (9.8, "1.25"),
            (10.95, "1.5"),
            (11.2, "1.75"),
            (12.05, "2"),
            (12.95, "3"),
            (14.15, "4"),
            (15.55, "5"),
            (17.05, "6"),
            (19.5, "7"),
            (22.7, "8"),
            (26.6, "9"),
            (28.1, "10"),
            (30.1, "11"),
            (32.6, "12"),
            (35.4, "13"),
            (38.9, "14"),
            (43, "15"),
            (47.4, "16"),
            (51.2, "17"),
            (55.8, "18"),
            (60.4, "19"),
            (66.7, "20"),
            (74.5, "21"),
            (83.2, "22"),
            (95.6, "23"),
            (110, "24"),
            (134, "25"),
            (169, "26"),
            (221, "27"),
            (390, "28"),
            (463, "29"),
            (561, "30"),
            (709, "31"),
            (965, "32"),
            (1419, "33"),
            (None, "34"),
        ]
    ),
}

TER_CATEGORY = {
    "TK/0": "A",
    "TK/1": "A",
    "K/0": "A",
    "TK/2": "B",
    "TK/3": "B",
    "K/1": "B",
    "K/2": "B",
    "K/3": "C",
}

# Setting payroll.rules (all amounts in rupiah, rates in %).
DEFAULT_RULES: dict[str, object] = {
    "cutoff_day": 25,
    "pay_day": 25,
    "field_allowance_per_day": "350000",
    # PP 35/2021 art. 31: hourly wage = 1/173 x monthly wage; workday overtime
    # first hour x1.5, following hours x2.
    "overtime_divisor": "173",
    "overtime_first_hour_factor": "1.5",
    "overtime_next_hours_factor": "2",
    "bpjs": {
        "kesehatan": {"employer": "4", "employee": "1", "cap": "12000000"},
        "jht": {"employer": "3.7", "employee": "2", "cap": None},
        "jp": {"employer": "2", "employee": "1", "cap": "10547400"},
        # Risk group V (oil & gas field work); 0.24-1.74 % by risk level.
        "jkk": {"employer": "1.74", "employee": "0", "cap": None},
        "jkm": {"employer": "0.3", "employee": "0", "cap": None},
    },
    # Annual PTKP (PMK 101/2016).
    "ptkp": {
        "TK/0": "54000000",
        "TK/1": "58500000",
        "TK/2": "63000000",
        "TK/3": "67500000",
        "K/0": "58500000",
        "K/1": "63000000",
        "K/2": "67500000",
        "K/3": "72000000",
    },
    # UU HPP art. 17 progressive brackets on annual PKP: (upper bound, rate %).
    "brackets": [
        ["60000000", "5"],
        ["250000000", "15"],
        ["500000000", "25"],
        ["5000000000", "30"],
        [None, "35"],
    ],
    "position_cost_pct": "5",
    "position_cost_max_year": "6000000",
    # Without NPWP/NIK the PPh 21 is 20 % higher (UU HPP art. 21(5a)).
    "no_npwp_surcharge_pct": "20",
}
