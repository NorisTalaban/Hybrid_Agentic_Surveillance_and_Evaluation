"""
seed_writer.py — Writes Scanner-discovered crises to Supabase.

CHANGES from original utils.py:
  - Extracted into its own module
  - Added duplicate name check before insert (prevents DB errors)
  - write() returns count of newly written crises
  - Validates required fields before attempting insert
"""

import uuid
from datetime import datetime, timezone
from db import get_client
from geo import get_lat_lng
from logger import get_logger

_log = get_logger("seed_writer")

_REQUIRED_FIELDS = ["name", "type", "severity"]


class SeedWriter:

    def __init__(self):
        self.db  = get_client()
        self.now = datetime.now(timezone.utc).isoformat()

    def write(self, crises: list) -> int:
        """Write validated crises to DB. Returns count of newly created crises."""
        written = 0
        for c in crises:
            if c.get("already_in_db"):
                self._update_existing(c)
                continue
            if c.get("possible_duplicate_of"):
                _log.warning(f"Skipping duplicate: {c['name']} (dup of {c['possible_duplicate_of']})")
                continue
            # Validate required fields
            missing = [f for f in _REQUIRED_FIELDS if not c.get(f)]
            if missing:
                _log.warning(f"Skipping '{c.get('name', '?')}' — missing fields: {missing}")
                continue
            # Check name doesn't already exist in DB
            if self._name_exists(c["name"]):
                _log.info(f"Skipping '{c['name']}' — already exists in DB")
                self._update_existing(c)
                continue
            self._write_crisis(c)
            written += 1
        _log.info(f"Seed Writer: wrote {written} new crises")
        return written

    def _name_exists(self, name: str) -> bool:
        """Check if a crisis with this exact name already exists."""
        try:
            result = (self.db.table("crises")
                      .select("id", count="exact")
                      .eq("name", name)
                      .execute())
            return (result.count or 0) > 0
        except Exception:
            return False

    def _write_crisis(self, c: dict):
        crisis_id = str(uuid.uuid4())
        countries = c.get("countries", [])
        primary   = countries[0] if countries else None
        lat, lng  = None, None
        if primary:
            coords = get_lat_lng(primary)
            if coords:
                lat, lng = coords

        # Sanitize dates: if started_at is older than 10 years, it's probably
        # the historical origin, not the current active phase. Use last_known_event
        # or current date as fallback.
        started_at = c.get("started_at")
        if started_at:
            try:
                dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                years_ago = (datetime.now(timezone.utc) - dt).days / 365
                if years_ago > 10:
                    _log.warning(
                        f"  [{c['name']}] started_at={started_at} is {years_ago:.0f} years ago. "
                        f"Using last_known_event or now as fallback."
                    )
                    started_at = c.get("last_known_event") or self.now
            except (ValueError, TypeError):
                pass

        last_event = c.get("last_known_event") or started_at

        try:
            self.db.table("crises").insert({
                "id":              crisis_id,
                "name":            c["name"],
                "type":            c["type"],
                "status":          c.get("status", "active"),
                "severity":        c["severity"],
                "severity_peak":   c["severity"],
                "countries":       countries,
                "primary_country": primary,
                "lat":             lat,
                "lng":             lng,
                "event_count":     1,  # starts with 1 (the synthetic event)
                "source":          "scanner",
                "summary":         c.get("summary", ""),
                "first_event_at":  started_at,
                "last_event_at":   last_event,
                "last_updated":    self.now,
                "media_gap":       False,
            }).execute()
        except Exception as e:
            _log.error(f"Failed to insert crisis '{c['name']}': {e}")
            return

        for i, tp in enumerate(c.get("key_timeline", [])):
            self._write_timeline_entry(crisis_id, tp, i)
        if started_at:
            self._write_synthetic_event(crisis_id, started_at, c["severity"])
        _log.debug(f"  ✓ Written: {c['name']} (severity={c['severity']})")

    def _update_existing(self, c: dict):
        try:
            result = self.db.table("crises").select("id, severity").eq("name", c["name"]).single().execute()
            if not result.data:
                return
            updates = {"last_updated": self.now}
            if c.get("summary"):
                updates["summary"] = c["summary"]
            if c.get("severity") and abs(c["severity"] - result.data["severity"]) >= 2:
                updates["severity"] = c["severity"]
            self.db.table("crises").update(updates).eq("id", result.data["id"]).execute()
        except Exception as e:
            _log.warning(f"Could not update existing crisis '{c.get('name', '?')}': {e}")

    def _write_timeline_entry(self, crisis_id: str, tp: dict, order_index: int):
        try:
            self.db.table("key_timeline").insert({
                "id":              str(uuid.uuid4()),
                "crisis_id":       crisis_id,
                "event_date":      tp.get("date"),
                "title":           tp.get("title", ""),
                "significance":    tp.get("significance", ""),
                "severity_impact": tp.get("severity_impact", ""),
                "source":          "scanner",
                "order_index":     order_index,
                "created_at":      self.now,
            }).execute()
        except Exception as e:
            _log.warning(f"Failed to insert timeline entry: {e}")

    def _write_synthetic_event(self, crisis_id: str, date_str: str, severity: int):
        try:
            self.db.table("crisis_events").insert({
                "id":            str(uuid.uuid4()),
                "crisis_id":     crisis_id,
                "event_id":      None,
                "event_date":    date_str,
                "severity_at":   severity,
                "status_at":     "active",
                "is_escalation": False,
                "source":        "scanner",
                "created_at":    self.now,
            }).execute()
        except Exception as e:
            _log.warning(f"Failed to insert synthetic event: {e}")
