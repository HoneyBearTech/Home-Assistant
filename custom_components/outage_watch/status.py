"""Interpret fresh provider and local observations."""
from statistics import median

DAY = 86400

def summarize(samples, feed, connected, now, freshness, run_start=0):
    recent = [row for row in samples if row[0] > now - DAY]
    run = [row for row in recent if row[0] >= run_start]
    active = [row for row in run if row[0] > now - freshness]
    # Backoff can spread three consecutive failures over several fresh-check windows.
    streak = run[-3:]
    unreachable = (
        len(streak) == 3
        and all(row[1] == "failed" for row in streak)
        and all(current[0] - prior[0] < freshness for prior, current in zip(streak, streak[1:]))
    )
    latest = active[-1] if active else None
    baseline = [row[2] for row in recent[:-1] if row[1] == "ok"]
    typical = round(median(baseline)) if len(baseline) >= 20 else None
    level = feed.get("level")
    if connected is not True:
        result = ("unknown", "internet_down" if connected is False else "checking")
    elif level in ("major", "critical"):
        result = ("outage", "provider_outage")
    elif latest and unreachable:
        result = ("outage", "unreachable")
    elif level == "minor":
        result = ("possible_problems", "provider_degraded")
    elif latest and latest[1] == "ok" and typical and latest[2] > 3 * typical:
        result = ("possible_problems", "slow")
    elif latest and latest[1] != "blocked" and sum(row[1] == "failed" for row in active[-5:]) >= 2:
        result = ("possible_problems", "intermittent")
    elif (latest and latest[1] == "ok") or level == "none":
        result = ("operational", "ok")
    else:
        result = ("unknown", latest[1] if latest else "no_data")
    return (*result, typical)
