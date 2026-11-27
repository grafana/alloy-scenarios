"""Deterministic, three-hour Forsaken leveling replay. Times are minutes of gameplay."""
import math
from bisect import bisect_right

# Map coordinates are percentages of Tirisfal Glades, measured from the top left.
# Each stop starts the named activity. The path between stops is illustrative.
STOPS = [
    (0, 30.0, 71.6, "Deathknell crypt", "Awakening"),
    (3, 32.0, 65.0, "Deathknell", "Speaking"),
    (6, 32.8, 62.0, "Deathknell", "Fighting"),
    (12, 31.3, 64.5, "Deathknell", "Speaking"),
    (16, 30.3, 60.3, "Deathknell", "Fighting"),
    (23, 32.0, 65.0, "Deathknell", "Speaking"),
    (25, 30.8, 63.4, "Deathknell", "Traveling"),
    (30, 27.8, 60.7, "Night Web's Hollow", "Fighting"),
    (37, 26.6, 59.5, "Night Web's Hollow", "Fighting"),
    (41, 28.5, 61.4, "Deathknell", "Traveling"),
    (45, 32.0, 65.0, "Deathknell", "Speaking"),
    (49, 34.9, 66.2, "Scarlet camp", "Fighting"),
    (55, 32.0, 65.0, "Deathknell", "Speaking"),
    (58, 36.5, 68.5, "Scarlet camp", "Fighting"),
    (64, 32.0, 65.0, "Deathknell", "Speaking"),
    (68, 36.0, 62.3, "Deathknell pass", "Traveling"),
    (73, 38.4, 55.9, "Deathknell pass", "Traveling"),
    (78, 42.0, 54.8, "Cold Hearth road", "Gathering"),
    (83, 48.9, 56.1, "Cold Hearth Manor", "Traveling"),
    (88, 53.0, 57.3, "Brill road", "Traveling"),
    (93, 61.0, 52.7, "Brill", "Speaking"),
    (98, 59.4, 52.3, "Brill", "Traveling"),
    (103, 50.5, 52.0, "Solliden road", "Fighting"),
    (108, 39.0, 51.9, "Solliden Farmstead", "Gathering"),
    (113, 37.4, 50.5, "Solliden Farmstead", "Fighting"),
    (118, 35.8, 50.6, "Solliden Farmstead", "Gathering"),
    (124, 42.8, 53.1, "Solliden road", "Traveling"),
    (130, 52.3, 56.1, "Brill road", "Fighting"),
    (136, 59.5, 52.4, "Brill", "Speaking"),
    (140, 61.7, 52.2, "Gallows' End Tavern", "Speaking"),
    (145, 56.8, 49.1, "Agamand road", "Traveling"),
    (151, 50.5, 46.6, "Agamand road", "Fighting"),
    (157, 47.2, 40.8, "Agamand Mills", "Fighting"),
    (163, 46.1, 37.7, "Agamand Mills", "Fighting"),
    (168, 48.1, 42.3, "Agamand Mills", "Traveling"),
    (174, 55.0, 48.4, "Brill road", "Traveling"),
    (180, 61.7, 52.2, "Gallows' End Tavern", "Speaking"),
]
# Wowhead quest IDs accompany the entries that describe a specific quest.
EVENTS = {
    0: ("Awoke in the crypt", "Undertaker Mordo", 363, False),
    3: ("Rude Awakening", "Shadow Priest Sarvis", 363, True),
    12: ("The Mindless Ones", "Shadow Priest Sarvis", 364, True),
    22: ("The Damned", "Novice Elreth", 376, True),
    23: ("Rattling the Rattlecages", "Shadow Priest Sarvis", 3901, True),
    25: ("Accepted Night Web's Hollow", "Executor Arren", 380, False),
    37: ("Cleared the spider mine", "Night Web's Hollow", 380, False),
    45: ("Night Web's Hollow", "Executor Arren", 380, True),
    55: ("The Scarlet Crusade", "Executor Arren", 381, True),
    64: ("The Red Messenger", "Executor Arren", 382, True),
    74: ("Accepted Fields of Grief", "Deathguard Simmer", 365, False),
    78: ("Gathered gloom weed", "Gordo's Task", 5481, False),
    93: ("Vital Intelligence", "Executor Zygand", 383, True),
    95: ("Gordo's Task", "Junior Apothecary Holland", 5481, True),
    98: ("Accepted A New Plague", "Apothecary Johaan", 367, False),
    108: ("Reached the pumpkin fields", "Solliden Farmstead", 365, False),
    118: ("Gathered the Tirisfal pumpkins", "Fields of Grief", 365, False),
    136: ("Fields of Grief", "Apothecary Johaan", 365, True),
    138: ("A New Plague", "Apothecary Johaan", 367, True),
    140: ("Accepted The Haunted Mills", "Coleman Farthing", 362, False),
    157: ("Found Devlin Agamand", "Agamand Mills", 362, False),
    163: ("Recovered Devlin's remains", "The Haunted Mills", 362, False),
    180: ("The Haunted Mills", "Coleman Farthing", 362, True),
}
CHAPTERS = [(0, "Deathknell"), (25, "Night Web's Hollow"), (45, "The Scarlet camp"),
            (68, "The road to Brill"), (98, "Solliden Farmstead"), (140, "Agamand Mills")]
LEVELS = [0, 6, 14, 27, 45, 68, 93, 118, 146, 180]
# Modeled equipment upgrades during five quest hand-ins.
GEAR_UPGRADES = [12, 45, 64, 93, 136]
XP = [400, 900, 1400, 2100, 2800, 3600, 4500, 5400, 6500, 7600]


def replay():
    samples = []
    kills = quests = copper = 0
    stop_times = [stop[0] for stop in STOPS]
    for half in range(361):
        minute = half / 2
        idx = bisect_right(stop_times, minute) - 1
        start, x, y, place, activity = STOPS[idx]
        stop, end_x, end_y, *_ = STOPS[min(idx + 1, len(STOPS) - 1)]
        ratio = (minute - start) / max(stop - start, 1)
        level = bisect_right(LEVELS, minute)
        if activity == "Fighting":
            kills += 1 + int(half % 4 == 0)
            copper += 2 + level
        event, who, quest_id, complete = EVENTS.get(minute, ("", "", 0, False))
        if complete:
            quests += 1
            copper += 4 * level
        max_hp, max_mana = 52 + level * 19, 80 + level * 24
        cost = (1 + math.sin(half * .7)) / 2 if activity == "Fighting" else 0
        chapter = bisect_right([c[0] for c in CHAPTERS], minute) - 1
        samples.append(dict(minute=minute, x=round(x + (end_x - x) * ratio, 2),
                            y=round(y + (end_y - y) * ratio, 2), place=place, activity=activity,
                            chapter=CHAPTERS[chapter][1], level=level, next_xp=XP[level-1],
                            hp=round(max_hp*(1-.35*cost)), max_hp=max_hp,
                            mana=round(max_mana*(1-.55*cost)), max_mana=max_mana, kills=kills,
                            copper=copper, quests=quests, item_level=1 + bisect_right(GEAR_UPGRADES, minute),
                            achievements=0, event=event, who=who, quest_id=quest_id))
    # Distribute each level's XP budget across kills, deliveries and exploration.
    samples[0].update(xp=0, total_xp=0)
    total = 0
    for level, (start, end) in enumerate(zip(LEVELS, LEVELS[1:]), 1):
        steps = samples[2*start+1:2*end+1]
        weights = []
        for previous, current in zip(samples[2*start:2*end], steps):
            kills = current["kills"] - previous["kills"]
            turn_ins = current["quests"] - previous["quests"]
            discovery = int(current["place"] != previous["place"] or current["minute"] == end)
            weights.append(8 * kills + 48 * turn_ins + 5 * discovery)
        accumulated, weight_total = 0, sum(weights)
        for row, weight in zip(steps, weights):
            accumulated += weight
            earned = XP[level-1] * accumulated // weight_total
            row.update(xp=earned if row["level"] == level else 0, total_xp=total + earned)
        total += XP[level-1]
    return samples


SAMPLES = replay()
