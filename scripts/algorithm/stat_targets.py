"""Ordered stat components each position predicts for league scoring."""

POSITION_STAT_TARGETS = {
    "QB": (
        "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions",
        "rushing_yards", "rushing_tds", "rushing_2pt_conversions", "targets", "receptions",
        "receiving_yards", "receiving_tds", "receiving_2pt_conversions", "fumbles_lost",
        "passing_attempts", "carries",
    ),
    "RB": (
        "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions", "carries",
        "rushing_yards", "rushing_tds", "rushing_2pt_conversions", "targets", "receptions",
        "receiving_yards", "receiving_tds", "receiving_2pt_conversions", "fumbles_lost",
    ),
    "WR": (
        "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions", "carries",
        "rushing_yards", "rushing_tds", "rushing_2pt_conversions", "targets", "receptions",
        "receiving_yards", "receiving_tds", "receiving_2pt_conversions", "fumbles_lost",
    ),
    "TE": (
        "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions", "carries",
        "rushing_yards", "rushing_tds", "rushing_2pt_conversions", "targets", "receptions",
        "receiving_yards", "receiving_tds", "receiving_2pt_conversions", "fumbles_lost",
    ),
    "DEF": (
        "sacks", "interceptions", "forced_fumbles", "fumble_recoveries",
        "defensive_tds", "special_teams_tds", "safeties", "points_allowed",
    ),
}

# Targets stored as raw counts are converted to per-opportunity rates for
# fitting, then multiplied by the separately predicted volume at prediction.
# A cap of 1.0 applies to events that can happen at most once per opportunity.
POSITION_EFFICIENCY_TARGETS = {
    "QB": {
        "passing_yards": ("passing_attempts", None),
        "passing_tds": ("passing_attempts", 1.0),
        "passing_interceptions": ("passing_attempts", 1.0),
        "passing_2pt_conversions": ("passing_attempts", 1.0),
        "rushing_yards": ("carries", None),
        "rushing_tds": ("carries", 1.0),
        "rushing_2pt_conversions": ("carries", 1.0),
        "receptions": ("targets", 1.0),
        "receiving_yards": ("targets", None),
        "receiving_tds": ("targets", 1.0),
        "receiving_2pt_conversions": ("targets", 1.0),
    },
    "RB": {
        "rushing_yards": ("carries", None),
        "rushing_tds": ("carries", 1.0),
        "rushing_2pt_conversions": ("carries", 1.0),
        "receptions": ("targets", 1.0),
        "receiving_yards": ("targets", None),
        "receiving_tds": ("targets", 1.0),
        "receiving_2pt_conversions": ("targets", 1.0),
    },
    "WR": {
        "rushing_yards": ("carries", None),
        "rushing_tds": ("carries", 1.0),
        "rushing_2pt_conversions": ("carries", 1.0),
        "receptions": ("targets", 1.0),
        "receiving_yards": ("targets", None),
        "receiving_tds": ("targets", 1.0),
        "receiving_2pt_conversions": ("targets", 1.0),
    },
    "TE": {
        "rushing_yards": ("carries", None),
        "rushing_tds": ("carries", 1.0),
        "rushing_2pt_conversions": ("carries", 1.0),
        "receptions": ("targets", 1.0),
        "receiving_yards": ("targets", None),
        "receiving_tds": ("targets", 1.0),
        "receiving_2pt_conversions": ("targets", 1.0),
    },
}
