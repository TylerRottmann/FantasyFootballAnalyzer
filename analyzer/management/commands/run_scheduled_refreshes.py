"""Run the production refresh schedules seeded by Django migrations."""
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analyzer.models import ScheduledRefresh
from scripts.commands.nflweek import SLEEPER_STATE_URL


# Leave time to release the database lease after the subprocess deadline.
LEASE = timedelta(hours=2)
RUN_LIMIT = LEASE.total_seconds() - 60


class Command(BaseCommand):
    help = "Run due UTC refresh jobs or rerun a named job manually."

    def add_arguments(self, parser):
        parser.add_argument("--job", help="Rerun a seeded job outside its UTC slot.")
        parser.add_argument("--lane", choices=("cache", "imports"))
        parser.add_argument("--list", action="store_true", help="List seeded schedules.")

    def handle(self, *args, **options):
        now = datetime.now(timezone.utc)
        slot = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
        jobs = ScheduledRefresh.objects.order_by("name")
        name = options["job"]
        if options["lane"] == "cache":
            jobs = jobs.filter(pk="external-cache")
        elif options["lane"] == "imports":
            jobs = jobs.exclude(pk="external-cache")
        if options["list"]:
            for job in jobs:
                self.stdout.write(
                    f"{job.name} UTC minutes={job.minutes} hours={job.hours or '*'} "
                    f"weekdays={job.weekdays or '*'}"
                )
            return
        if name:
            jobs = list(jobs.filter(pk=name))
            if not jobs:
                raise CommandError(f"Unknown refresh job: {name}")
        failures = []
        for job in jobs:
            if not name and (
                slot.minute not in job.minutes
                or job.hours and slot.hour not in job.hours
                or job.weekdays and slot.weekday() not in job.weekdays
            ):
                continue
            try:
                self.run_job(job.name, slot, manual=bool(name))
            except CommandError as exc:
                failures.append(str(exc))
        if failures:
            raise CommandError("\n".join(failures))

    def run_job(self, name, slot, *, manual):
        now = datetime.now(timezone.utc)
        with transaction.atomic():
            # Lock the rows in a consistent order to claim one lease per lane.
            lane = ScheduledRefresh.objects.order_by("name")
            lane = lane.filter(pk=name) if name == "external-cache" else lane.exclude(pk="external-cache")
            rows = {job.name: job for job in lane.select_for_update()}
            job = rows[name]
            if not manual and job.last_slot == slot:
                return
            if any(row.lease_until and row.lease_until > now for row in rows.values()):
                if manual:
                    raise CommandError(f"{name}: another refresh is running; retry when it finishes.")
                self.stderr.write(f"{slot.isoformat()} {name} skipped because another refresh is running.")
                return
            lease = now + LEASE
            job.last_slot = slot
            job.lease_until = lease
            job.save(update_fields=["last_slot", "lease_until"])

        self.deadline = monotonic() + RUN_LIMIT
        self.profile_month = job.profile_month
        self.stdout.write(f"{now.isoformat()} {name} started.")
        self.stdout.flush()
        try:
            period = self.run_pipeline(job, slot, manual=manual)
        except Exception as exc:
            ended = datetime.now(timezone.utc).isoformat()
            raise CommandError(f"{ended} {name} failed: {exc}") from exc
        else:
            if period:
                ScheduledRefresh.objects.filter(pk=name, lease_until=lease).update(
                    completed_period=period, profile_month=self.profile_month,
                )
            self.stdout.write(f"{datetime.now(timezone.utc).isoformat()} {name} finished.")
        finally:
            ScheduledRefresh.objects.filter(pk=name, lease_until=lease).update(lease_until=None)

    def step(self, *args, module=None):
        entry = ["-m", module] if module else ["manage.py"]
        command = [sys.executable, "-u", *entry, *map(str, args)]
        label = " ".join(command[2:])
        self.stdout.write(f"{datetime.now(timezone.utc).isoformat()} starting {label}")
        self.stdout.flush()
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise CommandError("Refresh exceeded its execution deadline.")
        subprocess.run(command, cwd=settings.BASE_DIR, check=True, timeout=remaining)
        self.stdout.write(f"{datetime.now(timezone.utc).isoformat()} finished {label}")

    def run_pipeline(self, job, slot, *, manual):
        name = job.name
        if name == "external-cache":
            self.step("refresh_external_cache", "--strict")
            return
        injury_due = slot.weekday() in (0, 3, 4, 5, 6) or slot.hour == 15
        if name == "injuries" and not (manual or injury_due):
            return
        response = requests.get(SLEEPER_STATE_URL, timeout=20)
        response.raise_for_status()
        state = response.json()
        season = int(state["season"])
        week = int(state.get("week") or 0)
        phase = state["season_type"]
        if not 2023 <= season <= 2100 or phase not in ("pre", "regular", "post", "off"):
            raise CommandError(f"Unexpected NFL season or phase: {season}, {phase}.")
        regular = phase == "regular" and 1 <= week <= 18
        draft = phase == "pre" or (phase != "regular" and slot.month in (7, 8, 9))
        self.stdout.write(f"Sleeper season={season} phase={phase} week={week}.")

        if name == "player-metadata":
            if manual or regular or draft or slot.weekday() == 1:
                self.metadata(slot, force=manual)
        elif name == "injuries":
            if regular:
                self.step("refresh_player_context", "--injuries-only", "--season", season, "--week", week)
        elif name == "adp":
            if manual or draft or regular and slot.weekday() == 1:
                adp_season = max(season, slot.year) if draft else season
                self.step("refresh_player_adp", "--season", adp_season)
        elif name == "market":
            if regular:
                self.market(season, week)
        elif name == "weekly":
            if phase == "pre" and state.get("season_start_date"):
                opener = date.fromisoformat(state["season_start_date"])
                if 0 <= (opener - slot.date()).days <= 2:
                    return self.weekly(job, slot, season, 1, "regular", True, manual=manual)
            return self.weekly(job, slot, season, week, phase, regular, manual=manual)

    def metadata(self, slot, *, force=False):
        day = slot.date().isoformat()
        job = ScheduledRefresh.objects.get(pk="player-metadata")
        if force or job.completed_period != day:
            self.step(module="scripts.imports.load_player_data")
            ScheduledRefresh.objects.filter(pk=job.pk).update(completed_period=day)

    def market(self, season, week):
        self.step(
            "import_sleeper_market_projections", "--season", season,
            "--weeks", *range(week, 19), "--require-coverage",
        )

    def weekly(self, job, slot, season, week, phase, regular, *, manual):
        if regular and week == 1:
            period = f"{season}-1"
            if not manual and job.completed_period == period:
                return
            self.require_artifact_directory()
            self.metadata(slot)
            self.step("--season", season, module="scripts.imports.import_nfl_schedule")
            self.step("refresh_player_context", "--injuries-only", "--season", season, "--week", 1)
            self.step("--seasons", *range(2023, season + 1), "--through-week", 0,
                      module="scripts.imports.prepare_kicker_data")
            self.market(season, 1)
            self.derived(season, 1)
            return period

        if not manual and slot.weekday() not in (1, 2):
            return
        if not regular and phase != "post":
            return

        final = phase == "post"
        through = 18 if final else week - 1
        period = f"{season}-final" if final else f"{season}-{week}"
        if not manual and job.completed_period == period:
            return
        self.require_artifact_directory()

        self.metadata(slot)
        self.step("--season", season, module="scripts.imports.import_nfl_schedule")
        context = ["--season", season, "--week", week, "--through-week", through]
        if final:
            context = ["--season", season, "--through-week", through, "--stats-only"]
        self.step("refresh_player_context", *context)
        for module in ("load_team_data", "load_dst_stats", "load_opportunity_stats", "load_advanced_team_data"):
            self.step("--seasons", season, "--through-week", through, module=f"scripts.imports.{module}")

        seasons = range(2023, season + 1)
        self.step("--seasons", *seasons, "--through-week", through, module="scripts.imports.prepare_kicker_data")
        month = slot.strftime("%Y-%m")
        if final or job.profile_month != month:
            self.step("build_injury_duration_profiles", "--seasons", *seasons, "--through-week", through)
            self.profile_month = month
        if not final:
            self.step("--season", season, "--through-week", through, "--strict", module="scripts.imports.build_team_features")
            self.step("--season", season, "--week", week, "--strict", module="scripts.imports.build_matchup_features")
            self.market(season, week)
            self.derived(season, week)
        return period

    def require_artifact_directory(self):
        directory = os.getenv("FFA_REFRESH_ARTIFACT_DIR")
        if not directory or not Path(directory).is_absolute() or not Path(directory).is_dir():
            raise CommandError("Set FFA_REFRESH_ARTIFACT_DIR to an existing shared absolute directory.")

    def derived(self, season, week):
        self.step("generate_projections", "--season", season, "--week", week, "--strict")
        self.step("refresh_market_ranks", "--season", season, "--weeks", week)
        self.step("--season", season, "--week", week, "--strict", module="scripts.generate_boom_bust_weekly")
